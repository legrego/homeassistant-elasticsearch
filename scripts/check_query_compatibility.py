"""Exercise query sensors against disposable Elasticsearch clusters and actual mappings.

Run from the repository root with:
PYTHONPATH=. poetry run python scripts/check_query_compatibility.py http://localhost:19219 http://localhost:19291

Use unsecured local test clusters only. Each run creates and removes a uniquely named test index.
"""

# This is an executable script, not an importable package.
# ruff: noqa: INP001
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from homeassistant.util import dt as dt_util

from custom_components.elasticsearch.datastreams.index_template import index_template_definition
from custom_components.elasticsearch.es_gateway_8 import Elasticsearch8Gateway, Gateway8Settings
from custom_components.elasticsearch.esql import QueryRunner
from custom_components.elasticsearch.query_sensor import read_sensor_result


async def check_cluster(url: str) -> None:
    """Verify filtering, sorting, aggregation and freshness with REST compatibility 8."""
    gateway = Elasticsearch8Gateway(gateway_settings=Gateway8Settings(url=url))
    runner = QueryRunner(gateway)
    index = f"ha-query-compatibility-{uuid4().hex}"
    created = False
    try:
        await gateway.async_init()
        await gateway.client.indices.create(
            index=index, mappings=index_template_definition["template"]["mappings"]
        )
        created = True
        now = dt_util.utcnow()
        for offset, value in enumerate([10, 20]):
            await gateway.client.index(
                index=index,
                document={
                    "@timestamp": (now - timedelta(seconds=2 - offset)).isoformat(),
                    "hass": {"entity": {"id": "sensor.compat", "valueas": {"float": value}}},
                },
                refresh=True,
            )
        latest = await runner.async_query(
            f"FROM {index} | WHERE hass.entity.id == ? AND @timestamp > NOW() - 1 hour "
            "| SORT @timestamp DESC | KEEP @timestamp, hass.entity.valueas.float | LIMIT 1",
            ["sensor.compat"],
        )
        reading = read_sensor_result(
            latest,
            {
                "value_column": "hass.entity.valueas.float",
                "timestamp_column": "@timestamp",
                "max_age": 60,
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
            },
        )
        assert reading.value == 20 and reading.expires_at
        assert latest.columns[0].type == "date_nanos"
        aggregate = await runner.async_query(
            f"FROM {index} | WHERE @timestamp > NOW() - 1 hour "
            "| STATS average = AVG(hass.entity.valueas.float), observed = MAX(@timestamp) | LIMIT 1"
        )
        summary = read_sensor_result(
            aggregate, {"value_column": "average", "timestamp_column": "observed", "max_age": 60}
        )
        assert summary.value == 15 and summary.expires_at
        empty = await runner.async_query(
            f"FROM {index} | WHERE hass.entity.id == ? "
            "| KEEP @timestamp, hass.entity.valueas.float | LIMIT 1",
            ["sensor.absent"],
        )
        assert read_sensor_result(empty, {"value_column": "hass.entity.valueas.float"}).value is None
        print(  # noqa: T201
            json.dumps(
                {
                    "version": gateway.cluster_version,
                    "latest": reading.value,
                    "average": summary.value,
                    "date_nanos": True,
                    "empty": True,
                }
            )
        )
    finally:
        await runner.async_shutdown()
        if created:
            await gateway.client.indices.delete(index=index)
        await gateway.stop()


async def main() -> None:
    """Check each supplied disposable cluster."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    for url in parser.parse_args().urls:
        await check_cluster(url)


if __name__ == "__main__":
    asyncio.run(main())
