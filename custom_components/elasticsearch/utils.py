"""Utilities."""

from __future__ import annotations

from typing import Any

from custom_components.elasticsearch import const as compconst


def skip_dict_values(d: dict, skip_values: list[Any]) -> dict:
    """Trim keys with values that match skip_values. Works best on a flattened dict."""
    if skip_values == ():
        return d

    return {k: v for k, v in d.items() if v not in skip_values}


def keep_dict_keys(d: dict, keys: list[str] | None = None, prefixes: list[str] | None = None) -> dict:
    """Trim keys that match keep_keys. Works best on a flattened dict."""

    new_dict = {}

    if keys:
        new_dict.update({k: v for k, v in d.items() if k in keys})

    if prefixes:
        new_dict.update({k: v for k, v in d.items() if any(k.startswith(prefix) for prefix in prefixes)})

    return new_dict


def prepare_dict(
    d: dict,
    flatten: bool = True,
    keep_keys: list[str] | None = None,
    skip_values: list[Any] | None = compconst.SKIP_VALUES,
) -> dict:
    """Clean a dictionary by flattening it, removing keys with empty values and optionally keeping only specified keys."""

    d = flatten_dict(d=d) if flatten else d

    d = keep_dict_keys(d=d, keys=keep_keys) if keep_keys else d

    d = skip_dict_values(d=d, skip_values=skip_values) if skip_values else d

    return d  # noqa: RET504


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flatten an n-level nested dictionary using periods."""

    flattened_dict = {}

    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key != "" else k

        if isinstance(v, dict):
            flattened_dict.update(
                flatten_dict(d=v, parent_key=new_key, sep=sep),
            )
        else:
            flattened_dict[new_key] = v

    return flattened_dict
