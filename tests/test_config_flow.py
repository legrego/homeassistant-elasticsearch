"""Test the Config Flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import custom_components.elasticsearch.const as compconst
import homeassistant.const as haconst
import probatio
import pytest
from custom_components.elasticsearch.config_flow import (
    ElasticFlowHandler,
    ElasticOptionsFlowHandler,
)
from custom_components.elasticsearch.errors import (
    AuthenticationRequired,
    CannotConnect,
    InsufficientPrivileges,
    InvalidCACertificate,
    UnsupportedServer,
    UnsupportedVersion,
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
                user_input={testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL},
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
                user_input={testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL},
            )

        assert result is not None
        assert result.get("type") == "form"
        assert result.get("step_id") == "authentication_issues"
        assert result.get("errors") is None

        return result["flow_id"]

    async def test_full_flow(self, hass: HomeAssistant, initial_form):
        """Test the full config flow."""
        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(
                initial_form, user_input={testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL}
            )

        # The entry should be now created
        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == testconst.CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL}
        assert "options" in result and result["options"] == ElasticOptionsFlowHandler.default_options
        assert "result" in result and result["result"].unique_id == testconst.CLUSTER_UUID

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
                initial_form, user_input={testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL}
            )

        assert "type" in result and result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == step_id

    @pytest.mark.parametrize(
        ("metadata", "headers"),
        [
            ({"version": {"number": "8.9.0"}}, {"X-Elastic-Product": "Elasticsearch"}),
            ([], {"X-Elastic-Product": "Elasticsearch"}),
            (testconst.CLUSTER_INFO_8DOT14_RESPONSE_BODY, {}),
        ],
        ids=["VictoriaLogs", "Non-object metadata", "Missing product header"],
    )
    async def test_ingestion_endpoint_metadata(self, hass, initial_form, es_mock_builder, metadata, headers):
        """Show a useful error for incompatible endpoints, then allow a corrected URL."""
        es_mock_builder.mocker.get(
            testconst.CONFIG_ENTRY_DATA_URL,
            json=metadata,
            headers=headers,
        )

        result = await hass.config_entries.flow.async_configure(
            initial_form, user_input={testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL}
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "unsupported_server"}

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(
                initial_form, user_input={testconst.CONF_URL: "http://elasticsearch:9200"}
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][testconst.CONF_URL] == "http://elasticsearch:9200"
        assert result["result"].unique_id == testconst.CLUSTER_UUID

    @pytest.mark.parametrize("step", ["user", "certificate_issues", "basic_auth", "api_key"])
    async def test_unsupported_server_at_each_step(self, hass, initial_form, step):
        """Keep incompatible server errors recoverable throughout setup."""
        flow_id = initial_form
        if step != "user":
            error = UntrustedCertificate if step == "certificate_issues" else AuthenticationRequired
            with patch(gateway_async_init, side_effect=error):
                await hass.config_entries.flow.async_configure(
                    flow_id, user_input={testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL}
                )
            if step in ("basic_auth", "api_key"):
                await hass.config_entries.flow.async_configure(
                    flow_id, user_input={compconst.CONF_AUTHENTICATION_TYPE: step}
                )

        inputs = {
            "user": {testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL},
            "certificate_issues": {
                haconst.CONF_VERIFY_SSL: False,
                compconst.CONF_SSL_VERIFY_HOSTNAME: False,
            },
            "basic_auth": {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"},
            "api_key": {haconst.CONF_API_KEY: "key"},
        }
        with patch(gateway_async_init, side_effect=UnsupportedServer):
            result = await hass.config_entries.flow.async_configure(flow_id, user_input=inputs[step])

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == step
        assert result["errors"] == {"base": "unsupported_server"}

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, user_input=inputs[step])

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == testconst.CLUSTER_UUID

    @pytest.mark.parametrize(
        "exception",
        [UntrustedCertificate, UnsupportedServer, InvalidCACertificate, UnsupportedVersion, RuntimeError],
    )
    @pytest.mark.parametrize(("verify_ssl", "verify_hostname"), [(False, False), (True, False)])
    async def test_certificate_choices_survive_error(
        self, hass, certificate_form, exception, verify_ssl, verify_hostname
    ):
        """Retain toggles and the CA path, and submit those settings on retry."""
        settings = {
            haconst.CONF_VERIFY_SSL: verify_ssl,
            compconst.CONF_SSL_VERIFY_HOSTNAME: verify_hostname,
            compconst.CONF_SSL_CA_PATH: "/config/custom-ca.pem",
        }
        with patch(gateway_async_init, side_effect=exception):
            result = await hass.config_entries.flow.async_configure(certificate_form, user_input=settings)

        assert result["step_id"] == "certificate_issues"
        fields = {key.schema: key for key in result["data_schema"].schema}
        for field, value in settings.items():
            assert fields[field].description["suggested_value"] == value

        # Retrying also allows the optional CA path to be cleared.
        settings.pop(compconst.CONF_SSL_CA_PATH)
        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID) as gateway:
            result = await hass.config_entries.flow.async_configure(certificate_form, user_input=settings)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"] == {testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL, **settings}
        gateway.assert_awaited_once_with(
            url=testconst.CONFIG_ENTRY_DATA_URL,
            verify_certs=verify_ssl,
            verify_hostname=verify_hostname,
            ca_certs=None,
        )

    async def test_url_to_certificate_issues_to_done(self, hass: HomeAssistant, certificate_form):
        """Test transitions from the ssl settings form to entry creation."""
        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(
                certificate_form,
                user_input={
                    compconst.CONF_SSL_VERIFY_HOSTNAME: True,
                    haconst.CONF_VERIFY_SSL: True,
                },
            )

        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == testconst.CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {
            testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL,
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
        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(
                authentication_form,
                user_input=settings,
            )

        assert "type" in result and result["type"] == FlowResultType.CREATE_ENTRY
        assert "title" in result and result["title"] == testconst.CONFIG_ENTRY_DATA_URL
        assert "data" in result and result["data"] == {
            testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL,
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


SETTINGS_BASIC_AUTH = {haconst.CONF_USERNAME: "username", haconst.CONF_PASSWORD: "password"}
SETTINGS_API_KEY = {haconst.CONF_API_KEY: "api_key"}
SETTINGS_CERTIFICATE = {
    haconst.CONF_VERIFY_SSL: True,
    compconst.CONF_SSL_VERIFY_HOSTNAME: True,
    compconst.CONF_SSL_CA_PATH: "/config/ca.crt",
}
SETTINGS_URL = {testconst.CONF_URL: testconst.CONFIG_ENTRY_DATA_URL}


class Test_Flow_Recovery:
    """Test that the user can finish the flow after each error it can show."""

    @staticmethod
    async def start_flow(hass: HomeAssistant, step_id: str) -> str:
        """Walk the flow to the given step, returning the flow id."""
        result = await hass.config_entries.flow.async_init(compconst.DOMAIN, context={"source": "user"})

        if step_id == "user":
            return result["flow_id"]

        if step_id == "certificate_issues":
            with patch(gateway_async_init, side_effect=UntrustedCertificate):
                result = await hass.config_entries.flow.async_configure(result["flow_id"], SETTINGS_URL)
            return result["flow_id"]

        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], SETTINGS_URL)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {compconst.CONF_AUTHENTICATION_TYPE: step_id}
        )
        return result["flow_id"]

    @pytest.mark.parametrize(
        ("step_id", "user_input", "exception", "errors"),
        [
            ("user", SETTINGS_URL, CannotConnect, {testconst.CONF_URL: "cannot_connect"}),
            ("user", SETTINGS_URL, UnsupportedVersion, {"base": "unsupported_version"}),
            ("user", SETTINGS_URL, RuntimeError, {"base": "unknown"}),
            (
                "certificate_issues",
                SETTINGS_CERTIFICATE,
                UntrustedCertificate,
                {"base": "untrusted_certificate"},
            ),
            (
                "certificate_issues",
                SETTINGS_CERTIFICATE,
                InvalidCACertificate,
                {"base": "invalid_ca_certificate"},
            ),
            ("certificate_issues", SETTINGS_CERTIFICATE, UnsupportedVersion, {"base": "unsupported_version"}),
            ("certificate_issues", SETTINGS_CERTIFICATE, RuntimeError, {"base": "unknown"}),
            ("basic_auth", SETTINGS_BASIC_AUTH, AuthenticationRequired, {"base": "invalid_basic_auth"}),
            ("basic_auth", SETTINGS_BASIC_AUTH, InsufficientPrivileges, {"base": "insufficient_privileges"}),
            ("basic_auth", SETTINGS_BASIC_AUTH, CannotConnect, {"base": "cannot_connect"}),
            ("basic_auth", SETTINGS_BASIC_AUTH, UnsupportedVersion, {"base": "unsupported_version"}),
            ("basic_auth", SETTINGS_BASIC_AUTH, RuntimeError, {"base": "unknown"}),
            ("api_key", SETTINGS_API_KEY, AuthenticationRequired, {"base": "invalid_api_key"}),
            ("api_key", SETTINGS_API_KEY, InsufficientPrivileges, {"base": "insufficient_privileges"}),
            ("api_key", SETTINGS_API_KEY, CannotConnect, {"base": "cannot_connect"}),
            ("api_key", SETTINGS_API_KEY, UnsupportedVersion, {"base": "unsupported_version"}),
            ("api_key", SETTINGS_API_KEY, RuntimeError, {"base": "unknown"}),
        ],
    )
    async def test_recovers_on_the_same_step(
        self, hass: HomeAssistant, step_id, user_input, exception, errors
    ):
        """Test that an error returns to the form, and that resubmitting it finishes the flow."""
        flow_id = await self.start_flow(hass, step_id)

        with patch(gateway_async_init, side_effect=exception):
            result = await hass.config_entries.flow.async_configure(flow_id, user_input)

        assert result["type"] == FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == step_id
        assert "errors" in result and result["errors"] == errors

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, user_input)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "result" in result and result["result"].unique_id == testconst.CLUSTER_UUID

        for key, value in user_input.items():
            assert result["data"][key] == value

    @pytest.mark.parametrize(
        ("step_id", "user_input"),
        [("basic_auth", SETTINGS_BASIC_AUTH), ("api_key", SETTINGS_API_KEY)],
    )
    async def test_recovers_from_invalid_ca_on_authentication_step(
        self, hass: HomeAssistant, step_id, user_input
    ):
        """Test that a CA file which stops loading can be corrected from the certificate step."""
        flow_id = await self.start_flow(hass, step_id)

        with patch(gateway_async_init, side_effect=InvalidCACertificate):
            result = await hass.config_entries.flow.async_configure(flow_id, user_input)

        assert "step_id" in result and result["step_id"] == "certificate_issues"
        assert "errors" in result and result["errors"] == {"base": "invalid_ca_certificate"}

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_CERTIFICATE)

        assert result["type"] == FlowResultType.CREATE_ENTRY

    async def test_recovers_from_certificate_step_connection_failure(self, hass: HomeAssistant):
        """Test that losing the connection on the certificate step can be resolved from the URL step."""
        flow_id = await self.start_flow(hass, "certificate_issues")

        with patch(gateway_async_init, side_effect=CannotConnect):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_CERTIFICATE)

        assert "step_id" in result and result["step_id"] == "user"
        assert "errors" in result and result["errors"] == {"base": "cannot_connect"}

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_URL)

        assert result["type"] == FlowResultType.CREATE_ENTRY

    async def test_recovers_from_certificate_step_requiring_authentication(self, hass: HomeAssistant):
        """Test that the certificate settings are kept when authentication is required next."""
        flow_id = await self.start_flow(hass, "certificate_issues")

        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_CERTIFICATE)

        assert "step_id" in result and result["step_id"] == "authentication_issues"

        result = await hass.config_entries.flow.async_configure(
            flow_id, {compconst.CONF_AUTHENTICATION_TYPE: "api_key"}
        )

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_API_KEY)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][compconst.CONF_SSL_CA_PATH] == SETTINGS_CERTIFICATE[compconst.CONF_SSL_CA_PATH]

    @pytest.mark.parametrize(
        ("step_id", "credentials"), [("basic_auth", SETTINGS_BASIC_AUTH), ("api_key", SETTINGS_API_KEY)]
    )
    async def test_clear_ca_after_authentication_challenge(self, hass, step_id, credentials):
        """Remove a previously saved CA path when returning from authentication."""
        flow_id = await self.start_flow(hass, "certificate_issues")
        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            await hass.config_entries.flow.async_configure(flow_id, SETTINGS_CERTIFICATE)

        await hass.config_entries.flow.async_configure(flow_id, {compconst.CONF_AUTHENTICATION_TYPE: step_id})
        with patch(gateway_async_init, side_effect=InvalidCACertificate):
            result = await hass.config_entries.flow.async_configure(flow_id, credentials)

        assert result["step_id"] == "certificate_issues"
        settings = {
            key: value for key, value in SETTINGS_CERTIFICATE.items() if key != compconst.CONF_SSL_CA_PATH
        }
        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            await hass.config_entries.flow.async_configure(flow_id, settings)

        await hass.config_entries.flow.async_configure(flow_id, {compconst.CONF_AUTHENTICATION_TYPE: step_id})
        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID) as gateway:
            result = await hass.config_entries.flow.async_configure(flow_id, credentials)

        assert gateway.call_args.kwargs["ca_certs"] is None
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert compconst.CONF_SSL_CA_PATH not in result["data"]


class Test_Unique_Config_Entry:
    """Test that a cluster can only be set up once."""

    @pytest.mark.parametrize(
        ("step_id", "user_input"),
        [
            ("user", SETTINGS_URL),
            ("certificate_issues", SETTINGS_CERTIFICATE),
            ("basic_auth", SETTINGS_BASIC_AUTH),
            ("api_key", SETTINGS_API_KEY),
        ],
    )
    async def test_duplicate_cluster_is_rejected(self, hass: HomeAssistant, step_id, user_input):
        """Test that the flow aborts on each path when the cluster is already configured."""
        MockConfigEntry(domain=compconst.DOMAIN, unique_id=testconst.CLUSTER_UUID).add_to_hass(hass)

        flow_id = await Test_Flow_Recovery.start_flow(hass, step_id)

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, user_input)

        assert result["type"] == FlowResultType.ABORT
        assert "reason" in result and result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(compconst.DOMAIN)) == 1

    async def test_concurrent_flow_for_the_same_cluster_is_rejected(self, hass: HomeAssistant):
        """Test that two flows for one cluster can't both create an entry."""
        first_flow_id = await Test_Flow_Recovery.start_flow(hass, "user")
        hass.config_entries.flow._progress[first_flow_id].context["unique_id"] = testconst.CLUSTER_UUID

        flow_id = await Test_Flow_Recovery.start_flow(hass, "user")

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_URL)

        assert result["type"] == FlowResultType.ABORT
        assert "reason" in result and result["reason"] == "already_in_progress"
        assert hass.config_entries.async_entries(compconst.DOMAIN) == []

    async def test_second_url_for_the_same_cluster_is_rejected(self, hass: HomeAssistant):
        """Test that the check follows the cluster, not the URL it was reached through."""
        MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id=testconst.CLUSTER_UUID,
            data={testconst.CONF_URL: "https://another_name_for_this_cluster:9200"},
        ).add_to_hass(hass)

        flow_id = await Test_Flow_Recovery.start_flow(hass, "user")

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_URL)

        assert "reason" in result and result["reason"] == "already_configured"

    async def test_different_cluster_is_allowed(self, hass: HomeAssistant):
        """Test that another cluster can be added alongside an existing one."""
        MockConfigEntry(domain=compconst.DOMAIN, unique_id="another_cluster").add_to_hass(hass)

        flow_id = await Test_Flow_Recovery.start_flow(hass, "user")

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_URL)

        assert result["type"] == FlowResultType.CREATE_ENTRY

    async def test_unknown_cluster_uuid(self, hass: HomeAssistant):
        """Test that setup still succeeds when the cluster cannot report a UUID."""
        flow_id = await Test_Flow_Recovery.start_flow(hass, "user")

        with patch(gateway_async_init, return_value=None):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_URL)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "result" in result and result["result"].unique_id is None


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
                **testconst.CONFIG_ENTRY_BASE_DATA,
                **existing_auth_settings,
            },
            options=testconst.CONFIG_ENTRY_DEFAULT_OPTIONS,
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
        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input,
            )

        assert "reason" in result and result["reason"] == "reauth_successful"

    @pytest.mark.parametrize(
        ("exception", "errors"),
        [
            (CannotConnect, {"base": "cannot_connect"}),
            (UnsupportedVersion, {"base": "unsupported_version"}),
            (RuntimeError, {"base": "unknown"}),
        ],
    )
    @pytest.mark.parametrize(
        ("step_id", "existing_auth_settings"),
        [("basic_auth", SETTINGS_BASIC_AUTH), ("api_key", SETTINGS_API_KEY)],
    )
    async def test_reauth_flow_recovers(
        self, hass: HomeAssistant, exception, errors, step_id, existing_auth_settings
    ):
        """Test that reauth can be completed after a failure that isn't related to the credentials."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id=testconst.CLUSTER_UUID,
            data={**testconst.CONFIG_ENTRY_BASE_DATA, **existing_auth_settings},
            options=testconst.CONFIG_ENTRY_DEFAULT_OPTIONS,
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            config_entry.async_start_reauth(hass)
            await hass.async_block_till_done()

        flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]

        with patch(gateway_async_init, side_effect=exception):
            result = await hass.config_entries.flow.async_configure(flow_id, existing_auth_settings)

        assert "step_id" in result and result["step_id"] == step_id
        assert "errors" in result and result["errors"] == errors

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, existing_auth_settings)

        assert "reason" in result and result["reason"] == "reauth_successful"

    @pytest.mark.parametrize(
        ("step_id", "existing_auth_settings", "other_auth_key"),
        [
            ("basic_auth", SETTINGS_BASIC_AUTH, haconst.CONF_API_KEY),
            ("api_key", SETTINGS_API_KEY, haconst.CONF_USERNAME),
        ],
    )
    async def test_reauth_flow_recovers_from_invalid_ca(
        self, hass: HomeAssistant, step_id, existing_auth_settings, other_auth_key
    ):
        """Test that a CA file which stops loading can be corrected during reauth."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id=testconst.CLUSTER_UUID,
            data={
                **testconst.CONFIG_ENTRY_BASE_DATA,
                **existing_auth_settings,
                compconst.CONF_SSL_CA_PATH: "/config/missing.crt",
            },
            options=testconst.CONFIG_ENTRY_DEFAULT_OPTIONS,
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        with patch(gateway_async_init, side_effect=InvalidCACertificate):
            config_entry.async_start_reauth(hass)
            await hass.async_block_till_done()

        flow = hass.config_entries.flow.async_progress()[0]
        flow_id = flow["flow_id"]
        assert "step_id" in flow and flow["step_id"] == "certificate_issues"

        # The connection can fail while the certificate is being corrected, without leaving this step
        with patch(gateway_async_init, side_effect=CannotConnect):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_CERTIFICATE)

        assert "step_id" in result and result["step_id"] == "certificate_issues"
        assert "errors" in result and result["errors"] == {"base": "cannot_connect"}

        # The certificate step has no credentials, which goes back to the entry's own auth method
        with patch(gateway_async_init, side_effect=AuthenticationRequired):
            result = await hass.config_entries.flow.async_configure(flow_id, SETTINGS_CERTIFICATE)

        assert "step_id" in result and result["step_id"] == step_id

        with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID):
            result = await hass.config_entries.flow.async_configure(flow_id, existing_auth_settings)

        assert "reason" in result and result["reason"] == "reauth_successful"
        assert (
            config_entry.data[compconst.CONF_SSL_CA_PATH] == SETTINGS_CERTIFICATE[compconst.CONF_SSL_CA_PATH]
        )
        assert other_auth_key not in config_entry.data

    @pytest.mark.parametrize(
        ("step_id", "credentials"), [("basic_auth", SETTINGS_BASIC_AUTH), ("api_key", SETTINGS_API_KEY)]
    )
    @pytest.mark.parametrize("needs_authentication", [True, False])
    async def test_reauth_prefills_tls_and_clears_saved_ca(
        self, hass, step_id, credentials, needs_authentication
    ):
        """Offer existing TLS settings and remove a cleared CA on both success paths."""
        previous_tls = {
            haconst.CONF_VERIFY_SSL: True,
            compconst.CONF_SSL_VERIFY_HOSTNAME: False,
            compconst.CONF_SSL_CA_PATH: "/config/removed-ca.pem",
        }
        entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id=testconst.CLUSTER_UUID,
            data={**testconst.CONFIG_ENTRY_BASE_DATA, **credentials, **previous_tls},
            options=testconst.CONFIG_ENTRY_DEFAULT_OPTIONS,
        )
        await add_config_entry_to_hass(hass, entry)
        with patch(gateway_async_init, side_effect=InvalidCACertificate):
            entry.async_start_reauth(hass)
            await hass.async_block_till_done()

        flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
        result = await hass.config_entries.flow.async_configure(flow_id)
        assert result["step_id"] == "certificate_issues"
        fields = {key.schema: key for key in result["data_schema"].schema}
        for field, value in previous_tls.items():
            assert fields[field].description["suggested_value"] == value

        submitted = {haconst.CONF_VERIFY_SSL: False, compconst.CONF_SSL_VERIFY_HOSTNAME: False}
        with patch(
            gateway_async_init,
            side_effect=AuthenticationRequired if needs_authentication else None,
            return_value=testconst.CLUSTER_UUID,
        ):
            result = await hass.config_entries.flow.async_configure(flow_id, submitted)

        if needs_authentication:
            assert result["step_id"] == step_id
            with patch(gateway_async_init, return_value=testconst.CLUSTER_UUID) as gateway:
                result = await hass.config_entries.flow.async_configure(flow_id, credentials)

            assert gateway.call_args.kwargs["ca_certs"] is None

        assert result["reason"] == "reauth_successful"
        assert compconst.CONF_SSL_CA_PATH not in entry.data
        for field, value in submitted.items():
            assert entry.data[field] == value

    async def test_reauth_flow_no_auth(self, hass: HomeAssistant):
        """Test the reauth flow completes when the user provides new authentication details."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id="config_entry_id",
            data={**testconst.CONFIG_ENTRY_BASE_DATA},
            options=testconst.CONFIG_ENTRY_DEFAULT_OPTIONS,
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
                **testconst.CONFIG_ENTRY_DEFAULT_DATA,
            },
            options=testconst.CONFIG_ENTRY_BASE_OPTIONS,
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        result = await hass.config_entries.options.async_init(config_entry.entry_id)

        # We should get a form to fill out publishing and polling options
        assert "type" in result and result["type"] is FlowResultType.FORM
        assert "step_id" in result and result["step_id"] == "options"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={**testconst.CONFIG_ENTRY_DEFAULT_OPTIONS}
        )

        assert "type" in result and result["type"] is FlowResultType.CREATE_ENTRY

        # The options should be updated, but they are stored under data
        assert "data" in result and result["data"] == {**testconst.CONFIG_ENTRY_DEFAULT_OPTIONS}

    @pytest.mark.parametrize(
        ("submitted", "expected"),
        [
            ({}, {}),
            ({compconst.CONF_TARGETS_TO_INCLUDE: {}, compconst.CONF_TARGETS_TO_EXCLUDE: {}}, {}),
            (
                {
                    compconst.CONF_TARGETS_TO_INCLUDE: {"label_id": ["kept"]},
                    compconst.CONF_TARGETS_TO_EXCLUDE: {"label_id": ["kept"]},
                },
                {"label_id": ["kept"]},
            ),
        ],
        ids=["left out of the form", "submitted empty", "still selected"],
    )
    async def test_options_flow_targets(self, hass: HomeAssistant, submitted: dict, expected: dict):
        """Test that the saved targets are exactly what the form submits, so they can be cleared."""

        config_entry = MockConfigEntry(
            domain=compconst.DOMAIN,
            unique_id="config_entry_id",
            version=ElasticFlowHandler.VERSION,
            data={**testconst.CONFIG_ENTRY_DEFAULT_DATA},
            options={
                **testconst.CONFIG_ENTRY_BASE_OPTIONS,
                compconst.CONF_TARGETS_TO_INCLUDE: {"label_id": ["previous"]},
                compconst.CONF_TARGETS_TO_EXCLUDE: {"label_id": ["previous"]},
            },
            title="config_entry_title",
        )

        await add_config_entry_to_hass(hass, config_entry)

        result = await hass.config_entries.options.async_init(config_entry.entry_id)

        # The current targets should be offered in the form without acting as a default
        assert "data_schema" in result and result["data_schema"] is not None
        fields = {key.schema: key for key in result["data_schema"].schema}
        for field in (compconst.CONF_TARGETS_TO_INCLUDE, compconst.CONF_TARGETS_TO_EXCLUDE):
            assert fields[field].description == {"suggested_value": {"label_id": ["previous"]}}
            assert fields[field].default is probatio.UNDEFINED

        user_input = {
            key: value
            for key, value in testconst.CONFIG_ENTRY_DEFAULT_OPTIONS.items()
            if key not in (compconst.CONF_TARGETS_TO_INCLUDE, compconst.CONF_TARGETS_TO_EXCLUDE)
        }

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={**user_input, **submitted}
        )

        assert "type" in result and result["type"] is FlowResultType.CREATE_ENTRY
        assert "data" in result
        assert result["data"][compconst.CONF_TARGETS_TO_INCLUDE] == expected
        assert result["data"][compconst.CONF_TARGETS_TO_EXCLUDE] == expected
