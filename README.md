# F1 Dashboard Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Add Repo](https://img.shields.io/badge/HACS-Repo%20hinzuf%C3%BCgen-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexw8702&repository=ha-f1-dashboard&category=integration)
[![Release](https://img.shields.io/github/v/release/alexw8702/ha-f1-dashboard?style=for-the-badge)](https://github.com/alexw8702/ha-f1-dashboard/releases)

Formel-1-Daten für Home Assistant, komplett kostenlos ohne API-Key.

![F1 Dashboard Integration Logo](brand/icon.svg)

> **Hinweis:** Die passenden Dashboard-Karten leben in einem separaten Repo: [**ha-f1-dashboard-card**](https://github.com/alexw8702/ha-f1-dashboard-card) (HACS-Kategorie *Dashboard/Plugin*). Beide Repos werden getrennt installiert, da HACS pro Repo nur eine Kategorie gleichzeitig verwaltet.
>
> **Versionsstand:** Integration `v0.3.1` · Card `v0.4.0`. Die Card wurde in v0.4.0 auf Vue 3 umgestellt und die Rennwochenende-Karte neu designt; die hier bereitgestellten Live-Timing-Sensoren (siehe unten) sind aktuell **nicht** in die neu gestaltete Session Card eingebunden, bleiben aber vollständig funktionsfähig für eigene Automationen, Templates oder Custom-Karten.

---

## Features der Integration

### 📋 Sensoren für Wertungen
- **Fahrer-WM**: Position, Punkte, Team, Teamfarbe, Nummer
- **Konstrukteurs-WM**: Position, Punkte, Teamfarbe

### 🏁 Session & Rennwochenende
- **Session-Status**: Aktuelle Session (FP1–FP3, Quali, Sprint, Rennen), Countdown zur nächsten Session
- **Streckenfakten**: Länge, Rundenzahl, Anzahl Kurven, Aktiv-Aero-Zonen, Höhenmeter, Rundenrekord, alle 22 Strecken der 2026-Saison
- **Wetter**: 4-Tages-Vorhersage + stündlicher Verlauf (Temperatur, Regen, Wind) für die Rennstrecke — nützlich für eigene Automationen; die mitgelieferte Session Card lädt ihr Wetter seit Card-v0.4.0 direkt im Frontend und benötigt diesen Sensor nicht mehr zwingend

### 🚗 Live-Timing (nur während aktiver Sessions)
- **Live-Streckenkarte**: Sensor mit Echtzeitpositionen aller 22 Fahrer (X/Y/Z, Bounds, Streckenstatus) — Rohdaten für eigene Visualisierungen, aktuell ohne Standard-Card
- **Flaggen-Logik im Sensor-Attribut**:
  - 🟢 **Grün**: Normale Darstellung
  - 🟡 **Gelb**: Normale Darstellung
  - 🚗 **Safety Car**: Status `4`
  - 🚨 **Rote Flagge**: Status `5`
  - 🟡 **VSC**: Status `6`
- **Timing Tower**: Position, Team, Gap zum Leader, letzte Rundenzeit, Box-/Out-Status je Fahrer
- **Live-Streckenstatus**: Grün/Gelb/Safety Car/Rot/VSC
- **Renn-Kontrollnachrichten**: Flaggen, Strafen, Untersuchungen (ausgewählte Events)
- **Datenquelle**: Offizielle F1-Live-Timing-Feed per WebSocket (livetiming.formula1.com), unauthentifiziert, automatischer Start/Stop je nach Session-Status

> Diese Live-Sensoren sind weiterhin Teil der Integration und aktiv nutzbar — sie sind lediglich (Stand Card v0.4.0) nicht mehr in die mitgelieferte `f1-session-card` eingebunden. Wer sie visuell nutzen möchte, kann eigene Karten/Templates auf Basis dieser Entities bauen oder vorerst Card-Version v0.3.0 verwenden.

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
4. Nach „F1 Dashboard" suchen → **Herunterladen**
5. **Home Assistant neu starten** (wichtig: Python-Komponenten laden)
6. **Einstellungen → Geräte & Dienste → Integrationen** → **Integration hinzufügen** → „F1 Dashboard" suchen
7. Optional: Live-Wetter oder Rennrückblick deaktivieren → **Absenden**

Alle Sensoren werden automatisch erstellt.

### 2. Karten installieren (separate Installation)

1. **HACS → Frontend (Dashboard)** → ⋮ → **Benutzerdefinierte Repositories**
2. Repo-URL: `https://github.com/alexw8702/ha-f1-dashboard-card`
3. Kategorie: **Dashboard/Plugin** → **Hinzufügen**
4. Nach „F1 Dashboard Card" suchen → **Herunterladen**
5. **Browser hart neu laden** (Strg+Shift+R)

> HACS legt die Ressource automatisch an. Falls nicht, unter *Einstellungen → Dashboards → ⋮ → Ressourcen* prüfen:
> `/hacsfiles/ha-f1-dashboard-card/f1-dashboard-card.js` als **JavaScript-Modul**.

---

## Verwendung in Dashboards

Alle vier Karten sind in [**ha-f1-dashboard-card**](https://github.com/alexw8702/ha-f1-dashboard-card) definiert. Beispiel-Dashboard:

```yaml
type: vertical-stack
cards:
  - type: custom:f1-session-card
    entity: sensor.f1_dashboard_session_status

  - type: custom:f1-drivers-card
    entity: sensor.f1_dashboard_fahrerwertung
    max: 10

  - type: custom:f1-constructors-card
    entity: sensor.f1_dashboard_konstrukteurswertung
    max: 10

  - type: custom:f1-race-recap-card
    entity: sensor.f1_dashboard_rennrueckblick
```

> Seit Card-v0.4.0 genügt für `f1-session-card` die reine `entity`-Angabe; Wetter wird automatisch im Frontend geladen.

---

## Entities der Integration

Nach der Einrichtung sind folgende Sensoren verfügbar:

| Entity-ID | Name | Zweck |
|-|-|-|
| `sensor.f1_dashboard_fahrerwertung` | Fahrer-WM | WM-Stand (JSON: Position, Punkte, Team, Teamfarbe, Nummer) |
| `sensor.f1_dashboard_konstrukteurswertung` | Konstrukteurs-WM | Team-WM-Stand (JSON: Position, Punkte, Teamfarbe) |
| `sensor.f1_dashboard_session_status` | Session-Status | Aktuelle Session, Countdown, Nächste Session |
| `sensor.f1_dashboard_streckenfakten` | Streckenfakten | Länge, Runden, Kurven, Aktiv-Aero, Höhenmeter, Rundenrekord |
| `sensor.f1_dashboard_wetter_vorhersage` | Wetter | 4-Tage-Vorhersage + stündlich Renntag (optional, für eigene Automationen) |
| `sensor.f1_dashboard_live_streckenstatus` | Live Track Status | (Live) Flaggenstatus, nur während Sessions — derzeit ohne Card-Anbindung |
| `sensor.f1_dashboard_live_timing_tower` | Live Timing Tower | (Live) Alle Fahrer: Position, Gap, Rundenzeit, Box-Status — derzeit ohne Card-Anbindung |
| `sensor.f1_dashboard_live_track_positionen` | Live Track Positionen | Echtzeitpositionen aller Fahrer (X/Y/Z), Bounds, Streckenstatus — derzeit ohne Card-Anbindung |
| `sensor.f1_dashboard_rennrueckblick` | Rennrückblick | Endergebnis, Reifen-Strategie, Boxenstopps (24h nach Rennen verfügbar) |

### Attribute des `live_track_positionen`-Sensors

```python
# state: "Live Track Positions"
# attributes: {
#   "positions": [
#     {"driver_number": 1, "tla": "VER", "team_colour": "#1e3050", "x": 1234.5, "y": 567.8, "status": "OnTrack"},
#     # ... alle Fahrer
#   ],
#   "bounds": {"min_x": 500, "max_x": 2500, "min_y": 200, "max_y": 1800},
#   "track_status": 1  # 1=Grün, 2=Gelb, 4=SC, 5=Rot, 6=VSC, 7=VSC-Ende
# }
```

---

## Datenquellen

| Daten | API | Authentifizierung | Rate-Limit |
|-|-|-|-|
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

### v0.3.1
- 🔧 Kleinere Fixes und Stabilisierung der bestehenden v0.3.0-Sensoren
- 🎯 Kompatibilitäts-Hinweis: Card-Repo ist ab jetzt unabhängig versioniert (aktuell v0.4.0) und bindet die Live-Sensoren dieser Integration vorübergehend nicht mehr standardmäßig ein

### v0.3.0 (Live-Streckenkarte)
- ✨ **Live-Streckenkarte**: Neuer Sensor `live_track_positionen` mit Echtzeit-Fahrzeugpositionen (X/Y/Z)
- 🎨 Canvas-Rendering: Fahrspuren zeichnen automatisch das Streckenlayout
- 🚩 Flaggen-Logik: Rote Flagge blendet Fahrer aus, SC/VSC friert ein, jeweils mit Overlay
- 📍 Automatische Bounds-Berechnung aus Live-Daten, Garage-Einträge gefiltert
- 🔄 Position.z-Topic des F1-Live-Timing-Feeds abonniert (base64/raw-DEFLATE-kodiert)
- 🛠️ **Wichtig**: Live-Wetter und Live-Timing-Daten nur während Sessions aktiv
- 📦 Alle Positionen-Attribute vom Home Assistant Recorder ausgenommen (Performance)

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

### Live-Sensoren sind gefüllt, aber ich sehe nichts in der Session Card

Das ist seit Card-v0.4.0 erwartet: Die neu gestaltete `f1-session-card` bindet die Live-Streckenkarte und den Timing Tower derzeit nicht mehr standardmäßig ein. Die Sensordaten selbst sind unter *Entwickler-Tools → Zustände* weiterhin einsehbar und können in eigenen Karten/Templates verwendet werden.

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

Dieses Projekt ist inoffiziell und steht in keiner Verbindung zu Formula 1, der FIA oder verbundenen Unternehmen. F1, FORMULA 1 und zugehörige Marken sind Eigentum von Formula One Licensing B.V.

**Gutes Rennen! 🏁**
