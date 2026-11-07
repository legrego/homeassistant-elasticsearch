# How publishing works

The integration doesn't fetch data from Elasticsearch. It gathers Home Assistant's own entity states, holds them in a queue, and sends them to your cluster at a fixed interval.

## How data moves

Three things feed and drain the queue. Each one uses an [option you can configure](configure.md#configuration-options).

1. **Entity changes.** The integration listens for Home Assistant's `state_changed` events. A change to an entity's state is queued as a `State change`, and a change to only its attributes is queued as an `Attribute change`. `Choose what types of entity changes to listen for and publish` decides which of the two are queued. Turn both off to stop listening.
2. **Polling.** Every `Gather all entity states at this interval` seconds, the state of every entity is queued as `Polling`, whether it has changed or not. This keeps a value in Elasticsearch for entities that rarely change. The default is 60 seconds, and `0` turns polling off.
3. **Publishing.** Every `Send events to Elasticsearch at this interval` seconds, the integration checks that it can reach the cluster, then drains the queue through bulk requests. The queue is sent in batches of up to 500 documents (or 100 MB), one request per batch, so a large queue takes several requests. The default is 60 seconds, and `0` turns publishing off entirely, so nothing is listened for, gathered, or sent.

Entity changes and polled states only reach the queue if they pass the include and exclude targets you've set. The reason each document was queued is published in `event.action`. See [Published fields](published_fields.md) for everything a document contains.

## When Elasticsearch is unavailable

Before each publish, the integration checks its connection to the cluster.

- **The cluster can't be reached.** Publishing is skipped, and entity changes and polled states keep being queued. When the connection comes back, the next publish sends everything that queued up in the meantime. Losing the connection and getting it back are each logged once.
- **The cluster is reachable, but a bulk request fails.** For example, a proxy times out or Elasticsearch returns an error. Publishing stops at that batch: batches sent before it are kept, the documents in the failed batch are dropped, and the rest of the queue stays queued for the next publish. (The client reads one document past a full batch before sending it, so that document is dropped too.) `Connection error in publishing loop.` is logged once until publishing recovers.
- **The cluster rejects the credentials.** The integration reloads. If the credentials still don't work, Home Assistant asks you to [reauthenticate](configure.md#credentials).

Elasticsearch can also reject individual documents in a request that otherwise succeeds. Each rejected document is logged with the reason, and isn't retried.

The queue lives in memory and has no size limit. See [Known limitations](#known-limitations) for what that means during long outages and restarts.

If the cluster is down when Home Assistant starts, setup is retried in the background until it succeeds. Nothing is queued until then.

## Known limitations

- **Events that haven't been published are lost on restart.** The queue is kept in memory only. Restarting Home Assistant, reloading the entry, or changing its options or connection settings (which reloads it) discards whatever hasn't been sent yet. With the default settings that's at most a minute of data.
- **The queue has no size limit.** During a long outage, the queue keeps growing until the cluster is reachable again, which uses more and more memory. Once the connection returns, the whole backlog is sent in the next publish, as many batches one after another. If you expect long outages, consider a longer polling interval, or turning polling off, so that fewer events queue up.
- **Failed documents aren't retried.** When a bulk request fails, the documents in that batch are dropped. So is any document Elasticsearch rejects. Elasticsearch's client only retries documents that were refused because the cluster was overloaded (HTTP 429), up to three times.
- **Only Elasticsearch 8.14 and later is supported**, including 9.x and Elastic Cloud Serverless. The integration checks the server's version, metadata, and `X-Elastic-Product` header, so OpenSearch, Elasticsearch-compatible endpoints such as VictoriaLogs, and proxies that don't pass these through are rejected as unsupported servers.
- **Elasticsearch 10 will need an update to this integration.** The integration asks the cluster for REST API compatibility with version 8. Elasticsearch accepts its own major version and the one before it, so this works with 8.x and 9.x clusters, but not with 10.x.
- **Each cluster can only be added once.** An entry is identified by its cluster's UUID, so the same cluster can't be added again under a different URL. To change the URL of an existing entry, [reconfigure it](configure.md#change-connection-settings).
- **Data is published to fixed data streams.** Documents always go to the `metrics-homeassistant.<domain>-default` time series data streams, using the integration's own index template. You can't choose other indices or data streams, but you can [customize ingest](ingest_advanced.md) with your own pipeline and mappings.
