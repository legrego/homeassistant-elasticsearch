# type: ignore  # noqa: PGH003
"""Sample data for testing."""

from datetime import datetime

from pytz import utc


def create_sample_state(**kwargs):
    """Create a sample state object."""

    return {
        "state": "off",
        "entity_id": "switch.sample_entity",
        "domain": "switch",
        "object_id": "sample_entity",
        "name": "Sample Entity",
        "last_updated": kwargs.get("last_updated", datetime.now().astimezone(utc)),
        "last_changed": kwargs.get("last_changed", datetime.now().astimezone(utc)),
        "attributes": kwargs.get("attributes", {"sample_attribute": "sample_attribute_value"}),
    }


sample_state_change_event = {
    "entity_id": "switch.sample_entity",
    "old_state": create_sample_state(),
    "new_state": create_sample_state(),
}
