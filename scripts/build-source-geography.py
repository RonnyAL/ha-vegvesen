"""Build complete discovery geography from public sources, outside HA setup."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.vegvesen.api import VegvesenApiClient  # noqa: E402
from custom_components.vegvesen.geography import (  # noqa: E402
    LOOKUP_CONCURRENCY,
    GeographyClient,
)


async def main() -> None:
    """Limit concurrency and publish only after both catalogues and all lookups pass."""
    async with aiohttp.ClientSession() as session:
        client = VegvesenApiClient(session)
        geography = GeographyClient(session)
        counties = await geography.async_get_counties()
        sources = {
            **{
                f"weather_station:{source_id}": source
                for source_id, source in (await client.async_get_weather()).items()
            },
            **{
                f"camera:{source_id}": source
                for source_id, source in (await client.async_get_cameras()).items()
            },
        }
        points = sorted(
            {
                (source.latitude, source.longitude)
                for source in sources.values()
                if source.latitude is not None and source.longitude is not None
            }
        )
        # Sequential batches prevent queuing the entire country on the service.
        membership = {}
        for start in range(0, len(points), LOOKUP_CONCURRENCY):
            batch = points[start : start + LOOKUP_CONCURRENCY]
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(geography.async_get_membership(point))
                    for point in batch
                ]
            membership.update(
                zip(batch, (task.result() for task in tasks), strict=True)
            )
            if start % 100 == 0:
                print(f"Resolved {start + len(batch)}/{len(points)} source coordinates")
        indexed = {}
        for key, source in sorted(sources.items()):
            point = source.latitude, source.longitude
            area = membership.get(point)
            if area is None:
                continue
            county_number, municipality_number = area
            county = counties[county_number]
            municipality = county.municipalities[municipality_number]
            indexed[key] = {
                "latitude": source.latitude,
                "longitude": source.longitude,
                "county": county.name,
                "county_number": county.number,
                "municipality": municipality.name,
                "municipality_number": municipality.number,
            }
        payload = {
            "version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "catalogue_counts": {
                "weather_station": sum(
                    key.startswith("weather_station:") for key in sources
                ),
                "camera": sum(key.startswith("camera:") for key in sources),
            },
            "sources": indexed,
        }
        target = ROOT / "custom_components/vegvesen/source_geography.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(target)
        print(f"Wrote {len(indexed)}/{len(sources)} recognized public source locations")


if __name__ == "__main__":
    asyncio.run(main())
