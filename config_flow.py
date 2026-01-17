"""Config flow for Medication Manager integration."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
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
    DEFAULT_DOSAGE,
    DEFAULT_DOSE_TIME,
    DEFAULT_DOSES_PER_DAY,
    DEFAULT_INVENTORY,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_REFILLS,
    DOMAIN,
    LOGGER,
)


class MedicationManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Medication Manager."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._medication_data: dict[str, Any] = {}
        self._people: list[dict[str, str]] = []
        self._last_added_person: str | None = None
        self._cancel_event: asyncio.Event | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        LOGGER.debug("In user step, user_input: %s", user_input)

        # Load existing people
        self._load_existing_people()

        if user_input is not None:
            if user_input.get("setup_type") == "add_person":
                LOGGER.debug("User chose to add person first")
                return await self.async_step_add_person()
            LOGGER.debug("User chose to add medication directly")
            return await self.async_step_medication_setup()

        options = {
            "add_medication": "Add a medication directly",
            "add_person": "Add a person first, then add their medication",
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("setup_type", default="add_medication"): vol.In(options)}
            ),
        )

    async def async_step_add_person(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new person."""
        if user_input is not None:
            person_name = user_input[CONF_NAME]
            self._people.append({CONF_NAME: person_name})
            self._last_added_person = person_name
            return await self.async_step_medication_setup()

        return self.async_show_form(
            step_id="add_person",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME): str}
            ),
            description_placeholders={
                "message": "Enter the name of the person who will take this medication"
            },
        )

    async def async_step_medication_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle setting up a medication."""
        if user_input is not None:
            med_data = dict(user_input)

            # Check if user wants to scan NFC
            if med_data.pop("nfc_scan_now", False):
                self._medication_data = med_data
                LOGGER.debug("User chose to scan NFC - proceeding to scan step")
                return await self.async_step_scan_nfc()

            # Handle person selection
            person_name = med_data.get(CONF_PERSON)
            if person_name and person_name != "none":
                if not any(p[CONF_NAME] == person_name for p in self._people):
                    self._people.append({CONF_NAME: person_name})
            elif CONF_PERSON in med_data:
                med_data.pop(CONF_PERSON)

            # Create entry title
            entry_title = med_data[CONF_NAME]
            if person_name and person_name != "none":
                entry_title = f"{person_name}'s {entry_title}"

            LOGGER.debug("Creating entry with title: %s", entry_title)
            return self.async_create_entry(
                title=entry_title,
                data={
                    CONF_PEOPLE: self._people,
                    CONF_MEDICATIONS: [med_data],
                },
            )

        # Create person options
        person_options = {"none": "No person (unassigned)"}
        for person in self._people:
            person_options[person[CONF_NAME]] = person[CONF_NAME]

        default_person = self._last_added_person or "none"

        return self.async_show_form(
            step_id="medication_setup",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(CONF_PERSON, default=default_person): vol.In(
                        person_options
                    ),
                    vol.Required(CONF_DOSAGE, default=DEFAULT_DOSAGE): cv.positive_int,
                    vol.Required(
                        CONF_INVENTORY, default=DEFAULT_INVENTORY
                    ): cv.positive_int,
                    vol.Required(
                        CONF_DOSE_TIME, default=DEFAULT_DOSE_TIME
                    ): str,
                    vol.Optional(
                        CONF_DOSES_PER_DAY, default=DEFAULT_DOSES_PER_DAY
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_REFILLS_REMAINING, default=DEFAULT_REFILLS
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_LOW_INVENTORY_THRESHOLD, default=DEFAULT_LOW_THRESHOLD
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_DOCTOR_REMINDER_THRESHOLD, default=DEFAULT_DOCTOR_THRESHOLD
                    ): cv.positive_int,
                    vol.Optional("nfc_scan_now", default=True): cv.boolean,
                }
            ),
            description_placeholders={
                "message": "Enter medication details. Enable NFC scanning to link a tag."
            },
        )

    async def async_step_scan_nfc(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the NFC scanning step with actual tag waiting."""
        errors: dict[str, str] = {}

        LOGGER.debug("In NFC scanning step, user_input: %s", user_input)

        if not self._medication_data:
            LOGGER.error("No medication data available for NFC scanning")
            return self.async_abort(reason="no_medication_data")

        if user_input is not None:
            # User submitted the form (either with scanned tag or manual entry)
            med_data = self._medication_data.copy()

            # Add the tag ID if provided
            tag_id = user_input.get("tag_id")
            if tag_id:
                med_data[CONF_NFC_ID] = tag_id
                LOGGER.debug("NFC tag ID added: %s", tag_id)

            # Handle person selection
            person_name = med_data.get(CONF_PERSON)
            if person_name == "none":
                med_data.pop(CONF_PERSON, None)
                person_name = None

            # Create entry title
            entry_title = med_data[CONF_NAME]
            if person_name:
                entry_title = f"{person_name}'s {entry_title}"

            LOGGER.debug("Creating entry from NFC step with title: %s", entry_title)
            return self.async_create_entry(
                title=entry_title,
                data={
                    CONF_PEOPLE: self._people,
                    CONF_MEDICATIONS: [med_data],
                },
            )

        # Try to use the async_wait_for_tag_scan helper if available
        scanned_tag_id = ""
        try:
            from homeassistant.components.tag import async_wait_for_tag_scan

            # Create a cancel event with a timeout
            self._cancel_event = asyncio.Event()

            # Wait for tag scan with a short timeout for the form display
            # The actual waiting happens in the background
            LOGGER.debug("Waiting for NFC tag scan...")

            # Use asyncio.wait_for with a very short timeout just to check
            # if a tag was recently scanned
            try:
                result = await asyncio.wait_for(
                    async_wait_for_tag_scan(self.hass, self._cancel_event),
                    timeout=0.1,  # Very short - just check if already scanned
                )
                if result is not None:
                    scanned_tag_id = result["tag_id"]
                    LOGGER.debug("Tag scanned during wait: %s", scanned_tag_id)
            except asyncio.TimeoutError:
                # No tag scanned yet, that's fine
                pass

        except ImportError:
            LOGGER.debug("async_wait_for_tag_scan not available")

        # Show the form for manual entry or confirmation
        return self.async_show_form(
            step_id="scan_nfc",
            data_schema=vol.Schema(
                {
                    vol.Optional("tag_id", default=scanned_tag_id): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "message": (
                    "Scan an NFC tag with your device or enter the tag ID manually. "
                    "Leave blank to skip NFC linking."
                )
            },
        )

    def _load_existing_people(self) -> None:
        """Load existing people from other config entries."""
        for entry in self._async_current_entries():
            if CONF_PEOPLE in entry.data:
                for person in entry.data[CONF_PEOPLE]:
                    if person not in self._people:
                        self._people.append(person)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return MedicationOptionsFlowHandler(config_entry)


class MedicationOptionsFlowHandler(OptionsFlow):
    """Handle medication options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        medications = self.config_entry.data.get(CONF_MEDICATIONS, [])

        if not medications:
            return self.async_abort(reason="no_medications")

        # Show options for the first medication
        medication = medications[0]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INVENTORY,
                        default=medication.get(CONF_INVENTORY, DEFAULT_INVENTORY),
                    ): cv.positive_int,
                    vol.Required(
                        CONF_REFILLS_REMAINING,
                        default=medication.get(CONF_REFILLS_REMAINING, DEFAULT_REFILLS),
                    ): cv.positive_int,
                    vol.Required(
                        CONF_LOW_INVENTORY_THRESHOLD,
                        default=medication.get(
                            CONF_LOW_INVENTORY_THRESHOLD, DEFAULT_LOW_THRESHOLD
                        ),
                    ): cv.positive_int,
                    vol.Required(
                        CONF_DOCTOR_REMINDER_THRESHOLD,
                        default=medication.get(
                            CONF_DOCTOR_REMINDER_THRESHOLD, DEFAULT_DOCTOR_THRESHOLD
                        ),
                    ): cv.positive_int,
                }
            ),
        )
