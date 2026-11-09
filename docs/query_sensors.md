# Query sensors

A query sensor periodically runs a saved ES|QL query and exposes one selected column as a Home Assistant sensor. Use it for a recent reading, an aggregate over a time window, or data collected outside Home Assistant. Each saved query creates one sensor.

Sensors share the connection, credentials, TLS settings, query runner, [version requirements](querying.md#requirements), and [result limits](querying.md#limits) of the query action. A query-only connection does not need publishing privileges or create data streams; see [query-only setup](configure.md#query-only-connections).

## Add a sensor

1. Open **Settings → Devices & services → Elasticsearch** and choose **Add query sensor** on the connection.
2. Enter a name, an ES|QL query, and optional positional parameters as a JSON array. Parameters bind to `?` placeholders; they are never interpolated into the query text.
3. Continue to execute the query and preview its columns and values. The preview shows at most 30 columns and 256 characters per cell; validation uses the complete result. Correct any query errors before continuing.
4. If the query returns no rows, an explicit **No observations yet** step lets you continue. Its column metadata is still available for selection.
5. Select the value column by name, then configure the refresh interval and optional metadata and freshness settings. Save to create the sensor.

A connection must be loaded to add or reconfigure a sensor. For query errors, the form remains editable. Use the [query action](querying.md) to inspect execution warnings or Elasticsearch's detailed rejection reason.

## Configuration fields

| Field | Required | Meaning |
| --- | --- | --- |
| Sensor name | Yes | A name you choose. Renaming preserves the entity's ID and history. |
| ES\|QL query | Yes | A static query returning at most one row. Select indices, aliases, or data streams in `FROM`. |
| Positional parameters | No | A JSON array such as `["sensor.outdoor_temperature", 10]`. Values may be strings, finite numbers, booleans, or `null`. Default: `[]`. |
| Value column | Yes | The result column to expose, identified by its name. Extra columns are allowed. |
| Refresh interval | Yes | Seconds between completed polls: 10–86400, default 60. Home Assistant may round the scheduled poll by up to a second. |
| Unit of measurement | No | An explicit physical unit. It must be compatible with the selected device class. Providing a unit requires a numeric result. |
| Device class | No | A supported Home Assistant sensor class, such as temperature, energy, date, timestamp, or uptime. Enumeration sensors are not supported. |
| State class | No | `measurement`, `total`, or `total_increasing`, compatible with the device class. Choose only when the query has those statistics semantics. |
| Observation timestamp column | No | A `date` or `date_nanos` column identifying when the source observation occurred. Requires a maximum age. |
| Maximum source-data age | No | 1–31536000 seconds. Requires the observation timestamp column. The sensor becomes unavailable when the observation reaches this age, even between polls. |

Units and statistics semantics are never inferred from ES|QL numeric types. For example, an average temperature can use `measurement`; a rolling count should not be marked `total_increasing`. Use ES|QL functions for calculation, conversion, and scalar extraction. Query text and parameters are static: there is no Jinja template or value-template field.

## Result behavior

| Result | Sensor state |
| --- | --- |
| One row with a supported scalar | The selected value |
| No rows, or a null selected value | `unknown` |
| Explicit numeric zero | `0` |
| Multiple rows | Rejected during setup; `unavailable` at runtime |
| Missing column, array, object, boolean, unsupported type, or incompatible metadata | Rejected during setup; `unavailable` at runtime |
| Connection, permission, execution, partial-result, or size-limit error | `unavailable`; polling retries automatically |
| Invalid or future observation timestamp | Rejected during setup; `unavailable` at runtime |
| Observation older than the maximum age | Rejected during setup; `unavailable` at runtime |

Supported values are finite numbers and text of at most 255 characters. Text columns include ES|QL keyword, text, IP, and version values. Date, timestamp, and uptime device classes require a date/date_nanos column; timestamp strings must include a timezone. Uptime uses the source timestamp as the device start time, rather than a numeric duration. Monetary sensors allow currency units such as `USD`. A null value has no observation to expire and remains unknown. No query rows or additional columns are copied into entity attributes.

All execution warnings prevent a reading from being accepted, except Elasticsearch's warning that it added its default row limit when the result is below that limit. This deliberately rejects warnings about ignored values, failed calculations, and unrecognized warning categories. The action returns those warnings for inspection.

For a latest-value query, explicitly use `SORT ... DESC | LIMIT 1`. The integration never chooses the first of multiple rows or appends a limit. For an aggregate, deliberately return one summary row with `STATS`.

## Examples

### Latest outdoor temperature with freshness

Enter this query:

```text
FROM metrics-homeassistant.sensor-default
| WHERE hass.entity.id == ?
| SORT @timestamp DESC
| LIMIT 1
| KEEP @timestamp, hass.entity.valueas.float
| RENAME hass.entity.valueas.float AS temperature
```

Use these settings:

| Setting | Value |
| --- | --- |
| Name | Outdoor temperature from Elasticsearch |
| Parameters | `["sensor.outdoor_temperature"]` |
| Value column | `temperature` |
| Refresh interval | `60` |
| Unit | `°C` (only if the source is Celsius) |
| Device class | `temperature` |
| State class | `measurement` |
| Observation timestamp | `@timestamp` |
| Maximum age | `300` |

A successfully fetched document from six minutes ago is unavailable. A current document expires five minutes after its observation time even if the next poll has not happened yet.

### Average temperature in the last hour

```text
FROM metrics-homeassistant.sensor-default
| WHERE hass.entity.id == ? AND @timestamp >= NOW() - 1 hour
| STATS average_temperature = AVG(hass.entity.valueas.float), observed = MAX(@timestamp)
| LIMIT 1
```

Use parameters `["sensor.outdoor_temperature"]`, value column `average_temperature`, a 60-second refresh, and the appropriate temperature unit and `measurement` state class. Optionally select `observed` with a maximum age of 300 seconds to require at least one recent observation. If there are no matching temperature readings, the aggregate value is null and the sensor is unknown.

## Polling and recovery

Each sensor has its own coordinator. Queries use the shared limit of four concurrent requests per connection, and each request uses the connection timeout (30 seconds by default). Polling a slow or invalid query does not disable other sensors or publishing. Disabling an entity stops its recurring polls. Unloading the entry stops coordinators, freshness timers, and in-flight query requests.

A failed poll marks that sensor unavailable; the next successful valid poll restores its state. Outages and recovery are logged once per transition, without repeating the error every poll. Expired credentials start the connection's reauthentication flow. Persistent mapping, permission, query-syntax, and unsupported-version problems create a Repair with instructions. A successful poll or removing the saved query clears its Repair.

Diagnostics include each query's availability, non-sensitive error category, last successful fetch time, elapsed time, server execution time, and polling interval. They omit sensor names, query text, parameters, column names, observation timestamps, and results. Sensor errors and routine logs do not contain query data. The setup preview intentionally displays query results to the user configuring the sensor.

## Publishing and removal

Query sensors are excluded from publishing by default on every Elasticsearch connection, even if a target filter includes them. This avoids feeding derived data back into its own source query. To opt in, enable **Publish Elasticsearch query sensors** in the connection's configuration options; the usual inclusion and exclusion filters still apply.

Use **Reconfigure query sensor** in the saved query's menu to change its name, query, column, metadata, or interval. The subentry ID remains unchanged, preserving its entity ID and history. User overrides made in the entity registry continue to apply. Adding, changing, or removing a sensor reloads its parent connection to apply the configuration.

Use **Delete** on the saved query to remove that sensor independently. All query sensors for a connection share an Elasticsearch service device identified by the cluster UUID. It represents the cluster service, not a physical device for each query. Removing the last saved query removes this service device on reload. An orphaned service device can also be deleted from its device page. Removing the connection removes its saved queries and entities; it does not delete source data in Elasticsearch.

Binary sensors, device trackers, multiple sensors per saved query, dynamic query templates, and automatic row-to-entity conversion are outside this feature.
