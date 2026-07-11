# F1 Dashboard Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Add Repo](https://img.shields.io/badge/HACS-Repo%20hinzuf%C3%BCgen-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexw8702&repository=ha-f1-dashboard&category=integration)
[![Release](https://img.shields.io/github/v/release/alexw8702/ha-f1-dashboard?style=for-the-badge)](https://github.com/alexw8702/ha-f1-dashboard/releases)

Formel-1-Daten für Home Assistant, komplett kostenlos ohne API-Key. **v0.3.0** bringt eine **Live-Streckenkarte mit Echtzeit-Fahrzeugpositionen** — direkt auf der Rennwochenende-Karte, während Sessions laufen.

![F1 Dashboard Integration Logo](brand/icon.svg)

> **Hinweis:** Die passenden Dashboard-Karten leben in einem separaten Repo: [**ha-f1-dashboard-card**](https://github.com/alexw8702/ha-f1-dashboard-card) (HACS-Kategorie *Dashboard/Plugin*). Beide Repos werden getrennt installiert, da HACS pro Repo nur eine Kategorie gleichzeitig verwaltet.

---

## Features der Integration

### 📋 Sensoren für Wertungen
- **Fahrer-WM**: Position, Punkte, Team, Teamfarbe, Nummer
- **Konstrukteurs-WM**: Position, Punkte, Teamfarbe

### 🏁 Session & Rennwochenende
- **Session-Status**: Aktuelle Session (FP1–FP3, Quali, Sprint, Rennen), Countdown zur nächsten Session
- **Streckenfakten**: Länge, Rundenzahl, Anzahl Kurven, Aktiv-Aero-Zonen, Höhenmeter, Rundenrekord, alle 22 Strecken der 2026-Saison
- **Wetter**: 4-Tages-Vorhersage + stündlicher Verlauf (Temperatur, Regen, Wind) für die Rennstrecke

### 🚗 Live-Timing (nur während aktiver Sessions) — **NEU in v0.3.0**
- **Live-Streckenkarte**: Canvas-Rendering aller 22 Fahrer in Echtzeit
  - Fahrzeuge als Kreise in Teamfarbe mit Startnummer und Fahrerhünzel
  - Fahrspuren zeichnen automatisch das Strechenlayout (keine Vorlagen nötig)
  - Sanfte Interpolation zwischen den Sekunden-Updates
  - **Flaggen-Logik**: 
    - 🟢 **Grün**: Normale Darstellung
    - 🟡 **Gelb**: Normale Darstellung
    - 🚗 **Safety Car**: Fahrzeuge eingefroren, 35% gedimmt + Overlay
    - 🚨 **Rote Flagge**: Alle Fahrer ausgeblendet, rotes Overlay
    - 🟡 **VSC**: Fahrzeuge eingefroren, gedimmt + Overlay
  - Nur Fahrer mit Status `OnTrack` werden gerendert
  - Automatische Bounds-Berechnung aus Live-Daten
  - DPR-scharfes Rendering, ResizeObserver, rAF pausiert außerhalb des Viewports

- **Timing Tower**: Position, Team, Gap zum Leader, letzte Rundenzeit, Box-/Out-Status je Fahrer
- **Live-Streckenstatus**: Grün/Gelb/Safety Car/Rot/VSC mit Overlay-Anzeigen
- **Renn-Kontrollnachrichten**: Flaggen, Strafen, Untersuchungen (ausgewählte Events)
- **Datenquelle**: Offizielle F1-Live-Timing-Feed per WebSocket (livetiming.formula1.com), unauthentifiziert, automatischer Start/Stop je nach Session-Status

### 📹 Letztes Rennen
- **Endergebnis**: DNF/DNS/DSQ-Status, Rückstand zum Sieger
- **Reifen-Strategie**: Pro-Fahrer-Compound-Anzeige (Rot/Gelb/Weiß nach F1-Standard)
- **Boxenstopps**: Anzahl und Dauer (via OpenF1-API, optional deaktivierbar)

---

## Installation

### 1. Integration installieren (YAML-frei, UI-Setup)

1. **HACS öffnen** → oben rechts ⋮ → **Benutzerdefinierte Repositories**
2. Diese Repo-URL einfügen: `https://github.com/alexw8702/ha-f1-dashboard`
3. Kategorie: **Integration** → **Hinzufügen**
4. Nach „F1 Dashboard“ suchen → **Herunterladen**
5. **Home Assistant neu starten** (wichtig: Python-Komponenten laden)
6. **Einstellungen → Geräte & Dienste → Integrationen** → **Integration hinzufügen** → „F1 Dashboard“ suchen
7. Optional: Live-Wetter oder Rennrückblick deaktivieren → **Absenden**

→ Alle Sensoren werden automatisch erstellt.

### 2. Karten installieren (separate Installation)

1. **HACS → Frontend (Dashboard)** → ⋮ → **Benutzerdefinierte Repositories**
2. Repo-URL: `https://github.com/alexw8702/ha-f1-dashboard-card`
3. Kategorie: **Dashboard/Plugin** → **Hinzufügen**
4. Nach „F1 Dashboard Card“ suchen → **Herunterladen**
5. **Browser hart neu laden** (Strg+Shift+R)

→ HACS legt die Ressource automatisch an.

---

## Verwendung in Dashboards

### Mit der passenden Card-Library (empfohlen)

Alle vier Karten sind in [**ha-f1-dashboard-card**](https://github.com/alexw8702/ha-f1-dashboard-card) definiert. Beispiel-Dashboard:

```yaml
type: vertical-stack
cards:
  - type: custom:f1-session-card
    entity: sensor.f1_dashboard_session_status
    live_track_entity: sensor.f1_dashboard_live_streckenstatus
    live_timing_entity: sensor.f1_dashboard_live_timing_tower
    live_positions_entity: sensor.f1_dashboard_live_track_positionen  # NEU: Live-Streckenkarte
    weather_entity: sensor.f1_dashboard_wetter_vorhersage

  - type: custom:f1-drivers-card
    entity: sensor.f1_dashboard_fahrerwertung
    max: 10

  - type: custom:f1-constructors-card
    entity: sensor.f1_dashboard_konstrukteurswertung
    max: 10

  - type: custom:f1-race-recap-card
    entity: sensor.f1_dashboard_rennrueckblick
```

---

## Entities der Integration

Nach der Einrichtung sind folgende Sensoren verfügbar:

| Entity-ID | Name | Zweck |
|-----------|------|-------|
| sensor.f1_dashboard_fahrerwertung | Fahrer-WM | WM-Stand (JSON: Position, Punkte, Team, Teamfarbe, Nummer) |
| sensor.f1_dashboard_konstrukteurswertung | Konstrukteurs-WM | Team-WM-Stand (JSON: Position, Punkte, Teamfarbe) |
| sensor.f1_dashboard_session_status | Session-Status | Aktuelle Session, Countdown, Nächste Session |
| sensor.f1_dashboard_streckenfakten | Streckenfakten | Länge, Runden, Kurven, Aktiv-Aero, Höhenmeter, Rundenrekord |
| sensor.f1_dashboard_wetter_vorhersage | Wetter | 4-Tage-Vorhersage + stündlich Renntag |
| sensor.f1_dashboard_live_streckenstatus | Live Track Status | (Live) Flaggenstatus (nur während Sessions) |
| sensor.f1_dashboard_live_timing_tower | Live Timing Tower | (Live) Alle Fahrer: Position, Gap, Rundenzeit, Box-Status |
| sensor.f1_dashboard_live_track_positionen | Live Track Positionen | **[NEU v0.3.0]** Echtzeitpositionen aller Fahrer (X/Y/Z), Bounds, Streckenstatus |
| sensor.f1_dashboard_rennrueckblick | Rennrückblick | Endergebnis, Reifen-Strategie, Boxenstopps (24h nach Rennen verfügbar) |

### Attribute des neuen `live_track_positionen`-Sensors (v0.3.0)

```python
# state: "Live Track Positions"
# attributes:
{
  "positions": [
    {"driver_number": 1, "tla": "VER", "team_colour": "#1e3050", "x": 1234.5, "y": 567.8, "status": "OnTrack"},
    # ... alle Fahrer
  ],
  "bounds": {"min_x": 500, "max_x": 2500, "min_y": 200, "max_y": 1800},
  "track_status": 1  # 1=Grün, 2=Gelb, 4=SC, 5=Rot, 6=VSC, 7=VSC-Ende
}
```

---

## Datenquellen

| Daten | API | Authentifizierung | Rate-Limit |
|-------|-----|-------------------|------------|
| Fahrer, Teams, Strecken, Wertungen | Jolpica-F1 (Ergast-kompatibel) | Keine | Großzügig |
| Live-Timing, Positionen, Flags | F1 Live Timing Feed (SignalR Core) | Keine (öffentlich) | N/A (WebSocket) |
| Wetter | Open-Meteo | Keine | 10.000/Tag |
| Boxenstopps, Reifen | OpenF1 | Keine | Großzügig |

**Wichtig**: Alle APIs sind **kostenlos** und erfordern **keinen API-Key**.

---

## Konfiguration (nach Installation)

Die Integration wird über die UI konfiguriert. Zum Anpassen später:

**Einstellungen → Geräte & Dienste → F1 Dashboard → ⚙️ Konfigurieren**

Optionen:
- **Live-Wetter aktiviert**: An/Aus (Standard: An)
- **Rennrückblick aktiviert**: An/Aus (Standard: An)

---

## Changelog

### v0.3.0 (Live-Streckenkarte)
- ✨ **Live-Streckenkarte**: Neuer Sensor `live_track_positionen` mit Echtzeit-Fahrzeugpositionen (X/Y/Z)
- 🎨 Canvas-Rendering: Fahrspuren zeichnen automatisch das Streckenlayout
- 🚩 Flaggen-Logik: Rote Flagge blendet Fahrer aus, SC/VSC friert ein, jeweils mit Overlay
- 📍 Automatische Bounds-Berechnung aus Live-Daten, Garage-Einträge gefiltert
- 🔄 Position.z-Topic des F1-Live-Timing-Feeds abonniert (base64/raw-DEFLATE-kodiert)
- 🛠️ **Wichtig**: Live-Wetter und Live-Timing-Daten nur während Sessions aktiv
- 📦 Alle Positionen-Attribute vom Home Assistant Recorder ausgenommen (Performance)
- 🎯 Integration & Card jetzt synchron (beide v0.3.0)

### v0.2.1
- Jolpica-F1 API als neue Quelle (schneller, zuverlässiger)
- Alle Sensoren via UI eingerichtet (kein YAML mehr nötig)
- Wetter-Vorhersage für Rennstrecken

### v0.2.0
- Live-Timing-Sensor (Timing Tower)
- Streckenfakten-Sensor
- Live-Streckenstatus (Flaggen)

---

## Troubleshooting

### Live-Daten erscheinen nicht

1. **Ist gerade eine Session aktiv?** Live-Sensoren sind nur während FP1–Rennen aktiv.
2. **HA-Logs prüfen**: `Einstellungen → System → Protokolle → custom_components.f1_dashboard` auf Debug setzen
3. **WebSocket-Verbindung prüfen**: livetiming.formula1.com/signalrcore sollte erreichbar sein

### Live-Streckenkarte bleibt leer

1. **Card-Konfiguration**: `live_positions_entity: sensor.f1_dashboard_live_track_positionen` gesetzt?
2. **Browser hart neu laden** (Strg+Shift+R)
3. **Sensor-Attribute prüfen**: In Entwickler-Tools die Entity `sensor.f1_dashboard_live_track_positionen` ansehen — sollte Positionen-Array mit Einträgen haben

### Fehlerhafte Streckenfakten

Die Strecke ist möglicherweise nicht in der Datenbank. [Issue öffnen](https://github.com/alexw8702/ha-f1-dashboard/issues) mit Rennwochenende-Info.

---

## Lizenz

MIT License — siehe [LICENSE](LICENSE)

---

## Credits

- **Daten**: Jolpica-F1, F1 Official Live Timing, Open-Meteo, OpenF1
- **Inspiriert von**: [FastF1](https://github.com/theOehrly/Fast-F1)

---

**Gutes Rennen! 🏁**


[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Add Repo](https://img.shields.io/badge/HACS-Repo%20hinzuf%C3%BCgen-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexw8702&repository=ha-f1-dashboard&category=integration)

Formel-1-Daten für Home Assistant, komplett kostenlos ohne API-Key. Alle Sensoren, per UI eingerichtet – kein YAML-Editieren nötig.

> **Hinweis:** Die passenden Dashboard-Karten leben in einem separaten Repo: [**ha-f1-dashboard-card**](https://github.com/alexw8702/ha-f1-dashboard-card) (HACS-Kategorie *Dashboard/Plugin*). Beide Repos werden getrennt installiert, da HACS pro Repo nur eine Kategorie gleichzeitig verwaltet.

| Karte | Element | Zeigt |
|-------|---------|-------|
| Fahrerwertung | `f1-drivers-card` | WM-Stand der Fahrer, Teamfarben, Klick-Details, Wikipedia-Link |
| Konstrukteurswertung | `f1-constructors-card` | WM-Stand der Teams, Teamfarben, Klick-Details |
| Rennwochenende | `f1-session-card` | Streckenlayout (SVG), Fakten, Countdown, Session-Zeitplan, Wetter |
| Letztes Rennen | `f1-race-recap-card` | Ergebnis (inkl. DNF/DSQ), Reifenstrategie, Boxenstopps (OpenF1) |

---

## Features

**Rennwochenende-Karte**
- **Streckenlayout** als SVG mit Start/Ziel-Linie und Fahrtrichtung (alle 22 Strecken der Saison 2026, inkl. Madrid)
- **Streckenfakten**: Länge, Runden, Kurven, Aktiv-Aero-Zonen, Höhenmeter, Rundenrekord
- **Live-Countdown** zur nächsten Session
- **Session-Zeitplan** (FP1–FP3, Quali, Sprint, Rennen) mit Hervorhebung der laufenden/nächsten Session
- **Wetter am Circuit**: 4-Tage-Übersicht + stündlicher Verlauf am Renntag (Temperatur, Regen, Wind)

**Wertungs-Karten**
- Positions-Badge, Team-Farbakzent, Punkte, Rückstand, Siege-Trophäe
- Klick auf eine Zeile öffnet Detail-Popup (Nationalität, Geburtsdatum + Alter, Team, Wikipedia-Link)

**Letztes-Rennen-Karte**
- Endergebnis inkl. DNF/DNS/DSQ-Status und Rückstand zum Sieger
- Reifenstrategie je Fahrer (Compound-Farbcodierung nach offizieller F1-Konvention)
- Boxenstopp-Anzahl und -Dauer je Fahrer

**Live-Timing (nur während aktiver Sessions)**
- Kompletter Timing Tower: Position, Team-Farbe, Gap, letzte Rundenzeit, Box-/Out-Status
- Live-Streckenstatus (Grün/Gelb/Safety Car/Rot)
- Aktuelle Renn-Kontrollnachrichten (Flaggen, Strafen, Untersuchungen)
- Datenquelle: der offizielle F1-Live-Timing-Feed per WebSocket, automatischer Start/Stop je nach Session-Status

---

## Installation

Zwei Teile, zwei HACS-Kategorien im selben Repository:

### 1. Sensoren – F1 Dashboard Integration (empfohlen)

Kein YAML-Editieren mehr nötig. Alle Sensoren werden über die Home-Assistant-UI eingerichtet.

1. HACS → oben rechts ⋮ → **Benutzerdefinierte Repositories**
2. URL dieses Repos einfügen, Kategorie **Integration** wählen, hinzufügen
3. „F1 Dashboard" suchen und **herunterladen**
4. Home Assistant neu starten
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → „F1 Dashboard" suchen
6. Optional Wetter/Rennrückblick deaktivieren, dann **Absenden**

Das legt automatisch alle Entities an (siehe Tabelle unten). Zum Anpassen später: bei der Integration auf **Konfigurieren** klicken.

<details>
<summary>Alternative: manuelles YAML-Package (Legacy)</summary>

Falls du kein HACS für Integrationen nutzen willst, kannst du stattdessen [`f1_sensors_package.yaml`](f1_sensors_package.yaml) nach `/config/packages/f1_dashboard.yaml` kopieren (Packages müssen in `configuration.yaml` aktiv sein: `homeassistant: packages: !include_dir_named packages`). Die Entity-IDs unterscheiden sich leicht von der Integration (z. B. `sensor.f1_fahrerwertung` statt `sensor.f1_dashboard_fahrerwertung`) – Card-Konfiguration entsprechend anpassen.
</details>

### 2. Karten – F1 Dashboard Card

1. HACS → **Frontend** (bzw. „Dashboard") → oben rechts ⋮ → **Benutzerdefinierte Repositories**
2. Gleiche Repo-URL einfügen, Kategorie **Dashboard/Plugin** wählen, hinzufügen
3. „F1 Dashboard Card" suchen und **herunterladen**
4. Browser hart neu laden (Strg+Shift+R)

> HACS legt die Ressource automatisch an. Falls nicht, unter *Einstellungen → Dashboards → ⋮ → Ressourcen* prüfen:
> `/hacsfiles/f1-dashboard-card/f1-dashboard-card.js` als **JavaScript-Modul**.

### Entities nach der Integrations-Einrichtung

| Entity-ID | Zweck |
|-----------|-------|
| `sensor.f1_dashboard_fahrerwertung` | WM-Stand der Fahrer |
| `sensor.f1_dashboard_konstrukteurswertung` | WM-Stand der Teams |
| `sensor.f1_dashboard_rennkalender` | Kompletter Rennkalender inkl. Session-Zeiten |
| `sensor.f1_dashboard_letztes_ergebnis` | Ergebnis des letzten Rennens (Jolpica) |
| `sensor.f1_dashboard_letztes_qualifying` | Ergebnis des letzten Qualifyings |
| `sensor.f1_dashboard_session_status` | Status (idle/upcoming/active) + nächstes Rennen |
| `sensor.f1_dashboard_wetter_vorhersage` | Tageswetter am nächsten Circuit |
| `sensor.f1_dashboard_wetter_stuendlich` | Stündliches Wetter am nächsten Circuit |
| `sensor.f1_dashboard_letztes_rennen_detail` | Ergebnis, Reifen, Boxenstopps (OpenF1) |
| `sensor.f1_dashboard_live_timing_tower` | Live-Positionen, Gaps, Rundenzeiten – nur während einer laufenden Session |
| `sensor.f1_dashboard_live_streckenstatus` | Live-Streckenstatus (Grün/Gelb/Safety Car/Rot) – nur während einer laufenden Session |
| `sensor.f1_dashboard_live_renn_kontrolle` | Aktuelle Renn-Kontrollnachrichten (Flaggen, Strafen) – nur während einer laufenden Session |

> Die drei Live-Sensoren beziehen Daten vom offiziellen F1-Live-Timing-Feed per WebSocket und sind ausserhalb aktiver Sessions bewusst `unavailable`, statt veraltete Daten zu zeigen.

> Die exakte Entity-ID kann je nach vorhandenen Entities leicht abweichen (Home Assistant hängt bei Kollisionen `_2` etc. an) – im Zweifel unter *Entwicklerwerkzeuge → Zustände* nach „F1 Dashboard" filtern.

---

## Verwendung

### Fahrerwertung

```yaml
type: custom:f1-drivers-card
entity: sensor.f1_dashboard_fahrerwertung
max: 10          # optional, Standard 10
```

### Konstrukteurswertung

```yaml
type: custom:f1-constructors-card
entity: sensor.f1_dashboard_konstrukteurswertung
max: 10          # optional
```

### Rennwochenende

```yaml
type: custom:f1-session-card
entity: sensor.f1_dashboard_session_status
weather_entity: sensor.f1_dashboard_wetter_vorhersage   # optional (Tages-Wetter)
hourly_entity: sensor.f1_dashboard_wetter_stuendlich    # optional (stündlicher Renntag)
```

> Ohne `weather_entity`/`hourly_entity` blendet die Karte den jeweiligen Wetterblock einfach aus.

### Letztes Rennen (Ergebnis, Reifen, Boxenstopps)

```yaml
type: custom:f1-race-recap-card
entity: sensor.f1_dashboard_letztes_rennen_detail
drivers_entity: sensor.f1_dashboard_fahrerwertung   # optional, für Fahrernamen
```

### Komplettes Dashboard (Beispiel)

```yaml
title: Formel 1
views:
  - title: Übersicht
    type: sections
    sections:
      - type: grid
        cards:
          - type: custom:f1-session-card
            entity: sensor.f1_dashboard_session_status
            weather_entity: sensor.f1_dashboard_wetter_vorhersage
            hourly_entity: sensor.f1_dashboard_wetter_stuendlich
      - type: grid
        cards:
          - type: custom:f1-drivers-card
            entity: sensor.f1_dashboard_fahrerwertung
          - type: custom:f1-constructors-card
            entity: sensor.f1_dashboard_konstrukteurswertung
      - type: grid
        cards:
          - type: custom:f1-race-recap-card
            entity: sensor.f1_dashboard_letztes_rennen_detail
            drivers_entity: sensor.f1_dashboard_fahrerwertung
```

---

## Konfigurationsoptionen

| Option | Karte | Pflicht | Standard | Beschreibung |
|--------|-------|---------|----------|--------------|
| `entity` | alle | ✅ | – | Zugehöriger Sensor |
| `max` | drivers/constructors | – | `10` | Maximale Anzahl Zeilen |
| `weather_entity` | session | – | – | Tages-Wetter-Sensor |
| `hourly_entity` | session | – | – | Stündlicher Wetter-Sensor |
| `drivers_entity` | race-recap | – | – | Fahrerwertungs-Sensor (für Namen statt Startnummern) |

---

## Datenquellen & Lizenz

- **Jolpica-F1** (Ergast-kompatibel) – Standings, Kalender, Ergebnisse
- **Open-Meteo** – Wettervorhersage
- **OpenF1** – Rennergebnis, Reifenstrategie, Boxenstopps (historische Daten, kostenlos, kein Key)
- **Streckenlayouts** – [julesr0y/f1-circuits-svg](https://github.com/julesr0y/f1-circuits-svg), lizenziert unter CC-BY-4.0

Dieses Projekt ist inoffiziell und steht in keiner Verbindung zu Formula 1, der FIA oder verbundenen Unternehmen. F1, FORMULA 1 und zugehörige Marken sind Eigentum von Formula One Licensing B.V.

Code lizenziert unter MIT.
