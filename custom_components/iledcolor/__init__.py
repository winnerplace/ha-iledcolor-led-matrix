from __future__ import annotations

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import CHAR_WRITE1, CHAR_WRITE2, CONF_CAPABILITY, DOMAIN
from .device import IledColorDevice
from .protocol import Capability

PLATFORMS = [Platform.LIGHT]

SERVICE_SEND_RAW = "send_raw"
SEND_RAW_SCHEMA = vol.Schema(
    {
        vol.Required("data"): cv.string,
        vol.Optional("characteristic", default="write1"): vol.In(["write1", "write2"]),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address = entry.data[CONF_ADDRESS]
    if bluetooth.async_ble_device_from_address(hass, address, connectable=True) is None:
        raise ConfigEntryNotReady(f"{address} not found")

    capability = Capability.from_dict(entry.data.get(CONF_CAPABILITY, {}))
    device = IledColorDevice(hass, address, capability)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = device

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RAW):
        return

    async def _send_raw(call: ServiceCall) -> None:
        data = bytes.fromhex(call.data["data"].replace(" ", ""))
        char = CHAR_WRITE2 if call.data["characteristic"] == "write2" else CHAR_WRITE1
        for device in hass.data.get(DOMAIN, {}).values():
            await device.send_raw(data, char)

    hass.services.async_register(DOMAIN, SERVICE_SEND_RAW, _send_raw, schema=SEND_RAW_SCHEMA)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        device: IledColorDevice = hass.data[DOMAIN].pop(entry.entry_id)
        await device.disconnect()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SEND_RAW)
    return unloaded
