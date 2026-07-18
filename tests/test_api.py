"""Tests fuer das Parsen und die Fehlerbehandlung der externen F1-APIs."""
from __future__ import annotations

import asyncio
import importlib
import unittest
from unittest.mock import AsyncMock, patch

from support import FakeResponse, FakeSession, install_test_stubs

install_test_stubs()
api = importlib.import_module("custom_components.f1_dashboard.api")


class ApiTests(unittest.IsolatedAsyncioTestCase):
    """Prueft API-Payloads mit aufgezeichneten, deterministischen Antworten."""

    async def test_jolpica_standings_and_calendar_are_flattened(self) -> None:
        session = FakeSession([
            FakeResponse(200, {"MRData": {"StandingsTable": {"StandingsLists": [{
                "season": "2026", "round": "4", "DriverStandings": [{"position": "1"}],
            }]}}}),
            FakeResponse(200, {"MRData": {"StandingsTable": {"StandingsLists": [{
                "season": "2026", "round": "4", "ConstructorStandings": [{"position": "1"}],
            }]}}}),
            FakeResponse(200, {"MRData": {"RaceTable": {"season": "2026", "Races": [{"round": "1"}]}}}),
        ])

        drivers = await api.async_get_driver_standings(session)
        constructors = await api.async_get_constructor_standings(session)
        calendar = await api.async_get_race_calendar(session)

        self.assertEqual(drivers, {"season": "2026", "round": "4", "DriverStandings": [{"position": "1"}]})
        self.assertEqual(constructors["ConstructorStandings"], [{"position": "1"}])
        self.assertEqual(calendar, {"season": "2026", "Races": [{"round": "1"}]})
        self.assertTrue(session.calls[0]["url"].endswith("/current/driverStandings.json"))

    async def test_empty_jolpica_responses_have_stable_schema(self) -> None:
        session = FakeSession([
            FakeResponse(200, {"MRData": {"StandingsTable": {"StandingsLists": []}}}),
            FakeResponse(200, {"MRData": {"RaceTable": {"Races": []}}}),
        ])

        self.assertEqual(
            await api.async_get_driver_standings(session),
            {"season": None, "round": None, "DriverStandings": []},
        )
        self.assertEqual(await api.async_get_last_result(session), {})

    async def test_weather_passes_daily_and_hourly_contract(self) -> None:
        session = FakeSession([FakeResponse(200, {
            "daily": {"time": ["2026-05-01"], "weather_code": [1]},
            "hourly": {"time": ["2026-05-01T12:00"], "wind_speed_10m": [12]},
        })])

        weather = await api.async_get_weather(session, "50.4", "5.9")

        self.assertEqual(weather["daily"]["weather_code"], [1])
        self.assertEqual(weather["hourly"]["wind_speed_10m"], [12])
        self.assertEqual(session.calls[0]["params"]["latitude"], "50.4")
        self.assertIn("wind_speed_10m", session.calls[0]["params"]["hourly"])

    async def test_openf1_session_url_keeps_comparison_operators(self) -> None:
        session = FakeSession([FakeResponse(200, [{"session_key": 99}])])

        found = await api.async_find_race_session(session, "2026", "2026-05-03")

        self.assertEqual(found, {"session_key": 99})
        self.assertIn("date_start>=2026-05-03", session.calls[0]["url"])
        self.assertIn("date_start<=2026-05-03T23:59:59", session.calls[0]["url"])

    async def test_openf1_rate_limit_retries_once(self) -> None:
        with patch.object(
            api, "_get_json", new=AsyncMock(side_effect=[
                api.F1ApiError("HTTP 429 von OpenF1"), {"ok": True},
            ])
        ) as get_json, patch.object(api.asyncio, "sleep", new=AsyncMock()) as sleep:
            result = await api._get_json_with_retry(object(), "https://example.invalid")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(get_json.await_count, 2)
        sleep.assert_awaited_once_with(api._RETRY_DELAY)

    async def test_non_retryable_error_is_not_retried(self) -> None:
        # HTTP 404 (z.B. falsche Season) ist kein transientes Problem - ein
        # Retry wuerde nur unnoetig Zeit kosten, der Fehler muss direkt durch.
        with patch.object(
            api, "_get_json", new=AsyncMock(side_effect=api.F1ApiError("HTTP 404 von Jolpica"))
        ) as get_json, patch.object(api.asyncio, "sleep", new=AsyncMock()) as sleep:
            with self.assertRaises(api.F1ApiError):
                await api._get_json_with_retry(object(), "https://example.invalid")

        get_json.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_non_200_status_raises_f1_api_error(self) -> None:
        session = FakeSession([FakeResponse(503, {"error": "unavailable"})])

        with self.assertRaises(api.F1ApiError):
            await api._get_json(session, "https://example.invalid")

    async def test_find_session_accepts_arbitrary_session_name(self) -> None:
        session = FakeSession([FakeResponse(200, [{"session_key": 7}])])

        found = await api.async_find_session(session, "2026", "2026-05-02", "Practice 1")

        self.assertEqual(found, {"session_key": 7})
        self.assertIn("session_name=Practice 1", session.calls[0]["url"])

    async def test_starting_grid_returns_rows(self) -> None:
        session = FakeSession([FakeResponse(200, [{"driver_number": 1, "position": 4}])])

        rows = await api.async_get_starting_grid(session, 42)

        self.assertEqual(rows, [{"driver_number": 1, "position": 4}])
        self.assertIn("starting_grid?session_key=42", session.calls[0]["url"])

    async def test_race_control_returns_rows(self) -> None:
        session = FakeSession([FakeResponse(200, [{"driver_number": 1, "message": "GRID PENALTY"}])])

        rows = await api.async_get_race_control(session, 42)

        self.assertEqual(rows, [{"driver_number": 1, "message": "GRID PENALTY"}])
        self.assertIn("race_control?session_key=42", session.calls[0]["url"])

    async def test_openf1_session_not_found_returns_none(self) -> None:
        session = FakeSession([FakeResponse(200, [])])

        found = await api.async_find_race_session(session, "2026", "2026-05-03")

        self.assertIsNone(found)

    async def test_last_qualifying_flattens_race_and_handles_empty(self) -> None:
        session = FakeSession([
            FakeResponse(200, {"MRData": {"RaceTable": {"Races": [{
                "season": "2026", "round": "4", "raceName": "Miami Grand Prix",
                "QualifyingResults": [{"position": "1"}],
            }]}}}),
            FakeResponse(200, {"MRData": {"RaceTable": {"Races": []}}}),
        ])

        qualifying = await api.async_get_last_qualifying(session)
        empty = await api.async_get_last_qualifying(session)

        self.assertEqual(qualifying["raceName"], "Miami Grand Prix")
        self.assertEqual(qualifying["QualifyingResults"], [{"position": "1"}])
        self.assertEqual(empty, {})

    async def test_invalid_json_payload_raises_f1_api_error(self) -> None:
        class FakeValueErrorResponse(FakeResponse):
            async def json(self) -> Any:
                raise ValueError("Invalid JSON")

        session = FakeSession([FakeValueErrorResponse(200, None)])

        with self.assertRaises(api.F1ApiError) as ctx:
            await api._get_json(session, "https://example.invalid")
        self.assertIn("Ungueltiges JSON-Format", str(ctx.exception))

    async def test_openf1_dictionary_response_fallback_to_safe_defaults(self) -> None:
        session = FakeSession([
            FakeResponse(200, {"error": "unexpected payload"}),
            FakeResponse(200, {"error": "unexpected payload"}),
        ])

        found = await api.async_find_race_session(session, "2026", "2026-05-03")
        results = await api.async_get_session_result(session, 42)

        self.assertIsNone(found)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
