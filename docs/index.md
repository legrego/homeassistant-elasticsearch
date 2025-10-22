---
title: Introduction
---

# Elasticsearch Component for Home-Assistant

Publish Home Assistant events to your [Elasticsearch](https://elastic.co) cluster!

## Features

- Efficiently publishes Home-Assistant events to Elasticsearch using the Bulk API
- Automatically sets up Datastreams using Time Series Data Streams ("TSDS") and Datastream Lifecycle Management ("DLM")
- Supports Elastic's [stack security features](https://www.elastic.co/elastic-stack/security) via optional username, password, and API keys
- Selectively publish events based on labels, entities, devices, or areas

## Compatibility

- Elasticsearch 8.14+ (Self, [Cloud](https://www.elastic.co/cloud), or [Serverless](https://www.elastic.co/docs/current/serverless)).
- [Elastic Common Schema version 1.0.0](https://github.com/elastic/ecs/releases/tag/v1.0.0)
- [Home Assistant Community Store](https://github.com/custom-components/hacs)
- Home Assistant >= 2025.6

## Older versions

[Version `1.0.0`](https://github.com/legrego/homeassistant-elasticsearch/releases/tag/v1.0.0) includes support for 7.11 to 8.13. No features or bugfixes will be backported to this version.
[Version `0.4.0`](https://github.com/legrego/homeassistant-elasticsearch/releases/tag/v0.4.0) includes support for versions of Elasticsearch older than 7.11. No features or bugfixes will be backported to this version.
