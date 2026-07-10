# F1 Dashboard

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Add Repo](https://img.shields.io/badge/HACS-Repo%20hinzuf%C3%BCgen-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alexw8702&repository=ha-f1-dashboard&category=plugin)

Formel-1-Daten und -Dashboard für Home Assistant, komplett kostenlos ohne API-Key. Zwei Teile:

- **F1 Dashboard** (HACS-Kategorie *Integration*) – alle Sensoren, per UI eingerichtet
- **F1 Dashboard Card** (HACS-Kategorie *Dashboard/Plugin*) – vier eigenständige Custom Cards

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
