# Shipping logs

This integration publishes entity state changes. It doesn't send logs. To get your Home Assistant logs into Elasticsearch, use the companion [Elastic Agent app](https://github.com/legrego/homeassistant-elastic-agent-app){:target="_blank"} (apps were formerly called add-ons).

The app runs [Elastic Agent](https://www.elastic.co/docs/reference/fleet){:target="_blank"} on your Home Assistant host and reads the host's systemd journal, so it can send:

- Home Assistant Core logs, including startup and crashes
- Supervisor logs
- Logs from every other app
- Host logs (network, Docker, the OS itself)

Because the app runs outside Home Assistant Core, it also captures what the integration never could: logs from before the integration loads, and from when Core crashes or fails to start.

Like this integration, the app is a community project, not an official Elastic product.

## Requirements

- Home Assistant OS or a Supervised install. Apps need the Supervisor. On Container or Core installs, run Elastic Agent yourself instead.
- A 64-bit host (`amd64` or `aarch64`).
- Elasticsearch 8.14 or newer, including 9.x, Elastic Cloud, and Serverless. These are the same versions this integration supports, so you can send both to the same cluster.

See the app's [documentation](https://github.com/legrego/homeassistant-elastic-agent-app/blob/main/elastic_agent/DOCS.md#requirements){:target="_blank"} for the full list, including memory and disk needs.

## Install the app

[![Open your Home Assistant instance and add this app repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Flegrego%2Fhomeassistant-elastic-agent-app){:target="_blank"}

Or add the repository yourself:

1. Go to **Settings** > **Apps** > **App store**.
2. Open the menu, choose **Repositories**, and add `https://github.com/legrego/homeassistant-elastic-agent-app`.
3. Install **Elastic Agent**.

Then start the app and select **Open web UI** to configure it. In standalone mode (recommended), you give it your Elasticsearch URL and either a superuser login or an API key, and it sets up the rest: an ingest pipeline that parses Core's log lines, a write-only API key for sending logs, and the agent's configuration. It can also enroll with Fleet instead.

The app's [documentation](https://github.com/legrego/homeassistant-elastic-agent-app/blob/main/elastic_agent/DOCS.md){:target="_blank"} covers configuration, its status page, Fleet mode, and the fields it extracts from Core logs.

## Where the data goes

The app and this integration write to different data streams, so they never collide:

| Source | Data streams | Contents |
|---|---|---|
| This integration | `metrics-homeassistant.*` | Entity state changes |
| Elastic Agent app | `logs-haos.core-default` | Home Assistant Core logs, one event per log record, tracebacks included |
| Elastic Agent app | `logs-haos.system-default` | Supervisor, app, and host logs, one event per line |

To browse the logs in Kibana, open **Discover** and create a data view for `logs-haos.*`, the same way you [created one](using_kibana.md#create-a-data-view) for `metrics-homeassistant.*`.

Core log events carry a `homeassistant.integration` field, so you can filter to a single integration's logs. For example, `homeassistant.integration: elasticsearch` shows this integration's own log messages, which helps when you [troubleshoot](troubleshooting.md) it.
