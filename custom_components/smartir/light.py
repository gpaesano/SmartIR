import asyncio
import logging

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, Event, EventStateChangedData
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType
from .smartir_helpers import closest_match_index
from .smartir_entity import load_device_data_file, SmartIR, PLATFORM_SCHEMA

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "SmartIR Light"

CMD_BRIGHTNESS_INCREASE = "brighten"
CMD_BRIGHTNESS_DECREASE = "dim"
CMD_COLOR_MODE_COLDER = "colder"
CMD_COLOR_MODE_WARMER = "warmer"
CMD_POWER_ON = "on"
CMD_POWER_OFF = "off"
CMD_NIGHTLIGHT = "night"
CMD_COLOR_TEMPERATURE = "colorTemperature"
CMD_BRIGHTNESS = "brightness"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string}
)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up the IR Light platform."""
    _LOGGER.debug("Setting up the SmartIR light platform")
    if not (
        device_data := await load_device_data_file(
            config,
            "light",
            {},
            hass,
        )
    ):
        _LOGGER.error("SmartIR light device data init failed!")
        return

    async_add_entities([SmartIRLight(hass, config, device_data)])


class SmartIRLight(LightEntity, RestoreEntity):

    def __init__(self, hass: HomeAssistant, config: ConfigType, device_data):
        # Initialize SmartIR device
        SmartIR.__init__(self, hass, config, device_data)

        self._brightness = None
        self._colortemp = None

        self._brightnesses = device_data["brightness"]
        self._colortemps = device_data["colorTemperature"]

        if CMD_COLOR_TEMPERATURE in self._commands or (
            CMD_COLOR_MODE_COLDER in self._commands
            and CMD_COLOR_MODE_WARMER in self._commands
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

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            if ATTR_BRIGHTNESS in last_state.attributes:
                self._brightness = last_state.attributes[ATTR_BRIGHTNESS]
            if ATTR_COLOR_TEMP_KELVIN in last_state.attributes:
                self._colortemp = last_state.attributes[ATTR_COLOR_TEMP_KELVIN]

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
            "on_by_remote": self._on_by_remote,
            "device_code": self._device_code,
            "manufacturer": self._manufacturer,
            "supported_models": self._supported_models,
            "supported_controller": self._supported_controller,
            "commands_encoding": self._commands_encoding,
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
            old_color_temp = closest_match_index(self._colortemp, self._colortemps)
            new_color_temp = closest_match_index(target, self._colortemps)
            final_color_temp = f"{self._colortemps[new_color_temp]}"
            if (
                CMD_COLOR_TEMPERATURE in self._commands
                and isinstance(self._commands[CMD_COLOR_TEMPERATURE], dict)
                and final_color_temp in self._commands[CMD_COLOR_TEMPERATURE]
            ):
                _LOGGER.debug(
                    f"Changing color temp from {self._colortemp}K to {target}K using found remote command for {final_color_temp}K"
                )
                found_command = self._commands[CMD_COLOR_TEMPERATURE][final_color_temp]
                self._colortemp = self._colortemps[new_color_temp]
                await self.send_remote_command(found_command)
            else:
                _LOGGER.debug(
                    f"Changing color temp from {self._colortemp}K step {old_color_temp} to {target}K step {new_color_temp}"
                )
                steps = new_color_temp - old_color_temp
                if steps < 0:
                    cmd = CMD_COLOR_MODE_WARMER
                    steps = abs(steps)
                else:
                    cmd = CMD_COLOR_MODE_COLDER

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
                old_brightness = closest_match_index(
                    self._brightness, self._brightnesses
                )
                new_brightness = closest_match_index(target, self._brightnesses)
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
