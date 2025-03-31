"""
Medication Manager integration for Home Assistant.
"""
import logging
import voluptuous as vol
import asyncio
from datetime import datetime, timedelta

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_NAME, CONF_ID, CONF_DEVICE_ID, CONF_ENTITIES,
    STATE_UNKNOWN
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import slugify
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DOMAIN = "medication_manager"

# Config schema definitions
PERSON_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
})

MEDICATION_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Required("nfc_id"): cv.string,
    vol.Required("dosage"): cv.positive_int,
    vol.Required("inventory"): cv.positive_int,
    vol.Required("dose_time"): cv.string,
    vol.Optional("person"): cv.string,
    vol.Optional("doses_per_day", default=1): cv.positive_int,
    vol.Optional("refills_remaining", default=0): cv.positive_int,
    vol.Optional("low_inventory_threshold", default=3): cv.positive_int,
    vol.Optional("doctor_reminder_threshold", default=10): cv.positive_int,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional("people"): vol.All(cv.ensure_list, [PERSON_SCHEMA]),
        vol.Required("medications"): vol.All(cv.ensure_list, [MEDICATION_SCHEMA]),
    }),
}, extra=vol.ALLOW_EXTRA)

# Service definitions
SERVICE_RECORD_DOSE = "record_dose"
SERVICE_UPDATE_INVENTORY = "update_inventory"
SERVICE_SCAN_NFC = "scan_nfc"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Medication Manager component from yaml configuration."""
    if DOMAIN not in config:
        return True

    # Create a medication manager instance
    manager = await _create_medication_manager(hass, config[DOMAIN])
    
    # Store medication manager in Home Assistant data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["manager"] = manager
    
    # Register services
    _register_services(hass, manager)
    
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Medication Manager from a config entry."""
    _LOGGER.debug(f"Setting up medication manager entry: {entry.title} with data: {entry.data}")
    
    # Set up the medication manager instance
    config_data = {
        "people": entry.data.get("people", []),
        "medications": entry.data.get("medications", [])
    }
    
    # Apply any options
    if entry.options:
        _LOGGER.debug(f"Applying options: {entry.options}")
        # Update medication with options
        for medication in config_data["medications"]:
            for key, value in entry.options.items():
                if key in medication:
                    medication[key] = value
    
    # Create manager
    try:
        _LOGGER.debug("Creating medication manager")
        manager = await _create_medication_manager(hass, config_data)
        
        # Store in hass data
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = manager
        
        # Register services if not already registered
        if "manager" not in hass.data[DOMAIN]:
            _LOGGER.debug("Registering services")
            hass.data[DOMAIN]["manager"] = manager
            _register_services(hass, manager)
        
        # Forward entry to sensor and tag platforms
        _LOGGER.debug("Setting up platforms")
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "tag"])
        
        _LOGGER.info(f"Medication Manager setup complete for entry: {entry.title}")
        return True
    except Exception as e:
        _LOGGER.error(f"Error setting up Medication Manager: {e}")
        return False

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload the platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor", "tag"])
    
    # Remove from hass data
    if unload_ok and entry.entry_id in hass.data[DOMAIN]:
        del hass.data[DOMAIN][entry.entry_id]
    
    return unload_ok

async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    return True

def _register_services(hass: HomeAssistant, manager):
    """Register services for the medication manager."""
    hass.services.async_register(
        DOMAIN, SERVICE_RECORD_DOSE, manager.handle_record_dose
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_INVENTORY, manager.handle_update_inventory
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_SCAN_NFC, manager.handle_scan_nfc
    )

async def _create_medication_manager(hass, config_data):
    """Create and initialize a medication manager."""
    manager = MedicationManager(hass, config_data.get("people", []), config_data.get("medications", []))
    
    # Set up sensors and automation
    await manager.setup_sensors()
    await manager.setup_automations()
    
    return manager


