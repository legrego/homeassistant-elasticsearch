# Advanced ingest configuration

!!! note

    This section describes advanced use cases. Most users will not need to customize their ingest configuration.

## Defining your own Index Mappings, Settings, and Ingest Pipeline

You can customize the mappings, settings and define an [ingest pipeline](https://www.elastic.co/guide/en/elasticsearch/reference/current/ingest.html) by creating a [component template](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-component-template.html) called `metrics-homeassistant@custom`

### Custom Ingest Pipeline

The following is an example on how to push your Home Assistant metrics into an ingest pipeline called `metrics-homeassistant-pipeline`:

=== "Dev Tools"
    Run these commands using Kibana's [Dev Tools console](https://www.elastic.co/guide/en/kibana/current/console-kibana.html):

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
            "mappings": {},
            "settings": {
                "index.default_pipeline": "metrics-homeassistant-pipeline"
            }
        }
    }
    ```

=== "curl"

    ```bash
    ES_URL=https://localhost:9200 # (1)
    ES_USER=elastic # (2)
    ES_PASSWORD=changeme # (3)
    curl -X PUT "$ES_URL/_ingest/pipeline/metrics-homeassistant-pipeline" \
        -u "$ES_USER":"$ES_PASSWORD" \
        -H "Content-Type: application/json" \
        -d'
        {
            "description": "Pipeline for HomeAssistant dataset",
            "processors": [ ]
        }
        ' # (4)

    curl -X PUT "$ES_URL/_component_template/metrics-homeassistant@custom" \
        -u "$ES_USER":"$ES_PASSWORD" \
        -H "Content-Type: application/json" \
        -d'
        {
            "template": {
                "mappings": {},
                "settings": {
                    "index.default_pipeline": "metrics-homeassistant-pipeline"
                }
            }
        }
        '
    ```

    1. Replace `https://localhost:9200` with the URL of your Elasticsearch instance
    2. Replace `elastic` with your Elasticsearch username
    3. Replace `changeme` with your Elasticsearch password
    4. Add your ingest pipeline processors to the `processors` array

Component template changes apply when the datastream performs a rollover so the first time you modify the template you may need to manually initiate index/datastream rollover to start applying the pipeline.

### Drop attributes to reduce storage

