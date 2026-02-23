"""Switch entities for Whirlpool Oven."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SAID, DOMAIN
from .coordinator import WhirlpoolOvenCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WhirlpoolOvenCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CavityLightSwitch(coordinator, entry)])


class CavityLightSwitch(CoordinatorEntity[WhirlpoolOvenCoordinator], SwitchEntity):
    """Toggle the oven cavity light."""

    def __init__(
        self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_SAID]}_cavity_light"
        self._attr_name = "Oven Cavity Light"
        self._attr_icon = "mdi:lightbulb"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_SAID])},
            "name": entry.title,
            "manufacturer": "Whirlpool",
            "model": entry.data.get("model"),
        }

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.primary_cavity.get("cavityLight", False))

    async def async_turn_on(self, **kwargs):  # type: ignore[override]
        await self.coordinator.async_set_cavity_light(True)

    async def async_turn_off(self, **kwargs):  # type: ignore[override]
        await self.coordinator.async_set_cavity_light(False)
