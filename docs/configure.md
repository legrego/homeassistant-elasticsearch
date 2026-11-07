# Configuration

## Gather Elasticsearch details

You will need the following details to configure the Elasticsearch integration:

1. The URL of your Elasticsearch instance
2. Credentials to access the Elasticsearch instance (if required)
3. The SSL certificate authority (CA) file, if you are using a custom CA not trusted by the host system

Use the URL of a supported Elasticsearch cluster. An Elasticsearch-compatible
ingestion endpoint, such as VictoriaLogs' `/insert/elasticsearch/`, is not
sufficient: this integration also requires Elasticsearch cluster metadata,
security APIs, index templates, and data streams. Incompatible server metadata
is reported as an unsupported server during setup.

Existing entries stop retrying setup when the server metadata is incompatible or
a successful response is missing the `X-Elastic-Product: Elasticsearch` header.
This includes a reverse proxy temporarily returning a success page while
Elasticsearch starts. Once the endpoint is ready or its configuration is corrected,
reload the integration to try again.

### Credentials

You must provide credentials if your Elasticsearch instance is secured. While we support authenticating via username/password, we recommend using API Keys for simplicity and compatibility with all versions of Elasticsearch.

Use the following command to create an API Key for the Home Assistant component.:

=== "curl"
    ```bash
    ES_URL=https://localhost:9200 # (1)
    ES_USER=elastic # (2)
    ES_PASSWORD=changeme # (3)
    curl "$ES_URL/_security/api_key" \
      -X POST \
      -H "Content-Type: application/json" \
      -u "$ES_USER":"$ES_PASSWORD" \
      -d'
      {
        "name": "home_assistant_component",
        "role_descriptors": {
          "hass_writer": {
            "cluster": [
              "manage_index_templates",
              "monitor"
            ],
            "indices": [
              {
                "names": [
                  "metrics-homeassistant.*"
                ],
                "privileges": [
                  "manage",
                  "index",
                  "create_index",
                  "create"
                ]
              }
            ]
          }
        }
      }
    '
    ```

    1. Replace `https://localhost:9200` with the URL of your Elasticsearch instance.
    2. Replace `elastic` with your Elasticsearch username.
    3. Replace `changeme` with your Elasticsearch password.

=== "Dev Tools"
    ```
    POST /_security/api_key
    {
      "name": "home_assistant_component",
      "role_descriptors": {
        "hass_writer": {
          "cluster": [
            "manage_index_templates",
            "monitor"
          ],
          "indices": [
            {
              "names": [
                "metrics-homeassistant.*"
              ],
              "privileges": [
                "manage",
                "index",
                "create_index",
                "create"
              ]
            }
          ]
        }
      }
    }
    ```

The API Key will be returned in the response. Save the `encoded` field for use in the configuration.

