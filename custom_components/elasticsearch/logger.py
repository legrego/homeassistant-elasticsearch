"""Component Logger."""

import logging
from collections.abc import Callable

LOGGER = logging.getLogger("es_integration")
es_logger = logging.getLogger("elasticsearch")
es_logger.name = "elasticsearch-library"

# if the logger is already set up, don't change the level
if LOGGER.level == logging.NOTSET:
    LOGGER.setLevel(logging.INFO)

if es_logger.level == logging.NOTSET:
    es_logger.setLevel(logging.WARNING)


def have_child(name: str) -> logging.Logger:
    """Create a child logger."""

    # Sanitize the param name only allowing lowercase a-z and 0-9 and replace spaces with underscores
    sanitized_name = "".join([c if c.isalnum() else "" for c in name.replace(" ", "_").lower()])

    parent = logging.getLogger("es_integration")
    new_logger = parent.getChild(f"{sanitized_name}")
    new_logger.name = f"{parent.name}-{sanitized_name}"

    return new_logger


# Returns a function
def log_enter_exit(func) -> Callable:
    """Log function start and end."""

    # Skip this function in debugger
    # noinspection PyBroadException
    def decorated_func(*args, **kwargs):  # noqa: ANN202
        logger = getattr(args[0], "_logger", LOGGER) if args and len(args) > 0 else LOGGER

        module = func.__module__

        name = func.__qualname__
        logger.debug("Entering %s : %s", module, name)
        try:
            result = func(*args, **kwargs)
            logger.debug("Returning from %s : %s", module, name)
        except:
            logger.debug("Error in %s : %s", module, name)
            raise
        return result

    return decorated_func


def async_log_enter_exit(func):  # noqa: ANN201
    """Log function start and end."""

    # noinspection PyBroadException
    async def decorated_func(*args, **kwargs):  # noqa: ANN202
        logger = getattr(args[0], "_logger", LOGGER) if args and len(args) > 0 else LOGGER

        module = func.__module__

        name = func.__qualname__
        logger.debug("Entering %s : %s", module, name)
        try:
            result = await func(*args, **kwargs)
            logger.debug("Returning from %s : %s", module, name)
        except:
            logger.debug("Error in %s : %s", module, name)
            raise
        return result

    return decorated_func
