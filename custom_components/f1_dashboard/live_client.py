"""Client fuer den offiziellen F1-Live-Timing-Feed (SignalR Core).

Reverse-engineert aus der Referenzimplementierung von FastF1
(theOehrly/Fast-F1, MIT-lizenziert) und mehreren weiteren
Open-Source-Projekten, die denselben Feed nutzen (LiveF1, OpenF1.Data).

Der Endpunkt selbst verlangt laut Aussage des FastF1-Maintainers
KEINE Authentifizierung und die Daten sind nicht verschluesselt - wir
verbinden daher unauthentifiziert (entspricht `no_auth=True` in FastF1).

Ablauf:
  1. OPTIONS-Request an .../signalrcore/negotiate, um das
     AWSALBCORS-Load-Balancer-Cookie zu erhalten (sonst schlaegt der
     WebSocket-Handshake fehl).
  2. WebSocket-Verbindung zu wss://livetiming.formula1.com/signalrcore
     mit diesem Cookie im Header.
  3. SignalR-Core-Handshake: {"protocol":"json","version":1} + \\x1e.
  4. "Subscribe"-Invocation mit der Liste gewuenschter Topics senden.
  5. Eingehende Frames sind JSON-Objekte, getrennt durch \\x1e.
     Frames vom Typ 1 (Invocation) mit target "feed" enthalten die
     eigentlichen Daten als Argumente [topic, data, timestamp].

Topics mit ".z"-Suffix (z.B. Position.z) sind base64-kodiert und
raw-DEFLATE-komprimiert; sie werden hier transportnah dekodiert,
bevor sie an den Manager weitergereicht werden.

Nur waehrend Sessions aktiv (siehe live_manager.py) - ausserhalb
liefert der Feed ohnehin nichts Sinnvolles.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import zlib
from collections.abc import Callable, Coroutine
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

_NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate"
_WS_URL = "wss://livetiming.formula1.com/signalrcore"
_RECORD_SEPARATOR = "\x1e"

# Topics, die fuer Timing-Tower + Streckenstatus + Track-Map benoetigt
# werden. Position.z liefert die X/Y-Koordinaten aller Fahrzeuge fuer
# die Live-Streckenkarte; CarData.z (Telemetrie-Feuerhose mit Speed/
# RPM/DRS) bleibt bewusst aussen vor, da unnoetig fuer unseren Fall.
DEFAULT_TOPICS = [
    "Heartbeat",
    "SessionInfo",
    "SessionStatus",
    "TrackStatus",
    "RaceControlMessages",
    "TimingData",
    "TimingAppData",
    "TopThree",
    "WeatherData",
    "DriverList",
    "LapCount",
    "Position.z",
]

_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY = 60


def _inflate_z_payload(data: str) -> Any:
    """Dekodiert ein ".z"-Topic: base64 -> raw DEFLATE -> JSON.

    Der Feed nutzt DEFLATE ohne zlib-Header, daher wbits=-MAX_WBITS.
    """
    raw = zlib.decompress(base64.b64decode(data), -zlib.MAX_WBITS)
    return json.loads(raw)


class F1LiveTimingClient:
    """Haelt eine WebSocket-Verbindung zum F1-Live-Timing-Feed offen.

    Ruft `on_message` fuer jedes empfangene (topic, data)-Paar auf.
    Verbindet automatisch neu bei Abbruch (exponentielles Backoff),
    bis `stop()` aufgerufen wird.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        on_message: Callable[[str, Any], Coroutine[Any, Any, None]],
        topics: list[str] | None = None,
    ) -> None:
        self._session = session
        self._on_message = on_message
        self._topics = topics or DEFAULT_TOPICS
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._connected = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def start(self) -> asyncio.Task:
        """Startet die Verbindung als Hintergrund-Task und gibt ihn zurueck."""
        self._stopped = False
        self._task = asyncio.ensure_future(self._run_forever())
        return self._task

    async def stop(self) -> None:
        """Beendet die Verbindung und den Hintergrund-Task sauber."""
        self._stopped = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_forever(self) -> None:
        delay = _RECONNECT_BASE_DELAY
        while not self._stopped:
            try:
                await self._connect_and_listen()
                delay = _RECONNECT_BASE_DELAY  # Erfolgreiche Verbindung -> Backoff zuruecksetzen
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - bewusst breit, Verbindung soll nie sterben
                _LOGGER.warning(
                    "F1 Live-Timing-Verbindung unterbrochen (%s); "
                    "neuer Versuch in %ss",
                    err,
                    delay,
                )
            finally:
                self._connected.clear()

            if self._stopped:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    async def _negotiate(self) -> str:
        """Holt das AWSALBCORS-Cookie, das der WebSocket-Handshake braucht."""
        async with self._session.options(_NEGOTIATE_URL) as resp:
            cookie = resp.cookies.get("AWSALBCORS")
            if cookie is None:
                raise RuntimeError("Kein AWSALBCORS-Cookie beim Negotiate erhalten")
            return cookie.value

    async def _connect_and_listen(self) -> None:
        cookie_value = await self._negotiate()
        headers = {"Cookie": f"AWSALBCORS={cookie_value}"}

        async with self._session.ws_connect(
            _WS_URL, headers=headers, heartbeat=30
        ) as ws:
            self._ws = ws

            # SignalR-Core-Handshake
            await ws.send_str(
                json.dumps({"protocol": "json", "version": 1}) + _RECORD_SEPARATOR
            )
            handshake_ok = await self._wait_for_handshake_ack(ws)
            if not handshake_ok:
                raise RuntimeError("SignalR-Handshake nicht bestaetigt")

            # Subscribe-Invocation senden
            subscribe_msg = {
                "type": 1,
                "target": "Subscribe",
                "arguments": [self._topics],
                "invocationId": "0",
            }
            await ws.send_str(json.dumps(subscribe_msg) + _RECORD_SEPARATOR)

            self._connected.set()
            _LOGGER.info("F1 Live-Timing verbunden, Topics: %s", self._topics)

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_raw_frame(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break

    async def _wait_for_handshake_ack(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> bool:
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=10)
        except TimeoutError:
            return False
        if msg.type != aiohttp.WSMsgType.TEXT:
            return False
        # Erfolgreiche Handshake-Antwort ist "{}\x1e" (leeres Objekt)
        frame = msg.data.rstrip(_RECORD_SEPARATOR)
        try:
            payload = json.loads(frame) if frame else {}
        except json.JSONDecodeError:
            return False
        return "error" not in payload

    async def _handle_raw_frame(self, raw: str) -> None:
        for frame in raw.split(_RECORD_SEPARATOR):
            if not frame:
                continue
            try:
                data = json.loads(frame)
            except json.JSONDecodeError:
                continue

            # Typ 1 = Invocation (Server ruft Client-Methode "feed" auf)
            if data.get("type") == 1 and data.get("target") == "feed":
                args = data.get("arguments", [])
                if len(args) >= 2:
                    topic, payload = args[0], args[1]
                    if topic.endswith(".z") and isinstance(payload, str):
                        try:
                            payload = _inflate_z_payload(payload)
                        except (ValueError, zlib.error) as err:
                            _LOGGER.debug(
                                "Dekodierung von %s fehlgeschlagen: %s", topic, err
                            )
                            continue
                    try:
                        await self._on_message(topic, payload)
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception(
                            "Fehler bei Verarbeitung von Topic %s", topic
                        )
            # Typ 6 = Ping vom Server, keine Aktion noetig (aiohttp
            # beantwortet WS-Pings bereits auf Transport-Ebene)
