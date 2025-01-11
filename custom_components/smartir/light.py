import asyncio
import logging

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
    PLATFORM_SCHEMA,
)
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType
from . import DeviceData
from .controller import get_controller, get_controller_schema

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "SmartIR Light"
DEFAULT_DELAY = 0.5
DEFAULT_POWER_SENSOR_DELAY = 10

CONF_UNIQUE_ID = "unique_id"
CONF_DEVICE_CODE = "device_code"
CONF_CONTROLLER_DATA = "controller_data"
CONF_DELAY = "delay"
CONF_POWER_SENSOR = "power_sensor"
CONF_POWER_SENSOR_DELAY = "power_sensor_delay"
CONF_POWER_SENSOR_RESTORE_STATE = "power_sensor_restore_state"

CMD_BRIGHTNESS_INCREASE = "brighten"
CMD_BRIGHTNESS_DECREASE = "dim"
CMD_COLORMODE_COLDER = "colder"
CMD_COLORMODE_WARMER = "warmer"
CMD_POWER_ON = "on"
CMD_POWER_OFF = "off"
CMD_NIGHTLIGHT = "night"
CMD_COLORTEMPERATURE = "colorTemperature"
CMD_BRIGHTNESS = "brightness"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_DEVICE_CODE): cv.positive_int,
        vol.Required(CONF_CONTROLLER_DATA): get_controller_schema(vol, cv),
        vol.Optional(CONF_DELAY, default=DEFAULT_DELAY): cv.positive_float,
        vol.Optional(CONF_POWER_SENSOR): cv.entity_id,
        vol.Optional(
            CONF_POWER_SENSOR_DELAY, default=DEFAULT_POWER_SENSOR_DELAY
        ): cv.positive_int,
        vol.Optional(CONF_POWER_SENSOR_RESTORE_STATE, default=True): cv.boolean,
    }
)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up the IR Light platform."""
    _LOGGER.debug("Setting up the SmartIR light platform")
    if not (
        device_data := await DeviceData.load_file(
            config.get(CONF_DEVICE_CODE),
            "light",
            {},
            hass,
        )
    ):
        _LOGGER.error("SmartIR light device data init failed!")
        return

    async_add_entities([SmartIRLight(hass, config, device_data)])


class SmartIRLight(LightEntity, RestoreEntity):
    _attr_should_poll = False

    def __init__(self, hass, config, device_data):
        self.hass = hass
        self._unique_id = config.get(CONF_UNIQUE_ID)
        self._name = config.get(CONF_NAME)
        self._device_code = config.get(CONF_DEVICE_CODE)
        self._controller_data = config.get(CONF_CONTROLLER_DATA)
        self._delay = config.get(CONF_DELAY)
        self._power_sensor = config.get(CONF_POWER_SENSOR)
        self._power_sensor_delay = config.get(CONF_POWER_SENSOR_DELAY)
        self._power_sensor_restore_state = config.get(CONF_POWER_SENSOR_RESTORE_STATE)

        self._state = STATE_OFF
        self._brightness = None
        self._colortemp = None
        self._on_by_remote = False
        self._power_sensor_check_expect = None
        self._power_sensor_check_cancel = None

        self._manufacturer = device_data["manufacturer"]
        self._supported_models = device_data["supportedModels"]
        self._supported_controller = device_data["supportedController"]
        self._commands_encoding = device_data["commandsEncoding"]
        self._brightnesses = device_data["brightness"]
        self._colortemps = device_data["colorTemperature"]
        self._commands = device_data["commands"]

        if CMD_COLORTEMPERATURE in self._commands or (
            CMD_COLORMODE_COLDER in self._commands
            and CMD_COLORMODE_WARMER in self._commands
        ):
            self._colortemp = self.max_color_temp_kelvin

        if (
            CMD_NIGHTLIGHT in self._commands
            or CMD_BRIGHTNESS in self._commands
            or (
                CMD_BRIGHTNESS_INCREASE in self._commands
                and CMD_BRIGHTNESS_DECREASE in self._commands
            )
        ):
            self._brightness = 100
            self._support_brightness = True
        else:
            self._support_brightness = False

        if self._colortemp:
            self._attr_supported_color_modes = [ColorMode.COLOR_TEMP]
        elif self._support_brightness:
            self._attr_supported_color_modes = [ColorMode.BRIGHTNESS]
        elif CMD_POWER_OFF in self._commands and CMD_POWER_ON in self._commands:
            self._attr_supported_color_modes = [ColorMode.ONOFF]

        # Init exclusive lock for sending IR commands
        self._temp_lock = asyncio.Lock()

        # Init the IR/RF controller
        self._controller = get_controller(
            self.hass,
            self._supported_controller,
            self._commands_encoding,
            self._controller_data,
        )

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._state = last_state.state
            if ATTR_BRIGHTNESS in last_state.attributes:
                self._brightness = last_state.attributes[ATTR_BRIGHTNESS]
            if ATTR_COLOR_TEMP_KELVIN in last_state.attributes:
                self._colortemp = last_state.attributes[ATTR_COLOR_TEMP_KELVIN]

        if self._power_sensor:
            async_track_state_change_event(
                self.hass, self._power_sensor, self._async_power_sensor_changed
            )

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the display name of the light."""
        return self._name

    @property
    def state(self):
        """Return the current state."""
        return self._state

    @property
    def color_mode(self):
        # We only support a single color mode currently, so no need to track it
        return self._attr_supported_color_modes[0]

    @property
    def color_temp_kelvin(self):
        return self._colortemp

    @property
    def min_color_temp_kelvin(self):
        if self._colortemps:
            return self._colortemps[0]
        else:
            return None

    @property
    def max_color_temp_kelvin(self):
        if self._colortemps:
            return self._colortemps[-1]
        else:
            return None

    @property
    def is_on(self):
        if self._state == STATE_ON:
            return True
        else:
            return False

    @property
    def brightness(self):
        return self._brightness

    @property
    def extra_state_attributes(self):
        """Platform specific attributes."""
        return {
            "device_code": self._device_code,
            "manufacturer": self._manufacturer,
            "supported_models": self._supported_models,
            "supported_controller": self._supported_controller,
            "commands_encoding": self._commands_encoding,
            "on_by_remote": self._on_by_remote,
        }

    async def async_turn_on(self, **params):
        did_something = False
        # Turn the light on if off
        if self._state != STATE_ON and not self._on_by_remote:
            self._state = STATE_ON
            if CMD_POWER_ON in self._commands:
                did_something = True
                await self.send_command(CMD_POWER_ON)
            else:
                if ATTR_COLOR_TEMP_KELVIN not in params:
                    _LOGGER.debug(
                        f"No power on command found, setting last color {self._colortemp}K"
                    )
                    params[ATTR_COLOR_TEMP_KELVIN] = self._colortemp
                if ATTR_BRIGHTNESS not in params:
                    _LOGGER.debug(
                        f"No power on command found, setting last brightness {self._brightness}"
                    )
                    params[ATTR_BRIGHTNESS] = self._brightness

        if (
            ATTR_COLOR_TEMP_KELVIN in params
            and ColorMode.COLOR_TEMP in self.supported_color_modes
        ):
            did_something = True
            target = params.get(ATTR_COLOR_TEMP_KELVIN)
            old_color_temp = DeviceData.closest_match(self._colortemp, self._colortemps)
            new_color_temp = DeviceData.closest_match(target, self._colortemps)
            final_color_temp = f"{self._colortemps[new_color_temp]}"
            if (
                CMD_COLORTEMPERATURE in self._commands
                and isinstance(self._commands[CMD_COLORTEMPERATURE], dict)
                and final_color_temp in self._commands[CMD_COLORTEMPERATURE]
            ):
                _LOGGER.debug(
                    f"Changing color temp from {self._colortemp}K to {target}K using found remote command for {final_color_temp}K"
                )
                found_command = self._commands[CMD_COLORTEMPERATURE][final_color_temp]
                self._colortemp = self._colortemps[new_color_temp]
                await self.send_remote_command(found_command)
            else:
                _LOGGER.debug(
                    f"Changing color temp from {self._colortemp}K step {old_color_temp} to {target}K step {new_color_temp}"
                )
                steps = new_color_temp - old_color_temp
                if steps < 0:
                    cmd = CMD_COLORMODE_WARMER
                    steps = abs(steps)
                else:
                    cmd = CMD_COLORMODE_COLDER

                if steps > 0 and cmd:
                    # If we are heading for the highest or lowest value,
                    # take the opportunity to resync by issuing enough
                    # commands to go the full range.
                    if (
                        new_color_temp == len(self._colortemps) - 1
                        or new_color_temp == 0
                    ):
                        steps = len(self._colortemps)
                    self._colortemp = self._colortemps[new_color_temp]
                    await self.send_command(cmd, steps)

        if ATTR_BRIGHTNESS in params and self._support_brightness:
            # before checking the supported brightnesses, make a special case
            # when a nightlight is fitted for brightness of 1
            if params.get(ATTR_BRIGHTNESS) == 1 and CMD_NIGHTLIGHT in self._commands:
                self._brightness = 1
                self._state = STATE_ON
                did_something = True
                await self.send_command(CMD_NIGHTLIGHT)

            elif self._brightnesses:
                did_something = True
                target = params.get(ATTR_BRIGHTNESS)
                old_brightness = DeviceData.closest_match(
                    self._brightness, self._brightnesses
                )
                new_brightness = DeviceData.closest_match(target, self._brightnesses)
                final_brightness = f"{self._brightnesses[new_brightness]}"
                if (
                    CMD_BRIGHTNESS in self._commands
                    and isinstance(self._commands[CMD_BRIGHTNESS], dict)
                    and final_brightness in self._commands[CMD_BRIGHTNESS]
                ):
                    _LOGGER.debug(
                        f"Changing brightness from {self._brightness} to {target} using found remote command for {final_brightness}"
                    )
                    found_command = self._commands[CMD_BRIGHTNESS][final_brightness]
                    self._brightness = self._brightnesses[new_brightness]
                    await self.send_remote_command(found_command)
                else:
                    _LOGGER.debug(
                        f"Changing brightness from {self._brightness} step {old_brightness} to {target} step {new_brightness}"
                    )
                    steps = new_brightness - old_brightness
                    if steps < 0:
                        cmd = CMD_BRIGHTNESS_DECREASE
                        steps = abs(steps)
                    else:
                        cmd = CMD_BRIGHTNESS_INCREASE

                    if steps > 0 and cmd:
                        # If we are heading for the highest or lowest value,
                        # take the opportunity to resync by issuing enough
                        # commands to go the full range.
                        if (
                            new_brightness == len(self._brightnesses) - 1
                            or new_brightness == 0
                        ):
                            steps = len(self._brightnesses)
                        self._brightness = self._brightnesses[new_brightness]
                        await self.send_command(cmd, steps)

        # If we did nothing above, and the light is not detected as on
        # already issue the on command, even though we think the light
        # is on.  This is because we may be out of sync due to use of the
        # remote when we don't have anything to detect it.
        # If we do have such monitoring, avoid issuing the command in case
        # on and off are the same remote code.
        if not did_something and not self._on_by_remote:
            self._state = STATE_ON
            await self.send_command(CMD_POWER_ON)

        self.async_write_ha_state()

    async def async_turn_off(self):
        if self._state != STATE_OFF:
            self._state = STATE_OFF
            await self.send_command(CMD_POWER_OFF)
            self.async_write_ha_state()

    async def async_toggle(self):
        await (self.async_turn_on() if not self.is_on else self.async_turn_off())

    async def send_command(self, cmd, count=1):
        if cmd not in self._commands:
            _LOGGER.error(f"Unknown command '{cmd}'")
            return
        _LOGGER.debug(f"Sending {cmd} remote command {count} times.")
        remote_cmd = self._commands.get(cmd)
        await self.send_remote_command(remote_cmd, count)

    async def send_remote_command(self, remote_cmd, count=1):
        async with self._temp_lock:
            self._on_by_remote = False
            try:
                for _ in range(count):
                    await self._controller.send(remote_cmd)
                    await asyncio.sleep(self._delay)
            except Exception as e:
                _LOGGER.exception(e)

    async def _async_power_sensor_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle power sensor changes."""
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if new_state is None:
            return

        if old_state is not None and new_state.state == old_state.state:
            return

        if new_state.state == STATE_ON and self._state != STATE_ON:
            self._state = STATE_ON
            self._on_by_remote = True
        elif new_state.state == STATE_OFF:
            self._on_by_remote = False
            if self._state != STATE_OFF:
                self._state = STATE_OFF
        self.async_write_ha_state()

    @callback
    def _async_power_sensor_check_schedule(self, state):
        if self._power_sensor_check_cancel:
            self._power_sensor_check_cancel()
            self._power_sensor_check_cancel = None
            self._power_sensor_check_expect = None

        @callback
        def _async_power_sensor_check(*_):
            self._power_sensor_check_cancel = None
            expected_state = self._power_sensor_check_expect
            self._power_sensor_check_expect = None
            current_state = getattr(
                self.hass.states.get(self._power_sensor), "state", None
            )
            _LOGGER.debug(
                "Executing power sensor check for expected state '%s', current state '%s'.",
                expected_state,
                current_state,
            )

            if (
                expected_state in [STATE_ON, STATE_OFF]
                and current_state in [STATE_ON, STATE_OFF]
                and expected_state != current_state
            ):
                self._state = current_state
                _LOGGER.debug(
                    "Power sensor check failed, reverted device state to '%s'.",
                    self._state,
                )
                self.async_write_ha_state()

        self._power_sensor_check_expect = state
        self._power_sensor_check_cancel = async_call_later(
            self.hass, self._power_sensor_delay, _async_power_sensor_check
        )
        _LOGGER.debug("Scheduled power sensor check for '%s' state.", state)
