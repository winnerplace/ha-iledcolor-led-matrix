from __future__ import annotations

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CHAR_WRITE1, CHAR_WRITE2, CONF_CAPABILITY, DOMAIN
from .device import IledColorDevice
from .protocol import Capability, find_capability_blob, parse_capability
from .status_display import StatusDisplay

PLATFORMS = [Platform.LIGHT, Platform.NUMBER, Platform.SELECT, Platform.SWITCH, Platform.TEXT]

SERVICE_SEND_RAW = "send_raw"
SERVICE_DISPLAY_TEXT = "display_text"
SERVICE_DISPLAY_IMAGE = "display_image"
SERVICE_DISPLAY_GIF = "display_gif"
SERVICE_DISPLAY_COLOR = "display_color"

SEND_RAW_SCHEMA = vol.Schema(
    {
        vol.Required("data"): cv.string,
        vol.Optional("characteristic", default="write1"): vol.In(["write1", "write2"]),
    }
)
_EFFECT = vol.All(vol.Coerce(int), vol.Range(min=0, max=7))
_BYTE = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
_RGB = vol.All([vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(min=3, max=3))
_FIT = vol.In(["contain", "cover", "stretch"])

DISPLAY_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required("text"): cv.string,
        vol.Optional("color", default=[255, 255, 255]): _RGB,
        vol.Optional("effect", default=0): _EFFECT,
        vol.Optional("speed", default=1): _BYTE,
        vol.Optional("dwell", default=30): _BYTE,
        vol.Optional("slide", default=False): cv.boolean,
    }
)
DISPLAY_COLOR_SCHEMA = vol.Schema(
    {
        vol.Required("color"): _RGB,
        vol.Optional("effect", default=0): _EFFECT,
        vol.Optional("speed", default=1): _BYTE,
        vol.Optional("dwell", default=30): _BYTE,
    }
)
DISPLAY_IMAGE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("source"): cv.string,
            vol.Optional("file"): cv.string,
            vol.Optional("fit", default="contain"): _FIT,
            vol.Optional("background"): _RGB,
            vol.Optional("tolerance", default=0): _BYTE,
            vol.Optional("effect", default=0): _EFFECT,
            vol.Optional("speed", default=1): _BYTE,
            vol.Optional("dwell", default=30): _BYTE,
        }
    ),
    cv.has_at_least_one_key("source", "file"),
)
DISPLAY_GIF_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("source"): cv.string,
            vol.Optional("file"): cv.string,
            vol.Optional("fit", default="contain"): _FIT,
            vol.Optional("background"): _RGB,
            vol.Optional("tolerance", default=0): _BYTE,
            vol.Optional("max_frames"): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
            vol.Optional("frame_hold", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
            vol.Optional("effect", default=0): _EFFECT,
            vol.Optional("speed"): _BYTE,
        }
    ),
    cv.has_at_least_one_key("source", "file"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address = entry.data[CONF_ADDRESS]
    if bluetooth.async_ble_device_from_address(hass, address, connectable=True) is None:
        raise ConfigEntryNotReady(f"{address} not found")

    capability = _reparse_capability(hass, entry, address)
    device = IledColorDevice(hass, entry, capability)
    coordinator = StatusDisplay(hass, entry, device)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "device": device,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _register_services(hass)
    return True


def _reparse_capability(hass: HomeAssistant, entry: ConfigEntry, address: str) -> Capability:
    stored = Capability.from_dict(entry.data.get(CONF_CAPABILITY, {}))
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    if info is None:
        return stored
    fresh = parse_capability(find_capability_blob(info))
    if fresh is None or not (1 <= fresh.width <= 1024 and 1 <= fresh.height <= 1024):
        return stored
    if fresh.as_dict() != stored.as_dict():
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_CAPABILITY: fresh.as_dict()}
        )
    return fresh


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator: StatusDisplay = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.apply_options()
    coordinator.notify()


def _devices(hass: HomeAssistant) -> list[IledColorDevice]:
    return [rt["device"] for rt in hass.data.get(DOMAIN, {}).values()]


async def _resolve_bytes(hass: HomeAssistant, source: str) -> str | bytes:
    if source.startswith(("http://", "https://")):
        async with async_get_clientsession(hass).get(source) as response:
            response.raise_for_status()
            return await response.read()
    return await hass.async_add_executor_job(_read_file, source)


def _read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _read_uploaded(hass: HomeAssistant, file_id: str) -> bytes:
    with process_uploaded_file(hass, file_id) as path:
        return path.read_bytes()


async def _resolve_input(hass: HomeAssistant, data: dict) -> bytes | str:
    file_id = data.get("file")
    if file_id:
        return await hass.async_add_executor_job(_read_uploaded, hass, file_id)
    return await _resolve_bytes(hass, data["source"])


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RAW):
        return

    async def _send_raw(call: ServiceCall) -> None:
        data = bytes.fromhex(call.data["data"].replace(" ", ""))
        char = CHAR_WRITE2 if call.data["characteristic"] == "write2" else CHAR_WRITE1
        for device in _devices(hass):
            await device.send_raw(data, char)

    async def _display_text(call: ServiceCall) -> None:
        color = tuple(call.data["color"])
        for device in _devices(hass):
            await device.display_text(
                call.data["text"],
                color=color,
                effect=call.data["effect"],
                speed=call.data["speed"],
                dwell=call.data["dwell"],
                slide=call.data["slide"],
            )

    async def _display_image(call: ServiceCall) -> None:
        source = await _resolve_input(hass, call.data)
        background = call.data.get("background")
        chroma = tuple(background) if background else None
        for device in _devices(hass):
            await device.display_image(
                source,
                fit=call.data["fit"],
                chroma=chroma,
                tol=call.data["tolerance"],
                effect=call.data["effect"],
                speed=call.data["speed"],
                dwell=call.data["dwell"],
            )

    async def _display_gif(call: ServiceCall) -> None:
        source = await _resolve_input(hass, call.data)
        background = call.data.get("background")
        chroma = tuple(background) if background else None
        for device in _devices(hass):
            await device.display_gif(
                source,
                fit=call.data["fit"],
                chroma=chroma,
                tol=call.data["tolerance"],
                max_frames=call.data.get("max_frames"),
                stay=call.data["frame_hold"],
                effect=call.data["effect"],
                speed=call.data.get("speed"),
            )

    async def _display_color(call: ServiceCall) -> None:
        color = tuple(call.data["color"])
        for device in _devices(hass):
            await device.display_color(
                color,
                effect=call.data["effect"],
                speed=call.data["speed"],
                dwell=call.data["dwell"],
            )

    hass.services.async_register(DOMAIN, SERVICE_SEND_RAW, _send_raw, schema=SEND_RAW_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISPLAY_TEXT, _display_text, schema=DISPLAY_TEXT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISPLAY_IMAGE, _display_image, schema=DISPLAY_IMAGE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISPLAY_GIF, _display_gif, schema=DISPLAY_GIF_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISPLAY_COLOR, _display_color, schema=DISPLAY_COLOR_SCHEMA)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime["coordinator"].async_stop()
        await runtime["device"].disconnect()
        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_SEND_RAW,
                SERVICE_DISPLAY_TEXT,
                SERVICE_DISPLAY_IMAGE,
                SERVICE_DISPLAY_GIF,
                SERVICE_DISPLAY_COLOR,
            ):
                hass.services.async_remove(DOMAIN, service)
    return unloaded
