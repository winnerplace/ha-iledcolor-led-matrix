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
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAPABILITY,
    CONF_ENTITIES,
    DOMAIN,
    SERVICE_UUID,
)
from .protocol import find_capability_blob, parse_capability


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
            return self.async_create_entry(data={**self._entry.options, **user_input})
        opts = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENTITIES, default=opts.get(CONF_ENTITIES, [])
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            multiple=True,
                            reorder=True,
                            domain=["sensor", "binary_sensor", "weather", "climate"],
                        )
                    ),
                }
            ),
        )
