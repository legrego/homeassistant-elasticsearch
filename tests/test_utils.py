"""Utility functions for the Elasticsearch Integration."""

from custom_components.elasticsearch.utils import flatten_dict


def test_flatten_dict():
    """Test the flatten_dict function."""
    # Test case 1: Flattening a nested dictionary with default separator
    nested_dict = {
        "a": 1,
        "b": {
            "c": 2,
            "d": {
                "e": 3,
            },
        },
        "f": 4,
    }
    expected_result = {
        "a": 1,
        "b.c": 2,
        "b.d.e": 3,
        "f": 4,
    }
    assert flatten_dict(nested_dict) == expected_result

    # Test case 2: Flattening a nested dictionary with specified keys to keep
    nested_dict = {
        "a": 1,
        "b": {
            "c": 2,
            "d": {
                "e": 3,
            },
        },
        "f": 4,
    }
    expected_result = {
        "a": 1,
        "b.c": 2,
        "f": 4,
    }
    assert flatten_dict(nested_dict, keep_keys=["a", "b.c", "f"]) == expected_result

    # Test case 3: Flattening a nested dictionary with lists, sets, and tuples in various locations
    nested_dict = {
        "a": 1,
        "b": {
            "c": [2, 3, 4],
            "d": {
                "e": (5, 6, 7),
            },
        },
        "f": {8, 9, 10},
    }

    expected_result = {
        "a": 1,
        "b.c": [2, 3, 4],
        "b.d.e": (5, 6, 7),
        "f": {8, 9, 10},
    }

    assert flatten_dict(nested_dict) == expected_result
