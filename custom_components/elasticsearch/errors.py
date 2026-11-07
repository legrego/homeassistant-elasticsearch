"""Errors for the Elastic component."""

from typing import Any

from homeassistant.exceptions import HomeAssistantError


class ESIntegrationException(HomeAssistantError):  # noqa: N818
    """Base class for Elastic exceptions."""


class InvalidCACertificate(ESIntegrationException):
    """The configured certificate authority file could not be loaded."""


class ESIntegrationConnectionException(ESIntegrationException):
    """Base class for Elasticsearch exceptions."""


class AuthenticationRequired(ESIntegrationConnectionException):
    """Cluster requires authentication."""


class InsufficientPrivileges(AuthenticationRequired):
    """Credentials are lacking the required privileges."""


class CannotConnect(ESIntegrationConnectionException):
    """Unable to connect to the cluster."""


class ServerError(CannotConnect):
    """Server Error."""


class ClientError(CannotConnect):
    """Client Error."""


class SSLError(CannotConnect):
    """Error related to SSL."""


class UntrustedCertificate(SSLError):
    """Received a untrusted certificate error."""


class UnsupportedVersion(ESIntegrationConnectionException):
    """Connected to an unsupported version of Elasticsearch."""

    def __init__(self, *args: object, version: str | None = None, **kwargs: Any) -> None:
        """Initialize the error with the version the cluster reported, when it is known."""
        super().__init__(*args, **kwargs)
        self.version = version


class UnsupportedServer(ESIntegrationConnectionException):
    """The endpoint does not provide the required Elasticsearch server metadata."""


class RequestTimeout(ServerError):
    """Elasticsearch did not respond before the request timed out."""


class BadRequest(ServerError):
    """Elasticsearch rejected the request as invalid.

    The message never includes the reason Elasticsearch gave, because it can quote the request. The
    reason is kept in `reason`, for callers that may show it to whoever made the request.
    """

    def __init__(
        self, *args: object, error_type: str | None = None, reason: str | None = None, **kwargs: Any
    ) -> None:
        """Initialize the error with the type and reason Elasticsearch reported."""
        super().__init__(*args, **kwargs)
        self.error_type = error_type
        self.reason = reason


class QueryError(ESIntegrationException):
    """Base class for errors running an ES|QL query."""


class QueryNotSupported(QueryError):
    """The cluster's version doesn't support querying."""

    def __init__(self, *args: object, version: str | None = None, **kwargs: Any) -> None:
        """Initialize the error with the version the cluster reported."""
        super().__init__(*args, **kwargs)
        self.version = version


class InvalidQueryResponse(QueryError):
    """Elasticsearch returned a response to a query that couldn't be read."""


class PartialQueryResult(QueryError):
    """Elasticsearch returned partial results for a query."""


class AmbiguousQueryColumns(QueryError):
    """A query returned more than one column with the same name."""

    def __init__(self, *args: object, columns: list[str], **kwargs: Any) -> None:
        """Initialize the error with the names that are used more than once."""
        super().__init__(*args, **kwargs)
        self.columns = columns


class TooManyQueryRows(QueryError):
    """A query returned more rows than the integration accepts."""

    def __init__(self, *args: object, rows: int, limit: int, **kwargs: Any) -> None:
        """Initialize the error with the number of rows and the limit."""
        super().__init__(*args, **kwargs)
        self.rows = rows
        self.limit = limit


class TruncatedQueryResult(QueryError):
    """Elasticsearch applied its default row limit, so the result may be incomplete."""

    def __init__(self, *args: object, limit: int, **kwargs: Any) -> None:
        """Initialize the error with the limit Elasticsearch applied."""
        super().__init__(*args, **kwargs)
        self.limit = limit


class QueryResultTooLarge(QueryError):
    """A query's result is larger than the integration accepts."""

    def __init__(self, *args: object, size: int, limit: int, **kwargs: Any) -> None:
        """Initialize the error with the size of the result and the limit, in bytes."""
        super().__init__(*args, **kwargs)
        self.size = size
        self.limit = limit
