"""Leichte Home-Assistant- und HTTP-Stubs fuer isolierte Integrationstests."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any


class _TimeoutContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False


class ConfigEntry:
    """Minimaler Ersatz mit nur dem in sensor.py genutzten entry_id-Feld.

    Auf Modulebene definiert (statt in install_test_stubs), damit Tests ihn
    direkt importieren koennen; install_test_stubs registriert dieselbe
    Klasse unter homeassistant.config_entries, damit beide Wege dasselbe
    Objekt liefern.
    """

    def __init__(self, entry_id: str = "test-entry") -> None:
        self.entry_id = entry_id


def install_test_stubs() -> None:
    """Registriert nur die HA-/HTTP-Oberflaechen, die die Tests benoetigen."""
    root = Path(__file__).resolve().parents[1]

    # Das Paket direkt bereitstellen, damit dessen produktives __init__.py nicht
    # geladen werden muss; die Unit-Tests testen gezielt einzelne Module.
    components = types.ModuleType("custom_components")
    components.__path__ = [str(root / "custom_components")]
    package = types.ModuleType("custom_components.f1_dashboard")
    package.__path__ = [str(root / "custom_components" / "f1_dashboard")]
    sys.modules.setdefault("custom_components", components)
    sys.modules.setdefault("custom_components.f1_dashboard", package)

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    aiohttp.ClientSession = object
    aiohttp.ClientWebSocketResponse = object
    sys.modules.setdefault("aiohttp", aiohttp)

    async_timeout = types.ModuleType("async_timeout")
    async_timeout.timeout = lambda _seconds: _TimeoutContext()
    sys.modules.setdefault("async_timeout", async_timeout)

    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda fn: fn

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda _hass: None
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_time_interval = lambda *_args, **_kwargs: lambda: None
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        """Minimaler Ersatz, ausreichend fuer die Coordinator-Unit-Tests."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.data: dict[str, Any] | None = None

        def __class_getitem__(cls, _item: Any) -> type:
            return cls

        def async_update_listeners(self) -> None:
            return None

        async def async_shutdown(self) -> None:
            return None

    class CoordinatorEntity:
        """Minimaler Ersatz: haelt nur die Coordinator-Referenz, kein State-Write."""

        def __init__(self, coordinator: Any, *_args: Any, **_kwargs: Any) -> None:
            self.coordinator = coordinator

        def __class_getitem__(cls, _item: Any) -> type:
            return cls

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault("homeassistant.helpers.event", event)
    sys.modules.setdefault("homeassistant.helpers.update_coordinator", update_coordinator)

    # Fuer sensor.py: nur die Basisklassen/Typen, die zur Modulebene importiert
    # werden - keine echte Entity-Lifecycle-Logik noetig fuer reine
    # native_value/extra_state_attributes-Tests.
    components = types.ModuleType("homeassistant.components")
    components_sensor = types.ModuleType("homeassistant.components.sensor")

    class SensorEntity:
        """Minimaler Ersatz: reine Attribut-Basisklasse ohne HA-Lifecycle."""

    components_sensor.SensorEntity = SensorEntity

    # ---- config_entries: ConfigFlow/OptionsFlow-Basisklassen fuer config_flow.py ----
    class AbortFlow(Exception):
        """Ersatz fuer homeassistant.data_entry_flow.AbortFlow."""

        def __init__(self, reason: str) -> None:
            super().__init__(reason)
            self.reason = reason

    class ConfigFlow:
        """Minimaler Ersatz: nur die von config_flow.py tatsaechlich genutzten
        Methoden (async_set_unique_id/_abort_if_unique_id_configured sind No-Ops,
        da die echte Registry-Logik hier nicht nachgebildet wird - Tests pruefen
        stattdessen, dass sie aufgerufen werden, per Spy/Patch)."""

        def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
            cls._test_domain = domain
            super().__init_subclass__(**kwargs)

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            return None

        def async_create_entry(self, *, title: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(self, *, step_id: str, data_schema: Any) -> dict[str, Any]:
            return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    class OptionsFlow:
        """Minimaler Ersatz mit denselben Ergebnis-Helfern wie ConfigFlow."""

        def async_create_entry(self, *, title: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(self, *, step_id: str, data_schema: Any) -> dict[str, Any]:
            return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow

    data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
    data_entry_flow.AbortFlow = AbortFlow
    sys.modules.setdefault("homeassistant.data_entry_flow", data_entry_flow)

    # ---- voluptuous: nur Schema()/Required() als durchreichende Marker-Objekte ----
    # config_flow.py validiert damit nichts inhaltlich in den Tests - die eigentliche
    # Validierung passiert im echten HA-Frontend. Required() traegt den Default in
    # einem .default-Attribut, damit Tests pruefen koennen, welche Werte die
    # Options-Flow-Schema-Defaults tatsaechlich verwenden (siehe test_config_flow.py).
    voluptuous = types.ModuleType("voluptuous")

    class _RequiredMarker(str):
        def __new__(cls, key: str, default: Any = None) -> "_RequiredMarker":
            obj = str.__new__(cls, key)
            obj.default = default() if callable(default) else default
            return obj

    class _VolSchema:
        def __init__(self, schema: dict[Any, Any]) -> None:
            self.schema = schema

        def __call__(self, data: Any) -> Any:
            return data

    voluptuous.Schema = _VolSchema
    voluptuous.Required = _RequiredMarker
    sys.modules.setdefault("voluptuous", voluptuous)

    # ---- homeassistant.const: nur Platform (fuer __init__.py's PLATFORMS-Liste) ----
    const_module = types.ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"

    const_module.Platform = Platform
    sys.modules.setdefault("homeassistant.const", const_module)

    entity = types.ModuleType("homeassistant.helpers.entity")

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    entity.EntityCategory = EntityCategory

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object

    sys.modules.setdefault("homeassistant.components", components)
    sys.modules.setdefault("homeassistant.components.sensor", components_sensor)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.helpers.entity", entity)
    sys.modules.setdefault("homeassistant.helpers.entity_platform", entity_platform)


class FakeResponse:
    """Asynchrone HTTP-Antwort mit festem Status und JSON-Payload."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False

    async def json(self) -> Any:
        return self._payload


class FakeSession:
    """HTTP-Session, die Antworten in Aufrufreihenfolge liefert."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self._responses.pop(0)
