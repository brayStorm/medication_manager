"""Constants for the Medication Manager integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "medication_manager"
LOGGER = logging.getLogger(__package__)

# Configuration keys
CONF_PERSON: Final = "person"
CONF_DOSAGE: Final = "dosage"
CONF_INVENTORY: Final = "inventory"
CONF_DOSE_TIME: Final = "dose_time"
CONF_DOSES_PER_DAY: Final = "doses_per_day"
CONF_REFILLS_REMAINING: Final = "refills_remaining"
CONF_LOW_INVENTORY_THRESHOLD: Final = "low_inventory_threshold"
CONF_DOCTOR_REMINDER_THRESHOLD: Final = "doctor_reminder_threshold"
CONF_NFC_ID: Final = "nfc_id"
CONF_MEDICATIONS: Final = "medications"
CONF_PEOPLE: Final = "people"

# Service names
SERVICE_RECORD_DOSE: Final = "record_dose"
SERVICE_UPDATE_INVENTORY: Final = "update_inventory"

# Attribute keys
ATTR_MEDICATION_ID: Final = "medication_id"
ATTR_TAG_ID: Final = "tag_id"

# Default values
DEFAULT_DOSES_PER_DAY: Final = 1
DEFAULT_REFILLS: Final = 0
DEFAULT_LOW_THRESHOLD: Final = 7
DEFAULT_DOCTOR_THRESHOLD: Final = 14
DEFAULT_INVENTORY: Final = 30
DEFAULT_DOSAGE: Final = 1
DEFAULT_DOSE_TIME: Final = "08:00:00"

# Sensor states
STATE_NOT_TAKEN: Final = "not_taken"
STATE_PARTIALLY_TAKEN: Final = "partially_taken"
STATE_TAKEN: Final = "taken"

# Platforms
PLATFORMS: Final = ["sensor"]
