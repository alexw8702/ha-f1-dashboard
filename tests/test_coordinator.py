"""Tests fuer Session-Logik und das Mapping der gesammelten Rennrueckblickdaten."""
from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from support import install_test_stubs

install_test_stubs()
api = importlib.import_module("custom_components.f1_dashboard.api")
coordinator_module = importlib.import_module("custom_components.f1_dashboard.coordinator")
F1DashboardCoordinator = coordinator_module.F1DashboardCoordinator


class _FixedDateTime(datetime):
    """UTC-Uhr fuer reproduzierbare Session-Grenzen."""

    current = datetime(2026, 5, 2, 13, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz: timezone | None = None) -> datetime:
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    """Prueft zentrale Datenverarbeitung ohne Netzwerk oder HA-Laufzeit."""

    def setUp(self) -> None:
        # Die getesteten Methoden brauchen nur eine Session; der produktive
        # Konstruktor startet dagegen HA-spezifische Timer und wird vermieden.
        self.coordinator = object.__new__(F1DashboardCoordinator)
        self.coordinator._session = object()
        self.coordinator._cached_race_recap = None
        self.coordinator._race_recap_trigger_key = None
        self.coordinator._cached_quali_sectors = {}
        self.coordinator._quali_sectors_session_key = None

    def test_session_status_marks_active_qualifying(self) -> None:
        calendar = {"Races": [{
            "date": "2026-05-03", "time": "13:00:00Z",
            "Qualifying": {"date": "2026-05-02", "time": "12:00:00Z"},
        }]}

        with patch.object(coordinator_module, "datetime", _FixedDateTime):
            status = self.coordinator._compute_session_status(calendar)

        self.assertEqual(status["state"], "active")
        self.assertEqual(status["active_session"], "Quali")
        self.assertEqual(status["next_race"], calendar["Races"][0])

    def test_session_status_ignores_finished_weekends(self) -> None:
        calendar = {"Races": [{"date": "2026-04-01", "time": "13:00:00Z"}]}

        with patch.object(coordinator_module, "datetime", _FixedDateTime):
            status = self.coordinator._compute_session_status(calendar)

        self.assertEqual(status, {"state": "idle", "next_race": None, "active_session": None})

    async def test_race_recap_maps_results_stints_and_pit_stops(self) -> None:
        last_result = {
            "season": "2026", "date": "2026-05-03",
            "Results": [{
                "number": "44", "position": "1",
                "Driver": {"givenName": "Lewis", "familyName": "Hamilton"},
                "Constructor": {"constructorId": "ferrari", "name": "Ferrari"},
            }],
        }
        with patch.object(api, "async_find_race_session", new=AsyncMock(return_value={
            "session_key": 42, "circuit_short_name": "Monaco", "country_name": "Monaco",
        })), patch.object(api, "async_get_session_result", new=AsyncMock(return_value=[{
            "driver_number": 44, "points": 25, "duration": 5423.123,
        }, {
            "driver_number": 99, "points": 0, "gap_to_leader": 12.5,
        }])), patch.object(api, "async_get_stints", new=AsyncMock(return_value=[
            {"driver_number": 44, "stint_number": 2, "compound": "HARD", "lap_end": 78},
            {"driver_number": 44, "stint_number": 1, "compound": "MEDIUM", "lap_end": 25},
        ])), patch.object(api, "async_get_pit_stops", new=AsyncMock(return_value=[
            {"driver_number": 44, "lap_number": 26, "stop_duration": 2.45},
        ])):
            recap = await self.coordinator._async_get_race_recap(last_result)

        self.assertEqual(recap["session_key"], 42)
        self.assertEqual(recap["results"][0]["driver"]["name"], "Lewis Hamilton")
        self.assertEqual(recap["results"][0]["time"], "1:30:23.123")
        self.assertEqual(recap["results"][1]["driver"]["name"], "Driver #99")
        self.assertEqual(recap["stints"][0]["compound"], ["MEDIUM", "HARD"])
        self.assertEqual(recap["pit_stops"][0]["duration"], "2.45s")

    async def test_openf1_part_failure_keeps_recap_available(self) -> None:
        result = await self.coordinator._async_get_openf1_part(
            AsyncMock(side_effect=api.F1ApiError("HTTP 429")), 42, "Boxenstopps"
        )

        self.assertEqual(result, [])

    async def test_unresolvable_driver_sorts_after_classified_winner(self) -> None:
        """Regressionstest: ein OpenF1-Fahrer ohne Jolpica-Zuordnung und ohne
        eigene Position darf nicht mit Position 0 vor dem bekannten Sieger
        einsortiert werden (siehe coordinator.py, pos = r.get("position") or 999)."""
        last_result = {
            "season": "2026", "date": "2026-05-03",
            "Results": [{
                "number": "1", "position": "1",
                "Driver": {"givenName": "Max", "familyName": "Verstappen"},
                "Constructor": {"constructorId": "red_bull", "name": "Red Bull"},
            }],
        }
        with patch.object(api, "async_find_race_session", new=AsyncMock(return_value={
            "session_key": 1, "circuit_short_name": "Miami", "country_name": "USA",
        })), patch.object(api, "async_get_session_result", new=AsyncMock(return_value=[
            # Bekannter Sieger zuerst in der OpenF1-Reihenfolge...
            {"driver_number": 1, "points": 25},
            # ...gefolgt von einem OpenF1-Fahrer ohne Jolpica-Zuordnung und
            # ohne eigene "position" (z.B. Reservefahrer/Testeinsatz).
            {"driver_number": 55, "points": 0},
        ])), patch.object(api, "async_get_stints", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_pit_stops", new=AsyncMock(return_value=[])):
            recap = await self.coordinator._async_get_race_recap(last_result)

        self.assertEqual(recap["results"][0]["driver"]["name"], "Max Verstappen")
        self.assertEqual(recap["results"][0]["position"], 1)
        self.assertEqual(recap["results"][1]["driver"]["name"], "Driver #55")
        self.assertEqual(recap["results"][1]["position"], 999)

    async def test_pit_stop_without_duration_shows_placeholder(self) -> None:
        last_result = {"season": "2026", "date": "2026-05-03", "Results": []}
        with patch.object(api, "async_find_race_session", new=AsyncMock(return_value={
            "session_key": 1, "circuit_short_name": "Miami", "country_name": "USA",
        })), patch.object(api, "async_get_session_result", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_stints", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_pit_stops", new=AsyncMock(return_value=[
                 {"driver_number": 1, "lap_number": 10},
             ])):
            recap = await self.coordinator._async_get_race_recap(last_result)

        self.assertEqual(recap["pit_stops"][0]["duration"], "–")

    async def test_stints_are_grouped_per_driver_and_sorted_by_position(self) -> None:
        last_result = {
            "season": "2026", "date": "2026-05-03",
            "Results": [
                {"number": "1", "position": "2", "Driver": {"givenName": "A", "familyName": "A"},
                 "Constructor": {"constructorId": "x", "name": "X"}},
                {"number": "2", "position": "1", "Driver": {"givenName": "B", "familyName": "B"},
                 "Constructor": {"constructorId": "y", "name": "Y"}},
            ],
        }
        with patch.object(api, "async_find_race_session", new=AsyncMock(return_value={
            "session_key": 1, "circuit_short_name": "Miami", "country_name": "USA",
        })), patch.object(api, "async_get_session_result", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_stints", new=AsyncMock(return_value=[
                 {"driver_number": 1, "stint_number": 1, "compound": "SOFT", "lap_end": 20},
                 {"driver_number": 2, "stint_number": 1, "compound": "MEDIUM", "lap_end": 30},
             ])), patch.object(api, "async_get_pit_stops", new=AsyncMock(return_value=[])):
            recap = await self.coordinator._async_get_race_recap(last_result)

        # Fahrer B (Position 1) muss vor Fahrer A (Position 2) stehen.
        self.assertEqual(recap["stints"][0]["driver"]["name"], "B B")
        self.assertEqual(recap["stints"][1]["driver"]["name"], "A A")

    async def test_race_recap_is_none_without_season_or_date(self) -> None:
        self.assertIsNone(await self.coordinator._async_get_race_recap({}))
        self.assertIsNone(
            await self.coordinator._async_get_race_recap({"season": "2026"})
        )

    async def test_race_recap_is_none_when_openf1_session_not_found(self) -> None:
        last_result = {"season": "2026", "date": "2026-05-03"}
        with patch.object(api, "async_find_race_session", new=AsyncMock(return_value=None)):
            recap = await self.coordinator._async_get_race_recap(last_result)

        self.assertIsNone(recap)

    async def test_race_recap_is_none_when_session_key_missing(self) -> None:
        last_result = {"season": "2026", "date": "2026-05-03"}
        with patch.object(api, "async_find_race_session", new=AsyncMock(return_value={
            "circuit_short_name": "Miami",
        })):
            recap = await self.coordinator._async_get_race_recap(last_result)

        self.assertIsNone(recap)

    async def test_weather_skipped_when_next_race_missing_coordinates(self) -> None:
        status_without_race = {"next_race": None}
        status_without_coords = {"next_race": {"Circuit": {"Location": {}}}}

        self.assertIsNone(
            await self.coordinator._async_get_weather_for_next_race(status_without_race)
        )
        self.assertIsNone(
            await self.coordinator._async_get_weather_for_next_race(status_without_coords)
        )

    def test_parse_session_dt_returns_none_for_invalid_input(self) -> None:
        self.assertIsNone(self.coordinator._parse_session_dt(None, "13:00:00Z"))
        self.assertIsNone(self.coordinator._parse_session_dt("not-a-date", "13:00:00Z"))

    def test_parse_session_dt_defaults_missing_time_to_midnight(self) -> None:
        dt = self.coordinator._parse_session_dt("2026-05-03", None)

        self.assertEqual(dt.hour, 0)
        self.assertEqual(dt.minute, 0)

    async def test_last_session_uses_qualifying_when_it_is_the_most_recent_started_session(self) -> None:
        calendar = {"Races": [{
            "season": "2026", "raceName": "Miami GP",
            "date": "2026-05-03", "time": "13:00:00Z",
            "Qualifying": {"date": "2026-05-02", "time": "12:00:00Z"},
        }]}
        last_qualifying = {"QualifyingResults": [{
            "position": "1", "Driver": {"code": "VER", "givenName": "Max", "familyName": "Verstappen"},
            "Constructor": {"name": "Red Bull"}, "Q3": "1:30.000",
        }]}

        with patch.object(coordinator_module, "datetime", _FixedDateTime):
            last_session = await self.coordinator._async_get_last_session(
                calendar, {}, last_qualifying
            )

        self.assertEqual(last_session["session_type"], "Qualifying")
        self.assertEqual(last_session["results"][0]["driver_code"], "VER")
        self.assertEqual(last_session["results"][0]["time_or_gap"], "1:30.000")

    async def test_last_session_uses_openf1_for_practice(self) -> None:
        calendar = {"Races": [{
            "season": "2026", "raceName": "Miami GP",
            "date": "2026-05-04", "time": "13:00:00Z",
            "FirstPractice": {"date": "2026-05-02", "time": "12:00:00Z"},
        }]}
        last_result = {"Results": [{
            "number": "1", "Driver": {"code": "VER", "givenName": "Max", "familyName": "Verstappen"},
            "Constructor": {"name": "Red Bull"},
        }]}

        with patch.object(coordinator_module, "datetime", _FixedDateTime), \
             patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 9})), \
             patch.object(api, "async_get_session_result", new=AsyncMock(return_value=[
                 {"driver_number": 1, "position": 1, "duration": 88.123},
             ])):
            last_session = await self.coordinator._async_get_last_session(
                calendar, last_result, {}
            )

        self.assertEqual(last_session["session_type"], "Practice 1")
        self.assertEqual(last_session["results"][0]["driver_code"], "VER")
        self.assertEqual(last_session["results"][0]["time_or_gap"], "88.123")

    async def test_last_session_is_none_without_any_started_session(self) -> None:
        calendar = {"Races": [{"date": "2026-06-01", "time": "13:00:00Z"}]}

        with patch.object(coordinator_module, "datetime", _FixedDateTime):
            last_session = await self.coordinator._async_get_last_session(calendar, {}, {})

        self.assertIsNone(last_session)

    GRID_CALENDAR = {"Races": [{
        "season": "2026", "round": "6", "raceName": "Miami GP",
        "date": "2026-05-04", "time": "13:00:00Z",
        "Qualifying": {"date": "2026-05-02", "time": "12:00:00Z"},
    }]}
    GRID_LAST_QUALIFYING = {
        "season": "2026", "round": "6", "raceName": "Miami GP",
        "QualifyingResults": [{
            "position": "1", "number": "1",
            "Driver": {"code": "VER", "givenName": "Max", "familyName": "Verstappen", "driverId": "max_verstappen"},
            "Constructor": {"name": "Red Bull"},
        }],
    }

    async def test_starting_grid_uses_openf1_starting_grid_when_published(self) -> None:
        # OpenF1s /starting_grid ist schon da (kurz nach dem Qualifying), obwohl das
        # Rennen selbst noch nicht gefahren wurde - das ist trotzdem final, nicht provisorisch.
        last_result = {"season": "2026", "round": "5"}
        self.coordinator.live = type("L", (), {"race_control_messages": []})()

        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})), \
             patch.object(api, "async_get_starting_grid", new=AsyncMock(return_value=[
                 {"driver_number": 1, "position": 4},
             ])), \
             patch.object(api, "async_get_race_control", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_laps", new=AsyncMock(return_value=[])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, self.GRID_LAST_QUALIFYING, self.GRID_CALENDAR
            )

        self.assertFalse(grid["provisional"])
        self.assertEqual(grid["grid"][0]["grid_position"], 4)
        self.assertEqual(grid["grid"][0]["quali_position"], 1)
        self.assertTrue(grid["grid"][0]["penalty"])

    async def test_starting_grid_falls_back_to_quali_order_when_openf1_grid_not_yet_published(self) -> None:
        last_result = {"season": "2026", "round": "5"}
        self.coordinator.live = type("L", (), {"race_control_messages": []})()

        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})), \
             patch.object(api, "async_get_starting_grid", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_race_control", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_laps", new=AsyncMock(return_value=[])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, self.GRID_LAST_QUALIFYING, self.GRID_CALENDAR
            )

        self.assertTrue(grid["provisional"])
        self.assertEqual(grid["grid"][0]["grid_position"], 1)
        self.assertEqual(grid["grid"][0]["quali_position"], 1)
        self.assertFalse(grid["grid"][0]["penalty"])

    async def test_starting_grid_prefers_race_result_once_the_race_has_run(self) -> None:
        last_result = {
            "season": "2026", "round": "6", "raceName": "Miami GP",
            "Results": [{
                "number": "1", "grid": "4",
                "Driver": {"code": "VER", "givenName": "Max", "familyName": "Verstappen", "driverId": "max_verstappen"},
                "Constructor": {"name": "Red Bull"},
            }],
        }
        # race_ran=True nimmt fuer grid_position den last_result-Pfad statt OpenF1s
        # /starting_grid - die Qualifying-session_key-Suche laeuft aber weiterhin, weil
        # auch diese Tier quali_time/sector_1..3 aus OpenF1s /v1/laps bekommen soll.
        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})), \
             patch.object(api, "async_get_laps", new=AsyncMock(return_value=[])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, self.GRID_LAST_QUALIFYING, self.GRID_CALENDAR
            )

        self.assertFalse(grid["provisional"])
        self.assertEqual(grid["grid"][0]["grid_position"], 4)
        self.assertEqual(grid["grid"][0]["quali_position"], 1)
        self.assertTrue(grid["grid"][0]["penalty"])

    async def test_starting_grid_none_without_qualifying_results(self) -> None:
        self.assertIsNone(await self.coordinator._async_build_starting_grid({}, {}, {"Races": []}))

    async def test_starting_grid_attaches_quali_time_and_sectors_from_openf1_laps(self) -> None:
        # quali_time kommt aus der bereits vorhandenen Jolpica Q3/Q2/Q1-Zuordnung,
        # sector_1..3 sind die einzige echte Neuerung: OpenF1s /v1/laps liefert mehrere
        # Runden je Fahrer, die schnellste gueltige (kein Boxenausfahrt, lap_duration
        # gesetzt) gewinnt.
        last_result = {"season": "2026", "round": "5"}
        self.coordinator.live = type("L", (), {"race_control_messages": []})()
        quali_with_time = {
            **self.GRID_LAST_QUALIFYING,
            "QualifyingResults": [{
                **self.GRID_LAST_QUALIFYING["QualifyingResults"][0],
                "Q3": "1:32.741",
            }],
        }

        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})),              patch.object(api, "async_get_starting_grid", new=AsyncMock(return_value=[
                 {"driver_number": 1, "position": 4},
             ])),              patch.object(api, "async_get_race_control", new=AsyncMock(return_value=[])),              patch.object(api, "async_get_laps", new=AsyncMock(return_value=[
                 {"driver_number": 1, "is_pit_out_lap": True, "lap_duration": 89.0,
                  "duration_sector_1": 27.0, "duration_sector_2": 30.0, "duration_sector_3": 32.0},
                 {"driver_number": 1, "is_pit_out_lap": False, "lap_duration": None,
                  "duration_sector_1": 26.0, "duration_sector_2": 29.0, "duration_sector_3": 31.0},
                 {"driver_number": 1, "is_pit_out_lap": False, "lap_duration": 92.741,
                  "duration_sector_1": 28.421, "duration_sector_2": 31.156, "duration_sector_3": 33.164},
                 {"driver_number": 1, "is_pit_out_lap": False, "lap_duration": 95.5,
                  "duration_sector_1": 29.0, "duration_sector_2": 32.0, "duration_sector_3": 34.5},
             ])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, quali_with_time, self.GRID_CALENDAR
            )

        row = grid["grid"][0]
        self.assertEqual(row["quali_time"], "1:32.741")
        self.assertEqual(row["sector_1"], "28.421")
        self.assertEqual(row["sector_2"], "31.156")
        self.assertEqual(row["sector_3"], "33.164")

    async def test_starting_grid_sectors_are_none_when_openf1_laps_missing(self) -> None:
        last_result = {"season": "2026", "round": "5"}
        self.coordinator.live = type("L", (), {"race_control_messages": []})()

        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})),              patch.object(api, "async_get_starting_grid", new=AsyncMock(return_value=[
                 {"driver_number": 1, "position": 1},
             ])),              patch.object(api, "async_get_race_control", new=AsyncMock(return_value=[])),              patch.object(api, "async_get_laps", new=AsyncMock(return_value=[])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, self.GRID_LAST_QUALIFYING, self.GRID_CALENDAR
            )

        row = grid["grid"][0]
        self.assertIsNone(row["sector_1"])
        self.assertIsNone(row["sector_2"])
        self.assertIsNone(row["sector_3"])

    async def test_quali_sectors_not_refetched_once_cached_for_same_session_key(self) -> None:
        # Kein neuer /v1/laps-Abruf mehr, sobald fuer diesen quali_session_key schon
        # erfolgreich Sektordaten im Cache stehen - siehe _async_get_quali_sectors.
        laps_mock = AsyncMock(return_value=[
            {"driver_number": 1, "is_pit_out_lap": False, "lap_duration": 90.0,
             "duration_sector_1": 28.0, "duration_sector_2": 30.0, "duration_sector_3": 32.0},
        ])
        with patch.object(api, "async_get_laps", new=laps_mock):
            first = await self.coordinator._async_get_quali_sectors(42)
            second = await self.coordinator._async_get_quali_sectors(42)

        self.assertEqual(first, second)
        laps_mock.assert_called_once()

    async def test_quali_sectors_refetch_when_session_key_changes(self) -> None:
        laps_mock = AsyncMock(return_value=[
            {"driver_number": 1, "is_pit_out_lap": False, "lap_duration": 90.0,
             "duration_sector_1": 28.0, "duration_sector_2": 30.0, "duration_sector_3": 32.0},
        ])
        with patch.object(api, "async_get_laps", new=laps_mock):
            await self.coordinator._async_get_quali_sectors(42)
            await self.coordinator._async_get_quali_sectors(43)

        self.assertEqual(laps_mock.await_count, 2)

    async def test_quali_sectors_empty_response_is_not_cached_and_retries_next_cycle(self) -> None:
        laps_mock = AsyncMock(return_value=[])
        with patch.object(api, "async_get_laps", new=laps_mock):
            first = await self.coordinator._async_get_quali_sectors(42)
            second = await self.coordinator._async_get_quali_sectors(42)

        self.assertEqual(first, {})
        self.assertEqual(second, {})
        self.assertEqual(laps_mock.await_count, 2)

    async def test_penalty_note_from_historical_openf1_race_control_when_no_live_session(self) -> None:
        # Niemand hat live zugehoert (leere race_control_messages) - die historische
        # OpenF1-Race-Control-Suche (driver_number-Join, kein Rateversuch) greift trotzdem.
        last_result = {"season": "2026", "round": "5"}
        self.coordinator.live = type("L", (), {"race_control_messages": []})()

        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})), \
             patch.object(api, "async_get_starting_grid", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_race_control", new=AsyncMock(return_value=[
                 {"driver_number": 1, "message": "CAR 1 (VER) GIVEN A 3-PLACE GRID PENALTY"},
             ])), \
             patch.object(api, "async_get_laps", new=AsyncMock(return_value=[])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, self.GRID_LAST_QUALIFYING, self.GRID_CALENDAR
            )

        self.assertTrue(grid["grid"][0]["penalty"])
        self.assertIn("GRID PENALTY", grid["grid"][0]["penalty_note"])

    async def test_penalty_note_stays_none_without_a_matching_race_control_row(self) -> None:
        last_result = {"season": "2026", "round": "5"}
        self.coordinator.live = type("L", (), {"race_control_messages": []})()

        with patch.object(api, "async_find_session", new=AsyncMock(return_value={"session_key": 42})), \
             patch.object(api, "async_get_starting_grid", new=AsyncMock(return_value=[])), \
             patch.object(api, "async_get_race_control", new=AsyncMock(return_value=[
                 {"driver_number": 1, "message": "TRACK LIMITS WARNING FOR CAR 1"},
             ])), \
             patch.object(api, "async_get_laps", new=AsyncMock(return_value=[])):
            grid = await self.coordinator._async_build_starting_grid(
                last_result, self.GRID_LAST_QUALIFYING, self.GRID_CALENDAR
            )

        self.assertFalse(grid["grid"][0]["penalty"])
        self.assertIsNone(grid["grid"][0]["penalty_note"])

    def test_live_penalty_note_matches_driver_code_and_keyword(self) -> None:
        self.coordinator.live = type("L", (), {"race_control_messages": [
            {"Message": "CAR 1 (VER) 5 SECOND TIME PENALTY - GRID PENALTY"},
        ]})()

        note = self.coordinator._find_live_penalty_note("VER", "Max Verstappen")

        self.assertIn("PENALTY", note)

    def test_live_penalty_note_is_none_without_a_matching_message(self) -> None:
        self.coordinator.live = type("L", (), {"race_control_messages": [
            {"Message": "TRACK LIMITS AT TURN 4 FOR CAR 44 (HAM)"},
        ]})()

        self.assertIsNone(self.coordinator._find_live_penalty_note("VER", "Max Verstappen"))


