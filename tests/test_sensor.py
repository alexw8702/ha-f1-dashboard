"""Tests fuer die Attribut-Vertraege der Sensoren.

Fokus: die 'standings'-Flattening-Logik (Grundlage fuer die Vue-3-Karten)
und die uebrigen extra_state_attributes/native_value-Eigenschaften duerfen
sich nicht unbemerkt aendern - eine falsche Flattening-Struktur hier war
bereits einmal ein realer Bug (siehe CHANGELOG v0.3.2).
"""
from __future__ import annotations

import importlib
import unittest
from typing import Any

from support import ConfigEntry, install_test_stubs

install_test_stubs()
sensor_module = importlib.import_module("custom_components.f1_dashboard.sensor")


class _FakeCoordinator:
    """Traegt nur das data-Dict, das die Sensoren lesen."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class _FakeLive:
    """Ersatz fuer F1LiveDataManager, wie von den Live-Sensoren gelesen."""

    def __init__(self, **attrs: Any) -> None:
        self.timing_tower: list[dict[str, Any]] = attrs.get("timing_tower", [])
        self.track_status: dict[str, Any] = attrs.get("track_status", {})
        self.race_control_messages: list[dict[str, Any]] = attrs.get(
            "race_control_messages", []
        )
        self.position_bounds: dict[str, float] = attrs.get("position_bounds", {})
        self.is_active: bool = attrs.get("is_active", True)
        self._positions = attrs.get("positions", [])

    def get_track_positions(self) -> list[dict[str, Any]]:
        return self._positions


class _FakeLiveCoordinator:
    """Traegt nur das live-Attribut, das die Live-Sensoren lesen."""

    def __init__(self, live: _FakeLive) -> None:
        self.live = live


ENTRY = ConfigEntry("entry-1")


class StandingsSensorTests(unittest.TestCase):
    def test_driver_standings_flattens_points_wins_and_team(self) -> None:
        coordinator = _FakeCoordinator({
            "driver_standings": {
                "season": "2026", "round": "5",
                "DriverStandings": [
                    {
                        "points": "44.0", "wins": "3",
                        "Driver": {
                            "givenName": "Max", "familyName": "Verstappen",
                            "code": "VER", "nationality": "Dutch",
                        },
                        "Constructors": [{"name": "Red Bull", "constructorId": "red_bull"}],
                    },
                    {
                        # Kein Constructors-Eintrag (z.B. Fahrerwechsel) + Kommastellen-Punkte
                        "points": "12.5", "wins": "0",
                        "Driver": {"givenName": "Foo", "familyName": "Bar"},
                        "Constructors": [],
                    },
                ],
            }
        })
        sensor = sensor_module.F1DriverStandingsSensor(coordinator, ENTRY)

        attrs = sensor.extra_state_attributes
        standings = attrs["standings"]

        self.assertEqual(attrs["season"], "2026")
        self.assertEqual(attrs["round"], "5")
        self.assertEqual(len(standings), 2)

        first = standings[0]
        self.assertEqual(first["name"], "Max Verstappen")
        self.assertEqual(first["team"], "Red Bull")
        self.assertEqual(first["teamId"], "red_bull")
        self.assertEqual(first["tla"], "VER")
        self.assertEqual(first["nationality"], "Dutch")
        # Ganzzahlige Punkte muessen als int vorliegen (Card-seitige Formatierung).
        self.assertIsInstance(first["points"], int)
        self.assertEqual(first["points"], 44)
        self.assertIsInstance(first["wins"], int)

        second = standings[1]
        self.assertEqual(second["team"], "–")
        self.assertEqual(second["teamId"], "")
        # Punkte mit Nachkommastellen bleiben float.
        self.assertIsInstance(second["points"], float)
        self.assertEqual(second["points"], 12.5)

        self.assertEqual(sensor.native_value, "Max Verstappen")

    def test_driver_standings_handles_malformed_points_gracefully(self) -> None:
        coordinator = _FakeCoordinator({
            "driver_standings": {
                "DriverStandings": [{
                    "points": "n/a", "wins": "?",
                    "Driver": {"givenName": "X", "familyName": "Y"},
                    "Constructors": [],
                }],
            }
        })
        sensor = sensor_module.F1DriverStandingsSensor(coordinator, ENTRY)

        standings = sensor.extra_state_attributes["standings"]
        self.assertEqual(standings[0]["points"], 0)
        self.assertEqual(standings[0]["wins"], 0)

    def test_driver_standings_native_value_none_when_empty(self) -> None:
        coordinator = _FakeCoordinator({"driver_standings": {"DriverStandings": []}})
        sensor = sensor_module.F1DriverStandingsSensor(coordinator, ENTRY)

        self.assertIsNone(sensor.native_value)
        self.assertEqual(sensor.extra_state_attributes["standings"], [])

    def test_constructor_standings_flattens_points_and_wins(self) -> None:
        coordinator = _FakeCoordinator({
            "constructor_standings": {
                "season": "2026", "round": "5",
                "ConstructorStandings": [{
                    "points": "300.0", "wins": "5",
                    "Constructor": {"name": "McLaren", "constructorId": "mclaren"},
                }],
            }
        })
        sensor = sensor_module.F1ConstructorStandingsSensor(coordinator, ENTRY)

        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["standings"][0]["name"], "McLaren")
        self.assertEqual(attrs["standings"][0]["points"], 300)
        self.assertIsInstance(attrs["standings"][0]["points"], int)
        self.assertEqual(sensor.native_value, "McLaren")


class PassthroughSensorTests(unittest.TestCase):
    """Diese Sensoren reichen Jolpica-Rohdaten nahezu unveraendert durch -
    der Vertrag (welche Keys existieren) muss trotzdem stabil bleiben, weil
    Automationen/Templates direkt darauf zugreifen koennen."""

    def test_calendar_sensor_counts_races_and_passes_season(self) -> None:
        coordinator = _FakeCoordinator({
            "calendar": {"season": "2026", "Races": [{"round": "1"}, {"round": "2"}]}
        })
        sensor = sensor_module.F1CalendarSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, 2)
        self.assertEqual(sensor.extra_state_attributes["season"], "2026")

    def test_last_result_sensor_exposes_race_name_and_results(self) -> None:
        coordinator = _FakeCoordinator({
            "last_result": {
                "season": "2026", "round": "5", "raceName": "Monaco Grand Prix",
                "date": "2026-05-03", "Results": [{"position": "1"}],
            }
        })
        sensor = sensor_module.F1LastResultSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "Monaco Grand Prix")
        self.assertEqual(sensor.extra_state_attributes["Results"], [{"position": "1"}])

    def test_last_qualifying_sensor_defaults_to_empty_list(self) -> None:
        coordinator = _FakeCoordinator({"last_qualifying": {}})
        sensor = sensor_module.F1LastQualifyingSensor(coordinator, ENTRY)

        self.assertIsNone(sensor.native_value)
        self.assertEqual(sensor.extra_state_attributes["QualifyingResults"], [])

    def test_session_status_sensor_exposes_state_and_active_session(self) -> None:
        coordinator = _FakeCoordinator({
            "session_status": {
                "state": "active", "next_race": {"round": "5"}, "active_session": "Quali",
            }
        })
        sensor = sensor_module.F1SessionStatusSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "active")
        self.assertEqual(sensor.extra_state_attributes["active_session"], "Quali")

    def test_session_status_sensor_defaults_to_idle_when_missing(self) -> None:
        coordinator = _FakeCoordinator({})
        sensor = sensor_module.F1SessionStatusSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "idle")

    def test_race_recap_sensor_handles_none_recap(self) -> None:
        coordinator = _FakeCoordinator({"race_recap": None})
        sensor = sensor_module.F1RaceRecapSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, 0)
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["results"], [])
        self.assertEqual(attrs["stints"], [])
        self.assertEqual(attrs["pit_stops"], [])

    def test_race_recap_sensor_counts_results(self) -> None:
        coordinator = _FakeCoordinator({
            "race_recap": {"results": [{"position": 1}, {"position": 2}], "stints": [], "pit_stops": []}
        })
        sensor = sensor_module.F1RaceRecapSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, 2)


class LastSessionAndStartingGridSensorTests(unittest.TestCase):
    def test_last_session_sensor_exposes_flat_results(self) -> None:
        coordinator = _FakeCoordinator({
            "last_session": {
                "session_type": "Qualifying", "session_name": "Miami GP - Quali",
                "date": "2026-05-02",
                "results": [{"position": 1, "driver_code": "VER"}],
            }
        })
        sensor = sensor_module.F1LastSessionSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "Qualifying")
        self.assertEqual(sensor.extra_state_attributes["results"][0]["driver_code"], "VER")

    def test_last_session_sensor_handles_missing_data(self) -> None:
        coordinator = _FakeCoordinator({})
        sensor = sensor_module.F1LastSessionSensor(coordinator, ENTRY)

        self.assertIsNone(sensor.native_value)
        self.assertEqual(sensor.extra_state_attributes["results"], [])

    def test_starting_grid_sensor_exposes_provisional_flag_and_grid(self) -> None:
        coordinator = _FakeCoordinator({
            "starting_grid": {
                "season": "2026", "round": "6", "raceName": "Miami GP",
                "provisional": True,
                "grid": [{"grid_position": 1, "quali_position": 1, "penalty": False}],
            }
        })
        sensor = sensor_module.F1StartingGridSensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "Miami GP")
        self.assertTrue(sensor.extra_state_attributes["provisional"])
        self.assertEqual(len(sensor.extra_state_attributes["grid"]), 1)

    def test_starting_grid_sensor_handles_missing_data(self) -> None:
        coordinator = _FakeCoordinator({"starting_grid": None})
        sensor = sensor_module.F1StartingGridSensor(coordinator, ENTRY)

        self.assertIsNone(sensor.native_value)
        self.assertEqual(sensor.extra_state_attributes["grid"], [])


class WeatherSensorTests(unittest.TestCase):
    def test_daily_sensor_reads_first_max_temperature(self) -> None:
        coordinator = _FakeCoordinator({
            "weather": {"daily": {"temperature_2m_max": [21.5, 22.0], "time": ["2026-05-01"]}}
        })
        sensor = sensor_module.F1WeatherDailySensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, 21.5)
        self.assertEqual(sensor.extra_state_attributes["time"], ["2026-05-01"])

    def test_daily_sensor_handles_missing_weather(self) -> None:
        coordinator = _FakeCoordinator({"weather": None})
        sensor = sensor_module.F1WeatherDailySensor(coordinator, ENTRY)

        self.assertIsNone(sensor.native_value)
        self.assertEqual(sensor.extra_state_attributes["time"], [])

    def test_hourly_sensor_reports_ok_when_data_present(self) -> None:
        coordinator = _FakeCoordinator({
            "weather": {"hourly": {"time": ["2026-05-01T12:00"], "wind_speed_10m": [12]}}
        })
        sensor = sensor_module.F1WeatherHourlySensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "ok")
        self.assertEqual(sensor.extra_state_attributes["wind_speed_10m"], [12])

    def test_hourly_sensor_reports_unknown_when_missing(self) -> None:
        coordinator = _FakeCoordinator({"weather": None})
        sensor = sensor_module.F1WeatherHourlySensor(coordinator, ENTRY)

        self.assertEqual(sensor.native_value, "unknown")


class LiveSensorTests(unittest.TestCase):
    def test_timing_tower_sensor_exposes_driver_count_and_list(self) -> None:
        live = _FakeLive(timing_tower=[{"driver_number": "1"}, {"driver_number": "44"}])
        sensor = sensor_module.F1LiveTimingTowerSensor(_FakeLiveCoordinator(live), ENTRY)

        self.assertEqual(sensor.native_value, 2)
        self.assertEqual(sensor.extra_state_attributes["drivers"], live.timing_tower)

    def test_track_status_sensor_reads_label(self) -> None:
        live = _FakeLive(track_status={"status": "2", "label": "Gelb", "message": None})
        sensor = sensor_module.F1LiveTrackStatusSensor(_FakeLiveCoordinator(live), ENTRY)

        self.assertEqual(sensor.native_value, "Gelb")

    def test_race_control_sensor_truncates_message_and_uses_latest(self) -> None:
        long_message = "x" * 300
        live = _FakeLive(race_control_messages=[{"Message": "erste"}, {"Message": long_message}])
        sensor = sensor_module.F1LiveRaceControlSensor(_FakeLiveCoordinator(live), ENTRY)

        self.assertEqual(sensor.native_value, long_message[:255])
        self.assertEqual(len(sensor.native_value), 255)

    def test_race_control_sensor_none_when_no_messages(self) -> None:
        live = _FakeLive(race_control_messages=[])
        sensor = sensor_module.F1LiveRaceControlSensor(_FakeLiveCoordinator(live), ENTRY)

        self.assertIsNone(sensor.native_value)

    def test_track_positions_sensor_exposes_positions_and_bounds(self) -> None:
        live = _FakeLive(
            positions=[{"driver_number": "1", "x": 10, "y": 20}],
            position_bounds={"min_x": 0, "max_x": 10, "min_y": 0, "max_y": 20},
        )
        sensor = sensor_module.F1LiveTrackPositionsSensor(_FakeLiveCoordinator(live), ENTRY)

        self.assertEqual(sensor.native_value, 1)
        self.assertEqual(sensor.extra_state_attributes["positions"], live._positions)
        self.assertEqual(sensor.extra_state_attributes["bounds"], live.position_bounds)

    def test_live_sensor_availability_follows_manager_active_flag(self) -> None:
        live = _FakeLive(is_active=False)
        sensor = sensor_module.F1LiveTimingTowerSensor(_FakeLiveCoordinator(live), ENTRY)

        self.assertFalse(sensor.available)


if __name__ == "__main__":
    unittest.main()
