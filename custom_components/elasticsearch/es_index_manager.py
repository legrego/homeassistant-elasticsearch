""" Index management facilities """
import json
import os

from homeassistant.const import CONF_ALIAS

from .const import (
    CONF_ILM_DELETE_AFTER,
    CONF_ILM_ENABLED,
    CONF_ILM_MAX_SIZE,
    CONF_ILM_POLICY_NAME,
    CONF_INDEX_FORMAT,
    CONF_PUBLISH_ENABLED,
    INDEX_TEMPLATE_NAME,
    VERSION_SUFFIX,
)
from .logger import LOGGER


class IndexManager:
    """ Index management facilities """

    def __init__(self, hass, config, gateway):
        """ Initializes index management """

        self._config = config

        if not config.get(CONF_PUBLISH_ENABLED):
            return

        self.index_alias = config.get(CONF_ALIAS) + VERSION_SUFFIX

        self._hass = hass

        self._gateway = gateway

        self._ilm_policy_name = config.get(CONF_ILM_POLICY_NAME)

        self._index_format = config.get(CONF_INDEX_FORMAT) + VERSION_SUFFIX

        self._using_ilm = True

    async def async_setup(self):
        """ Performs setup for index management. """
        if not self._config.get(CONF_PUBLISH_ENABLED):
            return
        self._using_ilm = self._config.get(CONF_ILM_ENABLED)

        await self._create_index_template()

        if self._using_ilm:
            await self._create_ilm_policy(self._config)

        LOGGER.debug("Index Manager initialized")

    async def _create_index_template(self):
        """
        Initializes the Elasticsearch cluster with an index template, initial index, and alias.
        """
        from elasticsearch.exceptions import ElasticsearchException

        client = self._gateway.get_client()

        with open(
            os.path.join(os.path.dirname(__file__), "index_mapping.json")
        ) as json_file:
            mapping = json.load(json_file)

        if not await client.indices.exists_template(name=INDEX_TEMPLATE_NAME):
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
                index_template["settings"][
                    "index.lifecycle.name"
                ] = self._ilm_policy_name
                index_template["settings"][
                    "index.lifecycle.rollover_alias"
                ] = self.index_alias

            try:
                await client.indices.put_template(
                    name=INDEX_TEMPLATE_NAME, body=index_template
                )
            except ElasticsearchException as err:
                LOGGER.exception("Error creating index template: %s", err)

        if not await client.indices.exists_alias(name=self.index_alias):
            LOGGER.debug("Creating initial index and alias")
            try:
                await client.indices.create(
                    index=self._index_format + "-000001",
                    body={"aliases": {self.index_alias: {"is_write_index": True}}},
                )
            except ElasticsearchException as err:
                LOGGER.exception("Error creating initial index/alias: %s", err)
        elif self._using_ilm:
            LOGGER.debug("Ensuring ILM Policy is attached to existing index")
            try:
                await client.indices.put_settings(
                    index=self.index_alias,
                    preserve_existing=True,
                    body={
                        "index.lifecycle.name": self._ilm_policy_name,
                        "index.lifecycle.rollover_alias": self.index_alias,
                    },
                )
            except ElasticsearchException as err:
                LOGGER.exception("Error updating index ILM settings: %s", err)

    async def _create_ilm_policy(self, config):
        """
        Creates the index lifecycle management policy.
        """
        from elasticsearch.exceptions import TransportError

        client = self._gateway.get_client()

        try:
            existing_policy = await client.ilm.get_lifecycle(self._ilm_policy_name)
        except TransportError as err:
            if err.status_code == 404:
                existing_policy = None
            else:
                LOGGER.exception("Error checking for existing ILM policy: %s", err)
                raise err

        ilm_hot_conditions = {"max_size": config.get(CONF_ILM_MAX_SIZE)}

        policy = {
            "policy": {
                "phases": {
                    "hot": {
                        "min_age": "0ms",
                        "actions": {"rollover": ilm_hot_conditions},
                    },
                    "delete": {
                        "min_age": config.get(CONF_ILM_DELETE_AFTER),
                        "actions": {"delete": {}},
                    },
                }
            }
        }

        if existing_policy:
            LOGGER.info("Updating existing ILM Policy '%s'", self._ilm_policy_name)
        else:
            LOGGER.info("Creating ILM Policy '%s'", self._ilm_policy_name)

        await client.ilm.put_lifecycle(self._ilm_policy_name, policy)
