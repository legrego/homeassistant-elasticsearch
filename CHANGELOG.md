# Changelog

## Unreleased

- Report incompatible Elasticsearch endpoints with an explicit unsupported-server
  error during configuration. Elasticsearch-compatible ingestion endpoints such
  as VictoriaLogs are not supported.
- Stop retrying setup for existing entries when server metadata is incompatible
  or a successful response lacks the Elasticsearch product header. This also
  applies to proxies temporarily returning a success page while Elasticsearch
  starts; reload the integration after the endpoint is ready or corrected.
- Preserve certificate settings after configuration errors and during
  reauthentication, including removal of a previously configured CA path when
  the optional field is cleared.
