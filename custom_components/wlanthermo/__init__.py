"""
Home Assistant integration for WLANThermodevices.
Handles setup, teardown, and data coordination for the integration.
"""

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN, CONF_PATH_PREFIX, CONF_MODEL
from .api import WLANThermoApi
from .data import WlanthermoData
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from datetime import timedelta
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
	"""
	Set up a WLANThermo integration entry.
	Initializes API, fetches device info, sets up data coordinator, and forwards platforms.
	"""
	# Retrieve connection and configuration options
	host = entry.options.get("host", entry.data.get("host"))
	port = entry.options.get("port", entry.data.get("port", 80))
	path_prefix = entry.data.get("path_prefix", "/")
	scan_interval = entry.options.get("scan_interval", 10)

	api = WLANThermoApi(hass, host, port, path_prefix)


	device_name = entry.data.get("device_name", "WLANThermo")
	host = entry.data.get("host")
	path_prefix = entry.data.get("path_prefix", "/")
	device_info = {}
	from .data import SettingsData
	try:
		# Attempt to fetch and parse device settings for richer device info
		settings_json = await api.get_settings()
		settings = None
		if settings_json:
			try:
				settings = SettingsData.from_json(settings_json)
				api.settings = settings
			except Exception as e:
				import logging
				logging.getLogger(__name__).error(f"WLANThermo: Failed to parse /settings JSON: {e}")
		if settings and hasattr(settings, "device"):
			dev = settings.device
			# Compose a descriptive model string from device attributes
			model_str = f"{getattr(dev, 'device', 'unknown')} {getattr(dev, 'hw_version', '')} {getattr(dev, 'cpu', '')}".strip()
			device_info = {
				"identifiers": {(DOMAIN, dev.serial or host)},
				"name": device_name,
				"manufacturer": "WLANThermo",
				"model": model_str,
				"sw_version": getattr(dev, "sw_version", "unknown"),
			}
		else:
			# Fallback if device info is incomplete
			model_str = f"{getattr(dev, 'device', 'unknown')} {getattr(dev, 'hw_version', '')} {getattr(dev, 'cpu', '')}".strip()
			device_info = {
				"identifiers": {(DOMAIN, host)},
				"name": device_name,
				"manufacturer": "WLANThermo",
				"model": model_str,
				"sw_version": "unknown",
			}
	except Exception:
		# Fallback if settings fetch or parse fails
		device_info = {
			"identifiers": {(DOMAIN, host)},
			"name": device_name,
			"manufacturer": "WLANThermo",
			"sw_version": "unknown",
		}

	import asyncio

	async def async_update_data():
		"""
		Fetch both /data and /settings.
		Do NOT raise UpdateFailed when device is offline.
		"""
		try:
			raw_data = await api.get_data()
			if not raw_data:
				_LOGGER.debug("WLANThermo: Device offline (no /data)")
				return None

			# Try to load settings
			try:
				raw_settings = await api.get_settings()
				if raw_settings:
					api.settings = SettingsData.from_json(raw_settings)
			except Exception:
				_LOGGER.debug("WLANThermo: Device offline (no /settings)")

			return WlanthermoData(raw_data)

		except Exception as exc:
			_LOGGER.debug(f"WLANThermo: Device offline: {exc}")
			return None

	class DebugDataUpdateCoordinator(DataUpdateCoordinator):
		"""
		Custom DataUpdateCoordinator for debugging and extension.
		"""
		async def _handle_coordinator_update(self) -> None:
			await super()._handle_coordinator_update()

	# Set up the coordinator to periodically fetch data
	coordinator = DebugDataUpdateCoordinator(
		hass,
		_LOGGER,
		name="WLANThermoData",
		update_method=async_update_data,
		update_interval=timedelta(seconds=scan_interval),
	)
	await coordinator.async_refresh()

	# Prepare entry_data early so listener can use it
	entry_data = {
		"api": api,
		"scan_interval": scan_interval,
		"coordinator": coordinator,
		"device_info": device_info,
		"platforms_setup": set(),
	}
	hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry_data

	platforms = ["sensor", "number", "select", "text", "light"]

	# If device is offline at setup → do NOT load platforms
	if not coordinator.last_update_success:
		_LOGGER.warning(
			"WLANThermo: Device offline during setup. Platforms will load when device becomes available."
		)

		async def _async_start_platforms():
			if coordinator.last_update_success and not entry_data["platforms_setup"]:
				await hass.config_entries.async_forward_entry_setups(entry, platforms)
				entry_data["platforms_setup"].update(platforms)

		coordinator.async_add_listener(_async_start_platforms)
		return True

	# Device was online → load platforms immediately
	await hass.config_entries.async_forward_entry_setups(entry, platforms)
	entry_data["platforms_setup"].update(platforms)

	return True



# Unload the integration and all platforms
import asyncio

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
	"""
	Unload a WLANThermointegration entry and all associated platforms.
	Cleans up hass.data and returns True if all platforms unloaded successfully.
	"""
	platforms = ["sensor", "number", "select", "text", "light"]
	results = await asyncio.gather(
		*(hass.config_entries.async_forward_entry_unload(entry, platform) for platform in platforms)
	)
	hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
	return all(results)

