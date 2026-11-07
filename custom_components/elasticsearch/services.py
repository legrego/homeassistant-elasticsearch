"""Actions provided by the Elasticsearch integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from custom_components.elasticsearch.const import DOMAIN
from custom_components.elasticsearch.errors import (
    AmbiguousQueryColumns,
    AuthenticationRequired,
    BadRequest,
    CannotConnect,
    InsufficientPrivileges,
    InvalidQueryResponse,
    PartialQueryResult,
    QueryCancelled,
    QueryNotSupported,
    QueryResultTooLarge,
    RequestTimeout,
    TooManyQueryRows,
    TruncatedQueryResult,
)
from custom_components.elasticsearch.esql import MAX_ROWS, QUERY_MINIMUM_VERSION_TEXT
from custom_components.elasticsearch.logger import LOGGER

if TYPE_CHECKING:  # pragma: no cover
    from custom_components.elasticsearch import ElasticIntegrationConfigEntry

SERVICE_QUERY: str = "query"

ATTR_QUERY: str = "query"
ATTR_PARAMS: str = "params"

# Elasticsearch's reason for rejecting a query is shown to whoever ran it, but can be long
MAX_REASON_LENGTH: int = 500


def _query_text(value: Any) -> str:
    """Validate that the query is a string with something in it."""
    text = cv.string(value).strip()
    if not text:
        msg = "The query can't be empty"
        raise probatio.Invalid(msg)
    return text


QUERY_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        probatio.Required(ATTR_QUERY): _query_text,
        # Each value is bound to a `?` placeholder in the query, in order. Only scalars can be bound.
        probatio.Optional(ATTR_PARAMS, default=list): probatio.All(
            list, [probatio.Any(None, bool, int, float, str)]
        ),
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    hass.services.async_register(
        DOMAIN,
        SERVICE_QUERY,
        _async_query,
        schema=QUERY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


async def _async_query(call: ServiceCall) -> ServiceResponse:
    """Run an ES|QL query against an entry's cluster, and respond with its result."""

    entry: ElasticIntegrationConfigEntry = service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID]
    )
    integration = entry.runtime_data

    try:
        result = await integration.query_runner.async_query(call.data[ATTR_QUERY], call.data[ATTR_PARAMS])

    except QueryNotSupported as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="query_not_supported",
            translation_placeholders={
                "version": str(err.version),
                "minimum_version": QUERY_MINIMUM_VERSION_TEXT,
            },
        ) from err

    except BadRequest as err:
        reason = err.reason or "no reason given"
        if len(reason) > MAX_REASON_LENGTH:
            reason = reason[:MAX_REASON_LENGTH] + "…"
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="query_rejected",
            translation_placeholders={"error_type": err.error_type or "unknown", "reason": reason},
        ) from err

    except AmbiguousQueryColumns as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="query_ambiguous_columns",
            translation_placeholders={"columns": ", ".join(err.columns)},
        ) from err

    except TooManyQueryRows as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="query_too_many_rows",
            translation_placeholders={"rows": str(err.rows), "limit": str(err.limit)},
        ) from err

    except TruncatedQueryResult as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="query_truncated",
            translation_placeholders={"limit": str(err.limit), "max_rows": str(MAX_ROWS)},
        ) from err

    except QueryResultTooLarge as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="query_result_too_large",
            translation_placeholders={"size": _kibibytes(err.size), "limit": _kibibytes(err.limit)},
        ) from err

    except PartialQueryResult as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="query_partial_result") from err

    except QueryCancelled as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="query_cancelled") from err

    except InvalidQueryResponse as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="query_invalid_response") from err

    except InsufficientPrivileges as err:
        # Checked before AuthenticationRequired, which it extends. The credentials work, but can't
        # read what the query asks for, so reauthenticating wouldn't help.
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="query_insufficient_privileges"
        ) from err

    except AuthenticationRequired as err:
        entry.async_start_reauth(call.hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="authentication_failed") from err

    except RequestTimeout as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="query_timeout",
            translation_placeholders={"timeout": str(integration.request_timeout)},
        ) from err

    except CannotConnect as err:
        # The message describes the connection problem, and never includes the query
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="query_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    except Exception as err:
        LOGGER.exception("Unexpected error running a query")
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="unexpected_error") from err

    return result.as_dict()


def _kibibytes(size: int) -> str:
    """Format a size in bytes as KiB, rounded up."""
    return f"{-(-size // 1024)} KiB"
