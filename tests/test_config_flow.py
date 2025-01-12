"""Test the Config Flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import custom_components.elasticsearch.const as compconst
import homeassistant.const as haconst
import pytest
from custom_components.elasticsearch.config_flow import (
    ElasticOptionsFlowHandler,
)
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    UntrustedCertificate,
)
from homeassistant.data_entry_flow import (
    FlowResultType,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,  # noqa: F401
)

import tests.const as testconst

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.core import HomeAssistant


base_path = "custom_components.elasticsearch"
config_flow_setup_entry = f"{base_path}.async_setup_entry"
gateway_async_init = f"{base_path}.es_gateway_8.Elasticsearch8Gateway.async_init_then_stop"


async def add_config_entry_to_hass(hass: HomeAssistant, config_entry):
    """Add a config entry to hass."""
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert compconst.DOMAIN in hass.config_entries.async_domains()
    return config_entry


@pytest.fixture(autouse=True, name="skip_setup")
async def _skip_setup_fixture():
    """Patch config flow setup to return success. This prevents loading the integration."""
    with patch(config_flow_setup_entry, return_value=True):
        yield


class Test_Setup_Flows:
    """Test Config Flow."""

    @pytest.fixture
    async def initial_form(self, hass):
        """Perform the initial form steps."""
        result = await hass.config_entries.flow.async_init(compconst.DOMAIN, context={"source": "user"})

        # We should get a form to fill in the URL
        assert result is not None
        assert result.get("type") == "form"
        assert result.get("step_id") == "user"
        assert result.get("errors") is None

        return result["flow_id"]

    @pytest.fixture
    async def certificate_form(self, hass: HomeAssistant, initial_form):
        """Perform the initial steps until the certificate form appears."""

        with patch(gateway_async_init, side_effect=UntrustedCertificate):
            result = await hass.config_entries.flow.async_configure(
                initial_form,
                user_input={testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL},
            )

        assert result is not None
        assert result.get("type") == "form"
        assert result.get("step_id") == "certificate_issues"
        assert result.get("errors") is None

        return result["flow_id"]

    @pytest.fixture
    async def authentication_form(self, hass: HomeAssistant, initial_form):
        """Perform the initial steps until the authentication form appears."""
        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            result = await hass.config_entries.flow.async_configure(
                initial_form,
                user_input={testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL},
            )

        assert result is not None
        assert result.get("type") == "form"
        assert result.get("step_id") == "authentication_issues"
        assert result.get("errors") is None

        return result["flow_id"]

    async def test_full_flow(self, hass: HomeAssistant, initial_form):
        """Test the full config flow."""
        with patch(gateway_async_init, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                initial_form, user_input={testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL}
            )

        # The entry should be now created
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == testconst.TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {
            testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL
        }
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

    @pytest.mark.parametrize(
        ("exception", "step_id"),
        [
            (UntrustedCertificate, "certificate_issues"),
            (CannotConnect, "user"),
            (AuthenticationRequired, "authentication_issues"),
        ],
    )
    async def test_url_to_extra_steps(self, hass: HomeAssistant, initial_form, exception, step_id):
        """Test transitions from the url form to other forms."""
        with patch(gateway_async_init, side_effect=exception()):
            result = await hass.config_entries.flow.async_configure(
                initial_form, user_input={testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL}
            )

        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == step_id

    async def test_url_to_certificate_issues_to_done(self, hass: HomeAssistant, certificate_form):
        """Test transitions from the ssl settings form to entry creation."""
        with patch(gateway_async_init, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                certificate_form,
                user_input={
                    compconst.CONF_SSL_VERIFY_HOSTNAME: True,
                    haconst.CONF_VERIFY_SSL: True,
                },
            )

        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == testconst.TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {
            testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL,
            compconst.CONF_SSL_VERIFY_HOSTNAME: True,
            haconst.CONF_VERIFY_SSL: True,
        }
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

    @pytest.mark.parametrize(
        ("exception", "step_id", "errors"),
        [
            (UntrustedCertificate, "certificate_issues", {"base": "untrusted_certificate"}),
            (CannotConnect, "user", {"base": "cannot_connect"}),
            (AuthenticationRequired, "authentication_issues", None),
        ],
        ids=[
            "Unresolved certificate issues",
            "Now cannot connect",
            "Now authentication required",
        ],
    )
    async def test_url_to_certificate_issue_to_extra_steps(
        self, hass: HomeAssistant, certificate_form, exception, step_id, errors
    ):
        """Test transitions from the ssl settings form to other forms."""
        with patch(gateway_async_init, side_effect=exception()):
            result = await hass.config_entries.flow.async_configure(
                certificate_form,
                user_input={
                    compconst.CONF_SSL_VERIFY_HOSTNAME: True,
                    haconst.CONF_VERIFY_SSL: True,
                },
            )

        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == step_id
        assert "errors" in result and result["errors"] == errors

    @pytest.mark.parametrize(
        ("authentication_type", "settings"),
        [
            (
                "basic_auth",
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
            ),
            ("api_key", {haconst.CONF_API_KEY: "api_key"}),
        ],
        ids=["Basic Auth", "API Key"],
    )
    async def test_url_to_authentication_issues_to_done(
        self, hass: HomeAssistant, authentication_form, authentication_type, settings
    ):
        """Test transitions from the authentication form to entry creation."""

        # Pick an authentication method from the form
        result = await hass.config_entries.flow.async_configure(
            authentication_form,
            user_input={
                compconst.CONF_AUTHENTICATION_TYPE: authentication_type,
            },
        )

        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == authentication_type

        # Now proceed on the form for the specific auth method
        with patch(gateway_async_init, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                authentication_form,
                user_input=settings,
            )

        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == testconst.TEST_CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {
            testconst.CONF_URL: testconst.TEST_CONFIG_ENTRY_DATA_URL,
            **settings,
        }
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options

    @pytest.mark.parametrize(
        ("authentication_type", "settings", "exception", "step_id", "errors"),
        [
            (
                "api_key",
                {haconst.CONF_API_KEY: "api_key"},
                InsufficientPrivileges,
                "api_key",
                {"base": "insufficient_privileges"},
            ),
            (
                "api_key",
                {haconst.CONF_API_KEY: "api_key"},
                AuthenticationRequired,
                "api_key",
                {"base": "invalid_api_key"},
            ),
            (
                "basic_auth",
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
                InsufficientPrivileges,
                "basic_auth",
                {"base": "insufficient_privileges"},
            ),
            (
                "basic_auth",
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
                AuthenticationRequired,
                "basic_auth",
                {"base": "invalid_basic_auth"},
            ),
        ],
        ids=[
            "API Key Insufficient Privileges",
            "API Key Invalid",
            "Basic Auth Insufficient Privileges",
            "Basic Auth Invalid",
        ],
    )
    async def test_url_to_authentication_issues_to_extra_steps(
        self,
        hass: HomeAssistant,
        authentication_form,
        authentication_type,
        settings,
        exception,
        step_id,
        errors,
    ):
        """Test transitions from the authentication form to other forms."""

        # Pick an authentication method from the form
        result = await hass.config_entries.flow.async_configure(
            authentication_form,
            user_input={
                compconst.CONF_AUTHENTICATION_TYPE: authentication_type,
            },
        )

        # Ensure we are now on the form for the specific authentication method
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == authentication_type

        # Simulate a failure on the gateway during authentication so that we are presented with a form
        with patch(gateway_async_init, side_effect=exception):
            result = await hass.config_entries.flow.async_configure(
                authentication_form,
                user_input=settings,
            )

        # Ensure we are sent back to the authentication form
        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == step_id
        assert "errors" in result and result["errors"] == errors


class Test_Reauth_Flow:
    """Test the reauth flow."""

    @pytest.fixture(autouse=True, name="skip_setup")
    async def _skip_setup_fixture(self):
        """Patch config flow setup to return success. This prevents loading the integration."""
        with patch(config_flow_setup_entry, return_value=True):
            yield

    @pytest.mark.parametrize(
        ("exception", "step_id", "existing_auth_settings", "user_input"),
        [
            (
                AuthenticationRequired,
                "basic_auth",
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
            ),
            (
                AuthenticationRequired,
                "api_key",
                {haconst.CONF_API_KEY: "api_key"},
                {haconst.CONF_API_KEY: "api_key"},
            ),
            (
                InsufficientPrivileges,
                "basic_auth",
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
                {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
            ),
            (
                InsufficientPrivileges,
                "api_key",
                {haconst.CONF_API_KEY: "api_key"},
                {haconst.CONF_API_KEY: "api_key"},
            ),
        ],
        ids=[
            "Reauth Basic Auth due to bad authentication",
            "Reauth API Key due to bad authentication",
            "Reauth Basic Auth due to insufficient privileges",
            "Reauth API Key due to insufficient privileges",
        ],
    )
    async def test_reauth_flow(
        self, hass: HomeAssistant, exception, step_id, existing_auth_settings, user_input
    ):
        """Test the reauth flow completes when the user provides new authentication details."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id="config_entry_id",
            data={
                **testconst.TEST_CONFIG_ENTRY_BASE_DATA,
                **existing_auth_settings,
            },
            options=testconst.TEST_CONFIG_ENTRY_DEFAULT_OPTIONS,
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        # Simulate a failure on the gateway during reauth so that we are presented with a form
        with patch(gateway_async_init, side_effect=exception):
            config_entry.async_start_reauth(hass)
            await hass.async_block_till_done()

        # Ensure we are on the form where we are prompted for the new authentication details
        flows = hass.config_entries.flow.async_progress()
        assert len(flows) == 1
        result = flows[0]
        assert "step_id" in result and result["step_id"] == step_id

        # Simulate the user entering details, the authentication now being successful, and completion of reauth
        with patch(gateway_async_init, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input,
            )

        assert "reason" in result and result["reason"] == "reauth_successful"

    async def test_reauth_flow_no_auth(self, hass: HomeAssistant):
        """Test the reauth flow completes when the user provides new authentication details."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id="config_entry_id",
            data={**testconst.TEST_CONFIG_ENTRY_BASE_DATA},
            options=testconst.TEST_CONFIG_ENTRY_DEFAULT_OPTIONS,
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        # Simulate a failure on the gateway during reauth, but because we have no auth
        # configured, the reauth will be aborted.
        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            config_entry.async_start_reauth(hass)
            await hass.async_block_till_done()

        # Ensure the reauth was aborted
        flows = hass.config_entries.flow.async_progress()
        assert len(flows) == 0


class Test_Options_Flow:
    """Test the options flow."""

    async def test_options_flow(
        self,
        hass: HomeAssistant,
    ):
        """Test the reauth flow completes when the user provides new authentication details."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id="config_entry_id",
            data={
                **testconst.TEST_CONFIG_ENTRY_DEFAULT_DATA,
            },
            options=testconst.TEST_CONFIG_ENTRY_BASE_OPTIONS,
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        result = await hass.config_entries.options.async_init(config_entry.entry_id)

        # We should get a form to fill out publishing and polling options
        assert "type" in result and result["type"] is FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "options"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={**testconst.TEST_CONFIG_ENTRY_DEFAULT_OPTIONS}
        )

        assert "type" in result and result["type"] is FlowResultType.CREATE_ENTRY

        # The options should be updated, but they are stored under data
        assert "data" in result and result["data"] == {**testconst.TEST_CONFIG_ENTRY_DEFAULT_OPTIONS}
