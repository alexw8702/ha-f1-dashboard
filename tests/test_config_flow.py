"""Tests fuer den Einrichtungs-/Options-Dialog (config_flow.py).

Bisher ungetestetes Modul (siehe Repo-Review) - das ist der Dialog, den jeder Nutzer
beim ersten Setup und bei jeder spaeteren Options-Aenderung durchlaeuft, daher hoeher
priorisiert als z.B. Formatierungs-Detailfragen in sensor.py.
"""
from __future__ import annotations

import importlib
import types
import unittest
from unittest.mock import patch

from support import install_test_stubs

install_test_stubs()
const = importlib.import_module("custom_components.f1_dashboard.const")
config_flow = importlib.import_module("custom_components.f1_dashboard.config_flow")
F1DashboardConfigFlow = config_flow.F1DashboardConfigFlow
F1DashboardOptionsFlow = config_flow.F1DashboardOptionsFlow


class ConfigFlowUserStepTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.flow = F1DashboardConfigFlow()

    async def test_shows_form_without_user_input(self) -> None:
        result = await self.flow.async_step_user(None)

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")
        # Schema enthaelt genau die beiden Options-Schluessel mit ihren Defaults.
        keys = {str(k): k.default for k in result["data_schema"].schema}
        self.assertEqual(keys, {
            const.CONF_ENABLE_WEATHER: const.DEFAULT_ENABLE_WEATHER,
            const.CONF_ENABLE_RACE_RECAP: const.DEFAULT_ENABLE_RACE_RECAP,
        })

    async def test_creates_entry_with_provided_user_input(self) -> None:
        user_input = {const.CONF_ENABLE_WEATHER: False, const.CONF_ENABLE_RACE_RECAP: True}

        result = await self.flow.async_step_user(user_input)

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "F1 Dashboard")
        self.assertEqual(result["data"], user_input)

    async def test_sets_a_stable_unique_id_and_checks_for_existing_entry(self) -> None:
        # Nur eine Instanz der Integration ist sinnvoll (ein globales Dashboard) -
        # async_set_unique_id/_abort_if_unique_id_configured muessen beide aufgerufen
        # werden, unabhaengig davon, ob user_input schon vorliegt.
        with patch.object(self.flow, "_abort_if_unique_id_configured") as abort_check:
            await self.flow.async_step_user(None)

        self.assertEqual(self.flow._unique_id, const.DOMAIN)
        abort_check.assert_called_once()

    async def test_already_configured_aborts_the_flow(self) -> None:
        # Simuliert die reale HA-Registry-Pruefung: existiert bereits ein Config-Entry
        # mit dieser unique_id, bricht der Flow ab, statt eine zweite Instanz anzulegen.
        abort_flow = importlib.import_module("homeassistant.data_entry_flow").AbortFlow
        with patch.object(
            self.flow, "_abort_if_unique_id_configured",
            side_effect=abort_flow("already_configured"),
        ):
            with self.assertRaises(abort_flow):
                await self.flow.async_step_user(None)


class ConfigFlowOptionsHandoffTests(unittest.TestCase):
    def test_async_get_options_flow_returns_bound_options_flow(self) -> None:
        entry = types.SimpleNamespace(entry_id="entry-1", data={}, options={})

        options_flow = F1DashboardConfigFlow.async_get_options_flow(entry)

        self.assertIsInstance(options_flow, F1DashboardOptionsFlow)
        self.assertIs(options_flow._config_entry, entry)


class OptionsFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_shows_form_with_current_values_as_defaults(self) -> None:
        entry = types.SimpleNamespace(
            entry_id="entry-1",
            data={const.CONF_ENABLE_WEATHER: True, const.CONF_ENABLE_RACE_RECAP: True},
            options={const.CONF_ENABLE_RACE_RECAP: False},  # Options ueberschreiben data
        )
        flow = F1DashboardOptionsFlow(entry)

        result = await flow.async_step_init(None)

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")
        keys = {str(k): k.default for k in result["data_schema"].schema}
        self.assertEqual(keys, {
            const.CONF_ENABLE_WEATHER: True,
            const.CONF_ENABLE_RACE_RECAP: False,  # options-Wert gewinnt gegen data-Wert
        })

    async def test_falls_back_to_defaults_when_entry_has_no_prior_values(self) -> None:
        entry = types.SimpleNamespace(entry_id="entry-1", data={}, options={})
        flow = F1DashboardOptionsFlow(entry)

        result = await flow.async_step_init(None)

        keys = {str(k): k.default for k in result["data_schema"].schema}
        self.assertEqual(keys, {
            const.CONF_ENABLE_WEATHER: const.DEFAULT_ENABLE_WEATHER,
            const.CONF_ENABLE_RACE_RECAP: const.DEFAULT_ENABLE_RACE_RECAP,
        })

    async def test_creates_entry_with_provided_user_input(self) -> None:
        entry = types.SimpleNamespace(entry_id="entry-1", data={}, options={})
        flow = F1DashboardOptionsFlow(entry)
        user_input = {const.CONF_ENABLE_WEATHER: False, const.CONF_ENABLE_RACE_RECAP: False}

        result = await flow.async_step_init(user_input)

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "")  # Options-Entries haben keinen Titel
        self.assertEqual(result["data"], user_input)


if __name__ == "__main__":
    unittest.main()
