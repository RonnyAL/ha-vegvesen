"""Disposable, loopback-only Home Assistant process for live smoke checks."""

import asyncio
import json
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path

import aiohttp
import requests
from awesomeversion import AwesomeVersion

ROOT = Path(__file__).resolve().parent.parent


class SmokeInstance:
    """Own only the test child; keep authentication inside its temporary config."""

    def __init__(self, config: Path, results: Path, python: Path, port: int) -> None:
        """Prepare configuration without starting a process."""
        self.config = config
        self.results = results
        self.python = python
        self.base = f"http://127.0.0.1:{port}"
        self.process = None
        self.tokens = {}
        self.session = requests.Session()
        self.session.trust_env = False
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        results.mkdir(parents=True, exist_ok=True)
        # A failed run must not leave a previous run's success marker behind.
        for name in ("result.json", "lifecycle.json", "failure.png"):
            (results / name).unlink(missing_ok=True)
        (results / "home-assistant.log").write_text("")
        (config / ".storage").mkdir()
        (config / ".storage/onboarding").write_text(
            json.dumps(
                {
                    "version": 4,
                    "minor_version": 1,
                    "key": "onboarding",
                    "data": {"done": ["core_config", "analytics", "integration"]},
                }
            )
        )
        (config / "configuration.yaml").write_text(
            "homeassistant:\n  name: Vegvesen isolated smoke test\n"
            "  latitude: 0\n  longitude: 0\n  elevation: 0\n"
            "  time_zone: Europe/Oslo\n  unit_system: metric\n"
            f"frontend:\nhttp:\n  server_host: 127.0.0.1\n  server_port: {port}\n"
            "logger:\n  default: warning\n"
            "zone:\n  - name: Trondheim\n    latitude: 63.43\n    longitude: 10.395\n"
            "  - name: Orkanger\n    latitude: 63.305\n    longitude: 9.846\n"
            f"ffmpeg:\n  ffmpeg_bin: {ROOT}/.tools/browsers/ffmpeg-1011/ffmpeg-linux\n"
        )

    def start(self) -> None:
        """Start the selected interpreter and wait for its HTTP API."""
        if self.process is not None:
            raise RuntimeError("Stop the existing test child before starting again")
        with (self.results / "home-assistant.log").open("a") as log:
            self.process = subprocess.Popen(  # noqa: S603
                [
                    str(self.python),
                    "-E",
                    "-m",
                    "homeassistant",
                    "--config",
                    str(self.config),
                    "--skip-pip",
                ],
                cwd=self.config,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 90
        endpoint = "/api/" if self.tokens else "/api/onboarding"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Temporary HA exited; inspect the smoke log")
            try:
                if self.session.get(self.base + endpoint, timeout=1).ok:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        raise RuntimeError("Temporary HA startup timed out")

    def onboard(self) -> None:
        """Create a disposable owner through HA's normal onboarding API."""
        owner = self.session.post(
            self.base + "/api/onboarding/users",
            json={
                "name": "Smoke test",
                "username": "smoke",
                "password": secrets.token_urlsafe(32),
                "client_id": self.base + "/",
                "language": "en",
            },
            timeout=30,
        )
        owner.raise_for_status()
        response = self.session.post(
            self.base + "/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": owner.json()["auth_code"],
                "client_id": self.base + "/",
            },
            timeout=10,
        )
        response.raise_for_status()
        self.tokens = response.json()
        self.session.headers["Authorization"] = "Bearer " + self.tokens["access_token"]
        response = self.session.get(self.base + "/api/config", timeout=10)
        response.raise_for_status()
        # The primary target reverts an unconfirmed HTTP binding after five
        # minutes. Use the same command as its native Confirm button before
        # waiting for interactive HACS authorization.
        if (
            AwesomeVersion(response.json()["version"]) >= AwesomeVersion("2026.9.0")
            and self.ws("http/config")["pending"] is not None
        ):
            self.ws("http/config/promote")
            print("Confirmed the disposable HTTP binding through HA's native API")

    def ws(self, command: str, **fields: object) -> object:
        """Call the same websocket commands used by the native frontend."""

        async def call() -> object:
            async with (
                asyncio.timeout(180),
                aiohttp.ClientSession() as session,
                session.ws_connect(self.base + "/api/websocket") as websocket,
            ):
                await websocket.receive_json()
                await websocket.send_json(
                    {"type": "auth", "access_token": self.tokens["access_token"]}
                )
                if (await websocket.receive_json())["type"] != "auth_ok":
                    raise RuntimeError("Temporary HA authentication failed")
                await websocket.send_json({"id": 1, "type": command, **fields})
                while True:
                    message = await websocket.receive_json()
                    if message.get("id") == 1:
                        if not message.get("success"):
                            raise RuntimeError(f"{command}: {message.get('error')}")
                        return message.get("result")

        return asyncio.run(call())

    def stop(self) -> None:
        """Stop only this child, including when a check fails."""
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        print("Temporary HA stopped")


def handle_termination() -> None:
    """Ensure SIGTERM reaches the runner's normal finally cleanup."""

    def stop_requested(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop_requested)
