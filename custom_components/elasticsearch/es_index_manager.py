"""Index management facilities."""

import json
import os

from elasticsearch7 import ElasticsearchException
from homeassistant.const import CONF_ALIAS

from custom_components.elasticsearch.errors import ElasticException, convert_es_error
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

from .const import (
    CONF_DATASTREAM_NAME_PREFIX,
    CONF_DATASTREAM_NAMESPACE,
    CONF_DATASTREAM_TYPE,
    CONF_ILM_ENABLED,
    CONF_ILM_POLICY_NAME,
    CONF_INDEX_FORMAT,
    CONF_INDEX_MODE,
    CONF_PUBLISH_ENABLED,
    DATASTREAM_METRICS_ILM_POLICY_NAME,
    DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    LEGACY_TEMPLATE_NAME,
    VERSION_SUFFIX,
)
from .logger import LOGGER


class IndexManager:
    """Index management facilities."""

    def __init__(self, hass, config, gateway):
        """Initialize index management."""

        self._config = config

        if not config.get(CONF_PUBLISH_ENABLED):
            return

        self._hass = hass

        self._gateway: ElasticsearchGateway = gateway

        # Differentiate between index and datastream

        self.index_mode = config.get(CONF_INDEX_MODE)

        if self.index_mode == INDEX_MODE_LEGACY:
            self.index_alias = config.get(CONF_ALIAS) + VERSION_SUFFIX
            self._ilm_policy_name = config.get(CONF_ILM_POLICY_NAME)
            self._index_format = config.get(CONF_INDEX_FORMAT) + VERSION_SUFFIX
            self._using_ilm = config.get(CONF_ILM_ENABLED)
        elif self.index_mode == INDEX_MODE_DATASTREAM:
            self.datastream_type = config.get(CONF_DATASTREAM_TYPE)
            self.datastream_name_prefix = config.get(CONF_DATASTREAM_NAME_PREFIX)
            self.datastream_namespace = config.get(CONF_DATASTREAM_NAMESPACE)
        else:
            raise ElasticException("Unexpected index_mode: %s", self.index_mode)

    async def async_setup(self):
        """Perform setup for index management."""
        if not self._config.get(CONF_PUBLISH_ENABLED):
            return

        if self.index_mode == INDEX_MODE_LEGACY:
            self._using_ilm = self._config.get(CONF_ILM_ENABLED)

            await self._create_legacy_template()

        else:
            await self._create_index_template()

        LOGGER.debug("Index Manager initialized")

    async def _create_index_template(self):
        """Initialize the Elasticsearch cluster with an index template, initial index, and alias."""
        LOGGER.debug("Initializing modern index templates")

        client = self._gateway.get_client()

        # Open datastreams/index_template.json and load the ES modern index template
        with open(
            os.path.join(
                os.path.dirname(__file__), "datastreams", "index_template.json"
            ),
            encoding="utf-8",
        ) as json_file:
            index_template = json.load(json_file)

        # Check if the index template already exists
        matching_templates = await client.indices.get_index_template(
            name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME, ignore=[404]
        )
        matching_templates_count = len(matching_templates.get("index_templates", []))

        template_exists = matching_templates and matching_templates_count > 0

        LOGGER.debug("got template response: " + str(template_exists))

        if template_exists:
            LOGGER.debug("Updating index template")
        else:
            LOGGER.debug("Creating index template")

        if self._gateway.es_version.supports_timeseries_datastream():
            LOGGER.debug(
                "Elasticsearch supports timeseries datastreams, including in template."
            )

            index_template["template"]["settings"]["index.mode"] = "time_series"

            mappings = index_template["template"]["mappings"]
            object_id = mappings["properties"]["hass"]["properties"]["object_id"]

            object_id["time_series_dimension"] = True

        if self._gateway.es_version.supports_ignore_missing_component_templates():
            LOGGER.debug(
                "Elasticsearch supports ignore_missing_component_templates, including in template."
            )

            index_template["composed_of"] = ["metrics-homeassistant@custom"]
            index_template["ignore_missing_component_templates"] = [
                "metrics-homeassistant@custom"
            ]

        if self._gateway.es_version.supports_datastream_lifecycle_management():
            LOGGER.debug(
                "Elasticsearch supports Datastream Lifecycle Management, including in template."
            )
            index_template["template"]["lifecycle"] = {"data_retention": "365d"}
        else:
            LOGGER.debug(
                "Elasticsearch does not support Datastream Lifecycle Management, falling back to Index Lifecycle Management."
            )
            await self._create_basic_ilm_policy(
                ilm_policy_name=DATASTREAM_METRICS_ILM_POLICY_NAME
            )

            index_template["template"]["settings"]["index.lifecycle.name"] = (
                DATASTREAM_METRICS_ILM_POLICY_NAME
            )

        try:
            await client.indices.put_index_template(
                name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME, body=index_template
            )

        except ElasticsearchException as err:
            LOGGER.exception("Error creating/updating index template: %s", err)
            # We do not want to proceed with indexing if we don't have any index templates as this
            # will result in the user having to clean-up indices with improper mappings.
            if not template_exists:
                raise err

    async def _create_legacy_template(self):
        """Initialize the Elasticsearch cluster with an index template, initial index, and alias."""

        LOGGER.debug("Initializing legacy index templates")

        if self._gateway.es_version.is_serverless():
            raise ElasticException(
                "Serverless environment detected, legacy index usage not allowed in ES Serverless. Switch to datastreams."
            )

        client = self._gateway.get_client()

        # For Legacy mode we offer flexible configuration of the ILM policy
        await self._create_basic_ilm_policy(ilm_policy_name=self._ilm_policy_name)

        with open(
            os.path.join(os.path.dirname(__file__), "index_mapping.json"),
            encoding="utf-8",
        ) as json_file:
            mapping = json.load(json_file)

        LOGGER.debug("checking if template exists")

        template = await client.indices.get_template(
            name=LEGACY_TEMPLATE_NAME, ignore=[404]
        )

        LOGGER.debug("got template response: " + str(template))
        template_exists = template and LEGACY_TEMPLATE_NAME in template

        if not template_exists:
            LOGGER.debug("Creating index template")

            index_template = {
                "index_patterns": [self._index_format + "*"],
                "settings": {
                    "number_of_shards": 1,
                    "codec": "best_compression",
                    "mapping": {"total_fields": {"limit": "10000"}},
                },
                "mappings": mapping,
                "aliases": {"all-hass-events": {}},
            }
            if self._using_ilm:
                index_template["settings"]["index.lifecycle.name"] = (
                    self._ilm_policy_name
                )
                index_template["settings"]["index.lifecycle.rollover_alias"] = (
                    self.index_alias
                )

            try:
                await client.indices.put_template(
                    name=LEGACY_TEMPLATE_NAME, body=index_template
                )
            except ElasticsearchException as err:
                raise convert_es_error(
                    "No index template present in Elasticsearch and failed to create one",
                    err,
                ) from err

        alias = await client.indices.get_alias(name=self.index_alias, ignore=[404])
        alias_exists = alias and not alias.get("error")
        if not alias_exists:
            LOGGER.debug("Creating initial index and alias")
            try:
                await client.indices.create(
                    index=self._index_format + "-000001",
                    body={"aliases": {self.index_alias: {"is_write_index": True}}},
                )
            except ElasticsearchException as err:
                LOGGER.exception("Error creating initial index/alias: %s", err)

    async def _create_basic_ilm_policy(self, ilm_policy_name):
        """Create the index lifecycle management policy."""
        from elasticsearch7.exceptions import TransportError

        client = self._gateway.get_client()

        try:
            existing_policy = await client.ilm.get_lifecycle(ilm_policy_name)
        except TransportError as err:
            if err.status_code == 404:
                existing_policy = None
            else:
                raise convert_es_error(
                    "Unexpected return code when checking for existing ILM policy", err
                ) from err
        except ElasticsearchException as err:
            raise convert_es_error(
                "Error checking for existing ILM policy", err
            ) from err

        if existing_policy:
            LOGGER.info("Found existing ILM Policy, do nothing '%s'", ilm_policy_name)
            return

        policy = {
            "policy": {
                "phases": {
                    "hot": {
                        "min_age": "0ms",
                        "actions": {
                            "rollover": {
                                "max_age": "30d",
                            },
                        },
                    },
                    "delete": {"min_age": "365d", "actions": {"delete": {}}},
                }
            }
        }

        if self._gateway.es_version.supports_max_primary_shard_size():
            LOGGER.debug(
                "Elasticsearch supports max_primary_shard_size, including in ILM template."
            )
            policy["policy"]["phases"]["hot"]["actions"]["rollover"][
                "max_primary_shard_size"
            ] = "50gb"

        LOGGER.info("Creating ILM Policy '%s'", ilm_policy_name)
        try:
            await client.ilm.put_lifecycle(ilm_policy_name, policy)
        except ElasticsearchException as err:
            raise convert_es_error("Error creating initial ILM policy", err) from err
