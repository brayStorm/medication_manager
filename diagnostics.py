"""Diagnostics support for Medication Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import MedicationManagerConfigEntry
from .const import CONF_MEDICATIONS, CONF_NFC_ID, CONF_PEOPLE


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MedicationManagerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # Redact sensitive information
    medications_data = []
    for med in entry.data.get(CONF_MEDICATIONS, []):
        med_copy = dict(med)
        # Redact NFC ID (could be used to identify physical tags)
        if CONF_NFC_ID in med_copy:
            med_copy[CONF_NFC_ID] = "**REDACTED**"
        medications_data.append(med_copy)

    # Get runtime state
    runtime_medications = {}
    if hasattr(entry, "runtime_data") and entry.runtime_data:
        for med_id, med in entry.runtime_data.medications.items():
            runtime_medications[med_id] = {
                "status": med.status,
                "doses_today": med.doses_today,
                "doses_per_day": med.doses_per_day,
                "inventory": med.inventory,
                "low_threshold": med.low_inventory_threshold,
                "is_low": med.inventory <= med.low_inventory_threshold,
                "refills_remaining": med.refills_remaining,
                "last_dose": med.last_dose.isoformat() if med.last_dose else None,
            }

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
        },
        "data": {
            CONF_PEOPLE: entry.data.get(CONF_PEOPLE, []),
            CONF_MEDICATIONS: medications_data,
        },
        "options": dict(entry.options),
        "runtime_state": runtime_medications,
    }
