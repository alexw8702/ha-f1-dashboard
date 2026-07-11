"""Tests fuer die Live-Timing-Nachrichtenverarbeitung (F1LiveDataManager).

Prueft die reinen Datenverarbeitungspfade (Positions-Batches, Timing-Tower-
Aufbau, Track-Status-Mapping, Race-Control-Dedup) ohne echte WebSocket-
Verbindung - die Robustheit gegenueber unvollstaendigen/kaputten
Feed-Nachrichten ist hier der eigentliche Stabilitaetsaspekt, da der
offizielle F1-Feed nicht dokumentiert und nicht versioniert ist.
"""
from __future__ import annotations

import importlib
import unittest

from support import install_test_stubs

install_test_stubs()
live_manager_module = importlib.import_module("custom_components.f1_dashboard.live_manager")
F1LiveDataManager = live_manager_module.F1LiveDataManager


def _manager() -> F1LiveDataManager:
    # __init__ selbst startet keine Netzwerk-/HA-Infrastruktur (das passiert
    # erst in async_set_active), daher genuegt eine direkte Instanziierung
    # mit hass=None fuer die reinen Nachrichtenverarbeitungs-Tests.
    return F1LiveDataManager(hass=None)  # type: ignore[arg-type]


class PositionHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _manager()

    def test_handles_valid_position_batch_and_updates_bounds(self) -> None:
        payload = {"Position": [{"Entries": {
            "1": {"X": 100, "Y": 200, "Status": "OnTrack"},
            "44": {"X": -50, "Y": 300, "Status": "OnTrack"},
        }}]}

        changed = self.manager._handle_position(payload)

        self.assertTrue(changed)
        positions = self.manager.get_track_positions()
        self.assertEqual(len(positions), 2)
        self.assertEqual(self.manager.position_bounds, {
            "min_x": -50, "max_x": 100, "min_y": 200, "max_y": 300,
        })

    def test_ignores_garage_entries_at_origin(self) -> None:
        payload = {"Position": [{"Entries": {"1": {"X": 0, "Y": 0, "Status": "OnTrack"}}}]}

        changed = self.manager._handle_position(payload)

        self.assertFalse(changed)
        self.assertEqual(self.manager.get_track_positions(), [])
        self.assertEqual(self.manager.position_bounds, {})

    def test_only_last_sample_of_batch_is_used(self) -> None:
        payload = {"Position": [
            {"Entries": {"1": {"X": 1, "Y": 1, "Status": "OnTrack"}}},
            {"Entries": {"1": {"X": 999, "Y": 999, "Status": "OnTrack"}}},
        ]}

        self.manager._handle_position(payload)

        positions = self.manager.get_track_positions()
        self.assertEqual(positions[0]["x"], 999)
        self.assertEqual(positions[0]["y"], 999)

    def test_rejects_malformed_payloads_without_raising(self) -> None:
        self.assertFalse(self.manager._handle_position("not-a-dict"))
        self.assertFalse(self.manager._handle_position({}))
        self.assertFalse(self.manager._handle_position({"Position": []}))
        self.assertFalse(self.manager._handle_position({"Position": [{"Entries": "not-a-dict"}]}))
        self.assertFalse(self.manager._handle_position(
            {"Position": [{"Entries": {"1": {"X": "not-a-number", "Y": 1}}}]}
        ))

    def test_get_track_positions_enriches_with_driver_info(self) -> None:
        self.manager._driver_list["1"] = {"Tla": "VER", "TeamColour": "1E41FF"}
        self.manager._handle_position(
            {"Position": [{"Entries": {"1": {"X": 5, "Y": 5, "Status": "OnTrack"}}}]}
        )

        rows = self.manager.get_track_positions()
        self.assertEqual(rows[0]["tla"], "VER")
        self.assertEqual(rows[0]["team_colour"], "1E41FF")

    def test_get_track_positions_handles_unknown_driver(self) -> None:
        self.manager._handle_position(
            {"Position": [{"Entries": {"77": {"X": 5, "Y": 5, "Status": "OnTrack"}}}]}
        )

        rows = self.manager.get_track_positions()
        self.assertEqual(rows[0]["tla"], "")
        self.assertEqual(rows[0]["team_colour"], "")


class DriverListAndTimingDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _manager()

    def test_driver_list_skips_signalr_metafield(self) -> None:
        self.manager._handle_driver_list({"_kf": True, "44": {"Tla": "HAM"}})

        self.assertNotIn("_kf", self.manager._driver_list)
        self.assertEqual(self.manager._driver_list["44"]["Tla"], "HAM")

    def test_driver_list_updates_are_merged_not_replaced(self) -> None:
        self.manager._handle_driver_list({"44": {"Tla": "HAM"}})
        self.manager._handle_driver_list({"44": {"TeamName": "Ferrari"}})

        self.assertEqual(self.manager._driver_list["44"], {"Tla": "HAM", "TeamName": "Ferrari"})

    def test_timing_data_deep_merges_nested_fields(self) -> None:
        self.manager._handle_timing_data({"Lines": {
            "44": {"Position": "1", "LastLapTime": {"Value": "1:23.456"}},
        }})
        self.manager._handle_timing_data({"Lines": {
            "44": {"LastLapTime": {"Status": 1}},
        }})

        timing = self.manager._timing_data["44"]
        self.assertEqual(timing["Position"], "1")
        # Beide Unterfelder von LastLapTime muessen erhalten bleiben (deep merge,
        # kein Ueberschreiben des gesamten Sub-Dicts).
        self.assertEqual(timing["LastLapTime"], {"Value": "1:23.456", "Status": 1})


class TimingTowerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _manager()

    def test_rebuild_sorts_by_position(self) -> None:
        self.manager._driver_list = {
            "1": {"Tla": "VER"}, "44": {"Tla": "HAM"},
        }
        self.manager._timing_data = {
            "44": {"Position": "1", "GapToLeader": ""},
            "1": {"Position": "2", "GapToLeader": "+5.2"},
        }

        self.manager._rebuild_timing_tower()

        self.assertEqual([r["tla"] for r in self.manager.timing_tower], ["HAM", "VER"])

    def test_missing_or_invalid_position_sorts_last(self) -> None:
        self.manager._timing_data = {
            "1": {"Position": "1"},
            "77": {"Position": None},
            "88": {"Position": "not-a-number"},
        }

        self.manager._rebuild_timing_tower()

        positions = [r["driver_number"] for r in self.manager.timing_tower]
        self.assertEqual(positions[0], "1")
        self.assertIn("77", positions[1:])
        self.assertIn("88", positions[1:])

    def test_nested_fields_default_to_empty_string_when_absent(self) -> None:
        self.manager._timing_data = {"44": {"Position": "1"}}

        self.manager._rebuild_timing_tower()

        row = self.manager.timing_tower[0]
        self.assertEqual(row["interval"], "")
        self.assertEqual(row["last_lap_time"], "")
        self.assertFalse(row["in_pit"])


class TrackStatusAndRaceControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _manager()

    def test_known_status_code_maps_to_label(self) -> None:
        self.manager._handle_track_status({"Status": "4", "Message": "Safety Car deployed"})

        self.assertEqual(self.manager.track_status["label"], "Safety Car")
        self.assertEqual(self.manager.track_status["message"], "Safety Car deployed")

    def test_unknown_status_code_maps_to_unbekannt(self) -> None:
        self.manager._handle_track_status({"Status": "99"})

        self.assertEqual(self.manager.track_status["label"], "Unbekannt")

    def test_race_control_deduplicates_and_caps_at_twenty(self) -> None:
        for i in range(25):
            self.manager._handle_race_control({"Messages": {str(i): {"Message": f"msg-{i}"}}})
        # Dieselbe Nachricht nochmal - darf keinen Duplikat-Eintrag erzeugen.
        self.manager._handle_race_control({"Messages": {"0": {"Message": "msg-24"}}})

        self.assertEqual(len(self.manager.race_control_messages), 20)
        self.assertEqual(self.manager.race_control_messages[-1]["Message"], "msg-24")

    def test_race_control_accepts_list_shaped_messages(self) -> None:
        self.manager._handle_race_control({"Messages": [{"Message": "list-form"}]})

        self.assertEqual(self.manager.race_control_messages[-1]["Message"], "list-form")


if __name__ == "__main__":
    unittest.main()