class MedicationManager:
    """Class to manage all medications."""
    
    def __init__(self, hass, people, medications):
        """Initialize the medication manager."""
        self.hass = hass
        self.people = {}
        self.medications = {}
        self._lock = asyncio.Lock()  # Add a lock for thread safety
        
        # Process each person
        for person_config in people:
            person_id = slugify(person_config[CONF_NAME])
            self.people[person_id] = {
                "name": person_config[CONF_NAME],
                "medications": [],
            }
        
        # Process each medication config
        for med_config in medications:
            med_id = slugify(med_config[CONF_NAME])
            
            # Check if a person is assigned
            person_name = med_config.get("person")
            person_id = None
            
            if person_name:
                # Find the person by name
                for p_id, p_data in self.people.items():
                    if p_data["name"] == person_name:
                        person_id = p_id
                        break
                
                # If not found, create a new person
                if person_id is None:
                    person_id = slugify(person_name)
                    self.people[person_id] = {
                        "name": person_name,
                        "medications": [],
                    }
            
            # Store the medication data
            self.medications[med_id] = {
                "config": med_config.copy(),  # Make a defensive copy
                "person_id": person_id,
                "last_dose": None,
                "doses_today": 0,
                "sensors": {},
            }
            
            # Add to person's medication list if assigned
            if person_id:
                self.people[person_id]["medications"].append(med_id)
    
    async def setup_sensors(self):
        """Set up the sensors for each medication."""
        async with self._lock:
            for med_id, med_data in self.medications.items():
                try:
                    med_name = med_data["config"][CONF_NAME]
                    person_id = med_data["person_id"]
                    
                    # Add person name to sensor if assigned
                    if person_id and person_id in self.people:
                        person_name = self.people[person_id]["name"]
                        display_name = f"{person_name}'s {med_name}"
                        # Create a sensor ID that includes the person
                        sensor_prefix = f"sensor.{slugify(person_name)}_{med_id}"
                    else:
                        display_name = med_name
                        sensor_prefix = f"sensor.{med_id}"
                    
                    # Create entity IDs
                    inventory_entity_id = f"{sensor_prefix}_inventory"
                    status_entity_id = f"{sensor_prefix}_status"
                    last_dose_entity_id = f"{sensor_prefix}_last_dose"
                    
                    # Get initial inventory from config
                    initial_inventory = med_data["config"].get("inventory", 0)
                    
                    # Create and register the sensors
                    inventory_sensor = MedicationInventorySensor(
                        self.hass, med_id, display_name, initial_inventory, 
                        entity_id=inventory_entity_id, person_id=person_id
                    )
                    
                    status_sensor = MedicationStatusSensor(
                        self.hass, med_id, display_name, 
                        entity_id=status_entity_id, person_id=person_id
                    )
                    
                    last_dose_sensor = MedicationLastDoseSensor(
                        self.hass, med_id, display_name, 
                        entity_id=last_dose_entity_id, person_id=person_id
                    )
                    
                    # Store the sensors in a thread-safe way
                    med_data["sensors"] = {
                        "inventory": inventory_sensor,
                        "status": status_sensor,
                        "last_dose": last_dose_sensor
                    }
                except Exception as e:
                    _LOGGER.error(f"Error setting up sensors for medication {med_id}: {e}")
    
    async def setup_automations(self):
        """Set up automations for reminders and notifications."""
        # Schedule time-based automations
        async_track_time_interval(
            self.hass, self.check_medication_schedule, timedelta(minutes=5)
        )
        
        # Schedule daily reset at midnight
        async_track_time_interval(
            self.hass, self.reset_daily_doses, timedelta(days=1)
        )
    
    async def check_medication_schedule(self, now=None):
        """Check medications and send reminders as needed."""
        if now is None:
            now = datetime.now()
            
        async with self._lock:
            for med_id, med_data in self.medications.items():
                try:
                    med_config = med_data["config"]
                    med_name = med_config[CONF_NAME]
                    
                    # Get person name if assigned
                    person_id = med_data["person_id"]
                    if person_id:
                        person_name = self.people[person_id]["name"]
                        display_name = f"{person_name}'s {med_name}"
                    else:
                        display_name = med_name
                    
                    # Check if medication has been taken today
                    dose_time_str = med_config["dose_time"]
                    try:
                        # Parse the time string
                        hour, minute, second = map(int, dose_time_str.split(':'))
                        dose_time = datetime.now().replace(hour=hour, minute=minute, second=second).time()
                    except (ValueError, AttributeError):
                        _LOGGER.error(f"Invalid dose_time format for {display_name}: {dose_time_str}")
                        continue
                        
                    current_time = now.time()
                    
                    # If it's past dose time and no dose recorded
                    if current_time > dose_time and med_data["doses_today"] < med_config["doses_per_day"]:
                        # Send a reminder notification
                        await self.send_notification(
                            f"Reminder: Time to take {display_name} medication."
                        )
                    
                    # Check inventory levels
                    inventory_sensor = med_data["sensors"].get("inventory")
                    if inventory_sensor and inventory_sensor.state is not None:
                        inventory = inventory_sensor.state
                        if inventory <= med_config["low_inventory_threshold"]:
                            # Check if refills are available
                            if med_config["refills_remaining"] > 0:
                                await self.send_notification(
                                    f"Low inventory alert: Only {inventory} doses of {display_name} remaining. "
                                    f"Please order a refill."
                                )
                            elif inventory <= med_config["doctor_reminder_threshold"]:
                                await self.send_notification(
                                    f"Doctor appointment needed: Only {inventory} doses of {display_name} remaining "
                                    f"and no refills left. Please schedule a doctor appointment."
                                )
                except Exception as e:
                    _LOGGER.error(f"Error checking medication schedule for {med_id}: {e}")
    
    async def reset_daily_doses(self, now=None):
        """Reset daily dose counters at midnight."""
        async with self._lock:
            for med_id, med_data in self.medications.items():
                try:
                    med_data["doses_today"] = 0
                    # Update status sensor
                    status_sensor = med_data["sensors"].get("status")
                    if status_sensor:
                        await status_sensor.update_state("not_taken")
                except Exception as e:
                    _LOGGER.error(f"Error resetting doses for {med_id}: {e}")
    
    async def handle_record_dose(self, call):
        """Handle the record_dose service call."""
        async with self._lock:
            try:
                med_id = call.data.get("medication_id")
                
                if med_id not in self.medications:
                    _LOGGER.error(f"Unknown medication ID: {med_id}")
                    return
                
                med_data = self.medications[med_id]
                med_config = med_data["config"]
                med_name = med_config[CONF_NAME]
                
                # Get person name if assigned
                person_id = med_data["person_id"]
                if person_id:
                    person_name = self.people[person_id]["name"]
                    display_name = f"{person_name}'s {med_name}"
                else:
                    display_name = med_name
                
                # Check if already dosed today
                if med_data["doses_today"] >= med_config["doses_per_day"]:
                    await self.send_notification(
                        f"Warning: You've already taken all doses of {display_name} today."
                    )
                    return
                
                # Record the dose
                med_data["last_dose"] = datetime.now()
                med_data["doses_today"] += 1
                
                # Update inventory - ensure this is atomic
                inventory_sensor = med_data["sensors"].get("inventory")
                if inventory_sensor:
                    current_inventory = inventory_sensor.state
                    new_inventory = current_inventory - 1 if current_inventory is not None else 0
                    await inventory_sensor.update_state(new_inventory)
                
                # Update last dose sensor
                last_dose_sensor = med_data["sensors"].get("last_dose")
                if last_dose_sensor:
                    await last_dose_sensor.update_state(med_data["last_dose"].isoformat())
                
                # Update status sensor
                status_sensor = med_data["sensors"].get("status")
                if status_sensor:
                    if med_data["doses_today"] >= med_config["doses_per_day"]:
                        await status_sensor.update_state("taken")
                    else:
                        await status_sensor.update_state("partially_taken")
                    
                # Confirmation notification
                await self.send_notification(
                    f"Recorded dose for {display_name}. {new_inventory} doses remaining."
                )
            except Exception as e:
                _LOGGER.error(f"Error recording dose: {e}")
    
    async def handle_update_inventory(self, call):
        """Handle the update_inventory service call."""
        async with self._lock:
            try:
                med_id = call.data.get("medication_id")
                new_inventory = call.data.get("inventory")
                
                if med_id not in self.medications:
                    _LOGGER.error(f"Unknown medication ID: {med_id}")
                    return
                
                # Update inventory
                med_data = self.medications[med_id]
                inventory_sensor = med_data["sensors"].get("inventory")
                if inventory_sensor:
                    await inventory_sensor.update_state(new_inventory)
                
                # Confirmation
                med_name = med_data["config"][CONF_NAME]
                
                # Get person name if assigned
                person_id = med_data["person_id"]
                if person_id:
                    person_name = self.people[person_id]["name"]
                    display_name = f"{person_name}'s {med_name}"
                else:
                    display_name = med_name
                
                await self.send_notification(
                    f"Updated inventory for {display_name}: {new_inventory} doses."
                )
            except Exception as e:
                _LOGGER.error(f"Error updating inventory: {e}")
    
    async def handle_scan_nfc(self, call):
        """Handle the scan_nfc service call."""
        try:
            nfc_id = None
            # Check if call is a dictionary or a proper ServiceCall object
            if isinstance(call, dict) and "data" in call:
                nfc_id = call["data"].get("nfc_id")
            else:
                nfc_id = call.data.get("nfc_id")
            
            if not nfc_id:
                _LOGGER.error("No NFC ID provided in scan_nfc call")
                return
                
            _LOGGER.debug(f"Processing NFC tag scan with ID: {nfc_id}")
            
            # Find medication by NFC ID - lock for thread safety
            found_medication = False
            async with self._lock:
                for med_id, med_data in self.medications.items():
                    if "config" in med_data and "nfc_id" in med_data["config"] and med_data["config"]["nfc_id"] == nfc_id:
                        _LOGGER.info(f"Found medication {med_id} for NFC tag {nfc_id}")
                        found_medication = True
                        # Create a proper service call object
                        service_call = type('obj', (object,), {
                            'data': {
                                'medication_id': med_id
                            }
                        })
                        # Schedule the record_dose operation to avoid potential deadlock
                        self.hass.async_create_task(self.handle_record_dose(service_call))
                        return
            
            if not found_medication:
                _LOGGER.info(f"No medication found with NFC ID: {nfc_id}. Add this tag ID to a medication to use it.")
        except Exception as e:
            _LOGGER.error(f"Error handling NFC scan: {e}")
    
    async def send_notification(self, message):
        """Send a notification through Home Assistant."""
        try:
            await self.hass.services.async_call(
                "notify", "notify", {"message": message}, blocking=False
            )
        except Exception as e:
            _LOGGER.error(f"Error sending notification: {e}")


