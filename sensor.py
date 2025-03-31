"""Sensor platform for medication manager."""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up the sensor platform."""
    _LOGGER.debug(f"Setting up sensor platform for entry: {config_entry.title}")
    
    # Get the medication manager instance
    manager = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not manager:
        _LOGGER.error("No medication manager found for entry")
        return False
    
    # Collect all sensors from medications
    sensors = []
    for med_id, med_data in manager.medications.items():
        sensor_dict = med_data.get("sensors", {})
        if sensor_dict:
            _LOGGER.debug(f"Adding sensors for medication: {med_id}")
            sensors.extend(sensor_dict.values())
    
    # Add sensors to Home Assistant
    if sensors:
        _LOGGER.debug(f"Adding {len(sensors)} sensors to Home Assistant")
        async_add_entities(sensors)
    else:
        _LOGGER.warning("No sensors found to add")
    
    return True

async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    """Set up the sensor platform from configuration.yaml."""
    _LOGGER.debug("Setting up sensor platform from configuration.yaml")
    
    # Get the medication manager instance
    manager = hass.data.get(DOMAIN, {}).get("manager")
    if not manager:
        _LOGGER.error("No medication manager found for YAML setup")
        return False
    
    # Collect sensors from all medications
    sensors = []
    for med_id, med_data in manager.medications.items():
        sensor_dict = med_data.get("sensors", {})
        if sensor_dict:
            _LOGGER.debug(f"Adding sensors for medication: {med_id}")
            sensors.extend(sensor_dict.values())
    
    # Add sensors to Home Assistant
    if sensors:
        _LOGGER.debug(f"Adding {len(sensors)} sensors to Home Assistant")
        async_add_entities(sensors)
    else:
        _LOGGER.warning("No sensors found to add")
    
    return True