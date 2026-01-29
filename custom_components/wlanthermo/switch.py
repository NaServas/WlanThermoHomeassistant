"""
Switch platform for WLANThermo PID profile fields (opl).
"""
from typing import Any, Callable
from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

async def async_setup_entry(hass: Any, config_entry: Any, async_add_entities: Callable) -> None:
    """
    Set up switch entities for each PID profile (OPL).

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry for the integration.
        async_add_entities: Callback to add entities.
    Returns:
        None.
    """
    entry_id = config_entry.entry_id
    entry_data = hass.data[DOMAIN][entry_id]
    coordinator = entry_data["coordinator"]
    entity_store = entry_data.setdefault("entities", {})
    entity_store.setdefault("pidprofile_switch", set())
    entity_store.setdefault("push_switch", set())
    entity_store.setdefault("bluetooth_switch", set())

    async def _async_discover_entities() -> None:
        """
        Discover and add new switch entities for each PID profile.
        Returns:
            None.
        """
        if not coordinator.data:
            return
        new_entities = []
        for profile in getattr(coordinator.api.settings, "pid", []):
            for key, cls in (
                ("opl", WlanthermoPidProfileOplSwitch),
                ("link", WlanthermoPidProfileLinkSwitch),
            ):
                unique_key = f"{profile.id}_{key}"
                if unique_key not in entity_store["pidprofile_switch"]:
                    new_entities.append(
                        cls(
                            coordinator,
                            entry_data,
                            profile_id=profile.id,
                        )
                    )
                    entity_store["pidprofile_switch"].add(unique_key)
        for key, cls in (
            ("telegram_enabled", WlanthermoTelegramEnabledSwitch),
            ("pushover_enabled", WlanthermoPushoverEnabledSwitch),
        ):
            if key not in entity_store["push_switch"]:
                new_entities.append(cls(coordinator, entry_data))
                entity_store["push_switch"].add(key)
        bluetooth = getattr(coordinator.data, "bluetooth", None)
        if (
            bluetooth
            and "bluetooth_enabled" not in entity_store["bluetooth_switch"]
        ):
            new_entities.append(
                WlanthermoBluetoothEnabledSwitch(coordinator, entry_data)
            )
            entity_store["bluetooth_switch"].add("bluetooth_enabled")
            for dev in bluetooth.devices:
                address = dev.get("address")
                count = int(dev.get("count", 0))

                for probe in range(count):
                    key = f"{address}_{probe}"
                    if key in entity_store["bluetooth_switch"]:
                        continue

                    new_entities.append(
                        WlanthermoBluetoothProbeSwitch(
                            coordinator,
                            entry_data,
                            address=address,
                            probe_index=probe,
                        )
                    )
                    entity_store["bluetooth_switch"].add(key)

        if new_entities:
            async_add_entities(new_entities)
    coordinator.async_add_listener(_async_discover_entities)
    await _async_discover_entities()


