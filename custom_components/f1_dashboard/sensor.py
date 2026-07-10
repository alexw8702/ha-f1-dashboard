"""Sensor-Entities fuer die F1-Dashboard-Integration.

Bildet exakt die Attribut-Struktur der vormaligen YAML-Sensoren nach,
damit die bestehenden Custom Cards (f1-drivers-card, f1-constructors-card,
f1-session-card, f1-race-recap-card) ohne Anpassung weiterlaufen.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import F1DashboardCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Legt alle F1-Dashboard-Sensoren an."""
    coordinator: F1DashboardCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        F1DriverStandingsSensor(coordinator, entry),
        F1ConstructorStandingsSensor(coordinator, entry),
        F1CalendarSensor(coordinator, entry),
        F1LastResultSensor(coordinator, entry),
        F1LastQualifyingSensor(coordinator, entry),
        F1SessionStatusSensor(coordinator, entry),
        F1WeatherDailySensor(coordinator, entry),
        F1WeatherHourlySensor(coordinator, entry),
        F1RaceRecapSensor(coordinator, entry),
        F1LiveTimingTowerSensor(coordinator, entry),
        F1LiveTrackStatusSensor(coordinator, entry),
        F1LiveRaceControlSensor(coordinator, entry),
        F1LiveTrackPositionsSensor(coordinator, entry),
    ]
    async_add_entities(entities)


