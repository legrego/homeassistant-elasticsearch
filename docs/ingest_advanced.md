# Advanced ingest configuration

!!! note

    This section describes advanced use cases. Most users will not need to customize their ingest configuration.

## Defining your own Index Mappings, Settings, and Ingest Pipeline

You can customize the mappings, settings and define an [ingest pipeline](https://www.elastic.co/guide/en/elasticsearch/reference/current/ingest.html) by creating a [component template](https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-component-template.html) called `metrics-homeassistant@custom`


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
            "mappings": {}
            "settings": {
                "index.default_pipeline": "metrics-homeassistant-pipeline",
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
        -u "$ES_USER":"ES_PASSWORD" \
        -H "Content-Type: application/json" \
        -d'
        {
            "description": "Pipeline for HomeAssistant dataset",
            "processors": [ ]
        }
        ' # (4)

    curl -X PUT "$ES_URL/_component_template/metrics-homeassistant@custom" \
        -u "$ES_USER":"ES_PASSWORD" \
        -H "Content-Type: application/json" \
        -d'
        {
            "template": {
                "mappings": {}
                "settings": {
                    "index.default_pipeline": "metrics-homeassistant-pipeline",
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