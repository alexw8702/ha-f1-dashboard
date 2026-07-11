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

    LAST_RESULT = {"season": "2026", "date": "2026-05-03"}
    SESSION_STATUS_IDLE = {"state": "idle", "active_session": None}
    SESSION_STATUS_ACTIVE = {"state": "active", "active_session": "Rennen"}

    async def test_first_call_always_fetches_even_without_prior_state(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap", new=AsyncMock(return_value={"session_key": 1})
        ) as fetch:
            recap = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        fetch.assert_awaited_once()
        self.assertEqual(recap, {"session_key": 1})

    async def test_unchanged_last_result_and_session_status_reuses_cache(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap", new=AsyncMock(return_value={"session_key": 1})
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        fetch.assert_awaited_once()  # kein zweiter Abruf trotz zweitem Aufruf
        self.assertEqual(second, {"session_key": 1})

    async def test_session_status_change_triggers_a_new_fetch(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[{"session_key": 1}, {"session_key": 2}]),
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_ACTIVE
            )

        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(second, {"session_key": 2})

    async def test_last_result_change_triggers_a_new_fetch_even_with_unchanged_status(self) -> None:
        # Randfall: state bleibt z.B. "idle" fuer zwei aufeinanderfolgende Rennen,
        # aber last_result (das naechste Rennergebnis) hat sich geaendert.
        new_last_result = {"season": "2026", "date": "2026-05-17"}
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[{"session_key": 1}, {"session_key": 2}]),
        ) as fetch:
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            second = await self.coordinator._async_get_race_recap_if_needed(
                new_last_result, self.SESSION_STATUS_IDLE
            )

        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(second, {"session_key": 2})

    async def test_failed_refetch_falls_back_to_last_known_good_cache(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=[{"session_key": 1}, api.F1ApiError("HTTP 429")]),
        ):
            await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )
            # Session-Status-Aenderung triggert einen neuen Versuch, der fehlschlaegt.
            second = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_ACTIVE
            )

        self.assertEqual(second, {"session_key": 1}, "letzter guter Stand haette erhalten bleiben muessen")

    async def test_failed_first_call_returns_none_without_prior_cache(self) -> None:
        with patch.object(
            self.coordinator, "_async_get_race_recap",
            new=AsyncMock(side_effect=api.F1ApiError("HTTP 500")),
        ):
            recap = await self.coordinator._async_get_race_recap_if_needed(
                self.LAST_RESULT, self.SESSION_STATUS_IDLE
            )

        self.assertIsNone(recap)


if __name__ == "__main__":
    unittest.main()
