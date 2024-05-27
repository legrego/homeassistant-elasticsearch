"""Component Logger."""

import logging

logger = logging.getLogger("es_integration")
es_logger = logging.getLogger("elasticsearch")
es_logger.name = "elasticsearch-library"

# if the logger is already set up, don't change the level
if logger.level == logging.NOTSET:
    logger.setLevel(logging.INFO)

if es_logger.level == logging.NOTSET:
    es_logger.setLevel(logging.WARNING)


def have_child(name: str):
    """Create a child logger."""

    # Sanitize the param name only allowing lowercase a-z and 0-9 and replace spaces with underscores
    sanitized_name = "".join([c if c.isalnum() else "" for c in name.replace(" ", "_").lower()])

    parent = logging.getLogger("es_integration")
    new_logger = parent.getChild(f"{sanitized_name}")
    new_logger.name = f"{parent.name}-{sanitized_name}"

    return new_logger
