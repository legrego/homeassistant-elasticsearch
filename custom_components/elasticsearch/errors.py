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


def convert_es_error(err):
    """Convert an internal error from the elasticsearch package into one of our own."""
    from elasticsearch7 import SSLError, AuthenticationException, AuthorizationException, ElasticsearchException
    from elasticsearch7 import (
        ConnectionError as ESConnectionError,
    )
    import aiohttp

    if isinstance(err, SSLError):
          return UntrustedCertificate(err)

    if isinstance(err, ESConnectionError):
        if isinstance(
            err.info, aiohttp.client_exceptions.ClientConnectorCertificateError
        ):
            return UntrustedCertificate(err)
        return CannotConnect(err)

    if isinstance(err, AuthenticationException):
         return AuthenticationRequired(err)

    if isinstance(err, AuthorizationException):
         return InsufficientPrivileges(err)

    if isinstance(err, ElasticsearchException):
        return ElasticException(err)

    return err