class MedicationSensor(Entity):
    """Base class for medication sensors."""
    
    def __init__(self, hass, med_id, med_name, entity_id=None, person_id=None):
        """Initialize the sensor."""
        self.hass = hass
        self.med_id = med_id
        self.med_name = med_name
        self._state = None
        self._entity_id = entity_id
        self.person_id = person_id
        self._update_lock = asyncio.Lock()  # Add a lock for thread-safe updates
    
    @property
    def entity_id(self):
        """Return the entity ID."""
        if self._entity_id:
            return self._entity_id
        return super().entity_id
    
    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
    
    async def update_state(self, new_state):
        """Update the state and trigger an update."""
        async with self._update_lock:
            self._state = new_state
            self.async_schedule_update_ha_state()


class MedicationInventorySensor(MedicationSensor):
    """Sensor for medication inventory."""
    
    def __init__(self, hass, med_id, med_name, initial_inventory, entity_id=None, person_id=None):
        """Initialize the inventory sensor."""
        super().__init__(hass, med_id, med_name, entity_id, person_id)
        self._state = initial_inventory
    
    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.med_name} Inventory"
    
    @property
    def unique_id(self):
        """Return a unique ID."""
        if self.person_id:
            return f"{self.person_id}_{self.med_id}_inventory"
        return f"{self.med_id}_inventory"
    
    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "doses"


class MedicationStatusSensor(MedicationSensor):
    """Sensor for medication status."""
    
    def __init__(self, hass, med_id, med_name, entity_id=None, person_id=None):
        """Initialize the status sensor."""
        super().__init__(hass, med_id, med_name, entity_id, person_id)
        self._state = "not_taken"
    
    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.med_name} Status"
    
    @property
    def unique_id(self):
        """Return a unique ID."""
        if self.person_id:
            return f"{self.person_id}_{self.med_id}_status"
        return f"{self.med_id}_status"


class MedicationLastDoseSensor(MedicationSensor):
    """Sensor for last medication dose time."""
    
    def __init__(self, hass, med_id, med_name, entity_id=None, person_id=None):
        """Initialize the last dose sensor."""
        super().__init__(hass, med_id, med_name, entity_id, person_id)
        self._state = None
    
    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.med_name} Last Dose"
    
    @property
    def unique_id(self):
        """Return a unique ID."""
        if self.person_id:
            return f"{self.person_id}_{self.med_id}_last_dose"
        return f"{self.med_id}_last_dose"