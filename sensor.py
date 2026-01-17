"""Sensor platform for Medication Manager integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Medication, MedicationManagerConfigEntry
from .const import DOMAIN, LOGGER


@dataclass(frozen=True, kw_only=True)
class MedicationSensorEntityDescription(SensorEntityDescription):
    """Describes Medication Manager sensor entity."""

    value_fn: Callable[[Medication], Any]
    extra_state_fn: Callable[[Medication], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[MedicationSensorEntityDescription, ...] = (
    MedicationSensorEntityDescription(
        key="status",
        translation_key="medication_status",
        icon="mdi:pill",
        value_fn=lambda med: med.status,
        extra_state_fn=lambda med: {
            "doses_today": med.doses_today,
            "doses_per_day": med.doses_per_day,
            "last_dose": med.last_dose.isoformat() if med.last_dose else None,
        },
    ),
    MedicationSensorEntityDescription(
        key="inventory",
        translation_key="medication_inventory",
        icon="mdi:counter",
        native_unit_of_measurement="doses",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda med: med.inventory,
        extra_state_fn=lambda med: {
            "low_threshold": med.low_inventory_threshold,
            "is_low": med.inventory <= med.low_inventory_threshold,
            "refills_remaining": med.refills_remaining,
        },
    ),
    MedicationSensorEntityDescription(
        key="next_dose",
        translation_key="next_dose_time",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda med: None,  # Will be computed in sensor
        extra_state_fn=lambda med: {
            "scheduled_time": med.dose_time,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MedicationManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Medication Manager sensors from a config entry."""
    LOGGER.debug("Setting up sensor platform for entry: %s", entry.title)

    sensors: list[MedicationSensor] = []

    for medication in entry.runtime_data.medications.values():
        for description in SENSOR_DESCRIPTIONS:
            sensors.append(
                MedicationSensor(
                    entry=entry,
                    medication=medication,
                    description=description,
                )
            )

    async_add_entities(sensors)
    LOGGER.debug("Added %d sensors for entry: %s", len(sensors), entry.title)


class MedicationSensor(SensorEntity):
    """Representation of a Medication Manager sensor."""

    _attr_has_entity_name = True
    entity_description: MedicationSensorEntityDescription

    def __init__(
        self,
        entry: MedicationManagerConfigEntry,
        medication: Medication,
        description: MedicationSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._medication = medication
        self._entry = entry

        # Set unique ID
        self._attr_unique_id = (
            f"{entry.entry_id}_{medication.medication_id}_{description.key}"
        )

        # Set device info to group all sensors for a medication
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{medication.medication_id}")},
            "name": medication.display_name,
            "manufacturer": "Medication Manager",
            "model": "Medication Tracker",
            "via_device": (DOMAIN, entry.entry_id),
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self._medication)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.extra_state_fn:
            return self.entity_description.extra_state_fn(self._medication)
        return None

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        await super().async_added_to_hass()

        @callback
        def handle_update(event: Any) -> None:
            """Handle medication update event."""
            if event.data.get("medication_id") == self._medication.medication_id:
                self.async_write_ha_state()

        # Listen for medication updates
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_medication_updated",
                handle_update,
            )
        )