class WlanthermoPidProfileOplSwitch(CoordinatorEntity, SwitchEntity):
    """
    Switch entity for PID profile open lid detection (opl).
    """
    _attr_has_entity_name = True
    _attr_icon = "mdi:pot-steam"
    _attr_entity_category = EntityCategory.CONFIG


    def __init__(self, coordinator: Any, entry_data: dict, *, profile_id: int) -> None:
        """
        Initialize a WlanthermoPidProfileOplSwitch entity.
        Args:
            coordinator: Data update coordinator.
            entry_data: Dictionary with entry data.
            profile_id: PID profile ID.
        Returns:
            None.
        """
        super().__init__(coordinator)
        self._profile_id = profile_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_pid_{profile_id}_opl"
        )
        self._attr_device_info = entry_data["device_info"]
        self._attr_translation_key = "pidprofile_opl"
        self._attr_translation_placeholders = {
            "profile_id": str(profile_id)
        }

    @property
    def is_on(self) -> bool:
        """
        Return True if open lid detection is enabled for this PID profile.
        Returns:
            True if enabled, False otherwise.
        """
        for profile in getattr(self.coordinator.api.settings, "pid", []):
            if profile.id == self._profile_id:
                return bool(profile.opl)
        return False

    async def async_turn_on(self, **kwargs) -> None:
        """
        Turn on open lid detection for this PID profile.
        Args:
            **kwargs: Additional arguments.
        Returns:
            None.
        """
        await self._async_set_opl(True)

    async def async_turn_off(self, **kwargs) -> None:
        """
        Turn off open lid detection for this PID profile.
        Args:
            **kwargs: Additional arguments.
        Returns:
            None.
        """
        await self._async_set_opl(False)

    async def _async_set_opl(self, value: bool) -> None:
        """
        Set the open lid detection value for this PID profile and update the coordinator.
        Args:
            value: True to enable, False to disable.
        Returns:
            None.
        """
        for p in self.coordinator.api.settings.pid:
            if p.id == self._profile_id:
                p.opl = value
                payload = p.to_full_payload()
                success = await self.coordinator.api.async_set_pid_profile(
                    [payload],
                )
                if success:
                    await self.coordinator.async_request_refresh()
                return
            

class WlanthermoPidProfileLinkSwitch(CoordinatorEntity, SwitchEntity):
    """
    Switch entity for PID profile actuator link (DAMPER only).
    """
    _attr_has_entity_name = True
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: Any, entry_data: dict, *, profile_id: int) -> None:
        """
        Initialize a WlanthermoPidProfileLinkSwitch entity.
        Args:
            coordinator: Data update coordinator.
            entry_data: Dictionary with entry data.
            profile_id: PID profile ID.
        Returns:
            None.
        """
        super().__init__(coordinator)
        self._profile_id = profile_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_pid_{profile_id}_link"
        )
        self._attr_device_info = entry_data["device_info"]
        self._attr_translation_key = "pidprofile_link"
        self._attr_translation_placeholders = {
            "profile_id": str(profile_id)
        }

    @property
    def is_on(self) -> bool:
        """
        Return True if actuator link is enabled for this PID profile.
        Returns:
            True if enabled, False otherwise.
        """
        for p in self.coordinator.api.settings.pid:
            if p.id == self._profile_id:
                return bool(p.link)
        return False

    @property
    def available(self) -> bool:
        """
        Return True if this PID profile supports actuator link.
        Returns:
            True if supported, False otherwise.
        """
        for p in self.coordinator.api.settings.pid:
            if p.id == self._profile_id:
                return p.supports_link
        return False

    async def async_turn_on(self, **kwargs) -> None:
        """
        Turn on actuator link for this PID profile.
        Args:
            **kwargs: Additional arguments.
        Returns:
            None.
        """
        await self._async_set_link(True)

    async def async_turn_off(self, **kwargs) -> None:
        """
        Turn off actuator link for this PID profile.
        Args:
            **kwargs: Additional arguments.
        Returns:
            None.
        """
        await self._async_set_link(False)

    async def _async_set_link(self, value: bool) -> None:
        """
        Set the actuator link value for this PID profile and update the coordinator.
        Args:
            value: True to enable, False to disable.
        Returns:
            None.
        """
        for p in self.coordinator.api.settings.pid:
            if p.id == self._profile_id:
                p.link = int(value)
                payload = p.to_full_payload()
                success = await self.coordinator.api.async_set_pid_profile(
                    [payload],
                )
                if success:
                    await self.coordinator.async_request_refresh()
                return
            
class WlanthermoTelegramEnabledSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to enable or disable Telegram push notifications."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:facebook-messenger"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "telegram_enabled"

    def __init__(self, coordinator, entry_data: dict) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_telegram_enabled"
        )
        self._attr_device_info = entry_data["device_info"]

    @property
    def available(self) -> bool:
        return self.coordinator.data.push is not None

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.push.telegram.enabled)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)

    async def _async_write(self, enabled: bool) -> None:
        telegram = self.coordinator.data.push.telegram
        telegram.enabled = enabled

        payload = {
            "telegram": telegram.to_payload(),
        }

        success = await self.coordinator.api.async_set_push(payload)
        if success:
            await self.coordinator.async_request_refresh()


