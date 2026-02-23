"""Button entities — start favourite / stop cooking."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import CONF_SAID, DOMAIN
from .coordinator import WhirlpoolOvenCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WhirlpoolOvenCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StartFavouriteButton(coordinator, entry),
            StopCookingButton(coordinator, entry),
        ]
    )


class _OvenButtonBase(ButtonEntity):
    def __init__(
        self,
        coordinator: WhirlpoolOvenCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
        name: str,
        icon: str,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_SAID]}_{unique_suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_SAID])},
            "name": entry.title,
            "manufacturer": "Whirlpool",
            "model": entry.data.get("model"),
        }


class StartFavouriteButton(_OvenButtonBase):
    """Start the currently selected favourite preset."""

    def __init__(
        self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator, entry, "start_favourite", "Start Favourite", "mdi:play"
        )

    async def async_press(self) -> None:
        """Find the FavouriteSelect entity and trigger the selected favourite."""
        er = async_get_entity_registry(self.hass)
        said = self._entry.data[CONF_SAID]

        # Look up the companion select entity
        select_uid = f"{said}_favourite"
        select_entry = er.async_get_entity_id("select", DOMAIN, select_uid)
        if select_entry is None:
            _LOGGER.warning("Favourite select entity not found")
            return

        state = self.hass.states.get(select_entry)
        if state is None or state.state in ("— select —", "unknown", "unavailable"):
            _LOGGER.warning("No favourite selected")
            return

        # Match name back to ID
        fav_name = state.state
        fav = next(
            (f for f in self._coordinator.favourites if f.get("name") == fav_name),
            None,
        )
        if fav is None:
            _LOGGER.error("Could not find favourite '%s'", fav_name)
            return

        await self._coordinator.async_trigger_favourite(fav["id"])


class StopCookingButton(_OvenButtonBase):
    """Cancel the active cooking cycle."""

    def __init__(
        self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(
            coordinator, entry, "stop_cooking", "Stop Cooking", "mdi:stop"
        )

    async def async_press(self) -> None:
        await self._coordinator.async_stop_cooking()
