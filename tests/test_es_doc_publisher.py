"""Tests for the Elasticsearch Document Publisher."""

from datetime import datetime
from unittest import mock

import pytest
from elasticsearch.system_info import SystemInfoResult
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    CONF_URL,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import UTC
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension

from custom_components.elasticsearch.config_flow import (
    build_new_data,
    build_new_options,
)
from custom_components.elasticsearch.const import (
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITIES,
    CONF_INCLUDED_DOMAINS,
    CONF_INCLUDED_ENTITIES,
    CONF_INDEX_MODE,
    CONF_PUBLISH_MODE,
    DOMAIN,
    INDEX_MODE_DATASTREAM,
    INDEX_MODE_LEGACY,
    PUBLISH_MODE_ANY_CHANGES,
    PUBLISH_MODE_STATE_CHANGES,
    PUBLISH_REASON_ATTR_CHANGE,
    PUBLISH_REASON_STATE_CHANGE,
)
from custom_components.elasticsearch.errors import ElasticException
from custom_components.elasticsearch.es_doc_publisher import (
    DocumentPublisher,
)
from custom_components.elasticsearch.es_gateway import ElasticsearchGateway
from tests.conftest import MockEntityState
from tests.const import (
    MOCK_LOCATION_SERVER,
    MOCK_NOON_APRIL_12TH_2023,
)
from tests.test_util.aioclient_mock_utils import extract_es_bulk_requests
from tests.test_util.es_startup_mocks import mock_es_initialization


@pytest.fixture(autouse=True)
def freeze_location(hass: HomeAssistant):
    """Freeze location so we can properly assert on payload contents."""

    hass.config.latitude = MOCK_LOCATION_SERVER["lat"]
    hass.config.longitude = MOCK_LOCATION_SERVER["lon"]


@pytest.fixture(autouse=True)
def mock_system_info():
    """Fixture to skip returning system info."""

    async def get_system_info():
        return SystemInfoResult(
            version="2099.1.2",
            arch="Test Arch",
            hostname="Test Host",
            os_name="Test OS",
            os_version="v9.8.7",
        )

    with mock.patch(
        "custom_components.elasticsearch.system_info.SystemInfo.async_get_system_info",
        side_effect=get_system_info,
    ):
        yield None


@pytest.fixture(autouse=True)
def data():
    """Provide a default empty data object."""

    return {}


@pytest.fixture(autouse=True)
def options():
    """Provide a default options data object."""

    return {}


@pytest.fixture(autouse=True)
def state():
    """Provide a default empty state object."""

    return 1.0


@pytest.fixture(autouse=True)
def state_type():
    """Provide a default float state_type object."""

    return "float"


@pytest.fixture(autouse=True)
def index_mode():
    """Provide a default index_mode."""

    return INDEX_MODE_DATASTREAM


@pytest.fixture(autouse=True)
def reason():
    """Provide a publish reason."""

    return PUBLISH_REASON_STATE_CHANGE


@pytest.fixture(autouse=True)
def snapshot(snapshot):
    """Provide a pre-configured snapshot object."""

    return snapshot.with_defaults(extension_class=JSONSnapshotExtension)


@pytest.fixture(autouse=True)
def freeze_time(freezer: FrozenDateTimeFactory):
    """Freeze time so we can properly assert on payload contents."""
    freezer.move_to(datetime(2023, 4, 12, 12, tzinfo=UTC))  # Monday


@pytest.fixture()
def standard_entity_state(
    hass,
    state,
    attributes={},
):
    """Create a standard entity state for testing."""
    return MockEntityState(
        hass=hass,
        entity_id="counter.test_1",
        state=state,
        attributes=attributes,
        last_changed=dt_util.parse_date(MOCK_NOON_APRIL_12TH_2023),
        last_updated=dt_util.parse_date(MOCK_NOON_APRIL_12TH_2023),
    )