class WlanthermoPushoverEnabledSwitch(CoordinatorEntity, SwitchEntity):
    """Enable/disable Pushover push notifications."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "pushover_enabled"

    def __init__(self, coordinator, entry_data: dict) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_pushover_enabled"
        )
        self._attr_device_info = entry_data["device_info"]

    @property
    def available(self) -> bool:
        return self.coordinator.data.push is not None

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.push.pushover.enabled)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)

    async def _async_write(self, enabled: bool) -> None:
        pushover = self.coordinator.data.push.pushover
        pushover.enabled = enabled

        payload = {
            "pushover": pushover.to_payload()
        }
        success = await self.coordinator.api.async_set_push(payload)
        if success:
            await self.coordinator.async_request_refresh()


class WlanthermoBluetoothEnabledSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:bluetooth"

    def __init__(self, coordinator, entry_data):
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_bluetooth_enabled"
        )
        self._attr_device_info = entry_data["device_info"]
        self._attr_translation_key = "bluetooth_enabled"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        return bool(data and data.bluetooth and data.bluetooth.enabled)

    async def async_turn_on(self, **kwargs) -> None:
        bt = self.coordinator.data.bluetooth
        if not bt:
            return
        bt.enabled = True
        await self._push()

    async def async_turn_off(self, **kwargs) -> None:
        bt = self.coordinator.data.bluetooth
        if not bt:
            return
        bt.enabled = False
        await self._push()

    async def _push(self) -> None:
        success = await self.coordinator.api.async_set_bluetooth(
            self.coordinator.data.bluetooth.to_payload()
        )
        if success:
            await self.coordinator.async_request_refresh()


class WlanthermoBluetoothProbeSwitch(CoordinatorEntity, SwitchEntity):
    """Enable/disable individual Bluetooth probes."""
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:thermometer-bluetooth"

    def __init__(self, coordinator, entry_data, address: str, probe_index: int):
        super().__init__(coordinator)
        self._address = address
        self._probe = probe_index
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_bt_{address}_probe_{probe_index+1}"
        )
        self._attr_device_info = entry_data["device_info"]
        self._attr_translation_key = "bluetooth_probe"
        self._attr_translation_placeholders = {
            "probe": str(self._probe + 1),
            "name": self._address.replace(":", "")[-6:],
        }

    def _get_device(self) -> dict | None:
        data = self.coordinator.data
        if not data or not data.bluetooth:
            return None
        for dev in data.bluetooth.devices:
            if dev.get("address") == self._address:
                return dev
        return None

    @property
    def is_on(self) -> bool:
        dev = self._get_device()
        if not dev:
            return False
        return is_bit_set(dev.get("selected", 0), self._probe)
    @property
    def available(self) -> bool:
        data = self.coordinator.data
        if not data or not data.bluetooth or not data.bluetooth.enabled:
            return False
        return self._get_device() is not None

    async def async_turn_on(self, **kwargs) -> None:
        dev = self._get_device()
        if not dev:
            return
        dev["selected"] = set_bit(dev.get("selected", 0), self._probe)
        await self._push()

    async def async_turn_off(self, **kwargs) -> None:
        dev = self._get_device()
        if not dev:
            return
        dev["selected"] = clear_bit(dev.get("selected", 0), self._probe)
        await self._push()

    async def _push(self) -> None:
        bluetooth = self.coordinator.data.bluetooth
        if not bluetooth:
            return
        success = await self.coordinator.api.async_set_bluetooth(
            bluetooth.to_payload()
        )
        if success:
            await self.coordinator.async_request_refresh()


def is_bit_set(mask: int, bit: int) -> bool:
    return bool(mask & (1 << bit))

def set_bit(mask: int, bit: int) -> int:
    return mask | (1 << bit)

def clear_bit(mask: int, bit: int) -> int:
    return mask & ~(1 << bit)
