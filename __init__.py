"""Medication Manager integration for Home Assistant."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from .const import (
    ATTR_MEDICATION_ID,
    CONF_DOCTOR_REMINDER_THRESHOLD,
    CONF_DOSAGE,
    CONF_DOSE_TIME,
    CONF_DOSES_PER_DAY,
    CONF_INVENTORY,
    CONF_LOW_INVENTORY_THRESHOLD,
    CONF_MEDICATIONS,
    CONF_NFC_ID,
    CONF_PEOPLE,
    CONF_PERSON,
    CONF_REFILLS_REMAINING,
    DEFAULT_DOCTOR_THRESHOLD,
    DEFAULT_DOSES_PER_DAY,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_REFILLS,
    DOMAIN,
    LOGGER,
    PLATFORMS,
    SERVICE_RECORD_DOSE,
    SERVICE_UPDATE_INVENTORY,
    STATE_NOT_TAKEN,
    STATE_PARTIALLY_TAKEN,
    STATE_TAKEN,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Service schemas
SERVICE_RECORD_DOSE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MEDICATION_ID): cv.string,
    }
)

SERVICE_UPDATE_INVENTORY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MEDICATION_ID): cv.string,
        vol.Required(CONF_INVENTORY): cv.positive_int,
    }
)


@dataclass
class Medication:
    """Representation of a medication."""

    medication_id: str
    name: str
    nfc_id: str | None
    dosage: int
    inventory: int
    dose_time: str
    doses_per_day: int
    refills_remaining: int
    low_inventory_threshold: int
    doctor_reminder_threshold: int
    person_id: str | None = None
    person_name: str | None = None
    last_dose: datetime | None = None
    doses_today: int = 0

    @property
    def display_name(self) -> str:
        """Return display name including person if assigned."""
        if self.person_name:
            return f"{self.person_name}'s {self.name}"
        return self.name

    @property
    def status(self) -> str:
        """Return current medication status."""
        if self.doses_today >= self.doses_per_day:
            return STATE_TAKEN
        if self.doses_today > 0:
            return STATE_PARTIALLY_TAKEN
        return STATE_NOT_TAKEN


@dataclass
class MedicationManagerData:
    """Runtime data for Medication Manager."""

    medications: dict[str, Medication] = field(default_factory=dict)
    people: dict[str, str] = field(default_factory=dict)  # id -> name
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


type MedicationManagerConfigEntry = ConfigEntry[MedicationManagerData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Medication Manager component."""
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: MedicationManagerConfigEntry
) -> bool:
    """Set up Medication Manager from a config entry."""
    LOGGER.debug("Setting up medication manager entry: %s", entry.title)

    # Create runtime data
    runtime_data = MedicationManagerData()

    # Process people
    for person_config in entry.data.get(CONF_PEOPLE, []):
        person_id = slugify(person_config[CONF_NAME])
        runtime_data.people[person_id] = person_config[CONF_NAME]

    # Process medications
    for med_config in entry.data.get(CONF_MEDICATIONS, []):
        med_id = slugify(med_config[CONF_NAME])

        # Find person if assigned
        person_name = med_config.get(CONF_PERSON)
        person_id = None
        if person_name and person_name != "none":
            person_id = slugify(person_name)
            if person_id not in runtime_data.people:
                runtime_data.people[person_id] = person_name

        # Apply options overrides
        inventory = entry.options.get(CONF_INVENTORY, med_config.get(CONF_INVENTORY, 0))
        refills = entry.options.get(
            CONF_REFILLS_REMAINING,
            med_config.get(CONF_REFILLS_REMAINING, DEFAULT_REFILLS),
        )
        low_threshold = entry.options.get(
            CONF_LOW_INVENTORY_THRESHOLD,
            med_config.get(CONF_LOW_INVENTORY_THRESHOLD, DEFAULT_LOW_THRESHOLD),
        )
        doctor_threshold = entry.options.get(
            CONF_DOCTOR_REMINDER_THRESHOLD,
            med_config.get(CONF_DOCTOR_REMINDER_THRESHOLD, DEFAULT_DOCTOR_THRESHOLD),
        )

        medication = Medication(
            medication_id=med_id,
            name=med_config[CONF_NAME],
            nfc_id=med_config.get(CONF_NFC_ID),
            dosage=med_config.get(CONF_DOSAGE, 1),
            inventory=inventory,
            dose_time=med_config.get(CONF_DOSE_TIME, "08:00:00"),
            doses_per_day=med_config.get(CONF_DOSES_PER_DAY, DEFAULT_DOSES_PER_DAY),
            refills_remaining=refills,
            low_inventory_threshold=low_threshold,
            doctor_reminder_threshold=doctor_threshold,
            person_id=person_id,
            person_name=person_name if person_name != "none" else None,
        )
        runtime_data.medications[med_id] = medication

    # Store runtime data
    entry.runtime_data = runtime_data

    # Register services (only once)
    await _async_setup_services(hass)

    # Set up tag scan listener
    _setup_tag_listener(hass, entry)

    # Set up scheduled tasks
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda now: hass.async_create_task(
                _check_medication_schedule(hass, entry, now)
            ),
            timedelta(minutes=5),
        )
    )

    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    LOGGER.info("Medication Manager setup complete for entry: %s", entry.title)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MedicationManagerConfigEntry
) -> bool:
    """Unload a config entry."""
    # Remove tag listener
    if listener := hass.data.get(DOMAIN, {}).get(f"{entry.entry_id}_tag_listener"):
        listener()
        hass.data[DOMAIN].pop(f"{entry.entry_id}_tag_listener", None)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _setup_tag_listener(
    hass: HomeAssistant, entry: MedicationManagerConfigEntry
) -> None:
    """Set up listener for NFC tag scans."""

    @callback
    def handle_tag_scan(event: Any) -> None:
        """Handle tag_scanned event."""
        tag_id = event.data.get("tag_id")
        if not tag_id:
            return

        LOGGER.debug("Tag scanned: %s", tag_id)

        # Find medication with this NFC ID
        for medication in entry.runtime_data.medications.values():
            if medication.nfc_id == tag_id:
                LOGGER.info(
                    "Found medication %s for NFC tag %s",
                    medication.medication_id,
                    tag_id,
                )
                hass.async_create_task(
                    _async_record_dose(hass, entry, medication.medication_id)
                )
                return

        LOGGER.debug("No medication found for NFC tag: %s", tag_id)

    # Register listener
    remove_listener = hass.bus.async_listen("tag_scanned", handle_tag_scan)

    # Store for cleanup
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][f"{entry.entry_id}_tag_listener"] = remove_listener


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the integration."""
    if hass.services.has_service(DOMAIN, SERVICE_RECORD_DOSE):
        return  # Already registered

    async def handle_record_dose(call: ServiceCall) -> None:
        """Handle record_dose service call."""
        med_id = call.data[ATTR_MEDICATION_ID]

        # Find the entry with this medication
        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data") and med_id in entry.runtime_data.medications:
                await _async_record_dose(hass, entry, med_id)
                return

        LOGGER.error("Unknown medication ID: %s", med_id)

    async def handle_update_inventory(call: ServiceCall) -> None:
        """Handle update_inventory service call."""
        med_id = call.data[ATTR_MEDICATION_ID]
        new_inventory = call.data[CONF_INVENTORY]

        # Find the entry with this medication
        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data") and med_id in entry.runtime_data.medications:
                await _async_update_inventory(hass, entry, med_id, new_inventory)
                return

        LOGGER.error("Unknown medication ID: %s", med_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RECORD_DOSE,
        handle_record_dose,
        schema=SERVICE_RECORD_DOSE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_INVENTORY,
        handle_update_inventory,
        schema=SERVICE_UPDATE_INVENTORY_SCHEMA,
    )


async def _async_record_dose(
    hass: HomeAssistant,
    entry: MedicationManagerConfigEntry,
    medication_id: str,
) -> None:
    """Record a dose for a medication."""
    async with entry.runtime_data._lock:
        medication = entry.runtime_data.medications.get(medication_id)
        if not medication:
            LOGGER.error("Medication not found: %s", medication_id)
            return

        # Check if already dosed today
        if medication.doses_today >= medication.doses_per_day:
            await _async_notify(
                hass,
                f"Warning: You've already taken all doses of {medication.display_name} today.",
            )
            return

        # Record the dose
        medication.last_dose = datetime.now()
        medication.doses_today += 1
        medication.inventory = max(0, medication.inventory - 1)

        LOGGER.info(
            "Recorded dose for %s. Inventory: %d",
            medication.display_name,
            medication.inventory,
        )

        # Notify
        await _async_notify(
            hass,
            f"Recorded dose for {medication.display_name}. {medication.inventory} doses remaining.",
        )

        # Trigger sensor updates
        hass.bus.async_fire(
            f"{DOMAIN}_medication_updated",
            {"medication_id": medication_id, "entry_id": entry.entry_id},
        )


async def _async_update_inventory(
    hass: HomeAssistant,
    entry: MedicationManagerConfigEntry,
    medication_id: str,
    new_inventory: int,
) -> None:
    """Update inventory for a medication."""
    async with entry.runtime_data._lock:
        medication = entry.runtime_data.medications.get(medication_id)
        if not medication:
            LOGGER.error("Medication not found: %s", medication_id)
            return

        medication.inventory = new_inventory

        LOGGER.info(
            "Updated inventory for %s to %d",
            medication.display_name,
            new_inventory,
        )

        await _async_notify(
            hass,
            f"Updated inventory for {medication.display_name}: {new_inventory} doses.",
        )

        hass.bus.async_fire(
            f"{DOMAIN}_medication_updated",
            {"medication_id": medication_id, "entry_id": entry.entry_id},
        )


async def _check_medication_schedule(
    hass: HomeAssistant,
    entry: MedicationManagerConfigEntry,
    now: datetime,
) -> None:
    """Check medications and send reminders."""
    async with entry.runtime_data._lock:
        for medication in entry.runtime_data.medications.values():
            try:
                # Parse dose time
                hour, minute, second = map(int, medication.dose_time.split(":"))
                dose_time = now.replace(
                    hour=hour, minute=minute, second=second, microsecond=0
                ).time()
                current_time = now.time()

                # Check if reminder needed
                if (
                    current_time > dose_time
                    and medication.doses_today < medication.doses_per_day
                ):
                    await _async_notify(
                        hass,
                        f"Reminder: Time to take {medication.display_name} medication.",
                    )

                # Check inventory levels
                if medication.inventory <= medication.low_inventory_threshold:
                    if medication.refills_remaining > 0:
                        await _async_notify(
                            hass,
                            f"Low inventory: Only {medication.inventory} doses of "
                            f"{medication.display_name} remaining. Please order a refill.",
                        )
                    elif medication.inventory <= medication.doctor_reminder_threshold:
                        await _async_notify(
                            hass,
                            f"Doctor appointment needed: Only {medication.inventory} doses of "
                            f"{medication.display_name} remaining and no refills left.",
                        )

            except (ValueError, AttributeError) as err:
                LOGGER.error(
                    "Error checking schedule for %s: %s",
                    medication.display_name,
                    err,
                )


async def _async_notify(hass: HomeAssistant, message: str) -> None:
    """Send a notification."""
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {"message": message, "title": "Medication Manager"},
            blocking=False,
        )
    except Exception as err:
        LOGGER.error("Error sending notification: %s", err)
