---
title: Introduction
---

# Elasticsearch Component for Home-Assistant

Publish Home Assistant events to your [Elasticsearch](https://elastic.co) cluster, and query them back into your automations!

Elasticsearch is a search and analytics engine for storing and exploring large amounts of data, and [Kibana](https://www.elastic.co/kibana) is its companion app for charts and dashboards. Sending your Home Assistant history there lets you keep it for as long as you choose, and analyze it across your whole home.

## Features

- Efficiently publishes Home-Assistant events to Elasticsearch using the Bulk API
- Automatically sets up Datastreams using Time Series Data Streams ("TSDS") and Datastream Lifecycle Management ("DLM")
- Supports Elastic's [stack security features](https://www.elastic.co/elastic-stack/security) via optional username, password, and API keys
- Selectively publish events based on labels, entities, devices, areas, or floors
- Run [ES|QL queries](querying.md) from automations and scripts with the `elasticsearch.query` action

## Compatibility

- Elasticsearch 8.14+, including 9.x (Self, [Cloud](https://www.elastic.co/cloud), or [Serverless](https://www.elastic.co/docs/current/serverless)). [Querying](querying.md#requirements) needs 8.19+, or 9.1+ on 9.x.
- [Elastic Common Schema version 1.0.0](https://github.com/elastic/ecs/releases/tag/v1.0.0)
- [Home Assistant Community Store](https://github.com/custom-components/hacs)
- Home Assistant >= 2026.10

## Older versions

[Version `1.0.0`](https://github.com/legrego/homeassistant-elasticsearch/releases/tag/v1.0.0) includes support for 7.11 to 8.13. No features or bugfixes will be backported to this version.
[Version `0.4.0`](https://github.com/legrego/homeassistant-elasticsearch/releases/tag/v0.4.0) includes support for versions of Elasticsearch older than 7.11. No features or bugfixes will be backported to this version.
