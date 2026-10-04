"""
Exercise real HACS installation, upgrade and removal in disposable HA.

GitHub's normal HACS device authorization is required interactively. Credentials
are never accepted as arguments or written to the retained result files.
"""

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import requests
from smoke_instance import ROOT, SmokeInstance, handle_termination

RESULTS = ROOT / ".tools/smoke-results-hacs"
HACS_VERSION = "2.0.5"
HACS_SHA256 = "97be6b824a4f38e683728cc6dd72367f6b8bad0a43428b1b3b987a3087adf413"
OLD_VERSION = "0.7.2"
NEW_VERSION = "0.7.3"
REPOSITORY = "RonnyAL/ha-vegvesen"


def flow_request(
    instance: SmokeInstance, method: str, path: str, **data: object
) -> dict:
    """Drive HA's native config flow API without logging response credentials."""
    response = instance.session.request(
        method, instance.base + path, json=data or None, timeout=60
    )
    response.raise_for_status()
    return response.json()


def configure_hacs(instance: SmokeInstance) -> None:
    """Wait at most fourteen minutes for native GitHub device authorization."""
    path = "/api/config/config_entries/flow"
    flow = flow_request(instance, "POST", path, handler="hacs")
    path += "/" + flow["flow_id"]
    flow = flow_request(
        instance,
        "POST",
        path,
        acc_logs=True,
        acc_addons=True,
        acc_untested=True,
        acc_disable=True,
    )
    if flow["type"] != "progress":
        raise RuntimeError(f"HACS authorization did not start: {flow.get('reason')}")
    placeholders = flow["description_placeholders"]
    print(
        "Authorize this disposable HACS instance at",
        placeholders["url"],
        "with code",
        placeholders["code"],
        flush=True,
    )
    deadline = time.monotonic() + 840
    while time.monotonic() < deadline:
        flow = flow_request(instance, "GET", path)
        if flow["type"] == "create_entry":
            print("HACS native authorization completed")
            return
        if flow["type"] == "abort":
            raise RuntimeError(f"HACS authorization aborted: {flow.get('reason')}")
        time.sleep(3)
    raise TimeoutError("HACS device authorization expired; rerun for a new code")


def wait_loaded(instance: SmokeInstance, domain: str) -> dict:
    """Wait for one fully loaded parent after setup, upgrade or reconfiguration."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        entries = instance.ws("config_entries/get", domain=domain)
        if len(entries) == 1 and entries[0]["state"] == "loaded":
            return entries[0]
        time.sleep(1)
    raise TimeoutError(f"{domain} did not finish loading")


def wait_hacs_ready(instance: SmokeInstance) -> None:
    """Wait for HACS startup, not just HA's earlier entry-loaded state."""
    wait_loaded(instance, "hacs")
    print("Waiting for HACS startup tasks to finish")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        info = instance.ws("hacs/info")
        if info["disabled_reason"] is not None:
            raise RuntimeError(f"HACS disabled: {info['disabled_reason']}")
        if (
            not info["startup"]
            and info["stage"] == "running"
            and not info["has_pending_tasks"]
        ):
            print("HACS startup finished")
            return
        time.sleep(2)
    raise TimeoutError("HACS did not finish its startup tasks")


def repository_info(instance: SmokeInstance) -> dict:
    """Resolve the repository through HACS after each process restart."""
    repositories = instance.ws("hacs/repositories/list")
    repository = next(
        (item for item in repositories if item["full_name"] == REPOSITORY), None
    )
    if repository is None:
        raise AssertionError("HACS did not retain the custom repository")
    return instance.ws("hacs/repository/info", repository_id=str(repository["id"]))


