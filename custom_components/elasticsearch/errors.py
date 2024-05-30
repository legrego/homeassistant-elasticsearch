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


class ClientError(ElasticException):
    """Connected with a Client Error."""


class UntrustedCertificate(ElasticException):
    """Connected with untrusted certificate."""


class UnsupportedVersion(ElasticException):
    """Connected to an unsupported version of Elasticsearch."""


def convert_es_error(msg, err):
    """Convert an internal error from the elasticsearch package into one of our own."""
    import aiohttp
    from elasticsearch7 import (
        AuthenticationException,
        AuthorizationException,
        ElasticsearchException,
        SSLError,
    )
    from elasticsearch7 import (
        ConnectionError as ESConnectionError,
    )

    if isinstance(err, SSLError):
        return UntrustedCertificate(msg, err)

    if isinstance(err, ESConnectionError):
        if isinstance(err.info, aiohttp.client_exceptions.ClientConnectorCertificateError):
            return UntrustedCertificate(msg, err)

        if isinstance(err.info, aiohttp.client_exceptions.ClientConnectorError):
            return ClientError(msg, err)
        return CannotConnect(msg, err)

    if isinstance(err, AuthenticationException):
        return AuthenticationRequired(msg, err)

    if isinstance(err, AuthorizationException):
        return InsufficientPrivileges(msg, err)

    if isinstance(err, ElasticsearchException):
        return ElasticException(msg, err)

    return err
