Elasticsearch Component for Home-Assistant
![build](https://github.com/legrego/homeassistant-elasticsearch/actions/workflows/cron.yml/badge.svg)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
=====

Publish HASS events to your [Elasticsearch](https://elastic.co) cluster!

## Features

- Efficiently publishes Home-Assistant events to Elasticsearch using the Bulk API
- Automatically sets up Datastreams using Time Series Data Streams ("TSDS"), Datastream Lifecycle Management ("DLM") Index Lifecycle Management ("ILM") depending on your cluster's capabilities
- Supports Elastic's [stack security features](https://www.elastic.co/elastic-stack/security) via optional username, password, and API keys
- Exclude specific entities or groups from publishing

## Compatibility

- Elasticsearch 8.0+, 7.11+ (Self or [Cloud](https://www.elastic.co/cloud) hosted). [Version `0.4.0`](https://github.com/legrego/homeassistant-elasticsearch/releases/tag/v0.4.0) includes support for older versions of Elasticsearch.
- [Elastic Common Schema version 1.0.0](https://github.com/elastic/ecs/releases/tag/v1.0.0)
- [Home Assistant Community Store](https://github.com/custom-components/hacs)
- Home Assistant 2024.1

| Elasticsearch Version | Datastreams | Time Series Datastreams | Datastream Lifecycle Management | Index Lifecycle Management |
|-----------------------|-------------|-------------------------|---------------------------------|----------------------------|
| 7.11.0 - 7.12.0       | Supported   |                         |                                 | Partially Supported [See Note]      |
| 7.13.0 - 7.17.0       | Supported   |                         |                                 | Supported                  |
| 8.0.0 - 8.6.0         | Supported   |                         |                                 | Supported                  |
| 8.7.0 - 8.12.0        |             | Supported               |                                 | Supported                  |
| 8.13.0+               |             | Supported               | Supported                       |                            |

Note: Index Lifecycle Management is partially supported in versions 7.11.0 - 7.12.0. The integration will create an ILM policy that performs time-based rollover but does not support shard-size-based rollover.

## What for?

Some usage examples inspired by [real users](https://github.com/legrego/homeassistant-elasticsearch/issues/203):

- Utilizing a Raspberry Pi in [kiosk mode](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/) with a 15" display, the homeassistant-elasticsearch integration enables the creation of rotating fullscreen [Elasticsearch Canvas](https://www.elastic.co/kibana/canvas). Those canvas displays metrics collected from various Home Assistant integrations, offering visually dynamic and informative dashboards for monitoring smart home data.
- To address temperature maintenance issues in refrigerators and freezers, temperature sensors in each appliance report data to Home Assistant, which is then published to Elasticsearch. Kibana's [alerting framework](https://www.elastic.co/kibana/alerting) is employed to set up rules that notify the user if temperatures deviate unfavorably for an extended period. The Elastic rule engine and aggregations simplify the monitoring process for this specific use case.
- Monitoring the humidity and temperature in a snake enclosure/habitat for a user's daughter, the integration facilitates the use of Elastic's Alerting framework. This choice is motivated by the framework's suitability for the monitoring requirements, providing a more intuitive solution compared to Home Assistant automations.
- The integration allows users to maintain a smaller subset of data, focusing on individual stats of interest, for an extended period. This capability contrasts with the limited retention achievable with Home Assistant and databases like MariaDB/MySQL. This extended data retention facilitates very long-term trend analysis, such as for weather data, enabling users to glean insights over an extended timeframe.

## Getting Started

The Elasticsearch component requires, well, [Elasticsearch](https://www.elastic.co/products/elasticsearch)!
This component will not host or configure Elasticsearch for you, but there are many ways to run your own cluster.
Elasticsearch is open source and free to use: just bring your own hardware!
Elastic has a [great setup guide](https://www.elastic.co/start) if you need help getting your first cluster up and running.

If you don't want to maintain your own cluster, then give the [Elastic Cloud](https://www.elastic.co/cloud) a try! There is a free trial available to get you started.

## Inspiration

### HVAC Usage
Graph your home's climate and HVAC Usage:

![img](assets/hvac-history.png)

### Weather Station
Visualize and alert on data from your weather station:

![img](assets/weather-station.png)

![img](assets/weather-station-wind-pressure.png)

## Installation

This component is available via the Home Assistant Community Store (HACS) in their default repository. Visit https://hacs.xyz/ for more information on HACS.

Alternatively, you can manually install this component by copying the contents of `custom_components` to your `$HASS_CONFIG/custom_components` directory, where `$HASS_CONFIG` is the location on your machine where Home-Assistant lives.
Example: `/home/pi/.homeassistant` and `/home/pi/.homeassistant/custom_components`. You may have to create the `custom_components` directory yourself.

## Create Elasticsearch Credentials

The integration supports authenticating via API Key, Username and Password or unauthenticated access.

### Authenticating via API Key

You must first create an API Key with the appropriate privileges.
Note that if you adjust the `index_format` or `alias` settings that the role definition must be updated accordingly:

```json
POST /_security/api_key
{
  "name": "home_assistant_component",
  "role_descriptors": {
    "hass_writer": {
      "cluster": [
        "manage_index_templates",
        "manage_ilm",
        "monitor"
      ],
      "indices": [
        {
          "names": [
            "hass-events*",
            "active-hass-index-*",
            "all-hass-events",
            "metrics-homeassistant*"
          ],
          "privileges": [
            "manage",
            "index",
            "create_index",
            "create"
          ]
        }
      ]
    }
  }
}
```

### Authenticating via username/password

If you choose not to authenticate via an API Key, you need to create a user and role with appropriate privileges.

```json
# Create role
POST /_security/role/hass_writer
{
  "cluster": [
    "manage_index_templates",
    "manage_ilm",
    "monitor"
  ],
  "indices": [
    {
      "names": [
        "hass-events*",
        "active-hass-index-*",
        "all-hass-events",
        "metrics-homeassistant*"
      ],
      "privileges": [
        "manage",
        "index",
        "create_index",
        "create"
      ]
    }
  ]
}
```

```json
# Create user
POST /_security/user/hass_writer
{
  "full_name": "Home Assistant Writer",
  "password": "changeme",
  "roles": ["hass_writer"]
}
```

## Setup

This component is configured interactively via Home Assistant's integration configuration page.

1. Restart Home-assistant once you've completed the installation instructions above.
2. From the `Integrations` configuration menu, add a new `Elasticsearch` integration. ![img](assets/add-integration.png)
3. Select the appropriate authentication method
4. Provide connection information and optionally credentials to begin setup. ![img](assets/configure-integration.png)
5. Once the integration is setup, you may tweak all settings via the "Options" button on the integrations page.
   ![img](assets/publish-options.png)


## Defining your own Index Mappings, Settings, and Ingest Pipeline

When in Datastream mode (Default for Elasticsearch 8.7+) you can customize the mappings, settings and define an [ingest pipeline](https://www.elastic.co/guide/en/elasticsearch/reference/current/ingest.html) by creating a [component template](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-component-template.html) called `metrics-homeassistant@custom`


The following is an example on how to push your Home Assistant metrics into an ingest pipeline called `metrics-homeassistant-pipeline`:

```
PUT _ingest/pipeline/metrics-homeassistant-pipeline
{
  "description": "Pipeline for HomeAssistant dataset",
  "processors": [ ]
}
```

```
PUT _component_template/metrics-homeassistant@custom
{
  "template": {
    "mappings": {}
    "settings": {
      "index.default_pipeline": "metrics-homeassistant-pipeline",
    }
  }
}
```

Component template changes apply when the datastream performs a rollover so the first time you modify the template you may need to manually initiate ILM rollover to start applying the pipeline.

## Create your own cluster health sensor
Versions prior to `0.6.0` included a cluster health sensor. This has been removed in favor of a more generic approach. You can create your own cluster health sensor by using Home Assistant's built-in [REST sensor](https://www.home-assistant.io/integrations/sensor.rest).

```yaml
# Example configuration
sensor:
  - platform: rest
    name: "Cluster Health"
    unique_id: "cluster_health" # Replace with your own unique id. See https://www.home-assistant.io/integrations/sensor.rest#unique_id
    resource: "https://example.com/_cluster/health" # Replace with your Elasticsearch URL
    username: hass # Replace with your username
    password: changeme # Replace with your password
    value_template: "{{ value_json.status }}"
    json_attributes: # Optional attributes you may want to include from the /_cluster/health API response
      - "cluster_name"
      - "status"
      - "timed_out"
      - "number_of_nodes"
      - "number_of_data_nodes"
      - "active_primary_shards"
      - "active_shards"
      - "relocating_shards"
      - "initializing_shards"
      - "unassigned_shards"
      - "delayed_unassigned_shards"
      - "number_of_pending_tasks"
      - "number_of_in_flight_fetch"
      - "task_max_waiting_in_queue_millis"
      - "active_shards_percent_as_number"
```

## Support

This project is not endorsed or supported by either Elastic or Home-Assistant - please open a GitHub issue for any questions, bugs, or feature requests.

## Contributing

Contributions are welcome! Please see the [Contributing Guide](CONTRIBUTING.md) for more information.
