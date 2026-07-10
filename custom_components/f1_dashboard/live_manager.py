"""Verwaltet den Lebenszyklus der Live-Timing-Verbindung.

Startet den F1LiveTimingClient nur waehrend einer aktiven Session
(gesteuert vom bestehenden session_status) und uebersetzt eingehende
Rohnachrichten in ein sauberes, direkt nutzbares Datenmodell fuer die
Sensoren (Timing Tower, Streckenstatus, Track-Positionen).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .live_client import F1LiveTimingClient

_LOGGER = logging.getLogger(__name__)

# TrackStatus-Codes laut F1-Live-Timing (reverse-engineert, siehe FastF1/
# Community-Dokumentation der SessionStatus/TrackStatus-Topics)
TRACK_STATUS_LABELS = {
    "1": "Grün",
    "2": "Gelb",
    "3": "Unbekannt",
    "4": "Safety Car",
    "5": "Rot",
    "6": "Virtual Safety Car",
    "7": "VSC Ende",
}

# Positions-Updates kommen im Feed gebuendelt etwa im Sekundentakt.
# Wir benachrichtigen die Sensoren fuer Positionsdaten hoechstens einmal
# pro Intervall, um die HA-State-Machine nicht zu fluten.
_POSITION_NOTIFY_INTERVAL = 1.0


class F1LiveDataManager:
    """Haelt den aktuellen Live-Zustand und steuert die Verbindung."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._client: F1LiveTimingClient | None = None
        self._active = False
        self._listeners: list[callback] = []

        # Live-Datenmodell, das die Sensoren lesen
        self.timing_tower: list[dict[str, Any]] = []
        self.track_status: dict[str, Any] = {"status": None, "label": None}
        self.race_control_messages: list[dict[str, Any]] = []
        self.session_live_info: dict[str, Any] = {}
        self.position_bounds: dict[str, float] = {}

        self._driver_list: dict[str, dict[str, Any]] = {}
        self._timing_data: dict[str, dict[str, Any]] = {}
        self._track_positions: dict[str, dict[str, Any]] = {}
        self._last_position_notify = 0.0

    @property
    def is_active(self) -> bool:
        return self._active

    async def async_set_active(self, active: bool) -> None:
        """Startet oder stoppt die Live-Verbindung je nach Session-Status."""
        if active == self._active:
            return
        self._active = active

        if active:
            _LOGGER.info("Session aktiv - starte F1 Live-Timing-Verbindung")
            session = async_get_clientsession(self._hass)
            self._client = F1LiveTimingClient(session, self._on_message)
            self._client.start()
        else:
            _LOGGER.info("Session beendet - trenne F1 Live-Timing-Verbindung")
            if self._client is not None:
                await self._client.stop()
                self._client = None
            # Live-Daten fuer die naechste Session zuruecksetzen
            self.timing_tower = []
            self.track_status = {"status": None, "label": None}
            self.race_control_messages = []
            self.position_bounds = {}
            self._driver_list = {}
            self._timing_data = {}
            self._track_positions = {}
            self._last_position_notify = 0.0

        self._notify_listeners()

    def add_listener(self, cb: callback) -> callback:
        """Registriert einen Callback, der bei Datenaenderung aufgerufen wird.

        Gibt eine Funktion zum Abmelden zurueck.
        """
        self._listeners.append(cb)

        def remove() -> None:
            self._listeners.remove(cb)

        return remove

    def _notify_listeners(self) -> None:
        for cb in list(self._listeners):
            cb()

    async def async_shutdown(self) -> None:
        if self._client is not None:
            await self._client.stop()
            self._client = None

    def get_track_positions(self) -> list[dict[str, Any]]:
        """Aktuelle Fahrzeugpositionen, angereichert um Fahrer-Infos."""
        rows = []
        for num, pos in self._track_positions.items():
            driver = self._driver_list.get(num, {})
            rows.append(
                {
                    "driver_number": num,
                    "tla": driver.get("Tla", ""),
                    "team_colour": driver.get("TeamColour", ""),
                    "x": pos["x"],
                    "y": pos["y"],
                    "status": pos.get("status", ""),
                }
            )
        return rows

    # -----------------------------------------------------------
    # Nachrichtenverarbeitung
    # -----------------------------------------------------------
    async def _on_message(self, topic: str, payload: Any) -> None:
        # Positionsdaten laufen ausserhalb des Timing-Tower-Pfads:
        # kein Tower-Rebuild noetig und Benachrichtigung gedrosselt.
        if topic == "Position.z":
            if self._handle_position(payload):
                now = time.monotonic()
                if now - self._last_position_notify >= _POSITION_NOTIFY_INTERVAL:
                    self._last_position_notify = now
                    self._notify_listeners()
            return

        handler = {
            "DriverList": self._handle_driver_list,
            "TimingData": self._handle_timing_data,
            "TrackStatus": self._handle_track_status,
            "RaceControlMessages": self._handle_race_control,
            "SessionInfo": self._handle_session_info,
        }.get(topic)

        if handler is not None:
            handler(payload)
            self._rebuild_timing_tower()
            self._notify_listeners()

    def _handle_position(self, payload: Any) -> bool:
        """Verarbeitet einen Position.z-Batch.

        Payload-Struktur (nach Dekompression):
          {"Position": [{"Timestamp": ..., "Entries": {
              "1": {"Status": "OnTrack", "X": -1073, "Y": -2836, "Z": 187},
              ...
          }}, ...]}

        Ein Batch enthaelt mehrere Samples; wir uebernehmen nur das
        juengste. Eintraege mit X=0 und Y=0 (Garage/kein Signal) werden
        ignoriert, damit sie weder Karte noch Bounds verzerren.
        """
        if not isinstance(payload, dict):
            return False
        samples = payload.get("Position")
        if not isinstance(samples, list) or not samples:
            return False
        entries = samples[-1].get("Entries")
        if not isinstance(entries, dict):
            return False

        changed = False
        for num, pos in entries.items():
            if not isinstance(pos, dict):
                continue
            x, y = pos.get("X"), pos.get("Y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            if x == 0 and y == 0:
                continue

            self._track_positions[num] = {
                "x": x,
                "y": y,
                "status": pos.get("Status", ""),
            }
            self._update_bounds(x, y)
            changed = True
        return changed

    def _update_bounds(self, x: float, y: float) -> None:
        b = self.position_bounds
        if not b:
            self.position_bounds = {"min_x": x, "max_x": x, "min_y": y, "max_y": y}
            return
        b["min_x"] = min(b["min_x"], x)
        b["max_x"] = max(b["max_x"], x)
        b["min_y"] = min(b["min_y"], y)
        b["max_y"] = max(b["max_y"], y)

    def _handle_driver_list(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        for num, info in payload.items():
            if num == "_kf":  # SignalR-Metafeld, kein Fahrer
                continue
            existing = self._driver_list.setdefault(num, {})
            if isinstance(info, dict):
                existing.update(info)

    def _handle_timing_data(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        lines = payload.get("Lines", {})
        for num, info in lines.items():
            existing = self._timing_data.setdefault(num, {})
            self._deep_merge(existing, info)

    def _handle_track_status(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        status = payload.get("Status")
        self.track_status = {
            "status": status,
            "label": TRACK_STATUS_LABELS.get(str(status), "Unbekannt"),
            "message": payload.get("Message"),
        }

    def _handle_race_control(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        messages = payload.get("Messages", {})
        # Messages kann Dict (keyed by index) oder Liste sein, je nach Feed-Version
        entries = messages.values() if isinstance(messages, dict) else messages
        for entry in entries:
            if isinstance(entry, dict) and entry not in self.race_control_messages:
                self.race_control_messages.append(entry)
        # Nur die juengsten 20 behalten
        self.race_control_messages = self.race_control_messages[-20:]

    def _handle_session_info(self, payload: dict[str, Any]) -> None:
        if isinstance(payload, dict):
            self.session_live_info = payload

    @staticmethod
    def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                F1LiveDataManager._deep_merge(target[key], value)
            else:
                target[key] = value

    def _rebuild_timing_tower(self) -> None:
        """Baut die sortierte Timing-Tower-Liste aus Driver-/Timing-Daten."""
        rows = []
        for num, timing in self._timing_data.items():
            driver = self._driver_list.get(num, {})
            position = timing.get("Position")
            try:
                position_int = int(position) if position is not None else 999
            except (TypeError, ValueError):
                position_int = 999

            rows.append(
                {
                    "driver_number": num,
                    "position": position_int,
                    "tla": driver.get("Tla", ""),
                    "full_name": driver.get("FullName", ""),
                    "team_name": driver.get("TeamName", ""),
                    "team_colour": driver.get("TeamColour", ""),
                    "gap_to_leader": timing.get("GapToLeader", ""),
                    "interval": (timing.get("IntervalToPositionAhead") or {}).get(
                        "Value", ""
                    ),
                    "last_lap_time": (timing.get("LastLapTime") or {}).get(
                        "Value", ""
                    ),
                    "in_pit": timing.get("InPit", False),
                    "retired": timing.get("Retired", False),
                    "knocked_out": timing.get("KnockedOut", False),
                }
            )

        rows.sort(key=lambda r: r["position"])
        self.timing_tower = rows
