"""API-Client-Funktionen fuer Jolpica-F1, Open-Meteo und OpenF1.

Alle drei Quellen sind kostenlos und benoetigen keinen API-Key.
Historische OpenF1-Daten (Sessions >30min beendet) sind ebenfalls frei.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import async_timeout

from .const import JOLPICA_BASE, OPEN_METEO_BASE, OPENF1_BASE, USER_AGENT

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = 30
_HEADERS = {"User-Agent": USER_AGENT}

# OpenF1 limitiert Requests strikt und unangekuendigt (429). Ein einzelner
# Wiederholungsversuch nach kurzer Pause genuegt in aller Regel.
_RETRYABLE_STATUS = {429}
_RETRY_DELAY = 2.0


class F1ApiError(Exception):
    """Fehler bei einem API-Aufruf."""


async def _get_json(
    session: aiohttp.ClientSession, url: str, *, params: dict[str, Any] | None = None
) -> Any:
    """Fuehrt einen GET-Request aus und gibt das geparste JSON zurueck."""
    try:
        async with async_timeout.timeout(_TIMEOUT):
            async with session.get(url, params=params, headers=_HEADERS) as resp:
                if resp.status != 200:
                    raise F1ApiError(f"HTTP {resp.status} von {url}")
                return await resp.json()
    except TimeoutError as err:
        raise F1ApiError(f"Timeout bei {url}") from err
    except aiohttp.ClientError as err:
        raise F1ApiError(f"Verbindungsfehler bei {url}: {err}") from err

async def _get_json_with_retry(
    session: aiohttp.ClientSession, url: str, *, params: dict[str, Any] | None = None
) -> Any:
    """Wie _get_json, aber mit einem Wiederholungsversuch bei 429/Timeout.

    OpenF1 antwortet unter Last mit HTTP 429 statt sauberem Backoff-Header;
    ein einzelner Retry nach kurzer Pause loest die meisten dieser Faelle,
    ohne dass der komplette Rennrueckblick verworfen werden muss.
    """
    try:
        return await _get_json(session, url, params=params)
    except F1ApiError as err:
        message = str(err)
        is_timeout = "Timeout bei" in message
        is_rate_limited = any(f"HTTP {code}" in message for code in _RETRYABLE_STATUS)
        if not (is_timeout or is_rate_limited):
            raise
        _LOGGER.debug("Retry nach %ss fuer %s (%s)", _RETRY_DELAY, url, message)
        await asyncio.sleep(_RETRY_DELAY)
        return await _get_json(session, url, params=params)


# =============================================================
# JOLPICA-F1  (Ergast-kompatibel)
# =============================================================

async def async_get_driver_standings(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Aktuelle Fahrerwertung."""
    data = await _get_json(session, f"{JOLPICA_BASE}/current/driverStandings.json")
    lists = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
    if not lists:
        return {"season": None, "round": None, "DriverStandings": []}
    return {
        "season": lists[0].get("season"),
        "round": lists[0].get("round"),
        "DriverStandings": lists[0].get("DriverStandings", []),
    }


async def async_get_constructor_standings(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Aktuelle Konstrukteurswertung."""
    data = await _get_json(session, f"{JOLPICA_BASE}/current/constructorStandings.json")
    lists = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
    if not lists:
        return {"season": None, "round": None, "ConstructorStandings": []}
    return {
        "season": lists[0].get("season"),
        "round": lists[0].get("round"),
        "ConstructorStandings": lists[0].get("ConstructorStandings", []),
    }


async def async_get_race_calendar(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Kompletter Rennkalender der aktuellen Saison (inkl. Session-Zeiten)."""
    data = await _get_json(session, f"{JOLPICA_BASE}/current.json")
    table = data.get("MRData", {}).get("RaceTable", {})
    return {"season": table.get("season"), "Races": table.get("Races", [])}


async def async_get_last_result(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Ergebnis des letzten abgeschlossenen Rennens."""
    data = await _get_json(session, f"{JOLPICA_BASE}/current/last/results.json")
    races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        return {}
    race = races[0]
    return {
        "season": race.get("season"),
        "round": race.get("round"),
        "raceName": race.get("raceName"),
        "date": race.get("date"),
        "Results": race.get("Results", []),
    }


async def async_get_last_qualifying(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Ergebnis des letzten Qualifyings."""
    data = await _get_json(session, f"{JOLPICA_BASE}/current/last/qualifying.json")
    races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        return {}
    race = races[0]
    return {
        "season": race.get("season"),
        "round": race.get("round"),
        "raceName": race.get("raceName"),
        "QualifyingResults": race.get("QualifyingResults", []),
    }


# =============================================================
# OPEN-METEO  (Wetter am naechsten Circuit)
# =============================================================

async def async_get_weather(
    session: aiohttp.ClientSession, lat: str, lon: str
) -> dict[str, Any]:
    """Taegliche + stuendliche Wettervorhersage fuer eine Koordinate.

    Ein einziger API-Call liefert beide Aufloesungen.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
        "timezone": "UTC",
        "forecast_days": 16,
    }
    data = await _get_json(session, OPEN_METEO_BASE, params=params)
    return {
        "daily": data.get("daily", {}),
        "hourly": data.get("hourly", {}),
    }


# =============================================================
# OPENF1  (historische Session-Daten: Ergebnis, Reifen, Boxenstopps)
# =============================================================

async def async_find_race_session(
    session: aiohttp.ClientSession, year: str, race_date: str
) -> dict[str, Any] | None:
    """Findet die OpenF1-Session fuer ein Renndatum (Jolpica-Datum).

    OpenF1 nutzt Vergleichsoperatoren (>=, <=) direkt als Teil des
    Query-Parameter-Namens. aiohttp's params-Dict kodiert Schluessel
    percent-encoded, was OpenF1 nicht korrekt interpretiert - daher
    wird die URL hier explizit zusammengesetzt statt ueber params=.
    """
    url = (
        f"{OPENF1_BASE}/sessions?year={year}&session_name=Race"
        f"&date_start>={race_date}&date_start<={race_date}T23:59:59"
    )
    data = await _get_json_with_retry(session, url)
    if not data:
        return None
    return data[0]


async def async_get_session_result(
    session: aiohttp.ClientSession, session_key: int
) -> list[dict[str, Any]]:
    """Endergebnis (inkl. DNF/DNS/DSQ) fuer eine Session."""
    data = await _get_json(session, f"{OPENF1_BASE}/session_result?session_key={session_key}")
    return data or []


async def async_get_stints(
    session: aiohttp.ClientSession, session_key: int
) -> list[dict[str, Any]]:
    """Reifenstrategie fuer eine Session."""
    data = await _get_json(session, f"{OPENF1_BASE}/stints?session_key={session_key}")
    return data or []


async def async_get_pit_stops(
    session: aiohttp.ClientSession, session_key: int
) -> list[dict[str, Any]]:
    """Boxenstopps fuer eine Session."""
    data = await _get_json(session, f"{OPENF1_BASE}/pit?session_key={session_key}")
    return data or []