Read the [Elasticsearch documentation](https://www.elastic.co/guide/en/elasticsearch/reference/current/security-api-create-api-key.html) for more information on creating API Keys.

To use a username and password instead, the user needs the same privileges. Create a role with them, then a user with that role:

```
PUT /_security/role/hass_writer
{
  "cluster": [
    "manage_index_templates",
    "monitor"
  ],
  "indices": [
    {
      "names": [
        "metrics-homeassistant.*"
      ],
      "privileges": [
        "manage",
        "index",
        "create_index",
        "create"
      ]
    }
  ]
}

POST /_security/user/home_assistant
{
  "password": "<a strong password>",
  "roles": ["hass_writer"]
}
```

The integration checks these privileges when you add it, and shows an error if any are missing. If an existing entry loses them, Home Assistant asks you to reauthenticate.

## Add the integration

This component is configured interactively via Home Assistant's integration configuration page.

1. Verify you have restarted Home Assistant after installing the component.
2. From the [`Integrations` configuration menu](https://my.home-assistant.io/redirect/integrations/), add a new `Elasticsearch` integration.
3. Provide the URL of your elasticsearch server in the format `https://<host>:<port>`. For example, `https://localhost:9200`.
4. If the server's certificate is not trusted, you will be prompted for TLS settings.
5. If your Elasticsearch instance is secured, you will be prompted to choose an authentication method, then for its credentials.
6. Once the integration is setup, you may tweak all configuration options via the `Configure` button on the [integrations page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}.

The setup asks for the following, depending on your cluster:

- `URL to access the Elasticsearch Cluster` - The address of your cluster, including the scheme and port.
- `Verify TLS certificate` - Check that the server's certificate is signed by a trusted certificate authority. Only asked when the certificate is not trusted. Turning this off leaves the connection open to interception.
- `Verify hostname matches server certificate` - Check that the certificate was issued for the host in the URL. This only applies when the certificate is verified.
- `Fully qualified path to custom certificate authority` - The path to a PEM-encoded CA file on the machine running Home Assistant. Leave empty to use the system's trusted certificates. See [Custom certificate authority (CA)](#custom-certificate-authority-ca).
- `Authentication method` - `Authenticate using an API Key` or `Authenticate using Username/Password`. Only asked when the cluster requires authentication.
- `Username` and `Password` - An Elasticsearch user with the [privileges listed above](#credentials).
- `API Key` - The `encoded` value of an API key created as [shown above](#credentials).

Each Elasticsearch cluster can only be added once, even when it can be reached through more than one URL.

## Change connection settings

To change the URL or TLS settings of an existing integration entry, open the entry's menu on the [integrations page](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"} and select `Reconfigure`. Your credentials and configuration options are kept.

The form shows the entry's current settings:

- `URL to access the Elasticsearch Cluster` - The address of your cluster, including the scheme and port.
- `Verify TLS certificate` - Check that the server's certificate is signed by a trusted certificate authority.
- `Verify hostname matches server certificate` - Check that the certificate was issued for the host in the URL.
- `Fully qualified path to custom certificate authority` - Leave empty to use the system's trusted certificates.

The new settings are tested with the entry's saved credentials before they are saved. If the cluster rejects those credentials, you will be prompted for new ones, using the same authentication method.

The new URL must reach the same Elasticsearch cluster. To publish to a different cluster, add it as a new integration entry.

!!! note
    An entry that has no saved TLS settings verifies the server's certificate and hostname. If an entry stops connecting after an update because its certificate can't be verified, use `Reconfigure` to provide a CA path or turn verification off.

## Configuration options

Select `Configure` from the integration's homepage to configure the following settings.

[![Open your Home Assistant instance and show the Elasticsearch integration.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=elasticsearch){:target="_blank"}

### Send events to Elasticsearch at this interval
The frequency at which events are published to Elasticsearch, in seconds, from `0` to `600`. The default is `60`. Setting it to `0` stops publishing entirely.

### Gather all entity states at this interval
The frequency at which all entity states are gathered, in seconds, from `0` to `3600`. The default is `60`. Setting it to `0` turns off gathering, so only changes are published.

### Choose what types of entity changes to listen for and publish
There are two types of entity changes that can be published to Elasticsearch:
- `Track entities with state changes` - Publish entities when their state changes
- `Track entities with attribute changes` - Publish entities when their attributes change

Enabling both options will publish entities when either their state or attributes change.

### Tags to apply to all published events
Tags are values that can be used to filter events in Elasticsearch. You can use this to add tags to all published events.

### Toggle to only publish the set of targets below

Pick floor, area, device, entity, or labels and only publish events from one of these targets. If you select multiple targets, events that match any of the targets will be published. If you select no targets, no events will be published.

An entity without an area of its own uses the area of its device, and belongs to the floor of that area.

Label targets match labels assigned directly to either the entity or its device. See [Published fields](published_fields.md) for how labels, areas, and floors appear in Elasticsearch documents.

### Toggle to exclude publishing the set of targets below

Pick floor, area, device, entity, or labels and exclude events from one of these targets. If you select multiple targets, events that match any of the targets will be excluded. If you also configure `Toggle to only publish the set of targets below`, the exclusion will be applied after the inclusion.

## Advanced configuration

### Custom certificate authority (CA)

This component will use the system's default certificate authority (CA) bundle to verify the Elasticsearch server's certificate. If you need to use a custom CA, you can provide the path to the CA file in the integration configuration.

1. Place the CA file somewhere within Home Assistant's `configuration` directory.
2. Follow the steps above to [add the integration](#add-the-integration).
3. After providing connection details, the component will attempt to establish a connection to the Elasticsearch server. If the server's certificate is not signed by a known CA, you will be prompted for the CA file's path.
4. Provide the path to the CA file and continue with the setup.

!!! note
    You can choose to bypass certificate verification during setup, if you do not have the CA file available.

To change the CA path or the verification settings later, [reconfigure the entry](#change-connection-settings).
