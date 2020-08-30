## Features
* Effeciently publishes Home-Assistant events to Elasticsearch using the Bulk API
* Automatically maintains Indexes and Index Templates using the Rollover API
* Supports [X-Pack Security](https://www.elastic.co/products/x-pack/security) via optional username and password
* Tracks the Elasticsearch cluster health in the `sensor.es_cluster_health` sensor
* Exclude specific entities or groups from publishing

## Compatability
* Elasticsearch 7.x (Self or [Cloud](https://www.elastic.co/cloud) hosted), with or without [X-Pack](https://www.elastic.co/products/x-pack).
* [Elastic Common Schema version 1.0.0](https://github.com/elastic/ecs/releases/tag/v1.0.0)

## Getting Started
The Elasticsearch component requires, well, [Elasticsearch](https://www.elastic.co/products/elasticsearch)!
This component will not host or configure Elasticsearch for you, but there are many ways to run your own cluster.
Elasticsearch is open source and free to use: just bring your own hardware!
Elastic has a [great setup guide](https://www.elastic.co/start) if you need help getting your first cluster up and running.

If you don't want to maintain your own cluster, then give the [Elastic Cloud](https://www.elastic.co/cloud) a try! There is a free trial available to get you started.

## Configuration
This is the bare-minimum configuration you need to get up-and-running:
```yaml
elastic:
    # URL should point to your Elasticsearch cluster
    url: http://localhost:9200
```

See https://github.com/legrego/homeassistant-elasticsearch for a complete list of configuration options.
