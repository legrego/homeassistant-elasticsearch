"""Errors for the Elastic component."""

from homeassistant.exceptions import HomeAssistantError


class ESIntegrationException(HomeAssistantError):  # noqa: N818
    """Base class for Elastic exceptions."""


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