class LiveStatusCheckTests(unittest.IsolatedAsyncioTestCase):
    """_async_check_live_status laeuft minuetlich (siehe __init__), unabhaengig vom
    stuendlichen Haupt-Poll, und muss sowohl die Live-Verbindung als auch
    self.data["session_status"] aktuell halten - Sensoren lesen ausschliesslich
    self.data, nicht self._cached_session_status direkt (siehe sensor.py)."""

    class _FakeLive:
        def __init__(self) -> None:
            self.active_calls: list[bool] = []

        async def async_set_active(self, active: bool) -> None:
            self.active_calls.append(active)

    def setUp(self) -> None:
        self.coordinator = object.__new__(F1DashboardCoordinator)
        self.coordinator.live = self._FakeLive()
        self.coordinator._cached_session_status = {
            "state": "idle", "next_race": None, "active_session": None,
        }

    async def test_updates_data_and_notifies_listeners_when_status_changes(self) -> None:
        calendar = {"Races": [{
            "date": "2026-05-03", "time": "13:00:00Z",
            "Qualifying": {"date": "2026-05-02", "time": "12:00:00Z"},
        }]}
        self.coordinator.data = {
            "calendar": calendar,
            "session_status": {"state": "idle", "next_race": None, "active_session": None},
        }
        notified = []
        self.coordinator.async_update_listeners = lambda: notified.append(self.coordinator.data)

        with patch.object(coordinator_module, "datetime", _FixedDateTime):
            await self.coordinator._async_check_live_status()

        self.assertEqual(self.coordinator.data["session_status"]["state"], "active")
        self.assertEqual(self.coordinator.data["session_status"]["active_session"], "Quali")
        self.assertEqual(len(notified), 1, "async_set_updated_data haette Listener benachrichtigen muessen")
        self.assertEqual(self.coordinator.live.active_calls, [True])

    async def test_no_listener_notification_when_status_is_unchanged(self) -> None:
        calendar = {"Races": [{"date": "2026-04-01", "time": "13:00:00Z"}]}
        unchanged = {"state": "idle", "next_race": None, "active_session": None}
        self.coordinator.data = {"calendar": calendar, "session_status": dict(unchanged)}
        notified = []
        self.coordinator.async_update_listeners = lambda: notified.append(True)

        with patch.object(coordinator_module, "datetime", _FixedDateTime):
            await self.coordinator._async_check_live_status()

        self.assertEqual(notified, [], "unveraenderter Status haette keine Benachrichtigung ausloesen duerfen")
        self.assertEqual(self.coordinator.live.active_calls, [False])

    async def test_before_first_refresh_only_toggles_live_connection(self) -> None:
        self.coordinator.data = None

        await self.coordinator._async_check_live_status()

        self.assertEqual(self.coordinator.live.active_calls, [False])


