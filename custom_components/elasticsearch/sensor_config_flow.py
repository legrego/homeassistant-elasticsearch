"""Add and reconfigure query sensor subentries with an executed preview."""

from __future__ import annotations

import html
import json
import math
from typing import Any

import probatio
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntryState,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .errors import AuthenticationRequired, InsufficientPrivileges
from .esql import QueryResult
from .query_sensor import (
    CONF_INTERVAL,
    CONF_MAX_AGE,
    CONF_TIMESTAMP_COLUMN,
    CONF_VALUE_COLUMN,
    SUPPORTED_DEVICE_CLASSES,
    SensorQueryError,
    error_code,
    read_sensor_result,
    validate_result,
)


def _parameters(value: str) -> list[Any]:
    """Accept a JSON array of static positional values, including nulls."""
    try:
        params = json.loads(value)
    except (ValueError, TypeError) as err:
        raise SensorQueryError("invalid_params") from err
    if not isinstance(params, list) or any(
        item is not None
        and (
            not isinstance(item, str | int | float | bool)
            or isinstance(item, float)
            and not math.isfinite(item)
        )
        for item in params
    ):
        raise SensorQueryError("invalid_params")
    return params


def _preview(result: QueryResult) -> str:
    """Render bounded, escaped preview cells without embedding active markup."""

    def cell(value: Any) -> str:
        text = str(value) if value is not None else "null"
        text = text[:256] + ("…" if len(text) > 256 else "")
        return (
            html.escape(text)
            .replace("|", "&#124;")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("`", "&#96;")
            .replace("[", "&#91;")
            .replace("*", "&#42;")
            .replace("_", "&#95;")
        )

    # A vertical table keeps wide result sets readable. Actual validation uses all columns.
    return "\n".join(
        f"| {cell(column.name)} | {cell(column.type)} | {cell(result.rows[0].get(column.name))} |"
        for column in result.columns[:30]
    )


class QuerySensorSubentryFlow(ConfigSubentryFlow):
    """One saved ES|QL query produces one sensor."""

    def __init__(self) -> None:
        """Hold prospective settings only for this flow."""
        self._config: dict[str, Any] = {}
        self._result: QueryResult | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Enter and execute the query before configuring its mapping."""
        return await self.async_step_query(user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Reuse the saved identity while allowing every setting to change."""
        subentry = self._get_reconfigure_subentry()
        self._config = {**subentry.data, "name": subentry.title}
        return await self.async_step_query(user_input)

    async def async_step_query(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Execute through the same bounded runner used by the action."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="connection_unloaded")
        errors = {}
        if user_input is not None:
            try:
                name = cv.string(user_input["name"]).strip()
                query = cv.string(user_input["query"]).strip()
                if not name or not query:
                    raise SensorQueryError("empty_query")
                params = _parameters(user_input.get("params", "[]"))
                self._config.update(name=name, query=query, params=params)
                result = await entry.runtime_data.query_runner.async_query(query, params)
                validate_result(result)
                self._result = result
            except Exception as err:  # noqa: BLE001
                if isinstance(err, AuthenticationRequired) and not isinstance(err, InsufficientPrivileges):
                    entry.async_start_reauth(self.hass)
                errors["base"] = error_code(err)
            else:
                if not result.rows:
                    return await self.async_step_empty()
                return await self.async_step_mapping()
        defaults = {**self._config, "params": json.dumps(self._config.get("params", []))}
        return self.async_show_form(
            step_id="query",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required("name"): TextSelector(),
                        probatio.Required("query"): TextSelector(TextSelectorConfig(multiline=True)),
                        probatio.Optional("params", default="[]"): TextSelector(
                            TextSelectorConfig(multiline=True)
                        ),
                    }
                ),
                user_input or defaults,
            ),
            errors=errors,
        )

    async def async_step_empty(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Explicitly confirm an empty observation set before choosing columns."""
        if user_input is not None:
            return await self.async_step_mapping()
        return self.async_show_form(step_id="empty", data_schema=probatio.Schema({}))

    async def async_step_mapping(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Preview the table, select columns, and validate metadata before saving."""
        assert self._result is not None
        result = self._result
        errors = {}
        if user_input is not None:
            # Replace optional fields rather than retaining cleared metadata on reconfigure.
            config = {key: self._config[key] for key in ("name", "query", "params")}
            config.update({key: value for key, value in user_input.items() if value not in (None, "")})
            try:
                read_sensor_result(result, config, check_freshness=False)
            except SensorQueryError as err:
                errors["base"] = err.code
            else:
                name = config.pop("name")
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_update_and_abort(
                        self._get_entry(), self._get_reconfigure_subentry(), title=name, data=config
                    )
                return self.async_create_entry(title=name, data=config)
        columns = [column.name for column in result.columns]
        timestamps = [column.name for column in result.columns if column.type in {"date", "date_nanos"}]
        schema = probatio.Schema(
            {
                probatio.Required(CONF_VALUE_COLUMN): SelectSelector(SelectSelectorConfig(options=columns)),
                probatio.Required(CONF_INTERVAL, default=60): NumberSelector(
                    NumberSelectorConfig(
                        min=10, max=86400, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="s"
                    )
                ),
                probatio.Optional("unit_of_measurement"): TextSelector(),
                probatio.Optional("device_class"): SelectSelector(
                    SelectSelectorConfig(options=SUPPORTED_DEVICE_CLASSES)
                ),
                probatio.Optional("state_class"): SelectSelector(
                    SelectSelectorConfig(options=[item.value for item in SensorStateClass])
                ),
                probatio.Optional(CONF_TIMESTAMP_COLUMN): SelectSelector(
                    SelectSelectorConfig(options=timestamps)
                ),
                probatio.Optional(CONF_MAX_AGE): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=31536000, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="s"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="mapping",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or self._config),
            errors=errors,
            description_placeholders={"preview": _preview(result) if result.rows else ""},
        )
