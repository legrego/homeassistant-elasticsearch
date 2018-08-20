"""
Sensors for the Elastic component.

"""
from datetime import timedelta
import logging

from homeassistant.components.sensor import ENTITY_ID_FORMAT
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['elastic']

SCAN_INTERVAL = timedelta(seconds=30)

ELASTIC_DOMAIN = 'elastic'


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Elastic sensor platform."""
    publisher = hass.data[ELASTIC_DOMAIN]['publisher']
    gateway = hass.data[ELASTIC_DOMAIN]['gateway']

    devices = [
        EsPublishQueueSensor(publisher),
        EsClusterHealthSensor(gateway)
    ]
    add_devices(devices, True)

class EsPublishQueueSensor(Entity):
    """Representation of the publish queue sensor"""
    def __init__(self, publisher):
        self._publisher = publisher
        self.current_value = None
        self.attr = {}
        self.entity_id = ENTITY_ID_FORMAT.format("es_publish_queue")

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
        _LOGGER.debug("Updating Elasticsearch queue stats")
        self.current_value = self._publisher.queue_size()
        self.attr = {
            "last_publish_time": self._publisher.last_publish_time()
        }

class EsClusterHealthSensor(Entity):
    """Representation of the Cluster Health sensor."""

    def __init__(self, gateway):
        """Initialize the sensor."""
        self.current_value = None
        self._latest_cluster_health = {}
        self._gateway = gateway

        self.entity_id = ENTITY_ID_FORMAT.format("es_cluster_health")

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.current_value

    @property
    def device_state_attributes(self):
        """Return the state attributes"""
        return self._latest_cluster_health

    def update(self):
        """Update the state from the sensor."""
        _LOGGER.debug("Updating Elasticsearch cluster health")
        self._latest_cluster_health = self._gateway.get_client().cluster.health()
        self.current_value = self._latest_cluster_health["status"]
