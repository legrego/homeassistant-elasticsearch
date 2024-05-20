"""Index management facilities."""

import json
import os

from elasticsearch7 import ElasticsearchException
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ALIAS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.elasticsearch.errors import ElasticException, convert_es_error
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway

from .const import (
    CAPABILITIES,
    CONF_ILM_ENABLED,
    CONF_ILM_POLICY_NAME,
    CONF_INDEX_FORMAT,
    CONF_INDEX_MODE,
    CONF_PUBLISH_ENABLED,
    DATASTREAM_DATASET_PREFIX,
    DATASTREAM_METRICS_ILM_POLICY_NAME,
    DATASTREAM_METRICS_INDEX_TEMPLATE_NAME,
    DATASTREAM_TYPE,
    DOMAIN,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    LEGACY_TEMPLATE_NAME,
    VERSION_SUFFIX,
)
from .logger import LOGGER


class IndexManager:
    """Index management facilities."""

    def __init__(
        self,
        hass: HomeAssistant,
        gateway: ElasticsearchGateway,
        config_entry: ConfigEntry,
    ):
        """Initialize index management."""

        if not config_entry.options.get(CONF_PUBLISH_ENABLED):
            return

        self._hass = hass
        self._gateway: ElasticsearchGateway = gateway

        self.index_mode = config_entry.data.get(CONF_INDEX_MODE)
        self.publish_enabled = config_entry.options.get(CONF_PUBLISH_ENABLED)

        if self.index_mode == INDEX_MODE_LEGACY:
            self.index_alias = config_entry.options.get(CONF_ALIAS) + VERSION_SUFFIX
            self.ilm_policy_name = config_entry.options.get(CONF_ILM_POLICY_NAME)
            self.index_format = config_entry.options.get(CONF_INDEX_FORMAT) + VERSION_SUFFIX
            self._using_ilm = config_entry.options.get(CONF_ILM_ENABLED)

            ir.async_create_issue(
                hass,
                domain=DOMAIN,
                issue_id="datastream_migration",
                issue_domain=DOMAIN,
                is_fixable=False,
                is_persistent=True,
                learn_more_url="https://github.com/legrego/homeassistant-elasticsearch/wiki/Migrating-from-Legacy-Indices-to-Datastreams",
                severity=ir.IssueSeverity.WARNING,
                translation_key="datastream_migration",
            )
        elif self.index_mode == "datastream":
            pass

        else:
            raise ElasticException("Unexpected index_mode: %s", self.index_mode)

    async def async_setup(self):
        """Perform setup for index management."""
        if not self.publish_enabled:
            return

        if self.index_mode == INDEX_MODE_LEGACY:
            self._using_ilm = self._using_ilm

            await self._create_legacy_template()

        else:
            await self._create_index_template()

        LOGGER.debug("Index Manager initialized")

    async def _create_index_template(self):
        """Initialize the Elasticsearch cluster with an index template, initial index, and alias."""
        LOGGER.debug("Initializing modern index templates")

        client = self._gateway.client

        # Open datastreams/index_template.json and load the ES modern index template
        with open(
            os.path.join(os.path.dirname(__file__), "datastreams", "index_template.json"),
            encoding="utf-8",
        ) as json_file:
            index_template = json.load(json_file)

        # Check if the index template already exists
        matching_templates = await client.indices.get_index_template(name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME, ignore=[404])
        matching_templates_count = len(matching_templates.get("index_templates", []))

        template_exists = matching_templates and matching_templates_count > 0

        LOGGER.debug("got template response: " + str(template_exists))

        if template_exists:
            LOGGER.debug("Updating index template")
        else:
            LOGGER.debug("Creating index template")

        if self._gateway.has_capability(CAPABILITIES.TIMESERIES_DATASTREAM):
            LOGGER.debug("Elasticsearch supports timeseries datastreams, including in template.")

            index_template["template"]["settings"]["index.mode"] = "time_series"

            mappings = index_template["template"]["mappings"]
            object_id = mappings["properties"]["hass"]["properties"]["object_id"]

            object_id["time_series_dimension"] = True

        if self._gateway.has_capability(CAPABILITIES.IGNORE_MISSING_COMPONENT_TEMPLATES):
            LOGGER.debug("Elasticsearch supports ignore_missing_component_templates, including in template.")

            index_template["composed_of"] = ["metrics-homeassistant@custom"]
            index_template["ignore_missing_component_templates"] = ["metrics-homeassistant@custom"]

        if self._gateway.has_capability(CAPABILITIES.DATASTREAM_LIFECYCLE_MANAGEMENT):
            LOGGER.debug("Elasticsearch supports Datastream Lifecycle Management, including in template.")
            index_template["template"]["lifecycle"] = {"data_retention": "365d"}
        else:
            LOGGER.debug("Elasticsearch does not support Datastream Lifecycle Management, falling back to Index Lifecycle Management.")
            await self._create_basic_ilm_policy(ilm_policy_name=DATASTREAM_METRICS_ILM_POLICY_NAME)

            index_template["template"]["settings"]["index.lifecycle.name"] = DATASTREAM_METRICS_ILM_POLICY_NAME

        try:
            await client.indices.put_index_template(name=DATASTREAM_METRICS_INDEX_TEMPLATE_NAME, body=index_template)

        except ElasticsearchException as err:
            LOGGER.exception("Error creating/updating index template: %s", err)
            if not template_exists:
                raise convert_es_error(
                    "No index template present in Elasticsearch and failed to create one",
                    err,
                ) from err
        try:
            if await self.requires_datastream_ignore_dynamic_fields_migration():
                LOGGER.debug("Performing a one-time migration of datastream write indices to set dynamic=false.")
                await self.migrate_datastreams_to_ignore_dynamic_fields()

        except ElasticsearchException as err:
            raise convert_es_error(err)

    async def _create_legacy_template(self):
        """Initialize the Elasticsearch cluster with an index template, initial index, and alias."""

        LOGGER.debug("Initializing legacy index templates")

        if self._gateway.has_capability(CAPABILITIES.SERVERLESS):
            raise ElasticException("Serverless environment detected, legacy index usage not allowed in ES Serverless. Switch to datastreams.")

        client = self._gateway.client

        # For Legacy mode we offer flexible configuration of the ILM policy
        await self._create_basic_ilm_policy(ilm_policy_name=self.ilm_policy_name)

        with open(
            os.path.join(os.path.dirname(__file__), "index_mapping.json"),
            encoding="utf-8",
        ) as json_file:
            mapping = json.load(json_file)

        LOGGER.debug("checking if template exists")

        template = await client.indices.get_template(name=LEGACY_TEMPLATE_NAME, ignore=[404])

        LOGGER.debug("got template response: " + str(template))
        template_exists = template and LEGACY_TEMPLATE_NAME in template

        if not template_exists:
            LOGGER.debug("Creating index template")

            index_template = {
                "index_patterns": [self.index_format + "*"],
                "settings": {
                    "number_of_shards": 1,
                    "codec": "best_compression",
                    "mapping": {"total_fields": {"limit": "10000"}},
                },
                "mappings": mapping,
                "aliases": {"all-hass-events": {}},
            }
            if self._using_ilm:
                index_template["settings"]["index.lifecycle.name"] = self.ilm_policy_name
                index_template["settings"]["index.lifecycle.rollover_alias"] = self.index_alias

            try:
                await client.indices.put_template(name=LEGACY_TEMPLATE_NAME, body=index_template)
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
                    index=self.index_format + "-000001",
                    body={"aliases": {self.index_alias: {"is_write_index": True}}},
                )
            except ElasticsearchException as err:
                LOGGER.exception("Error creating initial index/alias: %s", err)

    async def _create_basic_ilm_policy(self, ilm_policy_name):
        """Create the index lifecycle management policy."""
        from elasticsearch7.exceptions import TransportError

        client = self._gateway.client

        try:
            existing_policy = await client.ilm.get_lifecycle(ilm_policy_name)
        except TransportError as err:
            if err.status_code == 404:
                existing_policy = None
            else:
                raise convert_es_error("Unexpected return code when checking for existing ILM policy", err) from err
        except ElasticsearchException as err:
            raise convert_es_error("Error checking for existing ILM policy", err) from err

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

        if self._gateway.has_capability(CAPABILITIES.MAX_PRIMARY_SHARD_SIZE):
            LOGGER.debug("Elasticsearch supports max_primary_shard_size, including in ILM template.")
            policy["policy"]["phases"]["hot"]["actions"]["rollover"]["max_primary_shard_size"] = "50gb"

        LOGGER.info("Creating ILM Policy '%s'", ilm_policy_name)
        try:
            await client.ilm.put_lifecycle(ilm_policy_name, policy)
        except ElasticsearchException as err:
            raise convert_es_error("Error creating initial ILM policy", err) from err

    async def requires_datastream_ignore_dynamic_fields_migration(self):
        """Check if datastreams need to be migrated to ignore dynamic fields."""
        if self.index_mode != INDEX_MODE_DATASTREAM:
            return False

        client = self._gateway.client

        try:
            mappings = await client.indices.get_mapping(index=DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX + ".*")
        except ElasticsearchException as err:
            raise convert_es_error("Error checking datastream mapping for dynamic fields", err) from err

        for _index, mapping in mappings.items():
            if mapping["mappings"].get("dynamic") == "strict":
                return True

        return False

    async def migrate_datastreams_to_ignore_dynamic_fields(self):
        """Migrate datastreams to ignore dynamic fields."""
        if self.index_mode != INDEX_MODE_DATASTREAM:
            return

        client = self._gateway.client

        try:
            await client.indices.put_mapping(
                index=DATASTREAM_TYPE + "-" + DATASTREAM_DATASET_PREFIX + ".*",
                body={
                    "dynamic": "false",
                },
                allow_no_indices=True,
                write_index_only=True,
            )
        except ElasticsearchException as err:
            raise convert_es_error("Error migrating datastream to ignore dynamic fields", err) from err