class RaceRecapCachingTests(unittest.IsolatedAsyncioTestCase):
    """Der OpenF1-Rennrueckblick wird nur bei Erstinitialisierung oder einer Aenderung
    von last_result/session_status neu abgerufen (siehe __init__/_async_update_data) -
    nicht mehr bei jedem stuendlichen Poll-Zyklus, um die rate-limitierte OpenF1-API
    nicht unnoetig zu belasten."""

    def setUp(self) -> None:
        self.coordinator = object.__new__(F1DashboardCoordinator)
        self.coordinator._session = object()
        self.coordinator._cached_race_recap = None
        self.coordinator._race_recap_trigger_key = None
        self.coordinator._cached_quali_sectors = {}
        self.coordinator._quali_sectors_session_key = None

    LAST_RESULT = {"season": "2026", "date": "2026-05-03"}
    SESSION_STATUS_IDLE = {"state": "idle", "active_session": None}
    SESSION_STATUS_ACTIVE = {"state": "active", "active_session": "Rennen"}

    # Ein "vollstaendiger" Rueckblick braucht mindestens nicht-leere results, damit der
    # Trigger-Schluessel committed wird (siehe _async_get_race_recap_if_needed) - stints/
    # pit_stops sind fuer diese Tests irrelevant und werden weggelassen.
    COMPLETE_RECAP_1 = {"session_key": 1, "results": [{"position": 1}]}
    COMPLETE_RECAP_2 = {"session_key": 2, "results": [{"position": 1}]}

    async def test_first_call_always_fetches_even_without_prior_state(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap", new=AsyncMock(return_value=self.COMPLETE_RECAP_1)
        ) as fetch:
            recap = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        fetch.assert_awaited_once()
        self.assertEqual(recap, self.COMPLETE_RECAP_1)

    async def test_unchanged_last_result_and_session_status_reuses_cache(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap", new=AsyncMock(return_value=self.COMPLETE_RECAP_1)
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        fetch.assert_awaited_once()  # kein zweiter Abruf trotz zweitem Aufruf
        self.assertEqual(second, self.COMPLETE_RECAP_1)

    async def test_session_status_change_triggers_a_new_fetch(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[self.COMPLETE_RECAP_1, self.COMPLETE_RECAP_2]),
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_ACTIVE
            )

        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(second, self.COMPLETE_RECAP_2)

    async def test_last_result_change_triggers_a_new_fetch_even_with_unchanged_status(self) -> None:
        # Randfall: state bleibt z.B. "idle" fuer zwei aufeinanderfolgende Rennen,
        # aber last_result (das naechste Rennergebnis) hat sich geaendert.
        new_last_result = {"season": "2026", "date": "2026-05-17"}
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[self.COMPLETE_RECAP_1, self.COMPLETE_RECAP_2]),
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            second = await self.coordinator._async_get_race_recap_if_needed(
                new_last_result, self.SESSION_STATUS_IDLE
            )

        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(second, self.COMPLETE_RECAP_2)

    async def test_failed_refetch_falls_back_to_last_known_good_cache(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[self.COMPLETE_RECAP_1, api.F1ApiError("HTTP 429")]),
        ):
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            # Session-Status-Aenderung triggert einen neuen Versuch, der fehlschlaegt.
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_ACTIVE
            )

        self.assertEqual(second, self.COMPLETE_RECAP_1, "letzter guter Stand haette erhalten bleiben muessen")

    async def test_failed_first_call_returns_none_without_prior_cache(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=api.F1ApiError("HTTP 500")),
        ):
            recap = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        self.assertIsNone(recap)

    async def test_empty_results_are_not_cached_and_keep_retrying_every_cycle(self) -> None:
        # Regressionstest: kurz nach Rennende hat OpenF1 haeufig noch keine/unvollstaendige
        # Daten (Ingestion-Verzoegerung). _async_get_race_recap wirft dabei KEINEN Fehler
        # (die Teilabrufe fangen ihre eigenen Fehler ab, siehe _async_get_openf1_part),
        # sondern liefert einfach leere results. Ohne die results-Pruefung wuerde der
        # Trigger-Schluessel trotzdem committed und die Karte bliebe bis zum naechsten
        # Rennwochenende auf diesem leeren Stand haengen, da last_result/session_status
        # sich bis dahin nicht mehr aendern.
        empty_recap = {"session_key": 1, "results": [], "stints": [], "pit_stops": []}
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[empty_recap, empty_recap, self.COMPLETE_RECAP_1]),
        ) as fetch:
            first = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            # last_result/session_status unveraendert - trotzdem erneuter Abruf, weil der
            # vorherige Versuch keine results geliefert hat (Trigger-Schluessel nicht committed).
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            third = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            # Jetzt liegen results vor -> ab hier darf der Cache greifen.
            fourth = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        self.assertEqual(fetch.await_count, 3, "vierter Aufruf haette aus dem Cache bedient werden muessen")
        self.assertEqual(first, empty_recap)
        self.assertEqual(second, empty_recap)
        self.assertEqual(third, self.COMPLETE_RECAP_1)
        self.assertEqual(fourth, self.COMPLETE_RECAP_1)

    async def test_recap_without_results_key_is_treated_as_incomplete(self) -> None:
        # last_result ohne Season/Datum (z.B. ganz frueh in der Saison) laesst
        # _async_get_race_recap None zurueckgeben - auch das darf den Trigger-Schluessel
        # nicht committen, sonst bleibt "kein Rueckblick" dauerhaft eingefroren, sobald
        # doch noch ein Rennen stattfindet und last_result sich eigentlich aendert... aber
        # in diesem Test bleibt last_result absichtlich gleich, um nur die Cache-Bedingung
        # fuer recap=None zu pruefen.
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[None, None]),
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                {}, self.SESSION_STATUS_IDLE
            )
            await self.coordinator._async_get_race_recap_if_needed(
                {}, self.SESSION_STATUS_IDLE
            )

        self.assertEqual(fetch.await_count, 2, "recap=None haette nie gecached werden duerfen")


if __name__ == "__main__":
    unittest.main()
