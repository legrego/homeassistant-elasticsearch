"""Errors for the Elastic component."""
from homeassistant.exceptions import HomeAssistantError


class ElasticException(HomeAssistantError):
    """Base class for Elastic exceptions."""


class AlreadyConfigured(ElasticException):
    """Cluster is already configured."""


class AuthenticationRequired(ElasticException):
    """Cluster requires authentication."""


class InsufficientPrivileges(ElasticException):
    """Credentials are lacking the required privileges."""


class CannotConnect(ElasticException):
    """Unable to connect to the cluster."""


class UntrustedCertificate(ElasticException):
    """Connected with untrusted certificate."""


class UnsupportedVersion(ElasticException):
    """Connected to an unsupported version of Elasticsearch."""
