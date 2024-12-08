---
title: Introduction
---
# Elasticsearch Component for Home-Assistant

Publish Home Assistant events to your [Elasticsearch](https://elastic.co) cluster!

## Features

- Efficiently publishes Home-Assistant events to Elasticsearch using the Bulk API
- Automatically sets up Datastreams using Time Series Data Streams ("TSDS"), Datastream Lifecycle Management ("DLM"), or Index Lifecycle Management ("ILM") depending on your cluster's capabilities
- Supports Elastic's [stack security features](https://www.elastic.co/elastic-stack/security) via optional username, password, and API keys
- Selectively publish events based on domains or entities

## Compatibility

- Elasticsearch 8.0+, 7.17+ (Self or [Cloud](https://www.elastic.co/cloud) hosted).
- [Elastic Common Schema version 1.0.0](https://github.com/elastic/ecs/releases/tag/v1.0.0)
- [Home Assistant Community Store](https://github.com/custom-components/hacs)
- Home Assistant >= 2024.1

The following table covers the Elasticsearch functionality used by the integration when configured against various versions of Elasticsearch:

| Elasticsearch Version | Time Series Datastreams | Datastreams       | Datastream Lifecycle Management | Index Lifecycle Management |
|-----------------------|-------------------------|-------------------|---------------------------------|----------------------------|
| `8.11.0`+             | ✅&nbsp;Supported       |                   | ✅&nbsp;Supported               |                            |
| `8.7.0` - `8.10.0`    | ✅&nbsp;Supported       |                   |                                 | ✅&nbsp;Supported          |
| `8.0.0` - `8.6.0`     |                         | ✅&nbsp;Supported |                                 | ✅&nbsp;Supported          |
| `7.13.0` - `7.17.0`   |                         | ✅&nbsp;Supported |                                 | ✅&nbsp;Supported          |
| `7.11.0` - `7.12.0`   |                         | ✅&nbsp;Supported |                                 | ⚠️ Partially Supported [See Note] |


!!! note
    Index Lifecycle Management is partially supported in versions `7.11.0` - `7.12.0`. The integration will create an ILM policy that performs time-based rollover but does not support shard-size-based rollover.

## Older versions

[Version `0.4.0`](https://github.com/legrego/homeassistant-elasticsearch/releases/tag/v0.4.0) includes support for older versions of Elasticsearch. No features or bugfixes will be backported to this version.