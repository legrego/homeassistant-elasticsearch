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

## Removing the integration

1. From the [`Integrations` configuration menu](https://my.home-assistant.io/redirect/integrations/), select `Elasticsearch`, then delete each of its entries.
2. If you installed with HACS, remove `Elasticsearch` from HACS. Otherwise, delete the `custom_components/elasticsearch` directory.
3. Restart Home Assistant.

Home Assistant stops publishing at this point, but nothing is removed from Elasticsearch. Your existing data stays where it is, along with the following:

- The `metrics-homeassistant.*` data streams, which hold your data
- The `metrics-homeassistant` index template
- Any API key or user you created for this integration

If you no longer need them, you can delete the data streams and then the index template, in that order, from Dev Tools in Kibana:

!!! warning
    This permanently deletes all of the data published by Home Assistant.

```
DELETE _data_stream/metrics-homeassistant.*
DELETE _index_template/metrics-homeassistant
```

Then invalidate the API key, which you can do from `Stack Management` > `API keys` in Kibana.
