"""DataUpdateCoordinator fuer die F1-Dashboard-Integration.

Ein zentraler Coordinator pollt alle Datenquellen in einem Zyklus:
  - Jolpica-F1: Standings, Kalender, letztes Ergebnis/Qualifying
  - Open-Meteo: Wetter am naechsten Circuit (taeglich + stuendlich)
  - OpenF1: Ergebnis/Reifen/Boxenstopps des letzten Rennens (historisch)

Zusaetzlich verwaltet er den F1LiveDataManager, der waehrend aktiver
Sessions eine WebSocket-Verbindung zum offiziellen F1-Live-Timing-Feed
haelt (Timing Tower, Streckenstatus, Race Control).

Das ersetzt die vormals verkettete REST-Sensor/rest_command-YAML-Logik
durch einen einzigen, nativen Update-Zyklus.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import api
from .const import (
    CONF_ENABLE_RACE_RECAP,
    CONF_ENABLE_WEATHER,
    UPDATE_INTERVAL_STANDINGS,
)
from .live_manager import F1LiveDataManager

_LOGGER = logging.getLogger(__name__)

# Session-Reihenfolge fuer Zeitplan-Aufbau (Jolpica-Schluessel -> Label)
SESSION_DEFS = [
    ("FirstPractice", "FP1"),
    ("SecondPractice", "FP2"),
    ("ThirdPractice", "FP3"),
    ("SprintQualifying", "Sprint-Quali"),
    ("Sprint", "Sprint"),
    ("Qualifying", "Quali"),
]

# Die Live-Verbindung muss deutlich schneller reagieren als der stuendliche
# Haupt-Poll-Zyklus, damit sie zeitnah zu Sessionbeginn/-ende startet/stoppt.
_LIVE_CHECK_INTERVAL = timedelta(minutes=1)


class F1DashboardCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Koordiniert alle F1-Dashboard-Datenabrufe in einem Zyklus."""

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="F1 Dashboard",
            update_interval=UPDATE_INTERVAL_STANDINGS,
        )
        self._options = options
        self._session = async_get_clientsession(hass)
        self.live = F1LiveDataManager(hass)
        self._cached_session_status: dict[str, Any] = {
            "state": "idle", "next_race": None, "active_session": None,
        }
        # OpenF1-Rennrueckblick wird nicht mehr bei jedem stuendlichen Poll-Zyklus neu
        # abgerufen (unnoetige Last auf einer ohnehin rate-limitierten API, siehe
        # _async_update_data), sondern nur bei der Erstinitialisierung und wenn sich
        # entweder das letzte Jolpica-Rennergebnis oder der Session-Status aendert.
        # None ist der Startwert und erzwingt beim allerersten Refresh immer einen Abruf.
        self._cached_race_recap: dict[str, Any] | None = None
        self._race_recap_trigger_key: tuple[Any, ...] | None = None
        self._unsub_live_check = async_track_time_interval(
            hass, self._async_check_live_status, _LIVE_CHECK_INTERVAL
        )
        self.live.add_listener(self.async_update_listeners)

    async def async_shutdown(self) -> None:
        if self._unsub_live_check is not None:
            self._unsub_live_check()
        await self.live.async_shutdown()
        # Die von async_get_clientsession bereitgestellte Session gehoert
        # Home Assistant und wird zentral verwaltet - kein eigenes Schliessen.
        await super().async_shutdown()

    async def _async_check_live_status(self, _now: datetime | None = None) -> None:
        """Prueft unabhaengig vom Haupt-Poll, ob die Live-Verbindung an/aus soll.

        Der Rennkalender selbst aendert sich kaum, daher reicht es, ihn nur
        stuendlich neu abzurufen - aber der Session-Status (idle/upcoming/
        active) haengt von der aktuellen Uhrzeit ab und muss deutlich
        oefter neu berechnet werden, damit die Live-Verbindung zeitnah zu
        Sessionbeginn startet statt erst beim naechsten Stunden-Poll.
        """
        if self.data is not None:
            calendar = self.data.get("calendar", {})
            self._cached_session_status = self._compute_session_status(calendar)

        should_be_active = self._cached_session_status.get("state") == "active"
        await self.live.async_set_active(should_be_active)

    async def _async_update_data(self) -> dict[str, Any]:
        """Ruft alle Datenquellen ab und baut das kombinierte Datenmodell."""
        result: dict[str, Any] = {}

        try:
            result["driver_standings"] = await api.async_get_driver_standings(self._session)
            result["constructor_standings"] = await api.async_get_constructor_standings(
                self._session
            )
            result["calendar"] = await api.async_get_race_calendar(self._session)
            result["last_result"] = await api.async_get_last_result(self._session)
            result["last_qualifying"] = await api.async_get_last_qualifying(self._session)
        except api.F1ApiError as err:
            raise UpdateFailed(f"Jolpica-F1-Abruf fehlgeschlagen: {err}") from err

        result["session_status"] = self._compute_session_status(result["calendar"])
        self._cached_session_status = result["session_status"]

        if self._options.get(CONF_ENABLE_WEATHER, True):
            try:
                result["weather"] = await self._async_get_weather_for_next_race(
                    result["session_status"]
                )
            except api.F1ApiError as err:
                _LOGGER.warning("Wetterabruf fehlgeschlagen: %s", err)
                result["weather"] = None

        if self._options.get(CONF_ENABLE_RACE_RECAP, True):
            result["race_recap"] = await self._async_get_race_recap_if_needed(
                result["last_result"], result["session_status"]
            )

        return result

    def _build_race_recap_trigger_key(
        self, last_result: dict[str, Any], session_status: dict[str, Any]
    ) -> tuple[Any, ...]:
        """Baut den Vergleichsschluessel fuer 'hat sich seit dem letzten Abruf etwas
        geaendert, das einen neuen OpenF1-Abruf rechtfertigt'.

        Zwei unabhaengige Trigger: das Jolpica-Rennergebnis selbst (season+date - das
        ist der Schluessel, mit dem der OpenF1-Rennrueckblick ueberhaupt gesucht wird,
        siehe _async_get_race_recap) und der Session-Status (state+active_session).
        Letzterer allein waere nicht ausreichend: Status kann ueber zwei aufeinander-
        folgende Rennen hinweg z.B. beide Male "idle" sein, waehrend last_result sich
        bereits geaendert hat.
        """
        return (
            last_result.get("season"),
            last_result.get("date"),
            session_status.get("state"),
            session_status.get("active_session"),
        )

    async def _async_get_race_recap_if_needed(
        self, last_result: dict[str, Any], session_status: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Ruft den OpenF1-Rennrueckblick nur bei Erstinitialisierung oder einer
        Aenderung von last_result/session_status ab, sonst wird der zwischengespeicherte
        Wert wiederverwendet - siehe _cached_race_recap/_race_recap_trigger_key in
        __init__ fuer die Begruendung (OpenF1 ist rate-limitiert, ein stuendlicher
        Abruf ohne inhaltlichen Anlass war unnoetige Last).
        """
        trigger_key = self._build_race_recap_trigger_key(last_result, session_status)
        if self._race_recap_trigger_key is not None and trigger_key == self._race_recap_trigger_key:
            return self._cached_race_recap

        try:
            recap = await self._async_get_race_recap(last_result)
        except api.F1ApiError as err:
            _LOGGER.warning("OpenF1-Rennrueckblick fehlgeschlagen: %s", err)
            # Bei einem fehlgeschlagenen Abruf den zuletzt bekannten guten Stand
            # behalten, statt eine funktionierende Anzeige durch einen transienten
            # Fehler (z.B. OpenF1-Rate-Limit) zu leeren.
            return self._cached_race_recap

        self._cached_race_recap = recap
        self._race_recap_trigger_key = trigger_key
        return recap

    # -----------------------------------------------------------
    # Session-Status (idle/upcoming/active) + naechstes Rennen
    # -----------------------------------------------------------
    def _compute_session_status(self, calendar: dict[str, Any]) -> dict[str, Any]:
        races = calendar.get("Races", [])
        now = datetime.now(timezone.utc)

        for race in races:
            race_dt = self._parse_session_dt(race.get("date"), race.get("time"))
            if race_dt is None:
                continue
            race_end = race_dt + timedelta(hours=3)
            if now > race_end:
                continue

            state = "upcoming"
            active_session = None
            for key, label in [*SESSION_DEFS, ("__race__", "Rennen")]:
                sub = race if key == "__race__" else race.get(key)
                if not sub or not sub.get("date"):
                    continue
                dt = self._parse_session_dt(sub["date"], sub.get("time"))
                if dt and dt <= now <= dt + timedelta(hours=2):
                    state = "active"
                    active_session = label

            return {
                "state": state,
                "next_race": race,
                "active_session": active_session,
            }

        return {"state": "idle", "next_race": None, "active_session": None}

    @staticmethod
    def _parse_session_dt(date_str: str | None, time_str: str | None) -> datetime | None:
        if not date_str:
            return None
        time_part = (time_str or "00:00:00Z").replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(f"{date_str}T{time_part}")
        except ValueError:
            return None

    # -----------------------------------------------------------
    # Wetter fuer das naechste Rennen
    # -----------------------------------------------------------
    async def _async_get_weather_for_next_race(
        self, session_status: dict[str, Any]
    ) -> dict[str, Any] | None:
        next_race = session_status.get("next_race")
        if not next_race:
            return None
        circuit = next_race.get("Circuit", {})
        location = circuit.get("Location", {})
        lat, lon = location.get("lat"), location.get("long")
        if not lat or not lon:
            return None
        return await api.async_get_weather(self._session, lat, lon)

    # -----------------------------------------------------------
    # OpenF1-Rennrueckblick zum letzten Rennen
    # -----------------------------------------------------------
    async def _async_get_race_recap(
        self, last_result: dict[str, Any]
    ) -> dict[str, Any] | None:
        season = last_result.get("season")
        race_date = last_result.get("date")
        if not season or not race_date:
            return None

        openf1_session = await api.async_find_race_session(self._session, season, race_date)
        if not openf1_session:
            return None

        session_key = openf1_session.get("session_key")
        if session_key is None:
            return None

        # Jeder Teilaufruf wird einzeln abgesichert: schlaegt z.B. nur
        # der Boxenstopp-Abruf fehl (OpenF1-Rate-Limit), sollen Ergebnis
        # und Reifenstrategie trotzdem angezeigt werden, statt den
        # kompletten Rueckblick zu verwerfen.
        results = await self._async_get_openf1_part(
            api.async_get_session_result, session_key, "Ergebnis"
        )
        stints = await self._async_get_openf1_part(
            api.async_get_stints, session_key, "Reifenstrategie"
        )
        pit_stops = await self._async_get_openf1_part(
            api.async_get_pit_stops, session_key, "Boxenstopps"
        )

        # Fahrer- und Team-Mappings aus den Jolpica-Ergebnissen extrahieren
        driver_map = {}
        for r in last_result.get("Results", []):
            try:
                num = int(r.get("number", -1))
                driver_map[num] = {
                    "name": f"{r.get('Driver', {}).get('givenName', '')} {r.get('Driver', {}).get('familyName', '')}".strip(),
                    "constructorId": r.get("Constructor", {}).get("constructorId", ""),
                    "constructorName": r.get("Constructor", {}).get("name", ""),
                    "position": int(r.get("position", 999))
                }
            except (ValueError, TypeError):
                continue

        # 1) Rennergebnis aufbereiten
        mapped_results = []
        for r in (results or []):
            num = r.get("driver_number")
            info = driver_map.get(num)
            if info:
                name = info["name"]
                constr_id = info["constructorId"]
                constr_name = info["constructorName"]
                pos = info["position"]
            else:
                name = f"Driver #{num}"
                constr_id = ""
                constr_name = "–"
                # OpenF1 liefert fuer einzelne, nicht zuordenbare Fahrer nicht
                # immer eine Position. Diese Eintraege duerfen nicht mit 0 vor
                # bekannte klassifizierte Fahrer einsortiert werden.
                pos = r.get("position") or 999

            gap = r.get("gap_to_leader")
            if gap == 0 or gap is None:
                duration = r.get("duration")
                if duration:
                    h = int(duration // 3600)
                    m = int((duration % 3600) // 60)
                    s = duration % 60
                    time_str = f"{h}:{m:02d}:{s:06.3f}" if h > 0 else f"{m}:{s:06.3f}"
                else:
                    time_str = "Winner"
            elif isinstance(gap, (int, float)):
                time_str = f"+{gap:.3f}s"
            else:
                time_str = str(gap)

            mapped_results.append({
                "position": pos,
                "driver": {"name": name},
                "constructor": {"name": constr_name, "constructorId": constr_id},
                "points": int(r.get("points", 0)),
                "time": time_str,
            })
        mapped_results.sort(key=lambda x: x["position"])

        # 2) Reifenstrategie (Stints) gruppieren und aufbereiten
        driver_stints = {}
        for s in (stints or []):
            num = s.get("driver_number")
            if num not in driver_stints:
                driver_stints[num] = []
            driver_stints[num].append(s)

        mapped_stints = []
        for num, s_list in driver_stints.items():
            s_list.sort(key=lambda x: x.get("stint_number", 0))
            compounds = [s.get("compound", "") for s in s_list if s.get("compound")]
            
            total_laps = 0
            if s_list:
                total_laps = s_list[-1].get("lap_end", 0)

            info = driver_map.get(num)
            if info:
                name = info["name"]
                constr_id = info["constructorId"]
                pos = info["position"]
            else:
                name = f"Driver #{num}"
                constr_id = ""
                pos = 999

            mapped_stints.append({
                "driver": {"name": name},
                "constructor": {"constructorId": constr_id},
                "position": pos,
                "compound": compounds,
                "laps": total_laps
            })
        mapped_stints.sort(key=lambda x: x["position"])

        # 3) Boxenstopps aufbereiten
        sorted_pits = sorted((pit_stops or []), key=lambda x: (x.get("lap_number", 0), x.get("date", "")))
        driver_stop_counters = {}
        mapped_pits = []
        for p in sorted_pits:
            num = p.get("driver_number")
            if num is None:
                continue
            driver_stop_counters[num] = driver_stop_counters.get(num, 0) + 1
            stop_num = driver_stop_counters[num]

            info = driver_map.get(num)
            name = info["name"] if info else f"Driver #{num}"
            pos = info["position"] if info else 999

            duration_sec = p.get("stop_duration") or p.get("pit_duration")
            if duration_sec is not None:
                duration_str = f"{duration_sec:.2f}s"
            else:
                duration_str = "–"

            mapped_pits.append({
                "driver": {"name": name},
                "stop": stop_num,
                "lap": p.get("lap_number", 0),
                "duration": duration_str,
                "position": pos
            })
        
        def get_duration_val(x):
            try:
                return float(x["duration"].replace("s", ""))
            except ValueError:
                return 999.0
        mapped_pits.sort(key=get_duration_val)

        return {
            "session_key": session_key,
            "circuit_short_name": openf1_session.get("circuit_short_name"),
            "country_name": openf1_session.get("country_name"),
            "results": mapped_results,
            "stints": mapped_stints,
            "pit_stops": mapped_pits,
        }

    async def _async_get_openf1_part(
        self, fetch_fn: Any, session_key: int, label: str
    ) -> list[dict[str, Any]]:
        """Ruft einen einzelnen OpenF1-Teilbereich ab und faengt Fehler lokal ab.

        Gibt bei Fehlschlag eine leere Liste zurueck statt die Exception
        weiterzureichen, damit ein einzelner ausgelasteter Endpunkt nicht
        den gesamten Rennrueckblick blockiert.
        """
        try:
            return await fetch_fn(self._session, session_key)
        except api.F1ApiError as err:
            _LOGGER.warning("OpenF1 %s nicht verfuegbar: %s", label, err)
            return []
