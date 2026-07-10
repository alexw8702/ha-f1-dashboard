"""Constants for the F1 Dashboard integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "f1_dashboard"

# ---- Update-Intervalle ----------------------------------------------
UPDATE_INTERVAL_STANDINGS = timedelta(hours=1)
UPDATE_INTERVAL_CALENDAR = timedelta(hours=6)
UPDATE_INTERVAL_WEATHER = timedelta(hours=1)
UPDATE_INTERVAL_OPENF1 = timedelta(minutes=30)

# ---- Jolpica-F1 (Ergast-kompatibel, kostenlos, kein Key) -------------
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

# ---- Open-Meteo (kostenlos, kein Key) ---------------------------------
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# ---- OpenF1 (kostenlos fuer historische Daten, kein Key) --------------
OPENF1_BASE = "https://api.openf1.org/v1"

USER_AGENT = "HomeAssistant-F1-Dashboard/0.1.0"

# ---- Config-Flow-Optionen ---------------------------------------------
CONF_ENABLE_WEATHER = "enable_weather"
CONF_ENABLE_RACE_RECAP = "enable_race_recap"

DEFAULT_ENABLE_WEATHER = True
DEFAULT_ENABLE_RACE_RECAP = True
