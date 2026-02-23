"""Select entity — choose a saved favourite preset."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SAID, DOMAIN
from .coordinator import WhirlpoolOvenCoordinator

_NO_SELECTION = "— select —"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WhirlpoolOvenCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FavouriteSelect(coordinator, entry)])


class FavouriteSelect(CoordinatorEntity[WhirlpoolOvenCoordinator], SelectEntity):
    """Dropdown listing all saved favourites for this appliance."""

    def __init__(
        self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_SAID]}_favourite"
        self._attr_name = "Oven Favourite"
        self._attr_icon = "mdi:heart"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_SAID])},
            "name": entry.title,
            "manufacturer": "Whirlpool",
            "model": entry.data.get("model"),
        }
        self._selected_id: str | None = None

    @property
    def options(self) -> list[str]:
        names = [f.get("name", f["id"]) for f in self.coordinator.favourites]
        return [_NO_SELECTION] + names

    @property
    def current_option(self) -> str:
        if self._selected_id is None:
            return _NO_SELECTION
        fav = next(
            (f for f in self.coordinator.favourites if f["id"] == self._selected_id),
            None,
        )
        return fav["name"] if fav else _NO_SELECTION

    async def async_select_option(self, option: str) -> None:
        """Record which favourite is selected (doesn't start cooking yet)."""
        if option == _NO_SELECTION:
            self._selected_id = None
            self.coordinator.selected_favourite_id = None
            return
        fav = next(
            (f for f in self.coordinator.favourites if f.get("name") == option), None
        )
        self._selected_id = fav["id"] if fav else None
        self.coordinator.selected_favourite_id = self._selected_id
        self.async_write_ha_state()
