"""Tag platform for Medication Manager integration."""
import logging
import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

TAG_SCANNED_EVENT = "tag_scanned"
TAG_ID = "tag_id"

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    """Set up the platform to listen for tag scans."""
    _LOGGER.debug(f"Setting up tag platform for entry: {config_entry.title}")
    
    # Get the medication manager instance
    manager = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not manager:
        _LOGGER.error("No medication manager found for entry")
        return False

    @callback
    def handle_tag_scan(event: Event):
        """Handle the tag_scanned event from Home Assistant."""
        # Extract tag_id from the event
        tag_id = event.data.get(TAG_ID)
        device_id = event.data.get(ATTR_DEVICE_ID)
        
        if not tag_id:
            return
            
        _LOGGER.debug(f"Tag scanned event received - tag_id: {tag_id}, device_id: {device_id}")
        
        # Dispatch to medication manager to handle the scan
        hass.async_create_task(
            manager.handle_scan_nfc({"data": {"nfc_id": tag_id}})
        )

    # Register listener for tag scanned events
    remove_listener = hass.bus.async_listen(TAG_SCANNED_EVENT, handle_tag_scan)
    
    # Store the removal function
    hass.data.setdefault(f"{DOMAIN}_tag_listeners", {})
    hass.data[f"{DOMAIN}_tag_listeners"][config_entry.entry_id] = remove_listener
    
    _LOGGER.info("Tag scanning listener registered successfully")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload tag scanning when the config entry is removed."""
    _LOGGER.debug(f"Unloading tag listener for entry: {entry.entry_id}")
    
    # Remove the tag scan listener
    if entry.entry_id in hass.data.get(f"{DOMAIN}_tag_listeners", {}):
        remove_listener = hass.data[f"{DOMAIN}_tag_listeners"].pop(entry.entry_id)
        remove_listener()
        _LOGGER.debug("Tag scan listener removed")
    
    return True