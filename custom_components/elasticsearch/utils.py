"""Utilities."""


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".", keep_keys: list[str] | None = None) -> dict:
    """Flatten an n-level nested dictionary using periods."""

    flattened_dict = {}

    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key != "" else k

        if isinstance(v, dict):
            flattened_dict.update(
                flatten_dict(
                    d=v,
                    parent_key=new_key,
                    sep=sep,
                ),
            )
        else:
            flattened_dict[new_key] = v

    if keep_keys is not None:
        return {k: v for k, v in flattened_dict.items() if k in keep_keys}

    return flattened_dict