class _F1BaseSensor(CoordinatorEntity[F1DashboardCoordinator], SensorEntity):
    """Gemeinsame Basis fuer alle F1-Dashboard-Sensoren."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: F1DashboardCoordinator, entry: ConfigEntry, key: str, name: str
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "F1 Dashboard",
            "manufacturer": "Jolpica-F1 / Open-Meteo / OpenF1",
            "model": "Formel-1-Datenintegration",
        }


class F1DriverStandingsSensor(_F1BaseSensor):
    """Fahrerwertung (entspricht sensor.f1_fahrerwertung)."""

    _attr_icon = "mdi:racing-helmet"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "driver_standings", "Fahrerwertung")

    @property
    def native_value(self) -> str | None:
        rows = self._rows()
        if not rows:
            return None
        driver = rows[0].get("Driver", {})
        return f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("driver_standings", {})
        return {
            "season": data.get("season"),
            "round": data.get("round"),
            "DriverStandings": data.get("DriverStandings", []),
        }

    def _rows(self) -> list[dict[str, Any]]:
        return self.coordinator.data.get("driver_standings", {}).get("DriverStandings", [])


class F1ConstructorStandingsSensor(_F1BaseSensor):
    """Konstrukteurswertung (entspricht sensor.f1_konstrukteurswertung)."""

    _attr_icon = "mdi:car-sports"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "constructor_standings", "Konstrukteurswertung")

    @property
    def native_value(self) -> str | None:
        rows = self._rows()
        if not rows:
            return None
        return rows[0].get("Constructor", {}).get("name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("constructor_standings", {})
        return {
            "season": data.get("season"),
            "round": data.get("round"),
            "ConstructorStandings": data.get("ConstructorStandings", []),
        }

    def _rows(self) -> list[dict[str, Any]]:
        return self.coordinator.data.get("constructor_standings", {}).get(
            "ConstructorStandings", []
        )


class F1CalendarSensor(_F1BaseSensor):
    """Rennkalender (entspricht sensor.f1_rennkalender)."""

    _attr_icon = "mdi:calendar-star"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "calendar", "Rennkalender")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("calendar", {}).get("Races", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("calendar", {})
        return {"season": data.get("season"), "Races": data.get("Races", [])}


class F1LastResultSensor(_F1BaseSensor):
    """Letztes Rennergebnis (entspricht sensor.f1_letztes_ergebnis)."""

    _attr_icon = "mdi:flag-checkered"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_result", "Letztes Ergebnis")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("last_result", {}).get("raceName")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("last_result", {})
        return {
            "season": data.get("season"),
            "round": data.get("round"),
            "raceName": data.get("raceName"),
            "date": data.get("date"),
            "Results": data.get("Results", []),
        }


class F1LastQualifyingSensor(_F1BaseSensor):
    """Letztes Qualifying (entspricht sensor.f1_letztes_qualifying)."""

    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_qualifying", "Letztes Qualifying")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("last_qualifying", {}).get("raceName")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("last_qualifying", {})
        return {
            "season": data.get("season"),
            "round": data.get("round"),
            "raceName": data.get("raceName"),
            "QualifyingResults": data.get("QualifyingResults", []),
        }


class F1SessionStatusSensor(_F1BaseSensor):
    """Session-Status (entspricht sensor.f1_session_status)."""

    _attr_icon = "mdi:flag-checkered"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "session_status", "Session Status")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get("session_status", {}).get("state", "idle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get("session_status", {})
        return {
            "next_race": data.get("next_race"),
            "active_session": data.get("active_session"),
        }


class F1WeatherDailySensor(_F1BaseSensor):
    """Taegliches Wetter am naechsten Circuit (entspricht sensor.f1_wetter_vorhersage)."""

    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_native_unit_of_measurement = "°C"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "weather_daily", "Wetter Vorhersage")

    @property
    def native_value(self) -> float | None:
        daily = (self.coordinator.data.get("weather") or {}).get("daily", {})
        values = daily.get("temperature_2m_max", [])
        return values[0] if values else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = (self.coordinator.data.get("weather") or {}).get("daily", {})
        return {
            "time": daily.get("time", []),
            "temperature_2m_max": daily.get("temperature_2m_max", []),
            "temperature_2m_min": daily.get("temperature_2m_min", []),
            "precipitation_probability_max": daily.get("precipitation_probability_max", []),
            "weather_code": daily.get("weather_code", []),
        }


class F1WeatherHourlySensor(_F1BaseSensor):
    """Stuendliches Wetter am naechsten Circuit (entspricht sensor.f1_wetter_stuendlich)."""

    _attr_icon = "mdi:weather-partly-cloudy"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "weather_hourly", "Wetter Stuendlich")

    @property
    def native_value(self) -> str:
        hourly = (self.coordinator.data.get("weather") or {}).get("hourly", {})
        return "ok" if hourly.get("time") else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hourly = (self.coordinator.data.get("weather") or {}).get("hourly", {})
        return {
            "time": hourly.get("time", []),
            "temperature_2m": hourly.get("temperature_2m", []),
            "precipitation_probability": hourly.get("precipitation_probability", []),
            "weather_code": hourly.get("weather_code", []),
            "wind_speed_10m": hourly.get("wind_speed_10m", []),
        }


class F1RaceRecapSensor(_F1BaseSensor):
    """Rueckblick letztes Rennen: Ergebnis, Reifen, Boxenstopps (OpenF1)."""

    _attr_icon = "mdi:flag-checkered"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "race_recap", "Letztes Rennen (Detail)")

    @property
    def native_value(self) -> int:
        recap = self.coordinator.data.get("race_recap") or {}
        return len(recap.get("results", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        recap = self.coordinator.data.get("race_recap") or {}
        return {
            "session_key": recap.get("session_key"),
            "circuit_short_name": recap.get("circuit_short_name", ""),
            "country_name": recap.get("country_name", ""),
            "results": recap.get("results", []),
            "stints": recap.get("stints", []),
            "pit_stops": recap.get("pit_stops", []),
        }


class _F1LiveBaseSensor(SensorEntity):
    """Basis fuer Live-Sensoren: reagiert auf Push-Updates vom
    F1LiveDataManager statt auf den regulaeren Coordinator-Poll-Zyklus.

    Live-Daten aendern sich potenziell mehrmals pro Sekunde waehrend
    einer Session; das Standard-Coordinator-Polling (stuendlich) ist
    dafuer ungeeignet. Der Manager ruft stattdessen bei jeder neuen
    Nachricht einen Listener auf, der die Entity zum Aktualisieren
    veranlasst.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self, coordinator: F1DashboardCoordinator, entry: ConfigEntry, key: str, name: str
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "F1 Dashboard",
            "manufacturer": "Jolpica-F1 / Open-Meteo / OpenF1 / F1 Live Timing",
            "model": "Formel-1-Datenintegration",
        }
        self._unsub_live: Any = None

    async def async_added_to_hass(self) -> None:
        self._unsub_live = self._coordinator.live.add_listener(
            self._handle_live_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_live is not None:
            self._unsub_live()

    def _handle_live_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # Waehrend keine Session laeuft, sind Live-Sensoren bewusst
        # "unavailable" statt einen veralteten letzten Stand zu zeigen.
        return self._coordinator.live.is_active


class F1LiveTimingTowerSensor(_F1LiveBaseSensor):
    """Live-Positionen, Rundenzeiten und Gaps waehrend einer Session."""

    _attr_icon = "mdi:podium"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "live_timing_tower", "Live Timing Tower")

    @property
    def native_value(self) -> int:
        return len(self._coordinator.live.timing_tower)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"drivers": self._coordinator.live.timing_tower}


class F1LiveTrackStatusSensor(_F1LiveBaseSensor):
    """Aktueller Streckenstatus (gruen/gelb/Safety Car/rot) waehrend einer Session."""

    _attr_icon = "mdi:flag-variant"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "live_track_status", "Live Streckenstatus")

    @property
    def native_value(self) -> str | None:
        return self._coordinator.live.track_status.get("label")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._coordinator.live.track_status)


class F1LiveRaceControlSensor(_F1LiveBaseSensor):
    """Juengste Renn-Kontrollnachrichten (Strafen, Untersuchungen, Flaggen)."""

    _attr_icon = "mdi:message-alert"

    def __init__(self, coordinator: F1DashboardCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "live_race_control", "Live Renn-Kontrolle")

    @property
    def native_value(self) -> str | None:
        messages = self._coordinator.live.race_control_messages
        if not messages:
            return None
        return messages[-1].get("Message", "")[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"messages": self._coordinator.live.race_control_messages}