@pytest.fixture(scope="function")
def config_entry(hass: HomeAssistant, data, options):
    """Create a mock config entry."""
    es_url = "http://localhost:9200"

    # If we set data and options to have default values in our definition
    # the values wont pass through from the test so we need to set them to None here instead

    entry = MockConfigEntry(
        unique_id="pytest",
        domain=DOMAIN,
        version=5,
        data=build_new_data({"url": es_url, **data}),
        options=build_new_options(user_input={**options}),
        title="ES Config",
    )

    entry.add_to_hass(hass)

    return entry


@pytest.fixture()
def uninitialized_gateway(hass: HomeAssistant, config_entry: MockConfigEntry):
    """Create an uninitialized gateway."""
    return ElasticsearchGateway(hass=hass, config_entry=config_entry)


@pytest.fixture()
def uninitialized_publisher(
    config_entry: MockConfigEntry,
    uninitialized_gateway: ElasticsearchGateway,
    hass: HomeAssistant,
):
    """Create an uninitialized publisher."""
    publisher = DocumentPublisher(
        gateway=uninitialized_gateway, hass=hass, config_entry=config_entry
    )

    assert publisher.publish_queue.qsize() == 0

    return publisher


@pytest.fixture()
async def initialized_publisher(
    config_entry: MockConfigEntry,
    initialized_gateway: ElasticsearchGateway,
    hass: HomeAssistant,
):
    """Create an uninitialized publisher."""
    publisher = DocumentPublisher(
        gateway=initialized_gateway, hass=hass, config_entry=config_entry
    )

    await publisher.async_init()

    yield publisher

    publisher.stop_publisher()


@pytest.fixture()
async def initialized_gateway(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    es_aioclient_mock: AiohttpClientMocker,
):
    """Create an uninitialized gateway."""
    gateway = ElasticsearchGateway(hass=hass, config_entry=config_entry)

    mock_es_initialization(es_aioclient_mock, config_entry.data[CONF_URL])

    await gateway.async_init()

    yield gateway

    await gateway.async_stop_gateway()


