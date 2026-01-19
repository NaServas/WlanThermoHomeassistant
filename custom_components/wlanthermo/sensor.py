"""
Sensor platform for WLANThermo
Exposes system, channel, pitmaster, and temperature sensors as Home Assistant entities.
Includes diagnostic and device info sensors.
"""

from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
    UnitOfTime,
)


from homeassistant.core import callback
from .const import DOMAIN
from datetime import timedelta, datetime
from .data import WlanthermoData
import logging
import collections

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """
    Set up all sensor entities for the WLANThermo integration.
    Dynamically creates entities for channels, pitmasters, system, and settings based on available data.
    """
    entry_id = config_entry.entry_id
    coordinator = hass.data[DOMAIN][entry_id]["coordinator"]
    device_name = config_entry.data.get("device_name", "WLANThermo")
    api = hass.data[DOMAIN][entry_id]["api"]

    # Device offline? → coordinator.data = None → Plattformen NICHT laden
    if coordinator.data is None:
        import logging
        logging.getLogger(__name__).debug(
            "WLANThermo Sensor: coordinator.data is None → skipping platform setup"
        )
        return

    entities = []
    import re
    safe_device_name = re.sub(r'[^a-zA-Z0-9_]', '_', device_name.lower())

    # Channels
    for channel in getattr(coordinator.data, 'channels', []):
        entities.append(WlanthermoChannelTemperatureSensor(coordinator, channel))
        entities.append(WlanthermoChannelTimeLeftSensor(coordinator, channel))

    # Pitmasters
    for pitmaster in getattr(coordinator.data, 'pitmasters', []):
        entities.append(WlanthermoPitmasterValueSensor(coordinator, pitmaster, safe_device_name))
        entities.append(WlanthermoPitmasterTemperatureSensor(coordinator, pitmaster, safe_device_name))

    # System sensors
    sys_obj = getattr(coordinator.data, 'system', None)
    if sys_obj:
        entities.append(WlanthermoSystemSensor(coordinator, safe_device_name))
        entities.append(WlanthermoSystemTimeSensor(coordinator, sys_obj, safe_device_name))
        entities.append(WlanthermoSystemUnitSensor(coordinator, sys_obj, safe_device_name))
        entities.append(WlanthermoSystemSocSensor(coordinator, sys_obj, safe_device_name))
        entities.append(WlanthermoSystemChargeSensor(coordinator, sys_obj, safe_device_name))
        entities.append(WlanthermoSystemRssiSensor(coordinator, sys_obj, safe_device_name))
        entities.append(WlanthermoSystemOnlineSensor(coordinator, sys_obj, safe_device_name))

    # Settings sensors (NUR wenn coordinator.data vorhanden ist!)
    settings = getattr(api, "settings", None)
    if settings:
        if hasattr(settings, "device"):
            entities.append(WlanthermoDeviceInfoSensor(coordinator, settings.device, safe_device_name))
        if hasattr(settings, "system"):
            entities.append(WlanthermoSystemInfoSensor(coordinator, settings.system, safe_device_name))
            entities.append(WlanthermoSystemGetUpdateSensor(coordinator, settings.system, safe_device_name))
        if hasattr(settings, "iot"):
            entities.append(WlanthermoIotInfoSensor(coordinator, settings.iot, safe_device_name))
            entities.append(WlanthermoCloudLinkSensor(coordinator, settings.iot, safe_device_name))

    async_add_entities(entities)


class WlanthermoChannelTemperatureSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for a channel's temperature.
    Reports the current temperature for each channel.
    """
    def __init__(self, coordinator, channel, field=None):
        super().__init__(coordinator)
        self._channel_number = channel.number
        # Try to get a friendly device name from the coordinator or fallback
        device_name = getattr(coordinator, 'device_name', None)
        if not device_name:
            entry_id = getattr(coordinator, 'config_entry', None).entry_id if hasattr(coordinator, 'config_entry') else None
            hass = getattr(coordinator, 'hass', None)
            if hass and entry_id:
                device_name = hass.data[DOMAIN][entry_id]["device_info"].get("name", "WLANThermo")
            else:
                device_name = "WLANThermo"
        safe_device_name = device_name.replace(" ", "_").lower()
        self._attr_has_entity_name = True
        self._attr_translation_key = "channel_temperature"
        self._attr_translation_placeholders = {"channel_number": str(self._channel_number)}
        self._attr_unique_id = f"{safe_device_name}_channel_{self._channel_number}_temperatur"
        self._attr_icon = "mdi:thermometer"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def _get_channel(self):
        """
        Helper to get the current channel object from the coordinator data.
        """
        channels = getattr(self.coordinator.data, 'channels', [])
        for ch in channels:
            if ch.number == self._channel_number:
                return ch
        return None

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            device_info = hass.data[DOMAIN][entry_id]["device_info"].copy()
            api = hass.data[DOMAIN][entry_id].get("api")
            settings = getattr(api, "settings", None)
            if settings and hasattr(settings, "device"):
                dev = settings.device
                device_info["sw_version"] = getattr(dev, "sw_version", None)
                device_info["hw_version"] = getattr(dev, "hw_version", None)
                device_info["model"] = f"{getattr(dev, 'device', None)} {getattr(dev, 'hw_version', None)} {getattr(dev, 'cpu', None)}"
            return device_info
        return None

    @property
    def native_value(self):
        """
        Return the current temperature value, or None if sensor is not connected (999.0).
        """
        channel = self._get_channel()
        if not channel:
            return None
        temp = getattr(channel, "temp", None)
        if temp is None:
            return None  # No temperature data available

        show_inactive = self.coordinator.config_entry.options.get(
            "show_inactive_unavailable",
            self.coordinator.config_entry.data.get(
                "show_inactive_unavailable", True
            )
        )
        if temp == 999.0 and show_inactive:
            return None
        return temp
    
    @property
    def available(self):
        """
        Return True if the device is online and the channel is available and not marked as inactive.
        """
        if not self.coordinator.last_update_success:
            return False

        system = getattr(self.coordinator.data, "system", None)
        if system is None:
            return False

        channel = self._get_channel()
        if not channel:
            return False
        show_inactive = (
            self.coordinator.config_entry.options.get(
                "show_inactive_unavailable",
                self.coordinator.config_entry.data.get("show_inactive_unavailable", True)
            )
        )
        temp = getattr(channel, "temp", None)
        if temp == 999.0 and show_inactive:
            return False
        return True


class WlanthermoChannelTimeLeftSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity estimating time left until the channel reaches its max temperature.
    Uses a moving window to estimate rate of temperature change.
    """
    def __init__(self, coordinator, channel, window_seconds=300):
        super().__init__(coordinator)
        self._channel_number = channel.number
        # Try to get a friendly device name from the coordinator or fallback
        device_name = getattr(coordinator, 'device_name', None)
        if not device_name:
            entry_id = getattr(coordinator, 'config_entry', None).entry_id if hasattr(coordinator, 'config_entry') else None
            hass = getattr(coordinator, 'hass', None)
            if hass and entry_id:
                device_name = hass.data[DOMAIN][entry_id]["device_info"].get("name", "WLANThermo")
            else:
                device_name = "WLANThermo"
        safe_device_name = device_name.replace(" ", "_").lower()
        self._attr_has_entity_name = True
        self._attr_translation_key = "channel_time_left"
        self._attr_translation_placeholders = {"channel_number": str(self._channel_number)}
        self._attr_unique_id = f"{safe_device_name}_channel_{self._channel_number}_timeleft"
        self._attr_icon = "mdi:timer"
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        self._window_seconds = window_seconds
        self._history = collections.deque(maxlen=60)  # store (timestamp, temp)

    def _get_channel(self):
        """
        Helper to get the current channel object from the coordinator data.
        """
        channels = getattr(self.coordinator.data, 'channels', [])
        for ch in channels:
            if ch.number == self._channel_number:
                return ch
        return None

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property
    def native_value(self) -> float | None:
        """
        Estimate the time left (in minutes) until the channel reaches its max temperature.
        Uses a moving window of recent temperature readings to calculate the rate of change.
        """
        import time
        channel = self._get_channel()
        if not self.available or not channel:
            return None

        now = time.time()
        temp = getattr(channel, "temp", None)
        if temp is None:
            return None

        # Add current reading to history
        self._history.append((now, temp))
        window_start = now - self._window_seconds

        # Only consider readings within the time window
        recent = [x for x in self._history if x[0] >= window_start]
        if len(recent) < 2:
            return None

        dt = recent[-1][0] - recent[0][0]
        dtemp = recent[-1][1] - recent[0][1]
        if dt <= 0 or dtemp <= 0:
            return 0

        rate_per_sec = dtemp / dt
        target = getattr(channel, "max", None)
        if target is None:
            return None

        # Time left in minutes
        time_left_min = (target - temp) / (rate_per_sec * 60)
        return round(max(time_left_min, 0), 2)

    
    @property
    def available(self):
        """
        Return True if the device is online and the channel is available and not marked as inactive.
        """
        if not self.coordinator.last_update_success:
            return False

        system = getattr(self.coordinator.data, "system", None)
        if system is None:
            return False

        channel = self._get_channel()
        if not channel:
            return False
        show_inactive = (
            self.coordinator.config_entry.options.get(
                "show_inactive_unavailable",
                self.coordinator.config_entry.data.get("show_inactive_unavailable", True)
            )
        )
        temp = getattr(channel, "temp", None)
        if temp == 999.0 and show_inactive:
            return False
        return True


class WlanthermoSystemSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for system-level information (diagnostics, time, etc.).
    """
    def __init__(self, coordinator, device_name):
        super().__init__(coordinator)
        self._device_name = device_name
        self._attr_name = "System"
        self._attr_unique_id = f"{device_name}_system"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self):
        """
        Return the current system time value.
        """
        return None
        #return getattr(self.coordinator.data.system, 'time', None)

    @property
    def extra_state_attributes(self):
        """
        Return additional system attributes for diagnostics.
        """
        sys = self.coordinator.data.system
        return {
            "time": getattr(sys, 'time', None),
            "unit": getattr(sys, 'unit', None),
            "soc": getattr(sys, 'soc', None),
            "charge": getattr(sys, 'charge', None),
            "rssi": getattr(sys, 'rssi', None),
            "online": getattr(sys, 'online', None),
        }

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, "system", None)
        if system is None:
            return False
        return True

class WlanthermoSystemGetUpdateSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for system update availability (from /settings.system endpoint).
    """
    def __init__(self, coordinator, system, device_name):
        super().__init__(coordinator)
        self._system = system
        self._attr_name = "System Update Available"
        self._attr_unique_id = f"{device_name}_system_getupdate"

    def _handle_coordinator_update(self):
         # keep settings.system in sync if coordinator refreshes settings
        api = self.coordinator.hass.data[DOMAIN][self.coordinator.config_entry.entry_id].get("api")
        settings = getattr(api, "settings", None)
        if settings and hasattr(settings, "system"):
            self._system = settings.system
        self.async_write_ha_state()

    @property
    def device_info(self):
        entry_id = None
        hass = None
        if hasattr(self, 'coordinator') and hasattr(self.coordinator, 'config_entry'):
            entry_id = getattr(self.coordinator.config_entry, 'entry_id', None)
            hass = getattr(self.coordinator, 'hass', None)
        if not entry_id or not hass:
            try:
                import homeassistant.helpers.entity_platform
                platform = homeassistant.helpers.entity_platform.current_platform.get()
                hass = getattr(platform, 'hass', None)
                entry_id = getattr(platform, 'config_entry', None).entry_id if hasattr(platform, 'config_entry') else None
            except Exception:
                pass
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self) -> str | None:
        """
        Return the update state: can be 'false' or a number (update available).
        """
        return getattr(self._system, "getupdate", None)

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (version, unit).
        """
        return {
            "version": getattr(self._system, "version", None),
            "unit": getattr(self._system, "unit", None),
        }
    
    @property
    def available(self):
        """
        Return True if device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        return self._system is not None

class WlanthermoCloudLinkSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for the cloud link (from /settings.iot endpoint).
    """
    def __init__(self, coordinator, iot, device_name):
        super().__init__(coordinator)
        self._iot = iot
        self._attr_name = "Cloud Link"
        self._attr_unique_id = f"{device_name}_cloud_link"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC


    def _handle_coordinator_update(self):
        api = self.coordinator.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["api"]
        settings = getattr(api, "settings", None)
        if settings and hasattr(settings, "iot"):
            self._iot = settings.iot
        super()._handle_coordinator_update()

    @property
    def device_info(self):
        entry_id = None
        hass = None
        if hasattr(self, 'coordinator') and hasattr(self.coordinator, 'config_entry'):
            entry_id = getattr(self.coordinator.config_entry, 'entry_id', None)
            hass = getattr(self.coordinator, 'hass', None)
        if not entry_id or not hass:
            try:
                import homeassistant.helpers.entity_platform
                platform = homeassistant.helpers.entity_platform.current_platform.get()
                hass = getattr(platform, 'hass', None)
                entry_id = getattr(platform, 'config_entry', None).entry_id if hasattr(platform, 'config_entry') else None
            except Exception:
                pass
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property
    def native_value(self) -> str | None:
        """
        Return the cloud link URL if enabled, including the API token if available.
        """
        if getattr(self._iot, "CLon", False):
            url = getattr(self._iot, "CLurl", None)
            token = getattr(self._iot, "CLtoken", None)
            if url and token:
                return f"{url}?api_token={token}"
            return url or None
        return None
    
    @property
    def available(self):
        """
        Return True if the cloud link is enabled.
        """
        if not self.coordinator.last_update_success:
            return False

        system = getattr(self.coordinator.data, "system", None)
        if system is None:
            return False

        return getattr(system, "online", None) == 2
    

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (cloud link status, URL, token).
        """
        return {
            "CLon": getattr(self._iot, "CLon", None),
            "CLurl": getattr(self._iot, "CLurl", None),
            "CLtoken": getattr(self._iot, "CLtoken", None),
        }
    
class WlanthermoSystemTimeSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for system time (diagnostic, from system object).
    """
    def __init__(self, coordinator, sys, device_name):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "system_time"
        self._attr_unique_id = f"{device_name}_system_time"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = SensorDeviceClass.TIMESTAMP


    @property
    def icon(self):
        return "mdi:clock"
    
    @property
    def device_info(self):
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self):
        system = getattr(self.coordinator.data, 'system', None)
        unixtime = getattr(system, 'time', None) if system else None
        if unixtime is None:
            return None
        try:
            # Accept both int and str
            ts = int(unixtime)
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(unixtime)

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        return self.coordinator.last_update_success

class WlanthermoSystemUnitSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, sys, device_name):
        super().__init__(coordinator)
        self._sys = sys
        self._attr_has_entity_name = True
        self._attr_translation_key = "temperature_unit"
        self._attr_unique_id = f"{device_name}_system_unit"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:thermometer"
    
    @property
    def device_info(self):
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property
    def native_value(self) -> str | None:
        return getattr(self._sys, 'unit', None)

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, 'system', None)
        if system is None:
            return False
        return True

class WlanthermoSystemSocSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, sys, device_name):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "battery_level"
        self._attr_unique_id = f"{device_name}_system_soc"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE


    @property
    def icon(self):
        return "mdi:battery"
    
    @property
    def device_info(self):
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property
    def native_value(self):
        system = getattr(self.coordinator.data, 'system', None)
        return getattr(system, 'soc', None) if system else None

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, 'system', None)
        if system is None:
            return False
        return True
    
class WlanthermoSystemChargeSensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, sys, device_name):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "battery_charging"
        self._attr_unique_id = f"{device_name}_system_charge"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def icon(self):
        return "mdi:power-plug"
    
    @property
    def device_info(self):
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property 
    def is_on(self):
         """ 
         Return True if the battery is charging.
         """
         system = getattr(self.coordinator.data, "system", None)
         if not system: 
             return None # system.charge sollte True/False liefern
         return bool(getattr(system, "charge", False))

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, 'system', None)
        if system is None:
            return False
        return True

class WlanthermoSystemRssiSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, sys, device_name):
        super().__init__(coordinator)
        self._attr_name = "Wlan RSSI"
        self._attr_unique_id = f"{device_name}_system_rssi"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement ="dBm"


    @property
    def icon(self):
        return "mdi:network"
    
    @property
    def device_info(self):
            entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
            hass = getattr(self.coordinator, 'hass', None)
            if hass and entry_id:
                return hass.data[DOMAIN][entry_id]["device_info"]
            return None
    
    @property
    def native_value(self):
        """
        Return the current WLAN RSSI value from the system object.
        """
        system = getattr(self.coordinator.data, 'system', None)
        return getattr(system, 'rssi', None) if system else None
    
    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, 'system', None)
        if system is None:
            return False
        return True
    
class WlanthermoSystemOnlineSensor(CoordinatorEntity, SensorEntity):
    """
    Reports the WLANThermo system online state (0/1/2) as a translated string.
    """
    def __init__(self, coordinator, sys_obj, device_name):
        super().__init__(coordinator)
        self._sys = sys_obj
        self._translations = {}

        self._attr_has_entity_name = True
        self._attr_translation_key = "cloud_status"
        self._attr_unique_id = f"{device_name}_system_online"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["not_connected", "standby", "connected"]

    async def async_added_to_hass(self):
        await self._async_load_translations()

    async def _async_load_translations(self):
        import os, json
        hass = self.hass
        lang = getattr(hass.config, "language", "en")

        base = os.path.dirname(__file__)
        path = os.path.join(base, "translations", f"{lang}.json")

        if not os.path.exists(path):
            path = os.path.join(base, "translations", "en.json")

        def load(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)

        try:
            self._translations = await hass.async_add_executor_job(load, path)
        except Exception:
            self._translations = {}

    def _handle_coordinator_update(self):
        # Update system object
        self._sys = getattr(self.coordinator.data, "system", None)
        self.async_write_ha_state()

    @property
    def icon(self):
        return "mdi:cloud"

    @property
    def device_info(self):
        entry_id = self.coordinator.config_entry.entry_id
        hass = self.coordinator.hass
        return hass.data[DOMAIN][entry_id]["device_info"]

    @property
    def native_value(self) -> str | None:
        if not self.available:
            return "not_connected"

        system = self._sys
        value = getattr(system, "online", None) if system else None

        map_value = {
            0: "not_connected",
            1: "standby",
            2: "connected",
        }

        try:
            return map_value.get(int(value))
        except (TypeError, ValueError):
            return None

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, 'system', None)
        if system is None:
            return False
        return True

class WlanthermoDeviceInfoSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for device information (from /settings.device endpoint).
    Reports device details such as serial, CPU, hardware/software version, etc.
    """
    def __init__(self, coordinator, device, device_name):
        super().__init__(coordinator)
        self._device = device
        self._attr_has_entity_name = True
        self._attr_translation_key = "device_info"
        self._attr_unique_id = f"{device_name}_device_info"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _handle_coordinator_update(self):
        api = self.coordinator.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["api"]
        settings = getattr(api, "settings", None)
        if settings and hasattr(settings, "device"):
            self._device = settings.device
        self.async_write_ha_state()

    @property
    def icon(self):
        return "mdi:information"
    @property
    def device_info(self):
            entry_id = None
            hass = None
            if hasattr(self, 'coordinator') and hasattr(self.coordinator, 'config_entry'):
                entry_id = getattr(self.coordinator.config_entry, 'entry_id', None)
                hass = getattr(self.coordinator, 'hass', None)
            if not entry_id or not hass:
                try:
                    import homeassistant.helpers.entity_platform
                    platform = homeassistant.helpers.entity_platform.current_platform.get()
                    hass = getattr(platform, 'hass', None)
                    entry_id = getattr(platform, 'config_entry', None).entry_id if hasattr(platform, 'config_entry') else None
                except Exception:
                    pass
            if hass and entry_id:
                return hass.data[DOMAIN][entry_id]["device_info"]
            return None
    
    @property
    def native_value(self) -> str | None:
        """
        Return the device name from the device info object.
        """
        return getattr(self._device, "device", None)

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (serial, cpu, flash size, versions, language).
        """
        return {
            "serial": getattr(self._device, "serial", None),
            "cpu": getattr(self._device, "cpu", None),
            "flash_size": getattr(self._device, "flash_size", None),
            "hw_version": getattr(self._device, "hw_version", None),
            "sw_version": getattr(self._device, "sw_version", None),
            "api_version": getattr(self._device, "api_version", None),
            "language": getattr(self._device, "language", None),
        }
    @property
    def available(self):
        if not self.coordinator.last_update_success:
            return False
        return self._device is not None


class WlanthermoSystemInfoSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for system information (from /settings.system endpoint).
    Reports system details such as AP, host, language, update info, etc.
    """
    def __init__(self, coordinator, system, device_name):
        super().__init__(coordinator)
        self._system = system
        self._attr_name = "System Info"
        self._attr_unique_id = f"{device_name}_system_info"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _handle_coordinator_update(self):
        api = self.coordinator.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["api"]
        settings = getattr(api, "settings", None)
        if settings and hasattr(settings, "system"):
            self._system = settings.system
        self.async_write_ha_state()

    @property
    def icon(self):
        return "mdi:thermometer"

    @property
    def device_info(self):
        entry_id = None
        hass = None
        if hasattr(self, 'coordinator') and hasattr(self.coordinator, 'config_entry'):
            entry_id = getattr(self.coordinator.config_entry, 'entry_id', None)
            hass = getattr(self.coordinator, 'hass', None)
        if not entry_id or not hass:
            try:
                import homeassistant.helpers.entity_platform
                platform = homeassistant.helpers.entity_platform.current_platform.get()
                hass = getattr(platform, 'hass', None)
                entry_id = getattr(platform, 'config_entry', None).entry_id if hasattr(platform, 'config_entry') else None
            except Exception:
                pass
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property
    def native_value(self) -> str | None:
        """
        Return the system unit (e.g., temperature unit) from the system info object.
        """
        return getattr(self._system, "unit", None)

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (AP, host, language, update info).
        """
        return {
            "ap": getattr(self._system, "ap", None),
            "host": getattr(self._system, "host", None),
            "language": getattr(self._system, "language", None),
            "getupdate": getattr(self._system, "getupdate", None),
            "autoupd": getattr(self._system, "autoupd", None),
        }
    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        return self._system is not None

class WlanthermoIotInfoSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for IoT/cloud information (from /settings.iot endpoint).
    Reports first part for cloud URL.
    """
    def __init__(self, coordinator, iot, device_name):
        super().__init__(coordinator)
        self._iot = iot
        self._attr_name = "Cloud URL"
        self._attr_unique_id = f"{device_name}_cloud_url"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _handle_coordinator_update(self):
        api = self.coordinator.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["api"]
        settings = getattr(api, "settings", None)
        if settings and hasattr(settings, "iot"):
            self._iot = settings.iot
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """
        Return the cloud URL from the IoT info object.
        """
        return getattr(self._iot, "CLurl", None)

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (cloud URL).
        """
        return {
            "cloud_url": getattr(self._iot, "CLurl", None),
        }

    @property
    def device_info(self):
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None
    
    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False
        return self._iot is not None
    
class WlanthermoChannelSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for a channel, reporting temperature and channel details.
    """
    def __init__(self, coordinator, channel, device_name):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_translation_key = "channel"
        self._channel_number = channel.number
        self._device_name = device_name
        self._attr_unique_id = f"{device_name}_channel_{channel.number}"

    def _get_channel(self):
        """
        Helper to get the current channel object from the coordinator data.
        """
        channels = getattr(self.coordinator.data, "channels", [])
        for ch in channels:
            if ch.number == self._channel_number:
                return ch
        return None

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self) -> float | None:
        """
        Return the current temperature value for this channel.
        """
        ch = self._get_channel()
        return getattr(ch, "temp", None) if ch else None

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (channel details).
        """
        ch = self._get_channel()
        if not ch:
            return {}

        return {
            "number": ch.number,
            "name": ch.name,
            "typ": ch.typ,
            "temp": ch.temp,
            "min": ch.min,
            "max": ch.max,
            "alarm": ch.alarm,
            "color": ch.color,
            "fixed": ch.fixed,
            "connected": ch.connected,
        }

    @property
    def available(self):
        """
        Return True if the device is online.
        """
        if not self.coordinator.last_update_success:
            return False

        system = getattr(self.coordinator.data, "system", None)
        if system is None:
            return False

        ch = self._get_channel()
        if not ch:
            return False

        return True

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

class WlanthermoPitmasterSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for pitmaster, reporting pitmaster value and details.
    """
    def __init__(self, coordinator, pitmaster, device_name, idx):
        super().__init__(coordinator)
        self._pitmaster = pitmaster
        self._device_name = device_name
        self._attr_name = f"Pitmaster {idx}"
        self._attr_unique_id = f"{device_name}_pitmaster_{idx}"

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self) -> float | None:
        """
        Return the current pitmaster value.
        """
        return self._pitmaster.value

    @property
    def extra_state_attributes(self):
        """
        Return extra attributes for diagnostics (pitmaster details).
        """
        return {
            "id": self._pitmaster.id,
            "channel": self._pitmaster.channel,
            "pid": self._pitmaster.pid,
            "value": self._pitmaster.value,
            "set": self._pitmaster.set,
            "typ": self._pitmaster.typ,
            "set_color": self._pitmaster.set_color,
            "value_color": self._pitmaster.value_color,
        }
    
class WlanthermoPitmasterValueSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for pitmaster value, reporting the current value for a pitmaster.
    """
    def __init__(self, coordinator, pitmaster, device_name):
        super().__init__(coordinator)
        self._pitmaster_id = pitmaster.id
        self._attr_has_entity_name = True
        self._attr_translation_key = "pitmaster_value"
        self._attr_translation_placeholders = {"pitmaster_id": str(pitmaster.id)}
        safe_device_name = device_name.replace(" ", "_").lower()
        self._attr_unique_id = f"{safe_device_name}_pitmaster_{pitmaster.id}_value"
        self._attr_icon = "mdi:fan"
        self._attr_native_unit_of_measurement = PERCENTAGE

    def _get_pitmaster(self):
        """
        Helper to get the current pitmaster object from the coordinator data.
        """
        pitmasters = getattr(self.coordinator.data, 'pitmasters', [])
        for pm in pitmasters:
            if pm.id == self._pitmaster_id:
                return pm
        return None

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self) -> float | None:
        """
        Return the current value for this pitmaster, or None if not found.
        """
        pitmaster = self._get_pitmaster()
        return getattr(pitmaster, "value", None) if pitmaster else None

class WlanthermoPitmasterTemperatureSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor entity for a pitmaster's temperature.
    Reflects the temperature value of the channel associated with the pitmaster.
    """
    def __init__(self, coordinator, pitmaster, device_name):
        super().__init__(coordinator)
        self._pitmaster_id = pitmaster.id
        self._attr_name = f"Pitmaster {pitmaster.id} Temperature"
        self._attr_unique_id = f"{device_name}_pitmaster_{pitmaster.id}_temperature"
        self._attr_icon = "mdi:thermometer"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def _get_channel(self):
        """
        Helper to get the channel object associated with the pitmaster.
        """
        pitmasters = getattr(self.coordinator.data, 'pitmasters', [])
        pitmaster = next((pm for pm in pitmasters if pm.id == self._pitmaster_id), None)
        if not pitmaster:
            return None

        target_channel_number = getattr(pitmaster, "channel", None)
        if target_channel_number is None:
            return None
        
        channels = getattr(self.coordinator.data, 'channels', [])
        for channel in channels:
            if channel.number == target_channel_number:
                return channel
        return None

    @property
    def device_info(self):
        """
        Return device info for Home Assistant device registry.
        """
        entry_id = self.coordinator.config_entry.entry_id if hasattr(self.coordinator, 'config_entry') else None
        hass = getattr(self.coordinator, 'hass', None)
        if hass and entry_id:
            return hass.data[DOMAIN][entry_id]["device_info"]
        return None

    @property
    def native_value(self):
        """
        Return the temperature value for the pitmaster's associated channel.
        """
        channel = self._get_channel()
        if not channel:
            return None

        temp = getattr(channel, "temp", None)
        if temp == 999.0 and show_inactive:
            return None

        return temp
    

    @property
    def available(self):
        """
        Return True if the device is online and the pitmaster's associated channel is available.
        """
        if not self.coordinator.last_update_success:
            return False
        system = getattr(self.coordinator.data, 'system', None)
        if not (system and getattr(system, 'online', False)):
            return False
        channel = self._get_channel()
        return getattr(channel, 'temp', None) is not None if channel else False