If you only need entity states and metadata, you can remove [state attributes](published_fields.md#state-attributes) before Elasticsearch stores them. The following pipeline keeps attributes for `sensor` entities and removes them for all other domains. Entity values, names, labels, device details, areas, and floors are preserved.

Run these commands in Kibana's Dev Tools console. Creating the pipeline requires the `manage_pipeline` cluster privilege; the API key in the [configuration guide](configure.md#credentials) does not include this privilege. Use an account with permission to manage pipelines and index templates for this setup.

#### Create the pipeline

```
PUT _ingest/pipeline/metrics-homeassistant-pipeline
{
    "description": "Remove attributes from non-sensor Home Assistant entities",
    "processors": [
        {
            "dot_expander": {
                "field": "*"
            }
        },
        {
            "remove": {
                "field": "hass.entity.attributes",
                "ignore_missing": true,
                "if": "ctx.hass?.entity?.domain != 'sensor'"
            }
        }
    ]
}
```

The integration publishes dotted field names such as `hass.entity.attributes.temperature`. The [`dot_expander` processor](https://www.elastic.co/guide/en/elasticsearch/reference/8.14/dot-expand-processor.html) expands all top-level dotted fields into objects so the [`remove` processor](https://www.elastic.co/docs/reference/ingest-processor/remove-processor) can remove the entire attributes object. The stored document uses nested objects after expansion; the field paths used in Kibana stay the same.

The condition keeps attributes for the `sensor` domain. To remove attributes from every domain, delete the `if` property and its preceding comma. `ignore_missing` allows documents without attributes to pass through successfully.

If you already use `metrics-homeassistant-pipeline`, add these processors to its existing `processors` array instead of replacing the pipeline. Put the expansion step before processors that access nested fields, and remove attributes after any processors that need them.

#### Test with sample documents

Use the [simulate pipeline API](https://www.elastic.co/guide/en/elasticsearch/reference/8.14/ingest.html#test-pipeline) to check the result without indexing documents:

```
POST _ingest/pipeline/metrics-homeassistant-pipeline/_simulate
{
    "docs": [
        {
            "_source": {
                "hass.entity.id": "climate.living_room",
                "hass.entity.domain": "climate",
                "hass.entity.value": "heat",
                "hass.entity.valueas.string": "heat",
                "hass.entity.attributes.temperature": 21,
                "hass.entity.attributes.hvac_action": "heating"
            }
        },
        {
            "_source": {
                "hass.entity.id": "sensor.living_room_temperature",
                "hass.entity.domain": "sensor",
                "hass.entity.value": "21.5",
                "hass.entity.valueas.float": 21.5,
                "hass.entity.attributes.battery_level": 95
            }
        },
        {
            "_source": {
                "hass.entity.id": "switch.desk_lamp",
                "hass.entity.domain": "switch",
                "hass.entity.value": "on",
                "hass.entity.valueas.boolean": true
            }
        }
    ]
}
```

Inspect `docs[].doc._source` in the response:

- The climate document has no `hass.entity.attributes` object, while its `value` and `valueas.string` fields remain.
- The sensor document keeps `hass.entity.attributes.battery_level`.
- The switch document succeeds even though it has no attributes.

If you remove the condition to drop attributes from every domain, the sensor document should also lose its attributes.

#### Apply the pipeline to incoming events

Attach the pipeline using the `metrics-homeassistant@custom` component template, as in [Custom Ingest Pipeline](#custom-ingest-pipeline):

```
PUT _component_template/metrics-homeassistant@custom
{
    "template": {
        "settings": {
            "index.default_pipeline": "metrics-homeassistant-pipeline"
        }
    }
}
```

If this component template already contains custom mappings or settings, keep them in the request too: `PUT` replaces the component template rather than merging with it.

New data streams use the updated template automatically. For existing streams, the setting takes effect on backing indices created after a rollover. List the streams, then roll over each stream where you want to apply the pipeline. For example:

```
GET _data_stream/metrics-homeassistant.*-default
```

```
POST metrics-homeassistant.climate-default/_rollover
```

Replace `metrics-homeassistant.climate-default` with each relevant name from the list. If a stream's write index already uses this pipeline, changing the pipeline's processors does not require another rollover.

This reduces stored attributes for future events. It does not change existing documents or reduce the data sent from Home Assistant to Elasticsearch. To keep attributes again, remove the `remove` processor from the pipeline; previously discarded attributes cannot be restored from Elasticsearch.

### Custom Attribute mappings

Attributes are mapped as text with a `.keyword` subfield by default. To use an attribute in numeric aggregations, define a custom mapping. The following example maps `hass.entity.attributes.temperature` as a float:

=== "Dev Tools"
    Run these commands using Kibana's [Dev Tools console](https://www.elastic.co/guide/en/kibana/current/console-kibana.html):

    ```
    PUT /_component_template/metrics-homeassistant@custom
    {
        "template": {
            "mappings": {
                "properties": {
                    "hass.entity.attributes": {
                        "type": "object",
                        "properties": {
                            "temperature": {
                                "type": "float",
                                "ignore_malformed": true
                            }
                        }
                    }
                }
            }
        }
    }
    ```

=== "curl"

    ```bash
    ES_URL=https://localhost:9200 # (1)
    ES_USER=elastic # (2)
    ES_PASSWORD=changeme # (3)

    curl -X PUT "$ES_URL/_component_template/metrics-homeassistant@custom" \
        -u "$ES_USER":"$ES_PASSWORD" \
        -H "Content-Type: application/json" \
        -d'
        {
            "template": {
                "mappings": {
                    "properties": {
                        "hass.entity.attributes": {
                            "type": "object",
                            "properties": {
                                "temperature": {
                                    "type": "float",
                                    "ignore_malformed": true
                                }
                            }
                        }
                    }
                }
            }
        }
        '
    ```

    1. Replace `https://localhost:9200` with the URL of your Elasticsearch instance
    2. Replace `elastic` with your Elasticsearch username
    3. Replace `changeme` with your Elasticsearch password
    4. Modify the body of the component template to include desired mappings
