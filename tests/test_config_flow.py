"""Test Config Flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import (
    AsyncMock,
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
            (
                InsufficientPrivileges,
                "basic_auth",
                FlowResultType.FORM,
                {"basic_auth": "insufficient_privileges"},
            ),
            (AuthenticationRequired, "basic_auth", FlowResultType.FORM, {"basic_auth": "invalid_basic_auth"}),
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
            (InsufficientPrivileges, "api_key", FlowResultType.FORM, {"api_key": "insufficient_privileges"}),
            (AuthenticationRequired, "api_key", FlowResultType.FORM, {"api_key": "invalid_api_key"}),
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

    @pytest.mark.parametrize(
        ("user_input", "security_enabled"),
        [
            ({CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}, False),
            ({CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}, True),
            ({CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_API_KEY: "1234"}, True),
            ({CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_USERNAME: "user", CONF_PASSWORD: "password"}, True),
        ],
        ids=["no_auth_security_off", "no_auth", "api_key", "basic_auth"],
    )
    async def test_user_done(self, hass, user_input, security_enabled, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL + "/_xpack/usage", json={"security": {"enabled": security_enabled}}
        )
        es_aioclient_mock.post(
            TEST_CONFIG_ENTRY_DATA_URL + "/_security/user/_has_privileges", json={"has_all_requested": True}
        )

        result: ConfigFlowResult = await elastic_flow.async_step_user(user_input=user_input)

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == user_input
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
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL + "/_xpack/usage", json={"security": {"enabled": True}}
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
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL + "/_xpack/usage", json={"security": {"enabled": True}}
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

    async def test_cert_error_cannot_connect(self, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            side_effect=CannotConnect("specific error"),
        ):
            result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues(
                user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_VERIFY_SSL: False}
            )

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "errors" in result and result["errors"] == {"base": "cannot_connect"}
        assert "step_id" in result and result["step_id"] == "user"

    async def test_user_untrusted_cert_done(self, hass, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            exc=client_exceptions.ClientConnectorCertificateError(
                connection_key=MagicMock(), certificate_error=Exception("AHHHHH")
            ),
            headers={"x-elastic-product": "Elasticsearch"},
        )
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL + "/_xpack/usage", json={"security": {"enabled": True}}
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
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL + "/_xpack/usage", json={"security": {"enabled": True}}
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

    async def test_untrusted_auth(self, hass, elastic_flow, es_aioclient_mock):
        """Test user initiated step."""

        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            status=401,
            headers={"x-elastic-product": "Elasticsearch"},
        )

        elastic_flow._prospective_config = {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}

        next_result: ConfigFlowResult = await elastic_flow.async_step_certificate_issues(
            user_input={CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}, errors={"base": "untrusted_certificate"}
        )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.FORM
        assert "step_id" in next_result and next_result["step_id"] == "authentication_issues"

    @pytest.mark.parametrize(
        ("status_code", "error"),
        [
            (401, {"basic_auth": "invalid_basic_auth"}),
            (403, {"basic_auth": "insufficient_privileges"}),
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

        # Now success
        es_aioclient_mock.clear_requests()
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            return_value=True,
        ):
            next_result: ConfigFlowResult = await elastic_flow.async_step_basic_auth(
                user_input={CONF_USERNAME: "user", CONF_PASSWORD: "password"}
            )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in next_result and next_result["title"] == TEST_CONFIG_ENTRY_DATA_URL

    @pytest.mark.parametrize(
        ("status_code", "error"),
        [
            (401, {"api_key": "invalid_api_key"}),
            (403, {"api_key": "insufficient_privileges"}),
        ],
        ids=["401 = invalid basic auth", "403 = insufficient_privileges"],
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

        # Now success
        es_aioclient_mock.clear_requests()
        es_aioclient_mock.get(
            TEST_CONFIG_ENTRY_DATA_URL,
            json=CLUSTER_INFO_8DOT14_RESPONSE_BODY,
            status=200,
            headers={"x-elastic-product": "Elasticsearch"},
        )
        with mock.patch(
            "custom_components.elasticsearch.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop",
            return_value=True,
        ):
            next_result: ConfigFlowResult = await elastic_flow.async_step_api_key(
                user_input={CONF_API_KEY: "5678"}
            )

        assert next_result is not None
        assert "type" in next_result and next_result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in next_result and next_result["title"] == TEST_CONFIG_ENTRY_DATA_URL

    @pytest.mark.parametrize(
        ("data", "result_type", "step_id"),
        [
            ({CONF_URL: TEST_CONFIG_ENTRY_DATA_URL}, FlowResultType.ABORT, None),
            ({CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_API_KEY: "1234"}, FlowResultType.FORM, "api_key"),
            (
                {CONF_URL: TEST_CONFIG_ENTRY_DATA_URL, CONF_USERNAME: "user", CONF_PASSWORD: "password"},
                FlowResultType.FORM,
                "basic_auth",
            ),
        ],
        ids=["no_auth", "api_key", "basic_auth"],
    )
    async def test_reauth_done(
        self, hass, elastic_flow, config_entry, es_aioclient_mock, data, result_type, step_id
    ):
        """Test reauthorization."""

        elastic_flow.hass = hass
        elastic_flow.context = {"source": "reauth", "entry_id": config_entry.entry_id}

        result: ConfigFlowResult = await elastic_flow.async_step_reauth()

        assert result is not None
        assert "type" in result and result["type"] == result_type
        if step_id is not None:
            assert "step_id" in result and result["step_id"] == step_id
        else:
            assert "step_id" not in result

    async def test_reauth_missing_entry(self, hass, elastic_flow, config_entry, es_aioclient_mock):
        """Test reauthorization."""

        elastic_flow.hass = hass
        elastic_flow.context = {"source": "reauth", "entry_id": "100"}

        result: ConfigFlowResult = await elastic_flow.async_step_reauth()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.ABORT

    async def test_reauth_complete(self, hass, elastic_flow, config_entry, es_aioclient_mock):
        """Test reauthorization results in reload."""

        elastic_flow.hass = hass
        elastic_flow.context = {"source": "reauth", "entry_id": config_entry.entry_id}
        elastic_flow._reauth_entry = config_entry

        elastic_flow.async_update_reload_and_abort = AsyncMock()

        await elastic_flow.async_step_complete()

        elastic_flow.async_update_reload_and_abort.assert_called_once()

    async def test_async_step_options(self, hass, config_entry, elastic_flow):
        """Test user initiated step."""

        options_flow = elastic_flow.async_get_options_flow(config_entry)
        options_flow.hass = hass

        result: ConfigFlowResult = await options_flow.async_step_init()

        assert result is not None
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "options"
        assert "data_schema" in result and result["data_schema"] is not None

    async def test_async_step_options_done(self, hass, config_entry, elastic_flow):
        """Test user initiated step."""

        options_flow = elastic_flow.async_get_options_flow(config_entry)
        options_flow.hass = hass

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
