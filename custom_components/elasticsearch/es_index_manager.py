"""Index management facilities."""

import json
import os

from elasticsearch7 import ElasticsearchException
from homeassistant.const import CONF_ALIAS

from custom_components.elasticsearch.errors import ElasticException
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

        if not self._gateway.es_version.meets_minimum_version(major=8, minor=7):
            raise ElasticException(
                "A version of Elasticsearch that is not compatible with TSDS datastreams detected (%s). Use Legacy Index mode.",
                f"{self._gateway.es_version.major}.{self._gateway.es_version.minor}",
            )

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

        # For Datastream mode we do not offer configuration wtihin Home Assistant for the ILM policy
        if not self._gateway.es_version.meets_minimum_version(major=8, minor=11):
            LOGGER.debug("Running pre-8.10, using Index Lifecycle Management")
            await self._create_basic_ilm_policy(
                ilm_policy_name=DATASTREAM_METRICS_ILM_POLICY_NAME
            )

            LOGGER.debug("Inserting ILM Policy into Index Template: ")

            del index_template["template"]["lifecycle"]

            index_template["template"]["settings"]["index.lifecycle.name"] = (
                DATASTREAM_METRICS_ILM_POLICY_NAME
            )
        else:
            LOGGER.debug("Running 8.10+, using Datastream Lifecycle Management")

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
                LOGGER.exception("Error creating index template: %s", err)

                # Our template doesn't exist and we failed to create one, so we should not proceed
                raise err

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
                LOGGER.exception("Error checking for existing ILM policy: %s", err)
                raise err

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
                                "max_primary_shard_size": "50gb",
                            },
                        },
                    },
                    "delete": {"min_age": "365d", "actions": {"delete": {}}},
                }
            }
        }

        LOGGER.info("Creating ILM Policy '%s'", ilm_policy_name)

        await client.ilm.put_lifecycle(ilm_policy_name, policy)
