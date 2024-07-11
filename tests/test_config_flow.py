"""Test Config Flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import (
    MagicMock,
)

import pytest
from aiohttp import client_exceptions
from custom_components.elasticsearch.config_flow import (
    ElasticFlowHandler,
    ElasticOptionsFlowHandler,
)
from custom_components.elasticsearch.const import (
    CONF_AUTHENTICATION_TYPE,
    CONF_CHANGE_DETECTION_ENABLED,
    CONF_POLLING_FREQUENCY,
    CONF_PUBLISH_FREQUENCY,
    ELASTIC_DOMAIN,
)
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    UntrustedCertificate,
)
from homeassistant.config_entries import HANDLERS
from homeassistant.const import (
    CONF_API_KEY,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.data_entry_flow import (
    FlowResultType,
)
from pytest_homeassistant_custom_component.common import (
    mock_config_flow as new_mock_config_flow,
)
from pytest_homeassistant_custom_component.common import (
    mock_platform as new_mock_platform,
)

from tests.const import CLUSTER_INFO_8DOT14_RESPONSE_BODY, TEST_CONFIG_ENTRY_DATA_URL

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant


@pytest.fixture
async def mock_platform(hass: HomeAssistant):
    """Set up the platform for testing."""
    return new_mock_platform(hass, f"{ELASTIC_DOMAIN}.config_flow")


@pytest.fixture(autouse=True)
def config_flow(mock_platform, elastic_flow):
    """Set up the Elastic Integration config flow."""
    with new_mock_config_flow(ELASTIC_DOMAIN, elastic_flow):
        yield


@pytest.fixture
def elastic_flow():
    """Return a default ElasticFlowHandler."""
    return HANDLERS[ELASTIC_DOMAIN]()


class Test_Public_Methods:
    """Unit Tests for Config Flow."""

    async def test_step_user_show_form(
        self,
        elastic_flow: ElasticFlowHandler,
    ):
        """Test user initiated step."""

        result: ConfigFlowResult = await elastic_flow.async_step_user()

        assert result is not None

        assert "type" in result
        assert result["type"] == FlowResultType.FORM

        assert "step_id" in result
        assert "step_id" in result and result["step_id"] == "user"

        assert "data_schema" in result and result["data_schema"] is not None
        assert CONF_URL in result["data_schema"].schema

    async def test_step_user_done(
        self,
        elastic_flow: ElasticFlowHandler,
    ):
        """Test user initiated step."""
        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            return_value=True,
        ):
            result: ConfigFlowResult = await elastic_flow.async_step_user(
                user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
            )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

        assert result is not None

    @pytest.mark.parametrize(
        ("exception", "step_id"),
        [
            (UntrustedCertificate, "certificate_issues"),
            (CannotConnect, "user"),
            (AuthenticationRequired, "authentication_issues"),
        ],
    )
    async def test_step_user_extra_steps(
        self,
        elastic_flow: ElasticFlowHandler,
        exception,
        step_id,
    ):
        """Test user initiated step."""

        # Fill out the form
        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            side_effect=exception(),
        ):
            next_result: ConfigFlowResult = await elastic_flow.async_step_user(
                user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
            )

        assert "step_id" in next_result
        assert next_result["step_id"] == step_id

    async def test_step_certificate_issues_show_form(
        self,
        elastic_flow: ElasticFlowHandler,
    ):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "certificate_issues"
        assert "data_schema" in result and result["data_schema"] is not None

    async def test_step_certificate_issues_done(
        self,
        elastic_flow: ElasticFlowHandler,
    ):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            return_value=True,
        ):
            result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues(
                user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_VERIFY_SSL: False}
            )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {
            CONF_URL: TEST_CONFIG_ENTRY_DATA_URL,
            CONF_VERIFY_SSL: False,
        }
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

    @pytest.mark.parametrize(
        ("choice", "step_id"),
        [
            ("basic_auth", "basic_auth"),
            ("api_key", "api_key"),
        ],
    )
    async def test_authentication_issues(
        self,
        elastic_flow: ElasticFlowHandler,
        choice,
        step_id,
    ):
        """Test user initiated step."""

        result: ConfigFlowResult = await elastic_flow.async_step_authentication_issues()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "authentication_issues"
        assert "data_schema" in result and result["data_schema"] is not None

        next_result: ConfigFlowResult = await elastic_flow.async_step_authentication_issues(
            user_input={CONF_AUTHENTICATION_TYPE: choice}
        )

        assert "step_id" in next_result
        assert next_result["step_id"] == step_id

    @pytest.mark.parametrize(
        ("exception", "step_id", "result_type", "error"),
        [
            (InsufficientPrivileges, "basic_auth", FlowResultType.FORM, {"base": "insufficient_privileges"}),
            (AuthenticationRequired, "basic_auth", FlowResultType.FORM, {"base": "invalid_basic_auth"}),
        ],
    )
    async def test_step_basic_auth(
        self, elastic_flow: ElasticFlowHandler, exception, step_id, result_type, error
    ):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            side_effect=exception(),
        ):
            next_result: ConfigFlowResult = await elastic_flow.async_step_basic_auth(
                user_input={CONF_USERNAME: "user", CONF_PASSWORD: "password"}
            )

        if step_id is not None:
            assert "step_id" in next_result
            assert next_result["step_id"] == step_id

        assert "type" in next_result and next_result["type"] == result_type
        assert "errors" in next_result and next_result["errors"] == error

    @pytest.mark.parametrize(
        ("exception", "step_id", "result_type", "error"),
        [
            (InsufficientPrivileges, "api_key", FlowResultType.FORM, {"base": "insufficient_privileges"}),
            (AuthenticationRequired, "api_key", FlowResultType.FORM, {"base": "invalid_api_key"}),
        ],
    )
    async def test_step_api_key(
        self, elastic_flow: ElasticFlowHandler, exception, step_id, result_type, error
    ):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            side_effect=exception(),
        ):
            next_result: ConfigFlowResult = await elastic_flow.async_step_api_key(
                user_input={CONF_API_KEY: "1234"}
            )

        if step_id is not None:
            assert "step_id" in next_result
            assert next_result["step_id"] == step_id

        assert "type" in next_result and next_result["type"] == result_type
        assert "errors" in next_result and next_result["errors"] == error


class Test_Integration_Tests:
    """Integration Tests for Config Flow."""

    async def test_user_done(self, hass, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.post(
            TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges", json={"has_all_requested": True}
        )

        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

    async def test_user_authentication_issues_done(self, hass, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL, status=401, headers={"x-elastic-product": "Elasticsearch"}
        )

        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "authentication_issues"

    async def test_user_authentication_issues_authentication_issues_done(
        self, hass, elastic_flow, es_aioclient_mock
    ):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL, status=401, headers={"x-elastic-product": "Elasticsearch"}
        )

        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "authentication_issues"

    async def test_user_authentication_issues_insufficient_privileges_done(
        self, hass, elastic_flow, es_aioclient_mock
    ):
        """Test user initiated step."""

        # Handle a user that does not have the necessary privileges
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.post(
            TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges", json={"has_all_requested": False}
        )

        # Now pass input into the form and make sure we get redirected back to this form
        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "authentication_issues"

        # Handle a 403
        es_aioclient_mock.clear_requests()
        es_aioclient_mock.get(TEST_CONFIG_ENTRY_DATA_URL, status=403)

        # Now pass input into the form and make sure we get redirected back to this form
        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "authentication_issues"

        # Now make it work
        es_aioclient_mock.clear_requests()
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.post(
            TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges", json={"has_all_requested": True}
        )

        # Now pass input into the form and make sure we get a new config entry
        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

    async def test_user_untrusted_cert_done(self, hass, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            exc=client_exceptions.ClientConnectorCertificateError(
                connection_key=MagicMock(), certificate_error=Exception("AHHHHH")
            ),
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.post(
            TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges",
            json={"has_all_requested": True},
        )

        result: ConfigFlowResult = await elastic_flow.async_step_user(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "certificate_issues"

        # Bypass Certificate Issues
        es_aioclient_mock.clear_requests()
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.post(
            TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges", json={"has_all_requested": True}
        )

        # Now pass input into the form and make sure we get a new config entry
        next_result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_VERIFY_SSL: False}
        )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in next_result and next_result["title"] == TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in next_result and next_result["data"] == {
            CONF_URL: TEST_CONFIG_ENTRY_DATA_URL,
            CONF_VERIFY_SSL: False,
        }
        assert (
            "options" in next_result and next_result["options"] == ElasticOptionsFlowHandler.default_options
        )

    async def test_untrusted_untrusted_done(self, hass, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            exc=client_exceptions.ClientConnectorCertificateError(
                connection_key=MagicMock(), certificate_error=Exception("AHHHHH")
            ),
            headers={"x-elastic-product": "Elasticsearch"},
        )

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "certificate_issues"

        # Now pass input into the form and make sure we get redirected back to the same form
        next_result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}, errors={"base": "untrusted_certificate"}
        )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.FORM
        assert "step_id" in next_result and next_result["step_id"] == "certificate_issues"
        assert "errors" in next_result and next_result["errors"] == {"base": "untrusted_certificate"}

    @pytest.mark.parametrize(
        ("status_code", "error"),
        [
            (401, {"base": "invalid_basic_auth"}),
            (403, {"base": "insufficient_privileges"}),
        ],
        ids=["401 = invalid_basic_auth", "403 = insufficient_privileges"],
    )
    async def test_basic_basic_done(self, elastic_flow, status_code, error, es_aioclient_mock):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        result: ConfigFlowResult = await elastic_flow.async_step_basic_auth()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "basic_auth"

        # Now pass input into the form and make sure we get redirected back to the same form
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL, status=status_code, headers={"x-elastic-product": "Elasticsearch"}
        )

        next_result: ConfigFlowResult = await elastic_flow.async_step_basic_auth(
            user_input={CONF_USERNAME: "user", CONF_PASSWORD: "password"}
        )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.FORM
        assert "step_id" in next_result and next_result["step_id"] == "basic_auth"
        assert "errors" in next_result and next_result["errors"] == error

    @pytest.mark.parametrize(
        ("status_code", "error"),
        [
            (401, {"base": "invalid_api_key"}),
            (403, {"base": "insufficient_privileges"}),
        ],
        ids=["401 = invalid_api_key", "403 = insufficient_privileges"],
    )
    async def test_api_api_done(self, elastic_flow, status_code, error, es_aioclient_mock):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        result: ConfigFlowResult = await elastic_flow.async_step_api_key()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "api_key"

        # Now pass input into the form and make sure we get redirected back to the same form
        es_aioclient_mock.get(TEST_CONFIG_ENTRY_DATA_URL, status=status_code)

        next_result: ConfigFlowResult = await elastic_flow.async_step_api_key(
            user_input={CONF_API_KEY: "1234"}
        )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.FORM
        assert "step_id" in next_result and next_result["step_id"] == "api_key"
        assert "errors" in next_result and next_result["errors"] == error

    async def test_async_step_options(self, hass, config_entry):
        """Test user initiated step."""

        options_flow = ElasticOptionsFlowHandler(config_entry)
        result: ConfigFlowResult = await options_flow.async_step_init()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "options"
        assert "data_schema" in result and result["data_schema"] is not None

    async def test_async_step_options_done(self, hass, config_entry):
        """Test user initiated step."""

        options_flow = ElasticOptionsFlowHandler(config_entry)

        await options_flow.async_step_init()

        result: ConfigFlowResult = await options_flow.async_step_options(
            user_input={
                CONF_CHANGE_DETECTION_ENABLED: False,
                CONF_PUBLISH_FREQUENCY: 60,
                CONF_POLLING_FREQUENCY: 90,
            }
        )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == ""
        assert "data" in result and result["data"] == {
            "change_detection_enabled": False,
            "change_detection_type": [],
            "exclude_targets": False,
            "include_targets": False,
            "polling_frequency": 90,
            "publish_frequency": 60,
            "tags": [],
            "targets_to_exclude": {},
            "targets_to_include": {},
        }

    # async def test_async_stop_reauth(self, elastic_flow, config_entry):
    #     """Test user initiated step."""

    #     reuath_flow = ElasticFlowHandler()

    #     await reauth_flow.async_init()

    #     reauth_flow.config_entry = config_entry

    #     result: ConfigFlowResult = await reauth_flow.

    #     assert result is not None
    #     assert "type" in result and result["type"] == FlowResultType.ABORT
    #     assert "reason" in result and result["reason"] == "no_entry"
    #     assert "step_id" in result and result["step_id"] == "reauth"

    # async def async_step_reauth(self, user_input: dict | None) -> ConfigFlowResult:
    #     """Handle reauthorization."""
    #     entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
    #     if entry is None:
    #         return self.async_abort(reason="no_entry")

    #     self._reauth_entry = entry

    #     self._prospective_config = dict(entry.data)

    #     if self._prospective_config.get(CONF_USERNAME, None) is not None:
    #         return await self.async_step_basic_auth()
    #     if self._prospective_config.get(CONF_API_KEY, None) is not None:
    #         return await self.async_step_api_key()

    #     return self.async_abort(reason="no_auth")

    # @async_log_enter_exit_debug
    # async def async_step_options(
    #     self,
    #     user_input: dict | None = None,
    # ) -> ConfigFlowResult:
    #     """Publish Options."""
    #     if user_input is not None:
    #         self.options.update(user_input)
    #         self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
    #         return self.async_create_entry(title="", data=self.options)

    #     return self.async_show_form(
    #         step_id="options",
    #         data_schema=self._build_options_schema(),
    #     )

    # @log_enter_exit_debug
    # def _build_options_schema(self) -> vol.Schema:
    #     """Build the options schema."""

    #     from_options = self.config_entry.options.get

    #     SCHEMA_PUBLISH_FREQUENCY = {
    #         "schema": CONF_PUBLISH_FREQUENCY,
    #         "default": from_options(CONF_PUBLISH_FREQUENCY),
    #     }
    #     SCHEMA_POLLING_FREQUENCY = {
    #         "schema": CONF_POLLING_FREQUENCY,
    #         "default": from_options(CONF_POLLING_FREQUENCY),
    #     }

    #     SCHEMA_CHANGE_DETECTION_TYPE = {
    #         "schema": CONF_CHANGE_DETECTION_TYPE,
    #         "default": from_options(CONF_CHANGE_DETECTION_TYPE),
    #     }
    #     SCHEMA_TAGS = {
    #         "schema": CONF_TAGS,
    #         "default": from_options(CONF_TAGS),
    #     }
    #     SCHEMA_INCLUDE_TARGETS = {
    #         "schema": CONF_INCLUDE_TARGETS,
    #         "default": from_options(CONF_INCLUDE_TARGETS),
    #     }
    #     SCHEMA_TARGETS_TO_INCLUDE = {
    #         "schema": CONF_TARGETS_TO_INCLUDE,
    #         "default": from_options(CONF_TARGETS_TO_INCLUDE),
    #     }

    #     SCHEMA_EXCLUDE_TARGETS = {
    #         "schema": CONF_EXCLUDE_TARGETS,
    #         "default": from_options(CONF_EXCLUDE_TARGETS),
    #     }
    #     SCHEMA_TARGETS_TO_EXCLUDE = {
    #         "schema": CONF_TARGETS_TO_EXCLUDE,
    #         "default": from_options(CONF_TARGETS_TO_EXCLUDE),
    #     }

    #     return vol.Schema(
    #         {
    #             vol.Optional(**SCHEMA_PUBLISH_FREQUENCY): NumberSelector(
    #                 NumberSelectorConfig(
    #                     min=0,
    #                     max=600,
    #                     step=10,
    #                     unit_of_measurement="seconds",
    #                 )
    #             ),
    #             vol.Optional(**SCHEMA_POLLING_FREQUENCY): NumberSelector(
    #                 NumberSelectorConfig(
    #                     min=0,
    #                     max=3600,
    #                     step=10,
    #                     unit_of_measurement="seconds",
    #                 )
    #             ),
    #             vol.Optional(**SCHEMA_CHANGE_DETECTION_TYPE): SelectSelector(
    #                 SelectSelectorConfig(
    #                     options=[
    #                         {
    #                             "label": "Track entities with state changes",
    #                             "value": StateChangeType.STATE.value,
    #                         },
    #                         {
    #                             "label": "Track entities with attribute changes",
    #                             "value": StateChangeType.ATTRIBUTE.value,
    #                         },
    #                     ],
    #                     multiple=True,
    #                 )
    #             ),
    #             vol.Optional(**SCHEMA_TAGS): SelectSelector(
    #                 SelectSelectorConfig(options=[], custom_value=True, multiple=True)
    #             ),
    #             vol.Optional(**SCHEMA_INCLUDE_TARGETS): BooleanSelector(
    #                 BooleanSelectorConfig(),
    #             ),
    #             vol.Optional(**SCHEMA_TARGETS_TO_INCLUDE): TargetSelector(
    #                 TargetSelectorConfig(),
    #             ),
    #             vol.Optional(**SCHEMA_EXCLUDE_TARGETS): BooleanSelector(
    #                 BooleanSelectorConfig(),
    #             ),
    #             vol.Optional(**SCHEMA_TARGETS_TO_EXCLUDE): TargetSelector(
    #                 TargetSelectorConfig(),
    #             ),
    #         }
    #     )
