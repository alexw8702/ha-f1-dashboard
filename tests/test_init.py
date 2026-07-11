"""Tests fuer den Setup-/Unload-/Reload-Lebenszyklus der Integration (__init__.py).

Bisher ungetestetes Modul (siehe Repo-Review) - bricht hier etwas, installiert sich
die Integration gar nicht erst oder verliert beim Reload ihren Zustand, daher hoeher
priorisiert als reine Formatierungsfragen in sensor.py.
"""
from __future__ import annotations

import importlib
import importlib.util
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from support import install_test_stubs

install_test_stubs()
const = importlib.import_module("custom_components.f1_dashboard.const")

# install_test_stubs() registriert "custom_components.f1_dashboard" absichtlich als
# leeres Platzhalter-Paket (siehe support.py), damit andere Testdateien gezielt nur
# einzelne Submodule importieren koennen, ohne das produktive __init__.py mitzuladen -
# genau das wollen wir hier aber testen. importlib.import_module() wuerde daher nur
# den (leeren) Platzhalter aus sys.modules zurueckgeben. Stattdessen laden wir die Datei
# direkt ueber ihren Pfad unter einem eigenen Namen; __package__ wird manuell auf
# "custom_components.f1_dashboard" gesetzt, damit die relativen Imports (from .const
# import DOMAIN, from .coordinator import F1DashboardCoordinator) trotzdem ueber den
# bereits im Platzhalter hinterlegten __path__ aufgeloest werden.
_init_path = Path(__file__).resolve().parents[1] / "custom_components" / "f1_dashboard" / "__init__.py"
_spec = importlib.util.spec_from_file_location("f1_dashboard_init_under_test", _init_path)
init_module = importlib.util.module_from_spec(_spec)
init_module.__package__ = "custom_components.f1_dashboard"
_spec.loader.exec_module(init_module)


def _make_entry(entry_id: str = "entry-1", data: dict | None = None, options: dict | None = None):
    entry = types.SimpleNamespace(
        entry_id=entry_id,
        data=data or {},
        options=options or {},
    )
    entry.add_update_listener = MagicMock(return_value="unsub-sentinel")
    entry.async_on_unload = MagicMock()
    return entry


def _make_hass():
    hass = types.SimpleNamespace(data={})
    hass.config_entries = types.SimpleNamespace(
        async_forward_entry_setups=AsyncMock(),
        async_unload_platforms=AsyncMock(return_value=True),
        async_reload=AsyncMock(),
    )
    return hass


class AsyncSetupEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_coordinator_refreshes_and_forwards_platform_setup(self) -> None:
        hass = _make_hass()
        entry = _make_entry(options={const.CONF_ENABLE_WEATHER: False})
        fake_coordinator = MagicMock()
        fake_coordinator.async_config_entry_first_refresh = AsyncMock()

        with patch.object(
            init_module, "F1DashboardCoordinator", return_value=fake_coordinator
        ) as coordinator_cls:
            result = await init_module.async_setup_entry(hass, entry)

        coordinator_cls.assert_called_once_with(hass, {const.CONF_ENABLE_WEATHER: False})
        fake_coordinator.async_config_entry_first_refresh.assert_awaited_once()
        self.assertIs(hass.data[const.DOMAIN][entry.entry_id], fake_coordinator)
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry, init_module.PLATFORMS
        )
        self.assertTrue(result)

    async def test_falls_back_to_entry_data_when_options_are_empty(self) -> None:
        # dict(entry.options or entry.data) - leere Options duerfen nicht die
        # urspruengliche data-Konfiguration (erster Einrichtungsschritt) verdraengen.
        hass = _make_hass()
        entry = _make_entry(data={const.CONF_ENABLE_RACE_RECAP: False}, options={})
        fake_coordinator = MagicMock()
        fake_coordinator.async_config_entry_first_refresh = AsyncMock()

        with patch.object(
            init_module, "F1DashboardCoordinator", return_value=fake_coordinator
        ) as coordinator_cls:
            await init_module.async_setup_entry(hass, entry)

        coordinator_cls.assert_called_once_with(hass, {const.CONF_ENABLE_RACE_RECAP: False})

    async def test_registers_update_listener_for_unload(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        fake_coordinator = MagicMock()
        fake_coordinator.async_config_entry_first_refresh = AsyncMock()

        with patch.object(init_module, "F1DashboardCoordinator", return_value=fake_coordinator):
            await init_module.async_setup_entry(hass, entry)

        entry.add_update_listener.assert_called_once_with(init_module._async_update_listener)
        entry.async_on_unload.assert_called_once_with("unsub-sentinel")


class AsyncUnloadEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_shuts_down_and_removes_coordinator_on_successful_unload(self) -> None:
        hass = _make_hass()
        entry = _make_entry()
        fake_coordinator = MagicMock()
        fake_coordinator.async_shutdown = AsyncMock()
        hass.data[const.DOMAIN] = {entry.entry_id: fake_coordinator}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        result = await init_module.async_unload_entry(hass, entry)

        fake_coordinator.async_shutdown.assert_awaited_once()
        self.assertNotIn(entry.entry_id, hass.data[const.DOMAIN])
        self.assertTrue(result)

    async def test_keeps_coordinator_when_platform_unload_fails(self) -> None:
        # Schlaegt das Entladen der Sensor-Plattform fehl, darf der Coordinator nicht
        # trotzdem entfernt/heruntergefahren werden - sonst verliert eine fehlgeschlagene
        # Deinstallation den kompletten Zustand ohne Not.
        hass = _make_hass()
        entry = _make_entry()
        fake_coordinator = MagicMock()
        fake_coordinator.async_shutdown = AsyncMock()
        hass.data[const.DOMAIN] = {entry.entry_id: fake_coordinator}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        result = await init_module.async_unload_entry(hass, entry)

        fake_coordinator.async_shutdown.assert_not_awaited()
        self.assertIn(entry.entry_id, hass.data[const.DOMAIN])
        self.assertFalse(result)


class UpdateListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reloads_the_config_entry(self) -> None:
        hass = _make_hass()
        entry = _make_entry(entry_id="entry-42")

        await init_module._async_update_listener(hass, entry)

        hass.config_entries.async_reload.assert_awaited_once_with("entry-42")


if __name__ == "__main__":
    unittest.main()
