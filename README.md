# F1 Dashboard Card

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Add Repo](https://img.shields.io/badge/HACS-Repo%20hinzuf%C3%BCgen-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexw8702&repository=ha-f1-dashboard&category=plugin)

Ein Satz eleganter, dunkler Custom Cards für ein **Formel-1-Dashboard** in Home Assistant. Alle Daten stammen aus **kostenlosen APIs ohne API-Key** (Jolpica-F1 + Open-Meteo).

Das Bundle enthält **drei eigenständige Karten**:

| Karte | Element | Zeigt |
|-------|---------|-------|
| Fahrerwertung | `f1-drivers-card` | WM-Stand der Fahrer, Teamfarben, Klick-Details, Wikipedia-Link |
| Konstrukteurswertung | `f1-constructors-card` | WM-Stand der Teams, Teamfarben, Klick-Details |
| Rennwochenende | `f1-session-card` | Streckenlayout (SVG), Fakten, Countdown, Session-Zeitplan, Wetter |

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

---

## Installation

### 1. Karte via HACS

1. HACS → **Frontend** (bzw. „Dashboard") → oben rechts ⋮ → **Benutzerdefinierte Repositories**
2. URL dieses Repos einfügen, Kategorie **Dashboard/Plugin** wählen, hinzufügen
3. „F1 Dashboard Card" suchen und **herunterladen**
4. Browser hart neu laden (Strg+Shift+R)

> HACS legt die Ressource automatisch an. Falls nicht, unter *Einstellungen → Dashboards → ⋮ → Ressourcen* prüfen:
> `/hacsfiles/f1-dashboard-card/f1-dashboard-card.js` als **JavaScript-Modul**.

### 2. Sensoren einrichten

Die Karten brauchen einige Sensoren. Kopiere [`f1_sensors_package.yaml`](f1_sensors_package.yaml) nach:

```
/config/packages/f1_dashboard.yaml
```

Stelle sicher, dass Packages in `configuration.yaml` aktiv sind:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Danach Home Assistant neu starten (oder *Entwicklerwerkzeuge → YAML → RESTful entities* neu laden). Es entstehen:

- `sensor.f1_fahrerwertung`
- `sensor.f1_konstrukteurswertung`
- `sensor.f1_rennkalender`
- `sensor.f1_letztes_ergebnis`
- `sensor.f1_letztes_qualifying`
- `sensor.f1_wetter_vorhersage`
- `sensor.f1_wetter_stuendlich`
- `sensor.f1_session_status` (Template-Sensor, Basis der Rennwochenende-Karte)

---

## Verwendung

### Fahrerwertung

```yaml
type: custom:f1-drivers-card
entity: sensor.f1_fahrerwertung
max: 10          # optional, Standard 10
```

### Konstrukteurswertung

```yaml
type: custom:f1-constructors-card
entity: sensor.f1_konstrukteurswertung
max: 10          # optional
```

### Rennwochenende

```yaml
type: custom:f1-session-card
entity: sensor.f1_session_status
weather_entity: sensor.f1_wetter_vorhersage   # optional (Tages-Wetter)
hourly_entity: sensor.f1_wetter_stuendlich    # optional (stündlicher Renntag)
```

> Ohne `weather_entity`/`hourly_entity` blendet die Karte den jeweiligen Wetterblock einfach aus.

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
            entity: sensor.f1_session_status
            weather_entity: sensor.f1_wetter_vorhersage
            hourly_entity: sensor.f1_wetter_stuendlich
      - type: grid
        cards:
          - type: custom:f1-drivers-card
            entity: sensor.f1_fahrerwertung
          - type: custom:f1-constructors-card
            entity: sensor.f1_konstrukteurswertung
```

---

## Konfigurationsoptionen

| Option | Karte | Pflicht | Standard | Beschreibung |
|--------|-------|---------|----------|--------------|
| `entity` | alle | ✅ | – | Zugehöriger Sensor |
| `max` | drivers/constructors | – | `10` | Maximale Anzahl Zeilen |
| `weather_entity` | session | – | – | Tages-Wetter-Sensor |
| `hourly_entity` | session | – | – | Stündlicher Wetter-Sensor |

---

## Datenquellen & Lizenz

- **Jolpica-F1** (Ergast-kompatibel) – Standings, Kalender, Ergebnisse
- **Open-Meteo** – Wettervorhersage
- **Streckenlayouts** – [julesr0y/f1-circuits-svg](https://github.com/julesr0y/f1-circuits-svg), lizenziert unter CC-BY-4.0

Dieses Projekt ist inoffiziell und steht in keiner Verbindung zu Formula 1, der FIA oder verbundenen Unternehmen. F1, FORMULA 1 und zugehörige Marken sind Eigentum von Formula One Licensing B.V.

Code lizenziert unter MIT.
