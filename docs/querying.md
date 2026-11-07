# Querying Elasticsearch

The `elasticsearch.query` action runs an [ES|QL](https://www.elastic.co/docs/reference/query-languages/esql) query against your cluster, and returns the resulting rows to the automation or script that called it. Use it to bring data back into Home Assistant: the average of a sensor over the last hour, the last time something happened, or data that never passed through Home Assistant at all.

ES|QL is the only query language the action supports. It doesn't need anything else to be set up, and works with any loaded Elasticsearch entry.

## Requirements

- **Elasticsearch 8.19 or later, or 9.1 or later on 9.x.** Elastic Cloud Serverless is supported too. Publishing still works from 8.14, but older versions can't be queried:
    - Before 8.18, ES|QL can't filter on or compare the `date_nanos` timestamps the integration publishes, so most queries of Home Assistant data fail.
    - Before 8.19, and in 9.0, Elasticsearch can't be told to refuse partial results. The integration never accepts a partial result as complete.

    On an older cluster, the action fails with `Querying requires Elasticsearch 8.19 or later, or 9.1 or later on 9.x`, and nothing is sent to the cluster.

- **The `read` privilege on every index the query reads.** The [`hass_writer` role](configure.md#credentials) can only publish, so on its own it can't run queries, not even of the data the integration published. Add a second entry to the role's `indices`:

    ```json
    {
      "names": ["metrics-homeassistant.*"],
      "privileges": ["read"]
    }
    ```

    Add more names to query other indices or data streams. For a user, add this to its role. For an API key, [update the key's role descriptors](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-security-update-api-key), or create a new key with both entries and enter it when you [reauthenticate](configure.md#credentials). No cluster privileges are needed beyond the ones publishing already uses.

## Action fields

| Field | Required | Description |
| --- | --- | --- |
| `config_entry_id` | Yes | The Elasticsearch entry to query. In the UI, choose it from the list. In YAML, find the ID in the entry's URL on the [integration page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}. |
| `query` | Yes | The ES|QL query. Choose indices, aliases, or data streams with its `FROM` command. Surrounding whitespace is removed. |
| `params` | No | A list of values to bind to the query's `?` placeholders, in order. Each must be a string, number, boolean, or `null`. |

Always pass values with `params`, rather than templating them into the query. Bound values can't change the query's meaning, whatever they contain.

The action only returns data, so it must be called with `response_variable`.

## Response

The response has the query's columns, and one object per row, keyed by column name:

```json
{
  "columns": [
    {"name": "@timestamp", "type": "date_nanos"},
    {"name": "hass.entity.valueas.float", "type": "double"}
  ],
  "rows": [
    {"@timestamp": "2026-11-07T22:06:42.875933123Z", "hass.entity.valueas.float": 21.5}
  ],
  "warnings": [],
  "took_ms": 12
}
```

| Key | Description |
| --- | --- |
| `columns` | Each column's `name` and ES|QL `type`, in the order the query returns them. |
| `rows` | Each row, as an object with a value for every column. |
| `warnings` | The warnings Elasticsearch sent with the result, or an empty list. |
| `took_ms` | How long Elasticsearch says the query took, in milliseconds. `null` if it didn't say. |

- **Values are kept as Elasticsearch returns them.** Numbers and booleans stay numbers and booleans, and dates are ISO 8601 strings. A field with no value is `null`, and a field with several values is a list.
- **A query that matches nothing isn't an error.** `rows` is an empty list, and `columns` still describes the result.
- **Check `warnings` when a value is unexpectedly `null`.** When ES|QL can't evaluate an expression for a row, for example `TO_DOUBLE("abc")`, it returns `null` for that row and adds a warning, rather than failing the query.
- **Queries without a `LIMIT` always warn `No limit defined, adding default limit of [1000]`**, even when they summarize with `STATS`. It's harmless when the query returns fewer rows than that.
- **Fields ES|QL can't read have the type `unsupported`**, and their values are always `null`.
- **Each column name must be unique.** ES|QL can return two columns with the same name, which can't both be keys of a row, so the action fails instead. Rename one with `RENAME` or `EVAL`.

## Examples

### Latest reading of an entity

Runs the query, then uses the latest published value of `sensor.outdoor_temperature`. Replace `YOUR_ENTRY_ID` with your entry's ID.

```yaml
- action: elasticsearch.query
  data:
    config_entry_id: YOUR_ENTRY_ID
    query: |
      FROM metrics-homeassistant.*
      | WHERE hass.entity.id == ?
      | SORT @timestamp DESC
      | LIMIT 1
      | KEEP @timestamp, hass.entity.valueas.float
    params:
      - sensor.outdoor_temperature
  response_variable: latest

- if: "{{ latest.rows | count > 0 }}"
  then:
    - action: persistent_notification.create
      data:
        message: >-
          The outdoor temperature was
          {{ latest.rows[0]['hass.entity.valueas.float'] }}
          at {{ latest.rows[0]['@timestamp'] }}.
```

Column names with dots or `@` must be read with `['...']`, as above. To use simpler names, rename the columns in the query, for example `| RENAME hass.entity.valueas.float AS temperature`.

### Average over a time window

A query that summarizes with `STATS` returns one row, even when nothing matches.

```yaml
- action: elasticsearch.query
  data:
    config_entry_id: YOUR_ENTRY_ID
    query: |
      FROM metrics-homeassistant.sensor-default
      | WHERE hass.entity.id == ? AND @timestamp >= NOW() - 1 hour
      | STATS average_temperature = AVG(hass.entity.valueas.float)
    params:
      - sensor.outdoor_temperature
  response_variable: weather

- action: persistent_notification.create
  data:
    message: >-
      {% set average = weather.rows[0].average_temperature %}
      {% if average is none %}
        No readings in the last hour.
      {% else %}
        The average outdoor temperature over the last hour was {{ average | round(1) }}.
      {% endif %}
```

### Values from templates

`params` can be templated. Here, a script queries whichever entity it was called with:

```yaml
alias: Count state changes today
fields:
  entity:
    selector:
      entity:
sequence:
  - action: elasticsearch.query
    data:
      config_entry_id: YOUR_ENTRY_ID
      query: |
        FROM metrics-homeassistant.*
        | WHERE hass.entity.id == ?
          AND event.action == "State change"
          AND @timestamp >= NOW() - 1 day
        | STATS changes = COUNT(*)
      params:
        - "{{ entity }}"
    response_variable: result
  - stop: Done
    response_variable: result
```

## Limits

Each query is bounded, and a result that goes past a limit is an error rather than an incomplete result.

| Limit | Value | What happens |
| --- | --- | --- |
| Rows | 1,000 | More rows fail with `The query returned … rows, more than the limit of 1000`. Add a `LIMIT`, or summarize with `STATS`. |
| Elasticsearch's default limit | Usually 1,000 | Without a `LIMIT`, Elasticsearch stops at its default and says so in a warning. If the result reaches that default, it may be incomplete, so the action fails. Add an explicit `LIMIT`. |
| Result size | 1 MiB of JSON | A larger result fails, even within the row limit. Return fewer rows or columns, for example with `KEEP`. |
| Time | The entry's request timeout, 30 seconds by default | A slower query fails with `Elasticsearch didn't answer the query within 30 seconds`. |
| Queries at once | 4 per entry | Further queries wait for one to finish, so queries can't starve publishing. Unloading or reloading the entry cancels running and waiting queries. |

The size limit is checked once the response has arrived, so it bounds what reaches your automations, not what Elasticsearch sends. Elasticsearch has its own limits too: by default, it never returns more than 10,000 rows, however high the `LIMIT`.

There's no pagination. To work with more data, aggregate it in the query.

## Errors

The action fails with an error that says what went wrong. Errors caused by the query or its result are shown as validation errors.

| Error | What to do |
| --- | --- |
| `Elasticsearch rejected the query (…): …` | The query is invalid, or uses something the cluster doesn't support. The message includes Elasticsearch's reason, such as `Unknown index [weather-*]` or a parsing error, cut to 500 characters. |
| `Querying requires Elasticsearch 8.19 or later, …` | [Upgrade the cluster](#requirements). |
| `The entry's credentials aren't allowed to run this query.` | Grant the [`read` privilege](#requirements) on the indices the query reads. |
| `Elasticsearch rejected the credentials, or they lack the required privileges.` | The credentials no longer work. Home Assistant asks you to [reauthenticate](configure.md#credentials). |
| `The query returns more than one column named …` | Give each column a unique name. |
| `The query returned … rows`, `… may be incomplete`, or `The query's result is …` | The result went past a [limit](#limits). |
| `Elasticsearch could only return partial results for the query` | Part of the data couldn't be read, for example because a shard is unavailable. Check the cluster's health. |
| `Elasticsearch didn't answer the query within … seconds.` | Make the query cheaper, for example by narrowing its time range. |
| `The query was cancelled because its Elasticsearch entry was unloaded or reloaded.` | The entry was reloaded, for example after changing its options, while the query was running or waiting its turn. Run it again once the entry has loaded. |
| `The query couldn't be run: …` | The cluster couldn't be reached, or failed. The message describes the problem. |
| The config entry wasn't found, or isn't loaded | Check the entry ID, and that the entry is loaded on the [integration page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}. |

To stop an automation failing when a query does, set `continue_on_error: true` on the action.

## Privacy

- The integration never logs query text, parameter values, or results.
- An error from Elasticsearch can quote part of the query. It's shown to whoever ran the action, and Home Assistant logs errors raised by automations and scripts.
- Like any response variable, the result is stored in the automation's or script's [traces](https://www.home-assistant.io/docs/automation/troubleshooting/), along with the query and its parameters.

## Known limitations

- **ES|QL depends on the cluster's version.** Functions and commands added in later versions of ES|QL fail on older clusters with an `Elasticsearch rejected the query` error. Check the [ES|QL documentation](https://www.elastic.co/docs/reference/query-languages/esql) for the version each one needs.
- **Only positional parameters are supported.** Named parameters such as `?name` aren't.
- **The query runs as the entry's credentials.** Anyone who can run actions in Home Assistant can read whatever those credentials can.