@pytest.mark.asyncio
class Test_Unit_Tests:
    """Unit tests for the Elasticsearch Document Publisher."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "case,expected",
        [
            ("a_test_name", "a_test_name"),
            ("test-name", "test-name"),
            ("test_name_1", "test_name_1"),
            ("-test_name", "test_name"),
            ("test/name", "testname"),
            ("test? name", "test_name"),
            ("Test_Name_2", "test_name_2"),
            ("test..name", "test..name"),
            (".,?/:*<>|#+", None),
            (".", None),
            ("", None),
            ("......", None),
        ],
    )
    async def test_sanitize_datastream_name(
        self,
        case: str,
        expected: str,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test datastream names are sanitized correctly."""

        if expected is None:
            with pytest.raises(ElasticException):
                DocumentPublisher._sanitize_datastream_name(
                    type="metrics", dataset=case, namespace="default"
                )
        else:
            type, dataset, namespace, full_name = (
                DocumentPublisher._sanitize_datastream_name(
                    type="metrics", dataset=case, namespace="default"
                )
            )

            assert dataset == expected
            assert {"dataset": case, "sanitized_dataset": dataset} == snapshot

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "case,expected",
        [("a" * 256, "a" * 239)],
    )
    async def test_sanitize_long_datastream_name(
        self,
        case: str,
        expected: str,
        hass: HomeAssistant,
        snapshot: SnapshotAssertion,
    ):
        """Test datastream names are sanitized correctly."""

        if expected is None:
            with pytest.raises(ElasticException):
                DocumentPublisher._sanitize_datastream_name(
                    type="metrics", dataset=case, namespace="default"
                )
        else:
            type, dataset, namespace, full_name = (
                DocumentPublisher._sanitize_datastream_name(
                    type="metrics", dataset=case, namespace="default"
                )
            )
            assert dataset == expected

    class Test_Change_Mode:
        """Test change mode functions."""

        @pytest.mark.asyncio
        async def test_determine_change_type(
            self, hass, data, options, uninitialized_publisher: DocumentPublisher
        ):
            """Test entity change is published."""
            assert (
                uninitialized_publisher._determine_change_type(
                    new_state=MockEntityState(hass, entity_id="test.test_1", state="1"),
                    old_state=MockEntityState(hass, entity_id="test.test_1", state="0"),
                )
                == PUBLISH_REASON_STATE_CHANGE
            )

            assert (
                uninitialized_publisher._determine_change_type(
                    new_state=MockEntityState(
                        hass, entity_id="test.test_1", state="red"
                    ),
                    old_state=MockEntityState(
                        hass, entity_id="test.test_1", state="brown"
                    ),
                )
                == PUBLISH_REASON_STATE_CHANGE
            )

            assert (
                uninitialized_publisher._determine_change_type(
                    new_state=MockEntityState(
                        hass,
                        entity_id="test.test_1",
                        state="1",
                        attributes={"attr": "test"},
                    ),
                    old_state=MockEntityState(
                        hass,
                        entity_id="test.test_1",
                        state="1",
                        attributes={"attr": "test"},
                    ),  # this is a corner case
                )
                == PUBLISH_REASON_ATTR_CHANGE
            )

            assert (
                uninitialized_publisher._determine_change_type(
                    new_state=MockEntityState(
                        hass,
                        entity_id="test.test_1",
                        state="1",
                        attributes={"attr": "test"},
                    ),
                    old_state=MockEntityState(
                        hass,
                        entity_id="test.test_1",
                        state="1",
                        attributes={"attr": "test"},
                    ),
                )
                == PUBLISH_REASON_ATTR_CHANGE
            )

    class Test_Queue_Management:
        """Test queue management functions."""

        # @pytest.mark.asyncio
        # @pytest.mark.parametrize("data,options", ({},{}))
        # async def test_queue_enqueue(
        #     self,
        #     data,
        #     options: None,
        #     uninitialized_publisher: DocumentPublisher,
        # ):

        @pytest.mark.asyncio
        async def test_queue_enqueue(
            self,
            data: None,
            hass,
            options,
            uninitialized_publisher: DocumentPublisher,
        ):
            """Test entity change is published."""

            # Test enqueuing a state object into the publisher
            uninitialized_publisher.enqueue_state(
                MockEntityState(hass, entity_id="test.test_1", state="1"),
                "test",
                "test",
            )

            # Check queue size in publisher directly
            assert uninitialized_publisher.publish_queue.qsize() == 1

            assert uninitialized_publisher._has_entries_to_publish()
            assert uninitialized_publisher.queue_size() == 1

            uninitialized_publisher.empty_queue()

            assert not uninitialized_publisher._has_entries_to_publish()
            assert uninitialized_publisher.queue_size() == 0

        @pytest.mark.asyncio
        async def test_queue_empty(
            self,
            hass,
            uninitialized_publisher: DocumentPublisher,
        ):
            """Test entity change is published."""

            # Test enqueuing a state object into the publisher
            uninitialized_publisher.enqueue_state(
                MockEntityState(hass, entity_id="test.test_1", state="1"),
                "test",
                "test",
            )

            # Check queue size in publisher directly
            assert uninitialized_publisher.publish_queue.qsize() == 1

            uninitialized_publisher.empty_queue()

            assert uninitialized_publisher.publish_queue.qsize() == 0

        @pytest.mark.asyncio
        async def test_queue_has_entries_to_publish(
            self,
            hass,
            uninitialized_publisher: DocumentPublisher,
        ):
            """Test entity change is published."""

            # Test enqueuing a state object into the publisher
            uninitialized_publisher.enqueue_state(
                MockEntityState(hass, entity_id="test.test_1", state="1"),
                "test",
                "test",
            )

            assert uninitialized_publisher.publish_queue.qsize() == 1

            assert uninitialized_publisher._has_entries_to_publish()

    class Test_Publishing_Filters:
        """Test publishing functions."""

        @pytest.mark.asyncio  # fmt: skip
        @pytest.mark.parametrize(
            "data, options, entity_id, expected",
            [
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"]}, "counter.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_EXCLUDED_DOMAINS: ["test"]}, "counter.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_2", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                # now pass in combinations
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_2", True),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "counter.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_EXCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_2", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_EXCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                # now pass in combinations of 3
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_ENTITIES: ["test.test_2"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_ENTITIES: ["test.test_2"]}, "counter.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", False),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "counter.test_1", False),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_EXCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", True),
                # now pass in all 4
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_2", False),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_DOMAINS: ["test"]}, "counter.test_1", False),
                ( {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_2", False),
            ]

        )  # fmt: off
        async def test_publishing_datastream_filters(
            self,
            uninitialized_publisher: DocumentPublisher,
            entity_id: str,
            expected: bool,
            snapshot: SnapshotAssertion,
        ):
            """Test publishing filters."""

            result = uninitialized_publisher._should_publish_entity_passes_filter(
                entity_id=entity_id,
            )

            assert result == expected
            assert {
                "entity_id": entity_id,
                "should_publish": result,
            } == snapshot

        @pytest.mark.asyncio  # fmt: skip
        @pytest.mark.parametrize(
            "data, options, entity_id, expected",
            [
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                # now pass in combinations
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_EXCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", True),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_EXCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                # now pass in combinations of 3
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                ({CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ( {CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_EXCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", False),
                ( {CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_EXCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_1"]}, "test.test_1", False),
                # now pass in all 4
                ( {CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", False),
                ( {CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_1", True),
                ( {CONF_INDEX_MODE: INDEX_MODE_LEGACY}, {CONF_INCLUDED_DOMAINS: ["test"], CONF_INCLUDED_ENTITIES: ["test.test_1"], CONF_EXCLUDED_ENTITIES: ["test.test_2"], CONF_EXCLUDED_DOMAINS: ["test"]}, "test.test_2", False),
            ]

        )  # fmt: off
        async def test_publishing_legacy_filters(
            hass: HomeAssistant,
            uninitialized_publisher: DocumentPublisher,
            entity_id: str,
            expected: bool,
            snapshot: SnapshotAssertion,
        ):
            """Test publishing filters."""
            result = uninitialized_publisher._should_publish_entity_passes_filter(
                entity_id=entity_id,
            )

            assert {
                "entity": entity_id,
                "should_publish": result,
            } == snapshot

    class Test_Publisher_Document_Creation:
        """Test document creation functions."""

        @pytest.mark.asyncio
        @pytest.mark.parametrize(
            "data",
            [
                {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM},
                {CONF_INDEX_MODE: INDEX_MODE_LEGACY},
            ],
        )
        @pytest.mark.parametrize(
            "order,state,state_type,attributes,reason",
            [
                (0, 0.0, "float", {}, PUBLISH_REASON_ATTR_CHANGE),
                (1, 0.0, "float", {}, PUBLISH_REASON_ATTR_CHANGE),
                (2, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_ATTR_CHANGE),
                (3, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (4, 1.0, "float", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (5, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
            ],
        )
        async def test_state_to_bulk_action_via_uninitialized_publisher(
            self,
            order,
            data,
            state,
            state_type,
            attributes,
            reason,
            uninitialized_publisher: DocumentPublisher,
            standard_entity_state,
            snapshot: SnapshotAssertion,
        ):
            """Test state to bulk action."""
            result = uninitialized_publisher._state_to_bulk_action(
                state=standard_entity_state,
                time=dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
                reason=reason,
            )

            assert {
                "entity": standard_entity_state.as_dict(),
                "_bulk": result,
            } == snapshot

        @pytest.mark.asyncio
        @pytest.mark.parametrize(
            "data",
            [
                {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM},
                {CONF_INDEX_MODE: INDEX_MODE_LEGACY},
            ],
        )
        @pytest.mark.parametrize(
            "order,state,state_type,attributes,reason",
            [
                (0, 0.0, "float", {}, PUBLISH_REASON_ATTR_CHANGE),
                (1, 0.0, "float", {}, PUBLISH_REASON_ATTR_CHANGE),
                (2, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_ATTR_CHANGE),
                (3, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (4, 1.0, "float", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (5, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
            ],
        )
        async def test_state_to_bulk_action_via_initialized_publisher(
            self,
            order,
            data,
            state,
            state_type,
            attributes,
            reason,
            initialized_publisher: DocumentPublisher,
            standard_entity_state,
            snapshot: SnapshotAssertion,
        ):
            """Test state to bulk action."""
            result = initialized_publisher._state_to_bulk_action(
                state=standard_entity_state,
                time=dt_util.parse_datetime(MOCK_NOON_APRIL_12TH_2023),
                reason=reason,
            )

            assert {
                "entity": standard_entity_state.as_dict(),
                "_bulk": result,
            } == snapshot


class Test_Benchmark_Tests:
    """Benchmark tests for the Elasticsearch Document Publisher."""

    @pytest.fixture(autouse=True)
    def freeze_time(freezer: FrozenDateTimeFactory):
        """Do not freeze time, override auto-use fixture."""
        return

    @pytest.mark.asyncio
    async def test_publishing_benchmark(
        self,
        hass: HomeAssistant,
        state,
        initialized_publisher: DocumentPublisher,
        es_aioclient_mock: AiohttpClientMocker,
    ):
        """Benchmark entity publishing."""

        # If processing 500 entities takes more than 1s we have a significant performance degration
        for i in range(500):
            entity = MockEntityState(
                hass=hass,
                entity_id=f"counter.test_{i}",
                state=state,
                attributes={"some_attribute": "tomato"},
            )

            await entity.add_to_hass()

        start = datetime.now()

        await initialized_publisher.async_do_publish()

        end = datetime.now()

        duration = (end - start).total_seconds()

        assert duration < 1


class Test_Integration_Tests:
    """Integration tests for the Elasticsearch Document Publisher."""

    class Test_Publishing:
        """Test publishing functions."""

        # These are e2e tests, so we will need to mock the Elasticsearch Gateway and test the Document Publisher with it
        @pytest.mark.asyncio
        @pytest.mark.parametrize(
            "options",
            [
                {CONF_PUBLISH_MODE: PUBLISH_MODE_ANY_CHANGES},
                {CONF_PUBLISH_MODE: PUBLISH_MODE_STATE_CHANGES},
            ],
        )
        @pytest.mark.parametrize(
            "data",
            [
                {CONF_INDEX_MODE: INDEX_MODE_DATASTREAM},
                {CONF_INDEX_MODE: INDEX_MODE_LEGACY},
            ],
        )
        @pytest.mark.parametrize(
            "order,state,state_type,attributes,reason",
            [
                (0, 0.0, "float", {}, PUBLISH_REASON_STATE_CHANGE),
                (1, 0.0, "float", {}, PUBLISH_REASON_STATE_CHANGE),
                (2, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (3, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (4, 1.0, "float", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
                (5, "tomato", "string", {"attr": "value"}, PUBLISH_REASON_STATE_CHANGE),
            ],
        )
        async def test_publishing_state_change(
            self,
            data,
            options,
            order,
            state,
            state_type,
            attributes,
            reason,
            initialized_publisher: DocumentPublisher,
            standard_entity_state: MockEntityState,
            es_aioclient_mock: AiohttpClientMocker,
            snapshot: SnapshotAssertion,
        ):
            # mock the gateway
            """Test entity change is published."""

            await standard_entity_state.add_to_hass()

            await initialized_publisher.async_do_publish()

            requests = extract_es_bulk_requests(es_aioclient_mock)

            if options.get(CONF_PUBLISH_MODE) == PUBLISH_MODE_ANY_CHANGES:
                assert len(requests) == 1
                assert len(requests[0].data) == 2

            elif options.get(CONF_PUBLISH_MODE) == PUBLISH_MODE_STATE_CHANGES:
                if reason == PUBLISH_REASON_STATE_CHANGE:
                    assert len(requests) == 1
                    assert len(requests[0].data) == 2

                else:
                    assert len(requests) == 0

            assert {
                "entity": standard_entity_state.as_dict(),
                "request": requests[0].data,
            } == snapshot