def snapshot(instance: SmokeInstance, entry_id: str, *, removed: bool = False) -> dict:
    """Capture identities and source ownership without credentials or live values."""
    entities = [
        {
            key: item.get(key)
            for key in (
                "entity_id",
                "unique_id",
                "device_id",
                "config_subentry_id",
                "name",
            )
        }
        for item in instance.ws("config/entity_registry/list")
        if item.get("platform") == "vegvesen"
    ]
    devices = [
        {key: item.get(key) for key in ("id", "identifiers", "name", "name_by_user")}
        for item in instance.ws("config/device_registry/list")
        if entry_id in item["config_entries"]
    ]
    return {
        "entry_id": entry_id,
        "subentries": []
        if removed
        else sorted(
            instance.ws("config_entries/subentries/list", entry_id=entry_id),
            key=lambda item: item["subentry_id"],
        ),
        "entities": sorted(entities, key=lambda item: item["entity_id"]),
        "devices": sorted(devices, key=lambda item: item["id"]),
    }


def check_available(instance: SmokeInstance, expected: dict) -> None:
    """Wait for all registered integration entities to recover after restart."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = instance.session.get(instance.base + "/api/states", timeout=10)
        response.raise_for_status()
        states = {item["entity_id"]: item["state"] for item in response.json()}
        if all(
            states.get(item["entity_id"]) not in {None, "unknown", "unavailable"}
            for item in expected["entities"]
        ):
            return
        time.sleep(1)
    raise TimeoutError("Integration entities did not recover after restart")


def verify_removal(instance: SmokeInstance, before: dict) -> None:
    """Delete a weather station and route, then the parent and installed files."""
    entry_id = before["entry_id"]
    for family in ("weather_station", "route"):
        subentry = next(
            item for item in before["subentries"] if item["subentry_type"] == family
        )
        instance.ws(
            "config_entries/subentries/delete",
            entry_id=entry_id,
            subentry_id=subentry["subentry_id"],
        )
        time.sleep(1)
        wait_loaded(instance, "vegvesen")
        remaining = snapshot(instance, entry_id)
        if subentry in remaining["subentries"] or any(
            item["config_subentry_id"] == subentry["subentry_id"]
            for item in remaining["entities"]
        ):
            raise AssertionError(f"{family} ownership remained after removal")
        check_available(instance, remaining)
        print(f"Removed {family}; remaining sources stayed available")
    flow_request(instance, "DELETE", f"/api/config/config_entries/entry/{entry_id}")
    if instance.ws("config_entries/get", domain="vegvesen"):
        raise AssertionError("Parent remained after deletion")
    remaining = snapshot(instance, entry_id, removed=True)
    if remaining["entities"] or remaining["devices"]:
        raise AssertionError("Integration registry objects remained after deletion")


def run(instance: SmokeInstance) -> None:  # noqa: PLR0915
    """Use real HACS downloads and normal HA flows throughout the lifecycle."""
    instance.start()
    instance.onboard()
    configure_hacs(instance)
    wait_hacs_ready(instance)
    instance.ws("hacs/repositories/add", repository=REPOSITORY, category="integration")
    repository_id = str(repository_info(instance)["id"])
    instance.ws(
        "hacs/repository/download", repository=repository_id, version=OLD_VERSION
    )
    installed_manifest = instance.config / "custom_components/vegvesen/manifest.json"
    if json.loads(installed_manifest.read_text())["version"] != OLD_VERSION:
        raise AssertionError("HACS did not install the requested old release")
    print(f"HACS installed {OLD_VERSION}; restarting the disposable HA process")
    instance.stop()
    instance.start()
    wait_hacs_ready(instance)
    info = repository_info(instance)
    if info["installed_version"] != OLD_VERSION or not info["installed"]:
        raise AssertionError("HACS lost the installed release after restart")
    spec = importlib.util.spec_from_file_location(
        "smoke_ui", ROOT / "scripts/smoke-ui.py"
    )
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    ui.BASE = instance.base
    ui.RESULTS = RESULTS
    ui.run_browser(instance.tokens, instance.session)
    entry = wait_loaded(instance, "vegvesen")
    before = snapshot(instance, entry["entry_id"])
    repository_id = str(repository_info(instance)["id"])
    instance.ws(
        "hacs/repository/download", repository=repository_id, version=NEW_VERSION
    )
    info = instance.ws("hacs/repository/info", repository_id=repository_id)
    if info["installed_version"] != NEW_VERSION:
        raise AssertionError("HACS did not report the numbered upgraded release")
    if json.loads(installed_manifest.read_text())["version"] != NEW_VERSION:
        raise AssertionError("Installed files did not match the new release")
    print(f"HACS upgraded {OLD_VERSION} to {NEW_VERSION}; restarting HA")
    instance.stop()
    instance.start()
    wait_hacs_ready(instance)
    if repository_info(instance)["installed_version"] != NEW_VERSION:
        raise AssertionError("HACS lost the upgraded release after restart")
    wait_loaded(instance, "vegvesen")
    after = snapshot(instance, entry["entry_id"])
    if before != after:
        raise AssertionError(
            "Config subentries, entities or devices changed on upgrade"
        )
    check_available(instance, after)
    route = next(
        item for item in after["subentries"] if item["subentry_type"] == "route"
    )
    path = "/api/config/config_entries/subentries/flow"
    flow = flow_request(
        instance,
        "POST",
        path,
        handler=[entry["entry_id"], "route"],
        subentry_id=route["subentry_id"],
    )
    flow = flow_request(
        instance, "POST", path + "/" + flow["flow_id"], next_step_id="route_save"
    )
    if flow.get("reason") != "reconfigure_successful":
        raise AssertionError("Existing route could not be saved after upgrade")
    time.sleep(1)
    wait_loaded(instance, "vegvesen")
    if snapshot(instance, entry["entry_id"]) != after:
        raise AssertionError("Reconfiguration changed registry identities")
    print("Upgrade and reconfiguration preserved all source and entity identities")
    verify_removal(instance, after)
    instance.ws("hacs/repository/remove", repository=repository_id)
    if installed_manifest.exists():
        raise AssertionError("HACS uninstall left the integration installed")
    instance.stop()
    instance.start()
    wait_hacs_ready(instance)
    # HACS may omit an uninstalled custom repository from its next listing.
    # Both absence and an explicitly uninstalled listing are valid outcomes.
    repositories = instance.ws("hacs/repositories/list")
    if any(
        item["full_name"] == REPOSITORY and item["installed"] for item in repositories
    ):
        raise AssertionError("HACS still reports the integration as installed")
    if instance.ws("config_entries/get", domain="vegvesen"):
        raise AssertionError("Integration entry remained after uninstall and restart")
    summary = {
        "hacs": HACS_VERSION,
        "from_version": OLD_VERSION,
        "to_version": NEW_VERSION,
        "entities_preserved": len(after["entities"]),
        "devices_preserved": len(after["devices"]),
        "subentries_preserved": len(after["subentries"]),
        "reconfigure": "passed",
        "remove_sources": "passed",
        "uninstall": "passed",
    }
    (RESULTS / "lifecycle.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("Real HACS lifecycle passed:", summary)


def main() -> None:
    """Download pinned official HACS and clean up every test process and credential."""
    archive_path = ROOT / ".tools" / f"hacs-{HACS_VERSION}.zip"
    if not archive_path.exists():
        response = requests.get(
            f"https://github.com/hacs/integration/releases/download/{HACS_VERSION}/hacs.zip",
            timeout=60,
        )
        response.raise_for_status()
        archive_path.write_bytes(response.content)
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != HACS_SHA256:
        raise RuntimeError("Official HACS archive checksum mismatch")
    with TemporaryDirectory(prefix="vegvesen-hacs-", dir=ROOT / ".tools") as temporary:
        config = Path(temporary)
        with ZipFile(archive_path) as archive:
            archive.extractall(config / "custom_components/hacs")
        instance = SmokeInstance(config, RESULTS, Path(sys.executable), 18125)
        try:
            run(instance)
        finally:
            instance.stop()
    print("Disposable HACS configuration and authentication storage removed")


if __name__ == "__main__":
    handle_termination()
    main()
