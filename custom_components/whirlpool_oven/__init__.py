"""Whirlpool Oven integration for Home Assistant."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS
from .coordinator import WhirlpoolOvenCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Whirlpool Oven from a config entry."""
    session = async_get_clientsession(hass)
    coordinator = WhirlpoolOvenCoordinator(hass, entry, session)

    try:
        await coordinator.async_setup()
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to set up Whirlpool Oven: %s", err)
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: WhirlpoolOvenCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (e.g. options changed)."""
    await hass.config_entries.async_reload(entry.entry_id)
