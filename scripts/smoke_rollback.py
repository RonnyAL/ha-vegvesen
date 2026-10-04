"""Verify that a beta-created configuration still loads with stable 0.7.4."""

import json
import shutil
import subprocess
import time
from io import BytesIO
from zipfile import ZipFile

from smoke_instance import ROOT, SmokeInstance

STABLE_COMMIT = "10658a404a4aac1b7a6808e4e9ece02bea2a809e"


def snapshot(instance: SmokeInstance) -> dict:
    """Record public-fixture identities and saved subentries, excluding image state."""
    entry = instance.ws("config_entries/get", domain="vegvesen")[0]
    entities = [
        {
            key: item.get(key)
            for key in ("entity_id", "unique_id", "device_id", "config_subentry_id")
        }
        for item in instance.ws("config/entity_registry/list")
        if item.get("platform") == "vegvesen"
        and not item["entity_id"].startswith("image.")
    ]
    return {
        "entry_id": entry["entry_id"],
        "entities": sorted(entities, key=lambda item: item["entity_id"]),
        "subentries": instance.ws(
            "config_entries/subentries/list", entry_id=entry["entry_id"]
        ),
    }


def saved_configuration(instance: SmokeInstance) -> dict:
    """Read only this disposable instance's flushed integration configuration."""
    storage = json.loads((instance.config / ".storage/core.config_entries").read_text())
    entry = next(
        item for item in storage["data"]["entries"] if item["domain"] == "vegvesen"
    )
    return {
        key: entry[key]
        for key in ("version", "minor_version", "data", "options", "subentries")
    }


def verify_rollback(instance: SmokeInstance) -> None:
    """Replace only this runner's disposable component, then restart its HA child."""
    before = snapshot(instance)
    archive = subprocess.run(  # noqa: S603
        ["git", "archive", "--format=zip", STABLE_COMMIT, "custom_components/vegvesen"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    instance.stop()
    saved_before = saved_configuration(instance)
    component = instance.config / "custom_components/vegvesen"
    shutil.rmtree(component)
    with ZipFile(BytesIO(archive)) as package:
        package.extractall(instance.config)
    if json.loads((component / "manifest.json").read_text())["version"] != "0.7.4":
        raise AssertionError("Wrong rollback package")
    instance.start()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        entries = instance.ws("config_entries/get", domain="vegvesen")
        if entries and entries[0]["state"] == "loaded":
            states = instance.session.get(
                instance.base + "/api/states", timeout=10
            ).json()
            available = {
                state["entity_id"]
                for state in states
                if state["state"] != "unavailable"
            }
            expected = {item["entity_id"] for item in before["entities"]}
            if expected <= available:
                break
        time.sleep(1)
    else:
        raise AssertionError("Stable entities did not recover after rollback")
    if snapshot(instance) != before:
        raise AssertionError("Rollback changed existing identities or route settings")
    instance.stop()
    if saved_configuration(instance) != saved_before:
        raise AssertionError("Rollback changed saved configuration or route geometry")
    result = {
        "stable_version": "0.7.4",
        "stable_commit": STABLE_COMMIT,
        "preserved_entities": len(before["entities"]),
        "preserved_subentries": len(before["subentries"]),
        "saved_configuration_unchanged": True,
    }
    (instance.results / "rollback.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Stable rollback verified:", result)
