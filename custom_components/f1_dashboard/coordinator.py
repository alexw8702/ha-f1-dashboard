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

# Jolpica-Kalender-Schluessel -> (session_type-Label lt. Datenvertrag, OpenF1 session_name).
# Qualifying/Race werden nicht ueber OpenF1 abgefragt (dafuer gibt es bereits
# last_result/last_qualifying aus Jolpica), daher hier ohne OpenF1-Namen.
_SESSION_TYPE_DEFS: list[tuple[str, str, str | None]] = [
    ("FirstPractice", "Practice 1", "Practice 1"),
    ("SecondPractice", "Practice 2", "Practice 2"),
    ("ThirdPractice", "Practice 3", "Practice 3"),
    ("SprintQualifying", "Sprint Qualifying", "Sprint Qualifying"),
    ("Sprint", "Sprint", "Sprint"),
    ("Qualifying", "Qualifying", None),
    ("__race__", "Race", None),
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

        Der neu berechnete Status wird auch in self.data["session_status"]
        geschrieben (via async_set_updated_data), nicht nur in
        self._cached_session_status: Ohne das wuerde sensor.f1_dashboard_
        session_status (liest self.coordinator.data direkt, siehe sensor.py)
        bis zu 59 Minuten hinter der tatsaechlichen Session zurueckhaengen,
        obwohl die Live-Verbindung selbst puenktlich startet - der Sensor
        haette dann von diesem minuetlichen Check gar nichts gehabt.
        """
        if self.data is not None:
            calendar = self.data.get("calendar", {})
            self._cached_session_status = self._compute_session_status(calendar)
            if self._cached_session_status != self.data.get("session_status"):
                self.data["session_status"] = self._cached_session_status
                self.async_set_updated_data(self.data)

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

        result["last_session"] = await self._async_get_last_session(
            result["calendar"], result["last_result"], result["last_qualifying"]
        )
        result["starting_grid"] = await self._async_build_starting_grid(
            result["last_result"], result["last_qualifying"], result["calendar"]
        )

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
        if (
            self._race_recap_trigger_key is not None
            and trigger_key == self._race_recap_trigger_key
        ):
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
        # Den Trigger-Schluessel nur "committen" (und damit kuenftige Abrufe ueberspringen),
        # wenn tatsaechlich ein Ergebnis vorliegt. OpenF1 hat kurz nach Rennende oft noch
        # keine oder nur unvollstaendige Daten (Ingestion-Verzoegerung); _async_get_race_recap
        # wirft dabei keinen Fehler (die Teilabrufe fangen ihre Fehler selbst ab, siehe
        # _async_get_openf1_part), sondern liefert einfach leere results/stints/pit_stops.
        # Wuerde man den Trigger-Schluessel trotzdem committen, bliebe die Karte bis zum
        # naechsten Rennwochenende dauerhaft auf diesem unvollstaendigen Stand haengen, da
        # last_result/session_status sich bis dahin nicht mehr aendern und so nie wieder ein
        # neuer Abruf ausgeloest wuerde. Ohne committeten Trigger-Schluessel wird beim naechsten
        # Poll-Zyklus (stuendlich) automatisch erneut versucht, bis OpenF1 die Daten hat -
        # genau das Selbstheilungsverhalten, das der alte unbedingte stuendliche Abruf hatte.
        if recap and recap.get("results"):
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
    # Letzte/laufende Session: flaches Timing-Ergebnis fuer die Karte
    # -----------------------------------------------------------
    @staticmethod
    def _driver_map_from_jolpica(last_result: dict[str, Any]) -> dict[int, dict[str, str]]:
        """Baut eine Fahrernummer -> {code, name, team}-Zuordnung aus dem letzten
        Jolpica-Rennergebnis. Fahrernummern sind ueber ein Rennwochenende stabil,
        daher taugt das auch als Namens-/Team-Quelle fuer OpenF1-Sessions
        (Practice/Sprint), die selbst keine Fahrernamen liefern.
        """
        driver_map: dict[int, dict[str, str]] = {}
        for r in last_result.get("Results", []):
            try:
                num = int(r.get("number", -1))
            except (ValueError, TypeError):
                continue
            driver = r.get("Driver", {})
            driver_map[num] = {
                "code": driver.get("code", ""),
                "name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                "team": r.get("Constructor", {}).get("name", ""),
            }
        return driver_map

    async def _async_get_last_session(
        self,
        calendar: dict[str, Any],
        last_result: dict[str, Any],
        last_qualifying: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Findet die zuletzt gestartete Session (laufend oder abgeschlossen) im
        Kalender und baut daraus ein flaches Timing-Ergebnis (Datenvertrag fuer
        die Frontend-Karte: nie die verschachtelten Ergast/OpenF1-Formen direkt).
        """
        now = datetime.now(timezone.utc)
        best: tuple[datetime, str, str, str | None, dict[str, Any]] | None = None
        for race in calendar.get("Races", []):
            for key, label, openf1_name in _SESSION_TYPE_DEFS:
                sub = race if key == "__race__" else race.get(key)
                if not sub or not sub.get("date"):
                    continue
                dt = self._parse_session_dt(sub["date"], sub.get("time"))
                if dt is None or dt > now:
                    continue
                if best is None or dt > best[0]:
                    best = (dt, key, label, openf1_name, race)

        if best is None:
            return None
        dt, key, label, openf1_name, race = best

        if key == "__race__":
            results = self._reshape_race_results(last_result.get("Results", []))
        elif key == "Qualifying":
            results = self._reshape_qualifying_results(
                last_qualifying.get("QualifyingResults", [])
            )
        else:
            results = await self._async_get_openf1_session_results(
                race.get("season"), dt.date().isoformat(), openf1_name, last_result
            )

        return {
            "session_type": label,
            "session_name": f"{race.get('raceName', '')} - {label}".strip(" -"),
            "date": dt.date().isoformat(),
            "results": results,
        }

    async def _async_get_openf1_session_results(
        self, season: str | None, session_date: str, openf1_name: str, last_result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not season:
            return []
        session_meta = await self._async_openf1_find_session_safe(season, session_date, openf1_name)
        if not session_meta:
            return []
        session_key = session_meta.get("session_key")
        if session_key is None:
            return []
        raw_results = await self._async_get_openf1_part(
            api.async_get_session_result, session_key, f"Session-Ergebnis ({openf1_name})"
        )
        driver_map = self._driver_map_from_jolpica(last_result)

        flat: list[dict[str, Any]] = []
        for r in raw_results or []:
            num = r.get("driver_number")
            info = driver_map.get(num, {})
            gap = r.get("gap_to_leader")
            duration = r.get("duration")
            if isinstance(gap, (int, float)) and gap != 0:
                time_or_gap = f"+{gap:.3f}"
            elif isinstance(duration, (int, float)):
                time_or_gap = f"{duration:.3f}"
            else:
                time_or_gap = None
            if r.get("dnf"):
                status = "DNF"
            elif r.get("dns"):
                status = "DNS"
            elif r.get("dsq"):
                status = "DSQ"
            else:
                status = None
            flat.append({
                "position": r.get("position"),
                "driver_code": info.get("code", ""),
                "driver_name": info.get("name", f"#{num}" if num is not None else ""),
                "team": info.get("team", ""),
                "team_color": None,
                "time_or_gap": time_or_gap,
                "laps": None,
                "status": status,
            })
        flat.sort(key=lambda x: x.get("position") if x.get("position") is not None else 999)
        return flat

    async def _async_openf1_find_session_safe(
        self, season: str, session_date: str, openf1_name: str
    ) -> dict[str, Any] | None:
        try:
            return await api.async_find_session(self._session, season, session_date, openf1_name)
        except api.F1ApiError as err:
            _LOGGER.warning("OpenF1-Session-Suche (%s) fehlgeschlagen: %s", openf1_name, err)
            return None

    @staticmethod
    def _reshape_race_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flat = []
        for r in results:
            driver = r.get("Driver", {})
            time_info = r.get("Time", {})
            status = r.get("status")
            time_or_gap = time_info.get("time") if time_info else (status or None)
            try:
                laps = int(r.get("laps"))
            except (ValueError, TypeError):
                laps = None
            try:
                position = int(r.get("position"))
            except (ValueError, TypeError):
                position = None
            flat.append({
                "position": position,
                "driver_code": driver.get("code", ""),
                "driver_name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                "team": r.get("Constructor", {}).get("name", ""),
                "team_color": None,
                "time_or_gap": time_or_gap,
                "laps": laps,
                "status": status,
            })
        return flat

    @staticmethod
    def _reshape_qualifying_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flat = []
        for r in results:
            driver = r.get("Driver", {})
            best_time = r.get("Q3") or r.get("Q2") or r.get("Q1")
            try:
                position = int(r.get("position"))
            except (ValueError, TypeError):
                position = None
            flat.append({
                "position": position,
                "driver_code": driver.get("code", ""),
                "driver_name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                "team": r.get("Constructor", {}).get("name", ""),
                "team_color": None,
                "time_or_gap": best_time,
                "laps": None,
                "status": None,
            })
        return flat

    # -----------------------------------------------------------
    # Startaufstellung (mit Strafen-Kennzeichnung)
    # -----------------------------------------------------------
    _PENALTY_KEYWORDS = ("penalty", "grid", "startplatz")

    async def _async_build_starting_grid(
        self,
        last_result: dict[str, Any],
        last_qualifying: dict[str, Any],
        calendar: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Baut die Startaufstellung fuer das aktuelle Rennwochenende.

        Jolpica/Ergast veroeffentlicht das tatsaechliche Startfeld (Feld 'grid')
        nur rueckwirkend als Teil der Rennergebnisse. Vor dem Rennen deckt OpenF1s
        '/starting_grid'-Endpunkt (per Qualifying-session_key) die Luecke: laut
        OpenF1-Doku ist er wenige Minuten nach Veroeffentlichung der offiziellen
        Ergebnisse verfuegbar, also i.d.R. schon kurz nach dem Qualifying inkl.
        etwaiger FIA-Startplatzstrafen - nicht erst nach dem Rennen. Ist auch
        dieser Endpunkt noch leer (kurzes Zeitfenster direkt nach dem Qualifying,
        bevor OpenF1 die Daten eingepflegt hat), bleibt die Qualifying-Reihenfolge
        als Fallback (provisional=True).
        """
        quali_results = last_qualifying.get("QualifyingResults", [])
        if not quali_results:
            return None

        quali_by_number: dict[int, dict[str, Any]] = {}
        for q in quali_results:
            try:
                num = int(q.get("Driver", {}).get("permanentNumber") or q.get("number", -1))
            except (ValueError, TypeError):
                num = None
            try:
                pos = int(q.get("position"))
            except (ValueError, TypeError):
                continue
            key = num if num is not None else q.get("Driver", {}).get("driverId")
            quali_by_number[key] = {
                "quali_position": pos,
                "driver_code": q.get("Driver", {}).get("code", ""),
                "driver_name": f"{q.get('Driver', {}).get('givenName', '')} {q.get('Driver', {}).get('familyName', '')}".strip(),
                "team": q.get("Constructor", {}).get("name", ""),
                "driver_id": q.get("Driver", {}).get("driverId"),
                "number": num,
            }

        race_ran = (
            last_result.get("round") is not None
            and str(last_result.get("round")) == str(last_qualifying.get("round"))
            and str(last_result.get("season")) == str(last_qualifying.get("season"))
        )

        if race_ran:
            return self._build_final_starting_grid(last_result, last_qualifying, quali_by_number)

        quali_session_key = await self._async_find_quali_session_key(last_qualifying, calendar)
        penalty_notes: dict[int, str] = {}
        grid_rows: list[dict[str, Any]] = []
        if quali_session_key is not None:
            grid_rows = await self._async_get_openf1_part(
                api.async_get_starting_grid, quali_session_key, "Startaufstellung"
            )
            penalty_notes = await self._async_get_penalty_notes(quali_session_key)

        if grid_rows:
            return self._build_openf1_starting_grid(grid_rows, quali_by_number, penalty_notes, last_qualifying)

        return self._build_provisional_starting_grid(quali_by_number, penalty_notes, last_qualifying)

    async def _async_find_quali_session_key(
        self, last_qualifying: dict[str, Any], calendar: dict[str, Any]
    ) -> int | None:
        """Findet den OpenF1-session_key des Qualifyings, dessen QualifyingResults
        gerade in last_qualifying stecken (Runde+Saison-Abgleich gegen den Kalender)."""
        season = last_qualifying.get("season")
        round_ = last_qualifying.get("round")
        if not season or round_ is None:
            return None
        for race in calendar.get("Races", []):
            if str(race.get("round")) != str(round_) or str(race.get("season", season)) != str(season):
                continue
            sub = race.get("Qualifying")
            if not sub or not sub.get("date"):
                return None
            dt = self._parse_session_dt(sub["date"], sub.get("time"))
            if dt is None:
                return None
            session_meta = await self._async_openf1_find_session_safe(
                str(season), dt.date().isoformat(), "Qualifying"
            )
            return session_meta.get("session_key") if session_meta else None
        return None

    async def _async_get_penalty_notes(self, session_key: int) -> dict[int, str]:
        """Historische Race-Control-Nachrichten (OpenF1) fuer eine Session, gefiltert
        auf Strafen-Stichworte und mit klarem driver_number - im Gegensatz zur
        alten reinen Live-Textsuche ist driver_number ein strukturiertes Feld,
        eine Zuordnung darueber ist also kein Rateversuch mehr.
        """
        rows = await self._async_get_openf1_part(
            api.async_get_race_control, session_key, "Race Control (historisch)"
        )
        notes: dict[int, str] = {}
        for row in rows or []:
            num = row.get("driver_number")
            if num is None:
                continue
            message = str(row.get("message", ""))
            if not any(kw in message.lower() for kw in self._PENALTY_KEYWORDS):
                continue
            notes[num] = message
        return notes

    @staticmethod
    def _build_final_starting_grid(
        last_result: dict[str, Any],
        last_qualifying: dict[str, Any],
        quali_by_number: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        """Rennen bereits gefahren: 'grid' aus dem Jolpica-Rennergebnis ist die
        garantiert authoritative Quelle - hat Vorrang vor OpenF1s '/starting_grid'."""
        grid = []
        for r in last_result.get("Results", []):
            driver = r.get("Driver", {})
            try:
                grid_pos = int(r.get("grid"))
            except (ValueError, TypeError):
                grid_pos = None
            try:
                num = int(r.get("number", -1))
            except (ValueError, TypeError):
                num = None
            quali_info = quali_by_number.get(num) or quali_by_number.get(driver.get("driverId"))
            quali_pos = quali_info.get("quali_position") if quali_info else None
            penalty = quali_pos is not None and grid_pos is not None and grid_pos != quali_pos
            grid.append({
                "grid_position": grid_pos,
                "quali_position": quali_pos,
                "driver_code": driver.get("code", ""),
                "driver_name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                "team": r.get("Constructor", {}).get("name", ""),
                "penalty": penalty,
                "penalty_note": None,
            })
        grid.sort(key=lambda x: x["grid_position"] if x["grid_position"] is not None else 999)

        return {
            "season": last_result.get("season"),
            "round": last_result.get("round"),
            "raceName": last_result.get("raceName"),
            "provisional": False,
            "grid": grid,
        }

    @staticmethod
    def _build_openf1_starting_grid(
        grid_rows: list[dict[str, Any]],
        quali_by_number: dict[int, dict[str, Any]],
        penalty_notes: dict[int, str],
        last_qualifying: dict[str, Any],
    ) -> dict[str, Any]:
        """OpenF1 hat das offizielle (post-Strafen) Startfeld bereits veroeffentlicht,
        obwohl das Rennen selbst noch nicht gefahren ist - das ist die finale
        Startaufstellung, kein Ratewert mehr."""
        grid = []
        for row in grid_rows:
            num = row.get("driver_number")
            info = quali_by_number.get(num)
            try:
                grid_pos = int(row.get("position"))
            except (ValueError, TypeError):
                grid_pos = None
            quali_pos = info.get("quali_position") if info else None
            penalty = quali_pos is not None and grid_pos is not None and grid_pos != quali_pos
            grid.append({
                "grid_position": grid_pos,
                "quali_position": quali_pos,
                "driver_code": info.get("driver_code", "") if info else "",
                "driver_name": info.get("driver_name", f"#{num}" if num is not None else "") if info else f"#{num}",
                "team": info.get("team", "") if info else "",
                "penalty": penalty,
                "penalty_note": penalty_notes.get(num),
            })
        grid.sort(key=lambda x: x["grid_position"] if x["grid_position"] is not None else 999)

        return {
            "season": last_qualifying.get("season"),
            "round": last_qualifying.get("round"),
            "raceName": last_qualifying.get("raceName"),
            "provisional": False,
            "grid": grid,
        }

    def _build_provisional_starting_grid(
        self,
        quali_by_number: dict[int, dict[str, Any]],
        penalty_notes: dict[int, str],
        last_qualifying: dict[str, Any],
    ) -> dict[str, Any]:
        """OpenF1 hat das offizielle Startfeld noch nicht veroeffentlicht (typisches
        Zeitfenster: wenige Minuten direkt nach dem Qualifying) - Qualifying-
        Reihenfolge als Platzhalter, mit Strafenhinweis wo bereits bekannt (live
        Race-Control-Feed zuerst, dann die historische OpenF1-Suche als Fallback
        fuer den Fall, dass niemand live zugehoert hat)."""
        grid = []
        for info in sorted(quali_by_number.values(), key=lambda x: x["quali_position"]):
            note = self._find_live_penalty_note(info["driver_code"], info["driver_name"])
            if note is None:
                note = penalty_notes.get(info.get("number"))
            grid.append({
                "grid_position": info["quali_position"],
                "quali_position": info["quali_position"],
                "driver_code": info["driver_code"],
                "driver_name": info["driver_name"],
                "team": info["team"],
                "penalty": note is not None,
                "penalty_note": note,
            })
        return {
            "season": last_qualifying.get("season"),
            "round": last_qualifying.get("round"),
            "raceName": last_qualifying.get("raceName"),
            "provisional": True,
            "grid": grid,
        }

    def _find_live_penalty_note(self, driver_code: str, driver_name: str) -> str | None:
        """Best-effort-Suche nach einer zum Fahrer passenden Strafen-Nachricht in
        den live/zuletzt empfangenen Race-Control-Nachrichten (siehe live_manager.py).

        Bewusst konservativ: nur wenn eine Nachricht sowohl ein Strafen-Stichwort
        als auch den Fahrercode oder -nachnamen enthaelt, wird sie zugeordnet -
        sonst liefert dies None und der Aufrufer faellt auf die historische
        OpenF1-Race-Control-Suche zurueck (driver_number-basiert, siehe
        _async_get_penalty_notes), die kein Rateversuch ist.
        """
        messages = self.live.race_control_messages
        if not messages or not (driver_code or driver_name):
            return None
        last_name = driver_name.rsplit(" ", 1)[-1].lower() if driver_name else ""
        for msg in messages:
            text = str(msg.get("Message", ""))
            lower = text.lower()
            if not any(kw in lower for kw in self._PENALTY_KEYWORDS):
                continue
            if (driver_code and driver_code.lower() in lower) or (
                last_name and last_name in lower
            ):
                return text
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
