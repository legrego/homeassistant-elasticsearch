# Published fields

Each published document contains an entity's state, its Home Assistant registry metadata, and details about how it was collected. Use these fields to filter documents in Discover and build visualizations in Lens. See [Using Kibana](using_kibana.md) to create a data view first.

Fields whose values are unavailable, `null`, or empty lists or objects are omitted. For example, an entity without a device has no `hass.entity.device.*` fields, and an entity without labels has no `hass.entity.labels` field.

## Entity identity and metadata

| Field | Type | Description |
| --- | --- | --- |
| `hass.entity.id` | Keyword | Full entity ID, such as `sensor.living_room_temperature`. |
| `hass.entity.object.id` | Keyword | Entity ID without its domain, such as `living_room_temperature`. |
| `hass.entity.domain` | Keyword | Entity domain, such as `sensor` or `climate`. |
| `hass.entity.friendly_name` | Keyword | Display name from the entity's state, falling back to its object ID with underscores replaced by spaces. Use this for a human-readable name in Kibana. |
| `hass.entity.name` | Keyword | Name from the entity registry: the user-provided name, or the integration's original name. This can differ from the friendly name. |
| `hass.entity.platform` | Keyword | Integration platform that provides the entity, such as `esphome`. |
| `hass.entity.device_class` | Keyword | Entity's device class from the registry, preferring a user override to the original class, such as `temperature`. |
| `hass.entity.unit_of_measurement` | Keyword | Unit recorded in the entity registry, such as `°C` or `kWh`. |
| `hass.entity.labels` | Keyword array | IDs of labels assigned directly to the entity. |
| `hass.entity.device.id` | Keyword | ID of the entity's device in the Home Assistant device registry. |
| `hass.entity.device.name` | Keyword | Device's user-provided name, or its original name. |
| `hass.entity.device.labels` | Keyword array | IDs of labels assigned directly to the device. |

Label values are registry IDs, such as `energy_monitoring`, rather than display names such as `Energy monitoring`. Entity labels and device labels are published separately; neither list includes the other's labels or labels assigned to an area.

## Areas, floors, and coordinates

| Field | Type | Description |
| --- | --- | --- |
| `hass.entity.area.id` | Keyword | ID of the area assigned directly to the entity. |
| `hass.entity.area.name` | Keyword | Name of the area assigned directly to the entity. |
| `hass.entity.area.floor.id` | Keyword | ID of the floor containing the entity's directly assigned area. |
| `hass.entity.area.floor.name` | Keyword | Name of that floor. |
| `hass.entity.device.area.id` | Keyword | ID of the area assigned to the device. |
| `hass.entity.device.area.name` | Keyword | Name of the area assigned to the device. |
| `hass.entity.device.area.floor.id` | Keyword | ID of the floor containing the device's area. |
| `hass.entity.device.area.floor.name` | Keyword | Name of that floor. |
| `hass.entity.location` | Geo point | Entity's coordinates as `[longitude, latitude]`, when both state attributes are available. |

The published entity area and floor describe only the entity's own area assignment. If the entity has no directly assigned area, those fields are omitted even when its device has an area. The device's area and floor remain available under `hass.entity.device.area.*`.

