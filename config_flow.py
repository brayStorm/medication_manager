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
        self._scanned_tag_id: str | None = None
        self._scan_task: asyncio.Task | None = None
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
            data_schema=vol.Schema({vol.Required(CONF_NAME): str}),
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
                    vol.Required(CONF_DOSE_TIME, default=DEFAULT_DOSE_TIME): str,
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
        """Handle the NFC scanning step - show progress while waiting."""
        LOGGER.debug("In NFC scanning step")

        if not self._medication_data:
            LOGGER.error("No medication data available for NFC scanning")
            return self.async_abort(reason="no_medication_data")

        # Start the scan task if not already running
        if self._scan_task is None:
            self._cancel_event = asyncio.Event()
            self._scan_task = self.hass.async_create_task(
                self._async_wait_for_tag_scan(),
                "medication_manager_tag_scan",
            )

        # If task is still running, show progress
        if not self._scan_task.done():
            return self.async_show_progress(
                step_id="scan_nfc",
                progress_action="wait_for_tag",
                progress_task=self._scan_task,
                description_placeholders={
                    "medication_name": self._medication_data.get(CONF_NAME, "medication"),
                },
            )

        # Task completed - move to done step
        return self.async_show_progress_done(next_step_id="scan_nfc_done")

    async def _async_wait_for_tag_scan(self) -> None:
        """Background task that waits for NFC tag scan."""
        LOGGER.debug("Starting background tag scan listener")

        try:
            from homeassistant.components.tag import async_wait_for_tag_scan

            # Call the coroutine directly - it handles cancellation internally
            result = await async_wait_for_tag_scan(self.hass, self._cancel_event)

            if result is not None:
                self._scanned_tag_id = result["tag_id"]
                LOGGER.info("Tag scanned during config flow: %s", self._scanned_tag_id)
            else:
                LOGGER.debug("Tag scan returned None (cancelled)")

        except asyncio.CancelledError:
            LOGGER.debug("Tag scan task cancelled")
            raise
        except ImportError:
            LOGGER.warning("async_wait_for_tag_scan not available in this HA version")
            # Fall through to allow manual entry
        except Exception:
            LOGGER.exception("Error waiting for tag scan")

    async def async_step_scan_nfc_done(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle completion of NFC scanning."""
        LOGGER.debug("In scan_nfc_done step, user_input: %s", user_input)

        if user_input is not None:
            # User submitted the form
            med_data = self._medication_data.copy()

            # Use the tag ID from form or scanned
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

            # Clean up
            self._scan_task = None
            self._cancel_event = None

            LOGGER.debug("Creating entry from NFC step with title: %s", entry_title)
            return self.async_create_entry(
                title=entry_title,
                data={
                    CONF_PEOPLE: self._people,
                    CONF_MEDICATIONS: [med_data],
                },
            )

        # Show form with scanned tag ID pre-filled
        scanned_tag_id = self._scanned_tag_id or ""

        return self.async_show_form(
            step_id="scan_nfc_done",
            data_schema=vol.Schema(
                {
                    vol.Optional("tag_id", default=scanned_tag_id): str,
                }
            ),
            description_placeholders={
                "medication_name": self._medication_data.get(CONF_NAME, "medication"),
                "tag_status": (
                    f"Tag detected: {scanned_tag_id}"
                    if scanned_tag_id
                    else "No tag was scanned. You can enter a tag ID manually or leave blank to skip."
                ),
            },
        )

    async def async_step_skip_nfc(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle skipping NFC scanning."""
        # Cancel the scan task if running
        if self._scan_task and not self._scan_task.done():
            if self._cancel_event:
                self._cancel_event.set()
            self._scan_task.cancel()

        self._scanned_tag_id = None
        return await self.async_step_scan_nfc_done()

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
