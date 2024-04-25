# Installation

## HACS (recommended)
This component is available in [HACS](https://hacs.xyz/){:target="_blank"} (Home Assistant Community Store).

1. Install HACS if you don't have it already
2. Open HACS in Home Assistant
3. Go to "Integrations" section
4. Click button with "+" icon
5. Search for "Elasticsearch"

## Manual
1. Download the latest release from the [releases page](https://github.com/legrego/homeassistant-elasticsearch/releases)
2. Extract the contents of the zip file
3. Copy the `custom_components` directory to your `$HASS_CONFIG/custom_components` directory, where `$HASS_CONFIG` is the location on your machine where Home-Assistant lives. Example: `/home/pi/.homeassistant` and `/home/pi/.homeassistant/custom_components`. You may have to create the `custom_components` directory yourself.

You must restart Home Assistant after installation.

Next: [Configuration](./configure.md)