The [publish target filters](configure.md#toggle-to-only-publish-the-set-of-targets-below) use the device's area and floor when the entity has no area of its own. This fallback determines which events are published; it does not copy device metadata into the entity's fields.

## State values

| Field | Type | Description |
| --- | --- | --- |
| `hass.entity.value` | Text | Original state as a string, such as `"72.5"` or `"on"`. Use its `.keyword` subfield for exact matching or grouping. |
| `hass.entity.valueas.float` | Float | Numeric state, including whole numbers, such as `72.5` or `72.0`. Use this for numeric charts and aggregations. |
| `hass.entity.valueas.boolean` | Boolean | State converted to `true` or `false`. |
| `hass.entity.valueas.datetime` | Date | Parsed date and time, such as `2024-04-10T16:23:25.878000+00:00`. |
| `hass.entity.valueas.date` | Date | Date portion of a parsed datetime, such as `2024-04-10`. |
| `hass.entity.valueas.time` | Date | Time portion of a parsed datetime, such as `16:23:25.878000`. |
| `hass.entity.valueas.string` | Text | State when no boolean, numeric, or datetime conversion succeeds. Also has a `.keyword` subfield. |

The original `value` is always published. The integration attempts conversions in this order: boolean, number, then datetime. The first successful conversion determines which `valueas.*` fields appear. A datetime conversion produces all three of `datetime`, `date`, and `time`; otherwise, only one converted field is published.

Boolean conversion recognizes `true`, `on`, `locked`, `above_horizon`, `open`, and `home` as `true`; `false`, `off`, `unlocked`, `unknown`, `below_horizon`, `closed`, and `not_home` as `false`. Other states are tried as numbers and datetimes before falling back to a string.

## State attributes

Other supported state attributes appear under `hass.entity.attributes.*`. Attribute names are normalized to lowercase ASCII, with punctuation and whitespace replaced by underscores. For example, `Fan Speed` becomes `hass.entity.attributes.fan_speed`. If two names normalize to the same key, the later attribute replaces the earlier one.

The following attributes are excluded from this object:

| State attribute | Published representation |
| --- | --- |
| `friendly_name` | `hass.entity.friendly_name` |
| `device_class` | `hass.entity.device_class`, sourced from the entity registry |
| `unit_of_measurement` | `hass.entity.unit_of_measurement`, sourced from the entity registry |
| `entity_picture`, `icon`, `state_class` | Omitted. |

When updating older dashboards, use `hass.entity.friendly_name` instead of `hass.entity.attributes.friendly_name`. Device class and unit of measurement also have dedicated fields rather than copies under `attributes`.

Attributes are dynamically mapped as text with a `.keyword` subfield by default. Numeric state attributes therefore need a [custom attribute mapping](ingest_advanced.md#custom-attribute-mappings) if you want numeric aggregations. Dictionary-valued attributes are serialized as JSON strings; sets are converted to sorted lists. Attributes with unsupported value types or non-string or blank keys are skipped.

Date and time values nested inside list or dictionary attributes are serialized as ISO 8601 strings.

Outside the attributes object, extra fields without an explicit mapping are kept in the stored document but are not indexed for searching or aggregations. Add a custom mapping if you need to query those fields.

To reduce storage, you can [drop attributes with an ingest pipeline](ingest_advanced.md#drop-attributes-to-reduce-storage) while keeping entity states and metadata.

## Event, data stream, and host details

| Field | Type | Description |
| --- | --- | --- |
| `@timestamp` | Date with nanosecond precision | Time the state change was collected, or the time of the polling pass, rather than the time the batch reached Elasticsearch. |
| `event.action` | Keyword | Collection reason: `Polling`, `State change`, or `Attribute change`. |
| `event.kind` | Keyword | Always `event`. |
| `event.type` | Keyword | `info` for polling; `change` for state or attribute changes. |
| `data_stream.type` | Constant keyword | Always `metrics`. |
| `data_stream.dataset` | Constant keyword | `homeassistant.<domain>`, such as `homeassistant.sensor`. |
| `data_stream.namespace` | Constant keyword | Always `default`. |
| `tags` | Keyword array | Tags configured for all events. These are separate from Home Assistant labels. |
| `agent.version` | Keyword | Home Assistant version. |
| `host.architecture` | Keyword | Architecture reported by Home Assistant. |
| `host.os.name` | Keyword | Operating system name reported by Home Assistant. |
| `host.hostname` | Keyword | Supervisor-reported hostname when available, otherwise the runtime's hostname. |
| `host.location` | Geo point | Home Assistant's configured home coordinates as `[longitude, latitude]`. |

Host details and tags are gathered when the integration starts. Data stream fields determine the destination, such as `metrics-homeassistant.sensor-default`.

## Example document

This example shows a temperature entity assigned directly to the Living Room area, with an associated device in the same area. The area belongs to the Ground Floor. Host details are left out for brevity. Documents use dotted field names:

```json
{
  "@timestamp": "2026-11-06T18:00:00+00:00",
  "event.action": "State change",
  "event.kind": "event",
  "event.type": "change",
  "data_stream.type": "metrics",
  "data_stream.dataset": "homeassistant.sensor",
  "data_stream.namespace": "default",
  "hass.entity.id": "sensor.living_room_temperature",
  "hass.entity.object.id": "living_room_temperature",
  "hass.entity.domain": "sensor",
  "hass.entity.friendly_name": "Living Room Temperature",
  "hass.entity.name": "Temperature",
  "hass.entity.platform": "esphome",
  "hass.entity.device_class": "temperature",
  "hass.entity.unit_of_measurement": "°C",
  "hass.entity.labels": ["indoor"],
  "hass.entity.area.id": "living_room",
  "hass.entity.area.name": "Living Room",
  "hass.entity.area.floor.id": "ground_floor",
  "hass.entity.area.floor.name": "Ground Floor",
  "hass.entity.device.id": "abc123",
  "hass.entity.device.name": "Living Room Sensor",
  "hass.entity.device.labels": ["environment"],
  "hass.entity.device.area.id": "living_room",
  "hass.entity.device.area.name": "Living Room",
  "hass.entity.device.area.floor.id": "ground_floor",
  "hass.entity.device.area.floor.name": "Ground Floor",
  "hass.entity.attributes.battery_level": 95,
  "hass.entity.value": "21.5",
  "hass.entity.valueas.float": 21.5,
  "tags": ["home"]
}
```

## Filter by floor or label in Kibana

Use these examples in Discover's KQL search bar, replacing IDs with values from your documents.

To find entities on the Ground Floor, using the entity's own floor when assigned and otherwise the device's floor:

```text
hass.entity.area.floor.id: "ground_floor" or
(not hass.entity.area.id: * and hass.entity.device.area.floor.id: "ground_floor")
```

To find entities labeled `indoor` either directly or through their device:

```text
hass.entity.labels: "indoor" or hass.entity.device.labels: "indoor"
```
