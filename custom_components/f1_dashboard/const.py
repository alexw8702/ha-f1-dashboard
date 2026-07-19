"""Constants for the F1 Dashboard integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "f1_dashboard"

# ---- Update-Intervall --------------------------------------------------
# Ein einziger Coordinator pollt alle Quellen (Standings, Kalender, Wetter,
# OpenF1-Rennrueckblick) im selben Zyklus - siehe F1DashboardCoordinator in
# coordinator.py. Es gibt keine separaten Intervalle pro Quelle; frueher
# geplante, nie implementierte UPDATE_INTERVAL_CALENDAR/WEATHER/OPENF1-
# Konstanten wurden entfernt, da sie nirgends gelesen wurden und die
# Dokumentation (faelschlich "Calendar: 6-hourly, OpenF1: 30 minutes")
# in die Irre fuehrten.
UPDATE_INTERVAL_STANDINGS = timedelta(hours=1)

# ---- Jolpica-F1 (Ergast-kompatibel, kostenlos, kein Key) -------------
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

# ---- Open-Meteo (kostenlos, kein Key) ---------------------------------
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# ---- OpenF1 (kostenlos fuer historische Daten, kein Key) --------------
OPENF1_BASE = "https://api.openf1.org/v1"

# Haelt sich absichtlich an manifest.json["version"] - wird bei jedem Release
# mitgepflegt, siehe CLAUDE.md "Dokumentationspflege".
USER_AGENT = "HomeAssistant-F1-Dashboard/0.5.0-beta.2"

# ---- Config-Flow-Optionen ---------------------------------------------
CONF_ENABLE_WEATHER = "enable_weather"
CONF_ENABLE_RACE_RECAP = "enable_race_recap"

DEFAULT_ENABLE_WEATHER = True
DEFAULT_ENABLE_RACE_RECAP = True
