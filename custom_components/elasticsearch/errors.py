"""Errors for the Elastic component."""

from homeassistant.exceptions import HomeAssistantError


class ESIntegrationException(HomeAssistantError):
    """Base class for Elastic exceptions."""

class ESIntegrationConnectionException(ESIntegrationException):
    """Base class for Elasticsearch exceptions."""


class AuthenticationRequired(ESIntegrationConnectionException):
    """Cluster requires authentication."""

class InsufficientPrivileges(ESIntegrationConnectionException):
    """Credentials are lacking the required privileges."""

class CannotConnect(ESIntegrationConnectionException):
    """Unable to connect to the cluster."""

class ClientError(ESIntegrationConnectionException):
    """Connected with a Client Error."""

class UntrustedCertificate(ESIntegrationConnectionException):
    """Connected with untrusted certificate."""

class UnsupportedVersion(ESIntegrationConnectionException):
    """Connected to an unsupported version of Elasticsearch."""
