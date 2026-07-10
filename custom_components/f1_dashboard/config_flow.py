"""Config Flow fuer die F1-Dashboard-Integration.

Keine Zugangsdaten noetig (alle Datenquellen sind kostenlos und
schluessellos) - der Nutzer bestaetigt lediglich die Einrichtung und
kann optional Wetter/Rennrueckblick deaktivieren.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import (
    CONF_ENABLE_RACE_RECAP,
    CONF_ENABLE_WEATHER,
    DEFAULT_ENABLE_RACE_RECAP,
    DEFAULT_ENABLE_WEATHER,
    DOMAIN,
)

_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENABLE_WEATHER, default=DEFAULT_ENABLE_WEATHER): bool,
        vol.Required(CONF_ENABLE_RACE_RECAP, default=DEFAULT_ENABLE_RACE_RECAP): bool,
    }
)


class F1DashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handhabt den Einrichtungs-Dialog fuer F1 Dashboard."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Einziger Einrichtungsschritt: Bestaetigung + Optionen."""
        # Nur eine Instanz der Integration sinnvoll (ein globales Dashboard)
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="F1 Dashboard", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_OPTIONS_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> F1DashboardOptionsFlow:
        return F1DashboardOptionsFlow(config_entry)


class F1DashboardOptionsFlow(OptionsFlow):
    """Erlaubt das nachtraegliche Aendern der Optionen ueber die UI."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_WEATHER,
                    default=current.get(CONF_ENABLE_WEATHER, DEFAULT_ENABLE_WEATHER),
                ): bool,
                vol.Required(
                    CONF_ENABLE_RACE_RECAP,
                    default=current.get(CONF_ENABLE_RACE_RECAP, DEFAULT_ENABLE_RACE_RECAP),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
