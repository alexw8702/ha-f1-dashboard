"""F1 Dashboard Integration fuer Home Assistant.

Stellt Sensoren fuer Formel-1-Daten bereit: WM-Stand, Rennkalender,
Session-Status, Wetter am Circuit und Rueckblick auf das letzte Rennen
(Ergebnis, Reifenstrategie, Boxenstopps). Alle Datenquellen sind
kostenlos und benoetigen keinen API-Key (Jolpica-F1, Open-Meteo, OpenF1).
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import F1DashboardCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richtet die Integration fuer einen Config-Entry ein."""
    coordinator = F1DashboardCoordinator(hass, dict(entry.options or entry.data))
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entfernt die Integration und raeumt Ressourcen auf."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: F1DashboardCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Wird bei Options-Aenderungen aufgerufen; startet die Integration neu."""
    await hass.config_entries.async_reload(entry.entry_id)
