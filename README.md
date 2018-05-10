Elasticsearch Component for Home-Assistant
[![Build Status](https://travis-ci.org/legrego/homeassistant-elasticsearch.svg?branch=master)](https://travis-ci.org/legrego/homeassistant-elasticsearch)
=====

Publish HASS events to your [Elasticsearch](https://elastic.co) cluster!

## Features
* Effeciently publishes Home-Assistant events to Elasticsearch using the Bulk API
* Automatically maintains Indexes and Index Templates using the Rollover API
* Supports [X-Pack Security](https://www.elastic.co/products/x-pack/security) via optional username and password

## Compatability
* Elasticsearch 6.x (Self or [Cloud](https://www.elastic.co/cloud) hosted), with or without [X-Pack](https://www.elastic.co/products/x-pack).

## Getting Started
The Elasticsearch component requires, well, [Elasticsearch](https://www.elastic.co/products/elasticsearch)!
This component will not host or configure Elasticsearch for you, but there are many ways to run your own cluster.
Elasticsearch is open source and free to use: just bring your own hardware!
Elastic has a [great setup guide](https://www.elastic.co/start) if you need help getting your first cluster up and running.

If you don't want to maintain your own cluster, then give the [Elastic Cloud](https://www.elastic.co/cloud) a try! There is a free trial available to get you started.

## Installation
1. Copy `elastic.py` to your `$HASS_CONFIG/custom_components` directory, where `$HASS_CONFIG` is the location on your machine where Home-Assistant lives.
Example: `/home/pi/.homeassistant` and `/home/pi/.homeassistant/custom_components`. You may have to create the `custom_components` directory yourself.
2. Configure the component in `$HASS_CONFIG/configuration.yaml` (see Configuration section below)
3. Restart Home-Assistant

## Configuration
This is the bare-minimum configuration you need to get up-and-running:
```yaml
elastic:
    # URL should point to your Elasticsearch cluster
    url: http://localost:9200
```
### Configuration Variables
All variables are optional unless marked required.
#### Basic Configuration
- **url** (*Required*): The URL of your Elasticsearch cluster
- **username**: If your cluster is protected with Basic Authentication via [X-Pack Security](https://www.elastic.co/products/x-pack/security), then provide a username here
- **password**: If your cluster is protected with Basic Authentication via [X-Pack Security](https://www.elastic.co/products/x-pack/security), then provide a password here
#### Advanced Configuration
- **index_format** (*default:* `"hass-events"`): The format of all index names used by this component. The format specified will be used to derive the actual index names.
Actual names use the [Rollover API](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-rollover-index.html) convention of appending a 5-digit number to the end. e.g.: `hass-events-00001`
- **alias** (*default:* `"active-hass-index"`): The [index alias](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-aliases.html) which will always reference the index being written to.
- **publish_frequency** (*default:* `60`): Specifies how often, in seconds, this component should publish events to Elasticsearch.
- **request_rollover_frequency** (*default:* `3600`): Specifies how often, in seconds, this component should attempt a Rollover. The Rollover will only occur if the specified criteria has been met.
- **rollover_age** (*default:* `"7d"`): Specifies the `max_age` condition of the Rollover request
- **rollover_docs** (*default:* `15000`): Specifies the `max_docs` condition of the Rollover request
- **rollover_size** (*default:* `"5gb"`): Specifies the `max_size` condition of the Rollover request


## Support
This project is not endorsed or supported by either Elastic or Home-Assistant - please open a GitHub issue for any questions, bugs, or feature requests.
