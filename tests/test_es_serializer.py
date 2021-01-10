""" Tests against the Elasticsearch Serializer """

import json

from custom_components.elasticsearch.es_serializer import get_serializer

from .sample_data import create_sample_state


def test_simple_entry():
    """ Ensure that the serialier can handle a basic state change event. """

    state = create_sample_state(last_updated="", last_changed="")

    serializer = get_serializer()

    serialized_state = serializer.dumps(state)

    rehydrated_state = json.loads(serialized_state)

    assert state == rehydrated_state


def test_entry_with_set():
    """ Ensure that the serializer can handle a state change event which includes a set. """

    state = create_sample_state(
        last_updated="",
        last_changed="",
        attributes=dict({"set_key": set(["a", "b", "c"])}),
    )

    serializer = get_serializer()

    serialized_state = serializer.dumps(state)

    serialized_state = serializer.dumps(state)

    rehydrated_state = json.loads(serialized_state)

    assert isinstance(rehydrated_state["attributes"]["set_key"], list)
    rehydrated_state["attributes"]["set_key"].sort()
    assert rehydrated_state["attributes"]["set_key"] == ["a", "b", "c"]
