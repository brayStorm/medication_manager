"""Config flow for Medication Manager integration."""
import logging
import voluptuous as vol
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import (
    CONF_NAME, CONF_ID
)
import homeassistant.helpers.config_validation as cv

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Medication Manager."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize the config flow."""
        self._medication_data = {}
        self._people = []
        self._last_added_person = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        
        _LOGGER.debug(f"In user step, user_input: {user_input}")

        # Load existing people
        self._load_existing_people()

        if user_input is not None:
            # Determine next step based on selection
            if user_input.get("setup_type") == "add_person":
                _LOGGER.debug("User chose to add person first")
                return await self.async_step_add_person()
            else:
                _LOGGER.debug("User chose to add medication directly")
                return await self.async_step_medication_setup()

        # Create simple selection with clear labels
        options = {
            "add_medication": "Add a medication directly",
            "add_person": "Add a person first, then add their medication"
        }
        
        _LOGGER.debug("Showing initial setup options")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("setup_type", default="add_medication"): vol.In(options)
            }),
            errors=errors
        )

    async def async_step_add_person(self, user_input=None):
        """Handle adding a new person."""
        errors = {}

        if user_input is not None:
            person_name = user_input[CONF_NAME]
            
            # Store the person
            self._people.append({"name": person_name})
            # Remember this as the last added person for default selection
            self._last_added_person = person_name
            
            # Continue to medication setup
            return await self.async_step_medication_setup()

        return self.async_show_form(
            step_id="add_person",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, description="Person Name"): str,
            }),
            errors=errors,
            description_placeholders={"message": "Enter the name of the person who will take this medication"},
        )

    async def async_step_medication_setup(self, user_input=None):
        """Handle setting up a medication."""
        errors = {}

        if user_input is not None:
            # Make a copy of the user input to avoid modifying the original
            med_data = dict(user_input)
            
            # Check if user wants to scan NFC
            if med_data.get("nfc_scan_now", False):
                # Store data for the next step
                self._medication_data = med_data.copy()
                
                # Remove the scan flag before storing
                if "nfc_scan_now" in self._medication_data:
                    self._medication_data.pop("nfc_scan_now")
                
                # Proceed to NFC scanning step
                _LOGGER.debug("User chose to scan NFC - proceeding to scan step")
                return await self.async_step_scan_nfc()
            
            # Process without NFC scanning
            
            # Remove the scan flag if present
            if "nfc_scan_now" in med_data:
                med_data.pop("nfc_scan_now")
            
            # Handle person selection
            person_name = med_data.get("person")
            if person_name and person_name != "none":
                # Check if this person exists in our list
                if person_name not in [p["name"] for p in self._people]:
                    self._people.append({"name": person_name})
            
            # Remove "none" person selection if needed
            if "person" in med_data and med_data["person"] == "none":
                med_data.pop("person")
            
            # Create a more descriptive title that includes the person's name if available
            entry_title = med_data[CONF_NAME]
            person_name = med_data.get("person")
            if person_name and person_name != "none":
                entry_title = f"{person_name}'s {entry_title}"
            
            # Create the entry
            _LOGGER.debug(f"Creating entry with title: {entry_title}")
            return self.async_create_entry(
                title=entry_title,
                data={
                    "people": self._people,
                    "medications": [med_data],
                }
            )

        # Create a list of person options including "None"
        person_options = {"none": "No person (unassigned)"}
        for person in self._people:
            person_options[person["name"]] = person["name"]
        
        # Default to the last added person if available
        default_person = "none"
        if hasattr(self, "_last_added_person") and self._last_added_person:
            default_person = self._last_added_person

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, description="Medication Name"): str,
            vol.Optional("person", default=default_person): vol.In(person_options),
            vol.Required("dosage", default=1): cv.positive_int,
            vol.Required("inventory", default=30): cv.positive_int,
            vol.Required("dose_time", default="08:00:00"): str,
            vol.Optional("doses_per_day", default=1): cv.positive_int,
            vol.Optional("refills_remaining", default=0): cv.positive_int,
            vol.Optional("low_inventory_threshold", default=3): cv.positive_int,
            vol.Optional("doctor_reminder_threshold", default=10): cv.positive_int,
            vol.Optional("nfc_scan_now", default=True): cv.boolean,
        })

        return self.async_show_form(
            step_id="medication_setup",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "message": "Enter medication details. We'll scan the NFC tag in the next step."
            },
        )
        
    async def async_step_scan_nfc(self, user_input=None):
        """Handle the NFC scanning step."""
        errors = {}
        
        _LOGGER.debug(f"In NFC scanning step, user_input: {user_input}")
        
        # Check if we have medication data
        if not hasattr(self, "_medication_data") or not self._medication_data:
            _LOGGER.error("No medication data available for NFC scanning")
            return self.async_abort(reason="no_medication_data")
            
        if user_input is not None:
            # Complete the medication setup with the tag ID if provided
            med_data = self._medication_data.copy()
            
            # Add the tag ID if provided
            if user_input.get("tag_id"):
                med_data["nfc_id"] = user_input["tag_id"]
                _LOGGER.debug(f"NFC tag ID added: {user_input['tag_id']}")
            
            # Create a more descriptive title that includes the person's name if available
            entry_title = med_data[CONF_NAME]
            person_name = med_data.get("person")
            if person_name and person_name != "none":
                entry_title = f"{person_name}'s {entry_title}"
            
            # Create the config entry
            _LOGGER.debug(f"Creating entry from NFC step with title: {entry_title}")
            return self.async_create_entry(
                title=entry_title,
                data={
                    "people": self._people,
                    "medications": [med_data],
                }
            )
        
        # Show the form for scanning an NFC tag
        _LOGGER.debug("Displaying NFC scan form")
        return self.async_show_form(
            step_id="scan_nfc",
            data_schema=vol.Schema({
                vol.Optional("tag_id"): str,
            }),
            errors=errors,
            description_placeholders={
                "message": "Scan an NFC tag with your device and enter the tag ID. "
                "This is optional - you can leave it blank and add it later."
            },
        )

    def _load_existing_people(self):
        """Load existing people from other config entries."""
        for entry in self._async_current_entries():
            if "people" in entry.data:
                for person in entry.data["people"]:
                    if person not in self._people:
                        self._people.append(person)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MedicationOptionsFlowHandler(config_entry)


class MedicationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle medication options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        medications = self.config_entry.data.get("medications", [])
        
        if not medications:
            return self.async_abort(reason="no_medications")
        
        # For simplicity, we'll just show options for the first medication
        # In a more complex implementation, we'd provide a way to select which medication to edit
        medication = medications[0]
        
        schema = vol.Schema({
            vol.Required("inventory", default=medication.get("inventory", 30)): cv.positive_int,
            vol.Required("refills_remaining", default=medication.get("refills_remaining", 0)): cv.positive_int,
            vol.Required("low_inventory_threshold", default=medication.get("low_inventory_threshold", 3)): cv.positive_int,
            vol.Required("doctor_reminder_threshold", default=medication.get("doctor_reminder_threshold", 10)): cv.positive_int,
        })

        return self.async_show_form(step_id="init", data_schema=schema)