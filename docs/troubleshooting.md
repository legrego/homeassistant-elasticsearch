# Troubleshooting

Start with the integration's logs and diagnostics. They're described at the [end of this page](#collect-logs-and-diagnostics), and they're also what to attach when you [open an issue](https://github.com/legrego/homeassistant-elasticsearch/issues).

## Setup can't connect to the URL

**Symptom:** adding the integration fails with `Failed to connect to host on port. Is it reachable?`, or an existing entry shows `Unable to connect to Elasticsearch` and keeps retrying.

1. Check that the URL includes the scheme and port, such as `https://my-cluster:9200`. Elasticsearch uses `https` by default since 8.0.
2. Check that the cluster can be reached from the machine running Home Assistant, not just from your own computer. If Home Assistant runs in a container, `localhost` refers to the container.
3. Check that a firewall or proxy isn't blocking the port.

An existing entry retries setup in the background, so once the cluster is reachable it recovers on its own.

## The certificate isn't trusted

**Symptom:** after you enter the URL, setup asks for TLS settings and shows `Elasticsearch's server certificate could not be verified`.

The cluster's certificate isn't signed by a certificate authority (CA) that Home Assistant trusts. This is the default for a self-managed cluster, which creates its own CA.

1. Copy the cluster's CA certificate, such as `config/certs/http_ca.crt` in the Elasticsearch directory, into Home Assistant's `config` directory.
2. Enter its path in `Fully qualified path to custom certificate authority`. See [Custom certificate authority (CA)](configure.md#custom-certificate-authority-ca).
3. If the certificate was issued for a different hostname than the one in your URL, also turn off `Verify hostname matches server certificate`.

Turning off `Verify TLS certificate` works too, but leaves the connection open to interception.

If an existing entry reports that its CA file can't be loaded, check that the file still exists and is a readable, PEM-encoded certificate, or [reconfigure the entry](configure.md#change-connection-settings) to point at the right file.

## Insufficient privileges

**Symptom:** setup shows `Insufficient privileges for specified user.`, or Home Assistant asks you to reauthenticate an existing entry.

The user or API key can sign in, but it lacks a privilege the integration needs. Give it the privileges in the [`hass_writer` role](configure.md#credentials), or create a new API key with them. For an existing entry, enter the new credentials when Home Assistant asks you to reauthenticate.

## Unsupported version

**Symptom:** setup shows `Unsupported version of Elasticsearch detected.`, or an existing entry fails to load and Home Assistant raises a repair issue saying your version of Elasticsearch isn't supported.

The integration needs Elasticsearch 8.14 or later. An existing entry doesn't retry on its own, because nothing will change until the cluster does.

1. [Upgrade the cluster](https://www.elastic.co/docs/deploy-manage/upgrade) to 8.14 or later.
2. On the [integration page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}, open the entry's menu and select `Reload`. The repair issue clears once the entry loads.

To keep using an older cluster, use [version 1.0.0](index.md#older-versions) of this integration instead.

## Unsupported server

**Symptom:** setup shows `This endpoint does not provide the required Elasticsearch server information.`

The URL answered, but not like an Elasticsearch cluster. The integration checks the version and server metadata the endpoint reports, and that responses carry the `X-Elastic-Product: Elasticsearch` header. This usually means one of:

- **The URL points at something else**, such as Kibana, OpenSearch, or an Elasticsearch-compatible ingestion endpoint like VictoriaLogs. These aren't supported. See [Known limitations](publishing.md#known-limitations).
- **A reverse proxy is in the way.** It may return its own page, for example while Elasticsearch starts, or remove the `X-Elastic-Product` header. Configure the proxy to pass Elasticsearch's responses through unchanged, or connect to Elasticsearch directly.

An existing entry that hits this doesn't retry on its own. Once the endpoint is fixed, reload the entry.

## "This Elasticsearch cluster is already configured"

**Symptom:** adding the integration stops with `This Elasticsearch cluster is already configured.`

Another entry already publishes to this cluster, possibly under a different URL, such as an IP address instead of a hostname. Each cluster can only be added once. To change the URL of the existing entry, [reconfigure it](configure.md#change-connection-settings) instead.

## Two entries publish to the same cluster

**Symptom:** Home Assistant raises a repair issue saying two entries publish to the same Elasticsearch cluster.

Entries created before version 2.1 weren't checked for duplicates, so you may have two entries for the same cluster, possibly under different URLs. Both send the same Home Assistant data to it.

Remove one of the entries from the [integration page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}. The repair issue clears once only one is left.

## Nothing is published

**Symptom:** the integration loads, but no new documents appear in Elasticsearch.

Check these in order:

1. **Publishing is turned off.** If `Send events to Elasticsearch at this interval` is `0`, nothing is published, and the log says `No publish frequency set. Disabling publishing.` Set it to a value above `0` in the [integration options](configure.md#configuration-options).
2. **Nothing passes your targets.** If `Toggle to only publish the set of targets below` is on with no targets selected, every event is filtered out. Select some targets, or turn the toggle off.
3. **Nothing is gathered.** If `Gather all entity states at this interval` is `0` and both change types are turned off in `Choose what types of entity changes to listen for and publish`, nothing is queued.
4. **Publishing is failing.** Look in the log for:
    - `Connection to Elasticsearch has been lost.` The cluster can't be reached. Events keep queuing, and are sent once it's back.
    - `Connection error in publishing loop.` The cluster answers the connection check, but bulk requests fail, for example because a proxy times out or the cluster returns errors. Turn on debug logging to see the underlying error.
    - `Failed to publish N of M documents`, with a `failed to create` line for each one. Elasticsearch rejected those documents, often because of a [custom mapping or ingest pipeline](ingest_advanced.md).
5. **You're looking at the wrong data.** Documents go to the `metrics-homeassistant.*` data streams. In Kibana, check the time range, and that your [data view](using_kibana.md#create-a-data-view) matches those data streams.

See [How publishing works](publishing.md) for the full picture.

## Collect logs and diagnostics

### Turn on debug logging

Either open the [integration page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"} and select `Enable debug logging`, or add this to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.elasticsearch: debug
```

Debug logging is verbose, so turn it off again once you're done. When you use the integration page, turning it off also downloads the log.

### Download diagnostics

On the [integration page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}, open the entry's menu and select `Download diagnostics`. The file contains the entry's settings and options, the cluster's version, whether the connection is up, and how many events are waiting to be published. Usernames, passwords, API keys, and credentials in the URL are redacted.
