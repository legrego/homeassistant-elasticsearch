"""Component Logger."""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

LOGGER = logging.getLogger("custom_components.elasticsearch")
es_logger = logging.getLogger("elasticsearch")
es_logger.name = "elasticsearch-library"

# if the logger is already set up, don't change the level
if LOGGER.level == logging.NOTSET:
    LOGGER.setLevel(logging.INFO)

if es_logger.level == logging.NOTSET:
    es_logger.setLevel(logging.DEBUG)


def have_child(name: str) -> logging.Logger:
    """Create a child logger."""

    # Sanitize the param name only allowing lowercase a-z and 0-9 and replace spaces with underscores
    sanitized_name = "".join([c if c.isalnum() else "" for c in name.replace(" ", "_").lower()])

    parent = logging.getLogger("custom_components.elasticsearch")
    new_logger = parent.getChild(f"{sanitized_name}")
    new_logger.name = f"{parent.name}-{sanitized_name}"

    return new_logger


# Returns a function
def log_enter_exit_info(func: Callable) -> Callable:
    """Log function start and end."""

    def decorated_func(*args, **kwargs):  # noqa: ANN202
        logger = getattr(args[0], "_logger", LOGGER) if args and len(args) > 0 else LOGGER
        return call_and_log_enter_exit(func, logger, logging.INFO, *args, **kwargs)

    return decorated_func


def async_log_enter_exit_info(func: Callable[..., Coroutine]):  # noqa: ANN201
    """Log function start and end."""

    async def decorated_func(*args, **kwargs):  # noqa: ANN202
        logger = getattr(args[0], "_logger", LOGGER) if args and len(args) > 0 else LOGGER
        return await call_and_log_enter_exit(func, logger, logging.INFO, *args, **kwargs)

    return decorated_func


def log_enter_exit_debug(func: Callable) -> Callable:
    """Log function start and end."""

    def decorated_func(*args, **kwargs):  # noqa: ANN202
        logger = getattr(args[0], "_logger", LOGGER) if args and len(args) > 0 else LOGGER
        return call_and_log_enter_exit(func, logger, logging.DEBUG, *args, **kwargs)

    return decorated_func


def async_log_enter_exit_debug(func: Callable[..., Coroutine]):  # noqa: ANN201
    """Log function start and end."""

    async def decorated_func(*args, **kwargs):  # noqa: ANN202
        logger = getattr(args[0], "_logger", LOGGER) if args and len(args) > 0 else LOGGER
        return await async_call_and_log_enter_exit(func, logger, logging.DEBUG, *args, **kwargs)

    return decorated_func


def call_and_log_enter_exit(
    func: Callable,
    logger: logging.Logger,
    level: int = logging.DEBUG,
    *args,
    **kwargs,
) -> Any:  # noqa: ANN401
    """Log function start and end."""

    module = func.__module__

    name = func.__qualname__
    logger.log(level, "Entering %s : %s", module, name)
    try:
        result = func(*args, **kwargs)
        logger.log(level, "Returning from %s : %s", module, name)
    except:
        logger.log(level, "Error in %s : %s", module, name)
        raise
    return result


async def async_call_and_log_enter_exit(
    func: Callable,
    logger: logging.Logger,
    level: int = logging.DEBUG,
    *args,
    **kwargs,
) -> Any:  # noqa: ANN401
    """Log function start and end."""

    module = func.__module__

    name = func.__qualname__
    logger.log(level, "Entering %s : %s", module, name)
    try:
        result = await func(*args, **kwargs)
        logger.log(level, "Returning from %s : %s", module, name)
    except:
        logger.log(level, "Error in %s : %s", module, name)
        raise
    return result
