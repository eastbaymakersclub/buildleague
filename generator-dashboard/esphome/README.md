# Generator hardware

`voltage-reader.yaml` targets an Adafruit HUZZAH32 ESP32 Feather. Connect the DC
signal to A2/GPIO34 and its ground to GND. USB supplies power. Keep the signal
within 0–3.3 V; the useful direct measuring range is approximately 0.1–3.1 V.

The ADC targets a 1 ms interval, averages 200 readings, then rounds to two decimal
places. A 12-second check measured about 208 ms between reports (roughly 960
samples/second). Wi-Fi and software scheduling add jitter.

Copy `secrets.example.yaml` to ignored `secrets.yaml` and fill in the actual Wi-Fi,
API, and OTA values. If flashing a new reader, generate an API encryption key
with `openssl rand -base64 32`; the dashboard must use the same key.

Validated originally with ESPHome 2026.5.0:

```sh
esphome run voltage-reader.yaml --device /dev/cu.YOUR_USB_SERIAL_PORT
```

## Optional large display

`large-7-seg-display.yaml` controls the club's six-digit shift-register display,
with clock GPIO13, latch GPIO12, and serial data GPIO14. Its segment bit patterns
are specific to that hardware; it is not a generic seven-segment driver.

The decimal LED is always on after the third digit from the left. Incoming `1.23`
is rendered as `  1.230` (six digits plus the decimal LED); the final zero is
padding, not additional calibrated precision.

The optional [Home Assistant automation](../homeassistant/voltage-display-automation.yaml)
forwards `sensor.voltage_reader_input_voltage` to
`text.large_7_seg_display_display_text`. Install its mapping as a list entry in
Home Assistant's `automations.yaml`, or create the equivalent automation through
the UI. Check entity IDs against your installation. Disable any older automation
that writes competing values to that display. Unavailable readings produce dashes.

The browser dashboard connects to the reader independently and does not need
Home Assistant. Never include real `secrets.yaml` files in commits.

References:
- [HUZZAH32 pinouts](https://learn.adafruit.com/adafruit-huzzah32-esp32-feather/pinouts)
- [ESPHome ADC](https://esphome.io/components/sensor/adc/)
