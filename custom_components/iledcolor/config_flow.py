from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback, valid_entity_id
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    CONF_CAPABILITY,
    CONF_CUSTOM_TEXTS,
    CONF_ENTITIES,
    CONF_ROW_FORMAT,
    CONF_ROWS,
    DOMAIN,
    ROW_FORMAT_DEFAULT,
    SERVICE_UUID,
    merged_rows,
)
from .protocol import find_capability_blob, parse_capability

ROW_DOMAINS = ["sensor", "binary_sensor", "weather", "climate"]

ROW_FORMAT_TOKENS = [
    selector.SelectOptionDict(value="{area}", label="공간 {area}"),
    selector.SelectOptionDict(value="{name}", label="이름 {name}"),
    selector.SelectOptionDict(value="{value}", label="값 {value}"),
    selector.SelectOptionDict(value="{unit}", label="단위 {unit}"),
    selector.SelectOptionDict(value="{value}{unit}", label="값+단위 {value}{unit}"),
]


def _reorderable(config: selector.SelectSelectorConfig) -> selector.SelectSelector:
    sel = selector.SelectSelector(config)
    sel.config["reorder"] = True
    return sel


def _entity_area(hass: HomeAssistant, entity_id: str) -> str:
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return ""
    area_id = entry.area_id
    if area_id is None and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        area_id = device.area_id if device else None
    if area_id is None:
        return ""
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else ""


def _row_options(hass: HomeAssistant, current: list[str]) -> list[selector.SelectOptionDict]:
    options: list[selector.SelectOptionDict] = []
    seen: set[str] = set()
    for state in hass.states.async_all(ROW_DOMAINS):
        friendly = state.attributes.get("friendly_name") or state.entity_id
        area = _entity_area(hass, state.entity_id)
        label = f"{area} {friendly}".strip()
        options.append(selector.SelectOptionDict(value=state.entity_id, label=label))
        seen.add(state.entity_id)
    for row in current:
        if valid_entity_id(row) and row not in seen:
            options.append(selector.SelectOptionDict(value=row, label=row))
    options.sort(key=lambda option: option["label"])
    return options


def _label(info: BluetoothServiceInfoBleak) -> str:
    cap = parse_capability(find_capability_blob(info))
    size = f" {cap.width}x{cap.height}" if cap and cap.width else ""
    return f"{info.name or info.address}{size} ({info.address})"


class IledColorConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "IledColorOptionsFlow":
        return IledColorOptionsFlow(config_entry)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or discovery_info.address}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self._create(self._discovery)
        cap = parse_capability(find_capability_blob(self._discovery))
        size = f"{cap.width}x{cap.height}" if cap and cap.width else "?"
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovery.name or self._discovery.address,
                "size": size,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            info = self._discovered[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create(info)

        current = self._async_current_ids()
        matched: dict[str, BluetoothServiceInfoBleak] = {}
        every: dict[str, BluetoothServiceInfoBleak] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in current:
                continue
            every[info.address] = info
            if SERVICE_UUID in info.service_uuids or find_capability_blob(info):
                matched[info.address] = info

        self._discovered = matched or every
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In({a: _label(i) for a, i in self._discovered.items()})}
            ),
        )

    def _create(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        cap = parse_capability(find_capability_blob(info))
        return self.async_create_entry(
            title=info.name or info.address,
            data={
                CONF_ADDRESS: info.address,
                CONF_CAPABILITY: cap.as_dict() if cap else {},
            },
        )


class IledColorOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            rows = [r.strip() for r in user_input.get(CONF_ROWS, []) if r.strip()]
            row_format = " ".join(user_input.get(CONF_ROW_FORMAT, [])).strip()
            options = {
                **self._entry.options,
                CONF_ROWS: rows,
                CONF_ROW_FORMAT: row_format or ROW_FORMAT_DEFAULT,
            }
            options.pop(CONF_ENTITIES, None)
            options.pop(CONF_CUSTOM_TEXTS, None)
            return self.async_create_entry(data=options)
        opts = self._entry.options
        current_rows = merged_rows(opts)
        format_tokens = str(opts.get(CONF_ROW_FORMAT) or ROW_FORMAT_DEFAULT).split()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ROWS, default=current_rows): _reorderable(
                        selector.SelectSelectorConfig(
                            options=_row_options(self.hass, current_rows),
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_ROW_FORMAT, default=format_tokens): _reorderable(
                        selector.SelectSelectorConfig(
                            options=ROW_FORMAT_TOKENS,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
