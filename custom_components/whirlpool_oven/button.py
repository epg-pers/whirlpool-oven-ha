"""Button entities — start favourite / stop cooking."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
        """Trigger the currently selected favourite preset."""
        fav_id = self._coordinator.selected_favourite_id
        if fav_id is None:
            _LOGGER.warning("No favourite selected — pick one from the Oven Favourite dropdown first")
            return
        await self._coordinator.async_trigger_favourite(fav_id)


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
