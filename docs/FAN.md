# SmartIR Fan

Find your device's brand code [here](FAN_CODES.md) and add the number in the `device_code` field. If your device is not supported, you will need to learn your own IR codes and place them in the Json file in `smartir/custom_codes/fan` subfolder. Please refer to [this guide](CODES_SYNTAX.md) to find a way how to do it. Once you have working device file please do not forgot to submit Pull Request so it could be inherited to this project for other users.

## Configuration variables

| Name                         |  Type   | Default  | Description                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------- | :-----: | :------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                       | string  | optional | The name of the device                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `unique_id`                  | string  | optional | An ID that uniquely identifies this device. If two devices have the same unique ID, Home Assistant will raise an exception.                                                                                                                                                                                                                                                                                                               |
| `device_code`                | number  | required | (Accepts only positive numbers)                                                                                                                                                                                                                                                                                                                                                                                                           |
| `controller_data`            | string  | required | The data required for the controller to function. Look into configuration examples bellow for valid configuration entries for different controllers types.                                                                                                                                                                                                                                                                                |
| `delay`                      | number  | optional | Adjusts the delay in seconds between multiple commands. The default is 0.5                                                                                                                                                                                                                                                                                                                                                                |
| `power_sensor`               | string  | optional | _entity_id_ for a sensor that monitors whether your device is actually `on` or `off`. This may be a power monitor sensor. (Accepts only on/off states)                                                                                                                                                                                                                                                                                    |
| `power_sensor_delay`         |   int   | optional | Maximum delay in second in which power sensor is able to report back to HA changed state of the device, default is 10 seconds. If sensor reaction time is longer extend this time, otherwise you might get unwanted changes in the device state.                                                                                                                                                                                          |
| `power_sensor_restore_state` | boolean | optional | If `true` than in case power sensor will report to HA that device is `on` without HA actually switching it `on `(device was switched on by remote, of device cycled, etc.), than HA will report last assumed state and attributes at the time when the device was `on` managed by HA. If set to `false` when device will be reported as `on` by the power sensors all device attributes will be reported as `UNKNOWN`. Default is `true`. |

## Example configurations

### Example (using broadlink controller)

Add a Broadlink RM device named "Bedroom" via config flow (read the [docs](https://www.home-assistant.io/integrations/broadlink/)).

```yaml
fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 1000
    controller_data:
      controller_type: Broadlink
      remote_entity: remote.bedroom_remote
      delay_secs: 0.5
      num_repeats: 3
    power_sensor: binary_sensor.fan_power
```

## Example (using xiaomi controller)

```yaml
remote:
  - platform: xiaomi_miio
    host: 192.168.10.10
    token: YOUR_TOKEN

fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 2000
    controller_data:
      controller_type: Xiaomi
      remote_entity: remote.xiaomi_miio_192_168_10_10
    power_sensor: binary_sensor.fan_power
```

### Example (using MQTT controller)

```yaml
fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 3000
    controller_data:
      controller_type: MQTT
      mqtt_topic: home-assistant/bedroom_fan/command
    power_sensor: binary_sensor.fan_power
```

### Example (using mqtt Z06/UFO-R11 controller)

```yaml
fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 3000
    controller_data:
      controller_type: UFOR11
      mqtt_topic: home-assistant/bedroom_fan/command
    power_sensor: binary_sensor.fan_power
```

### Example (using LOOKin controller)

```yaml
fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 4000
    controller_data:
      controller_type: LOOKin
      remote_host: 192.168.10.10
    power_sensor: binary_sensor.fan_power
```

### Example (using ESPHome -- see climate)

ESPHome configuration example:

```yaml
esphome:
  name: my_espir
  platform: ESP8266
  board: esp01_1m

includes:
    - cmdtoraw.h
api:
  services:
    - service: send_multi_command
      variables:
        command: string
      then:
        - remote_transmitter.transmit_raw:
            code: !lambda return cmdtoraw(command); 
            carrier_frequency: 38000hz    

remote_transmitter:
  pin: GPIO14
  carrier_duty_percent: 50%
```

HA configuration.yaml:

```yaml
fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 4000
    controller_data:
      controller_type: ESPHome
      esphome_service: my_espir_send_multi_command
    power_sensor: binary_sensor.fan_power
```

### Example (using ZHA controller and a TuYa ZS06)

```yaml
fan:
  - platform: smartir
    name: Bedroom fan
    unique_id: bedroom_fan
    device_code: 5000
    controller_data:
      controller_type: ZHA
      zha_ieee: "XX:XX:XX:XX:XX:XX:XX:XX"
      zha_endpoint_id: 1
      zha_cluster_id: 57348
      zha_cluster_type: "in"
      zha_command: 2
      zha_command_type: "server"
    power_sensor: binary_sensor.fan_power
```

## Available codes for Fan devices

[**Fan codes**](/docs/FAN_CODES.md)
