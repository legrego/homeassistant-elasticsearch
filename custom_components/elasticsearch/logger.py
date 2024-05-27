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


# Add a filter to the logger that trims log messages longer than 1024 characters
class TrimLogMessage(logging.Filter):
    """Filter to trim log messages to 1024 characters."""

    def filter(self, record):
        """Filter log messages."""
        record.msg = f"{record.msg[:1024]}... (truncated)"
        return True


es_logger.addFilter(TrimLogMessage())
logger.addFilter(TrimLogMessage())


def have_child(name: str):
    """Create a child logger."""

    # Sanitize the param name only allowing lowercase a-z and 0-9 and replace spaces with underscores
    sanitized_name = "".join([c if c.isalnum() else "" for c in name.replace(" ", "_").lower()])

    parent = logging.getLogger("es_integration")
    new_logger = parent.getChild(f"{sanitized_name}")
    new_logger.name = f"{parent.name}-{sanitized_name}"
    new_logger.addFilter(TrimLogMessage())

    return new_logger
