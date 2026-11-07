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
