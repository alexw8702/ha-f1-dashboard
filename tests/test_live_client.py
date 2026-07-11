"""Tests fuer das Parsen des F1-Live-Timing-Feeds (SignalR-Core-Frames).

Der Feed ist inoffiziell/unversioniert (siehe Modul-Docstring in
live_client.py) - kaputte oder unerwartet geformte Frames duerfen die
Verarbeitung nicht crashen, sondern muessen einzeln uebersprungen werden.
"""
from __future__ import annotations

import base64
import importlib
import json
import unittest
import zlib
from unittest.mock import AsyncMock

from support import install_test_stubs

install_test_stubs()
live_client_module = importlib.import_module("custom_components.f1_dashboard.live_client")
F1LiveTimingClient = live_client_module.F1LiveTimingClient
_inflate_z_payload = live_client_module._inflate_z_payload


def _deflate_b64(payload: object) -> str:
    """Erzeugt einen ".z"-Payload wie ihn der echte Feed liefert (Gegenstueck
    zu _inflate_z_payload, fuer Roundtrip-Tests)."""
    compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    raw = compressor.compress(json.dumps(payload).encode()) + compressor.flush()
    return base64.b64encode(raw).decode()


class InflateTests(unittest.TestCase):
    def test_roundtrip_decodes_back_to_original_payload(self) -> None:
        original = {"Position": [{"Entries": {"1": {"X": 1, "Y": 2}}}]}

        decoded = _inflate_z_payload(_deflate_b64(original))

        self.assertEqual(decoded, original)


class RawFrameHandlingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.on_message = AsyncMock()
        self.client = F1LiveTimingClient(session=object(), on_message=self.on_message)

    async def test_dispatches_plain_feed_invocation(self) -> None:
        frame = json.dumps({
            "type": 1, "target": "feed", "arguments": ["TrackStatus", {"Status": "1"}, "ts"],
        }) + "\x1e"

        await self.client._handle_raw_frame(frame)

        self.on_message.assert_awaited_once_with("TrackStatus", {"Status": "1"})

    async def test_decompresses_dot_z_topics_before_dispatch(self) -> None:
        payload = {"Position": [{"Entries": {"1": {"X": 1, "Y": 2}}}]}
        frame = json.dumps({
            "type": 1, "target": "feed",
            "arguments": ["Position.z", _deflate_b64(payload), "ts"],
        }) + "\x1e"

        await self.client._handle_raw_frame(frame)

        self.on_message.assert_awaited_once_with("Position.z", payload)

    async def test_skips_dot_z_topic_with_corrupt_payload_without_raising(self) -> None:
        frame = json.dumps({
            "type": 1, "target": "feed",
            "arguments": ["Position.z", "not-valid-base64-deflate", "ts"],
        }) + "\x1e"

        await self.client._handle_raw_frame(frame)

        self.on_message.assert_not_awaited()

    async def test_ignores_non_feed_invocations(self) -> None:
        frame = json.dumps({"type": 6}) + "\x1e"  # SignalR-Ping

        await self.client._handle_raw_frame(frame)

        self.on_message.assert_not_awaited()

    async def test_ignores_malformed_json_frame(self) -> None:
        await self.client._handle_raw_frame("{not valid json\x1e")

        self.on_message.assert_not_awaited()

    async def test_handles_multiple_frames_in_one_batch(self) -> None:
        frame_a = json.dumps({
            "type": 1, "target": "feed", "arguments": ["Heartbeat", {}, "ts"],
        })
        frame_b = json.dumps({
            "type": 1, "target": "feed", "arguments": ["SessionInfo", {"Meeting": {}}, "ts"],
        })

        await self.client._handle_raw_frame(frame_a + "\x1e" + frame_b + "\x1e")

        self.assertEqual(self.on_message.await_count, 2)

    async def test_on_message_exception_does_not_propagate(self) -> None:
        self.on_message.side_effect = RuntimeError("boom")
        frame = json.dumps({
            "type": 1, "target": "feed", "arguments": ["Heartbeat", {}, "ts"],
        }) + "\x1e"

        # Darf keine Exception nach aussen werfen - ein einzelner defekter
        # Handler-Aufruf soll nicht die gesamte Verbindung abreissen lassen.
        await self.client._handle_raw_frame(frame)

        self.on_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
