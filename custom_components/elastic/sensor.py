"""
Sensors for the Elastic component.

"""
import logging
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Union
from homeassistant.const import DEVICE_CLASS_BATTERY
from homeassistant.components.sensor import ENTITY_ID_FORMAT
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.config_entries import ConfigEntry

from .es_doc_publisher import DocumentPublisher
from .const import DOMAIN, CONF_HEALTH_SENSOR_ENABLED, CONF_PUBLISH_ENABLED
from .utils import get_merged_config

LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ["elastic"]

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistantType,
    config_entry: ConfigEntry,
    async_add_entiries: Callable[[List[Entity], bool], None],
):
    """ Setup Elastic sensors"""

    devices = []

    config = get_merged_config(config_entry)

    es_integration = hass.data[DOMAIN]

    if config.get(CONF_HEALTH_SENSOR_ENABLED):
        LOGGER.info("Initializing cluster health sensor")
        devices.append(EsClusterHealthSensor(config_entry, es_integration.gateway))
    else:
        LOGGER.info("Cluster health sensor not enabled")

    if config.get(CONF_PUBLISH_ENABLED):
        LOGGER.info("Initializing publish queue sensor")
        devices.append(EsPublishQueueSensor(config_entry, es_integration.publisher))
    else:
        LOGGER.info("Publish queue sensor not enabled")

    if devices:
        LOGGER.debug(str.format("Adding {} devices", len(devices)))
        async_add_entiries(devices, True)
    else:
        LOGGER.debug("Not registering any devices")


class EsBaseSensor(Entity):
    """ Base Sensor """

    def __init__(self, config_entry: ConfigEntry):
        self.config_entry = config_entry

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self.config_entry.entry_id)}}


class EsPublishQueueSensor(EsBaseSensor):
    """Representation of the publish queue sensor"""

    def __init__(self, config_entry: ConfigEntry, publisher: DocumentPublisher):
        super().__init__(config_entry)
        self._publisher = publisher
        self.current_value = None
        self.attr = {}
        self.entity_id = ENTITY_ID_FORMAT.format("es_publish_queue")

    # As per the sensor, this must be a unique value within this domain.
    @property
    def unique_id(self):
        """Return Unique ID string."""
        return self.entity_id

    @property
    def name(self):
        """Return the display name."""
        return "Publish Queue Size"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.current_value

    @property
    def device_state_attributes(self):
        """Return the state attributes"""
        return self.attr

    def update(self):
        """Update the state from the sensor."""
        LOGGER.debug("Updating Elasticsearch queue stats")
        self.current_value = self._publisher.queue_size()
        self.attr = {"last_publish_time": self._publisher.last_publish_time()}


class EsClusterHealthSensor(EsBaseSensor):
    """Representation of the Cluster Health sensor."""

    def __init__(self, config_entry: ConfigEntry, gateway):
        """Initialize the sensor."""
        super().__init__(config_entry)
        self.current_value = None
        self._latest_cluster_health = {}
        self._gateway = gateway

        self.entity_id = ENTITY_ID_FORMAT.format("es_cluster_health")

    # As per the sensor, this must be a unique value within this domain.
    @property
    def unique_id(self):
        """Return Unique ID string."""
        return self.entity_id

    @property
    def name(self):
        """Return the display name."""
        return "Cluster Health Sensor"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.current_value

    @property
    def device_state_attributes(self):
        """Return the state attributes"""
        return self._latest_cluster_health

    async def async_update(self):
        """Update the state from the sensor."""
        LOGGER.debug("Updating Elasticsearch cluster health")
        self._latest_cluster_health = await self._gateway.get_client().cluster.health()
        self.current_value = self._latest_cluster_health["status"]
