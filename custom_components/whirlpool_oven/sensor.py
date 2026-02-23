"""Sensor entities for Whirlpool Oven."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SAID, DOMAIN
from .coordinator import WhirlpoolOvenCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WhirlpoolOvenCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OvenTemperatureSensor(coordinator, entry, "current"),
            OvenTemperatureSensor(coordinator, entry, "target"),
            OvenCavityStateSensor(coordinator, entry),
            OvenDoorSensor(coordinator, entry),
            OvenRecipeStateSensor(coordinator, entry),
        ]
    )


class _OvenSensorBase(CoordinatorEntity[WhirlpoolOvenCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: WhirlpoolOvenCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_SAID]}_{unique_suffix}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_SAID])},
            "name": entry.title,
            "manufacturer": "Whirlpool",
            "model": entry.data.get("model"),
        }


class OvenTemperatureSensor(_OvenSensorBase):
    """Current or target oven temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: WhirlpoolOvenCoordinator,
        entry: ConfigEntry,
        kind: str,  # "current" or "target"
    ) -> None:
        label = "Oven Temperature" if kind == "current" else "Oven Target Temperature"
        super().__init__(coordinator, entry, f"temp_{kind}", label)
        self._kind = kind

    @property
    def native_value(self) -> float | None:
        cavity = self.coordinator.primary_cavity
        if self._kind == "current":
            val = cavity.get("ovenDisplayTemperature")
        else:
            val = cavity.get("targetTemperature")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None


class OvenCavityStateSensor(_OvenSensorBase):
    """The current cooking state (idle / preheating / cooking / …)."""

    def __init__(self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "cavity_state", "Oven Cavity State")
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.primary_cavity.get("cavityState")


class OvenDoorSensor(_OvenSensorBase):
    """Door open/closed status."""

    def __init__(self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "door", "Oven Door")
        self._attr_icon = "mdi:door"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.primary_cavity.get("doorStatus")


class OvenRecipeStateSensor(_OvenSensorBase):
    """Recipe execution state (idle / running / paused / …)."""

    def __init__(self, coordinator: WhirlpoolOvenCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "recipe_state", "Oven Recipe State")
        self._attr_icon = "mdi:chef-hat"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.primary_cavity.get("recipeExecutionState")
