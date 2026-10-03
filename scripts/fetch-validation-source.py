"""Fetch checksum-pinned official validator source into ignored local tools."""

import hashlib
import io
import sys
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "core": (
        "https://codeload.github.com/home-assistant/core/tar.gz/2026.9.4",
        "2e8b7519622d24c82fe71f2956f8aef104cfca2e7485dd3039f85775e83dda0b",
        "core-2026.9.4",
    ),
    "hacs": (
        "https://codeload.github.com/hacs/integration/tar.gz/2.0.5",
        "c16902a5e2dd5da016583bbab409217cc0cfcd4a4899bb89aa1fd3e6f7b8a263",
        "hacs-integration-2.0.5",
    ),
}

url, digest, directory = SOURCES[sys.argv[1]]
tools = ROOT / ".tools"
tools.mkdir(exist_ok=True)
archive_path = tools / f"{directory}.tar.gz"
if not archive_path.exists():
    with urlopen(url, timeout=60) as response:
        archive_path.write_bytes(response.read())
archive = archive_path.read_bytes()
if hashlib.sha256(archive).hexdigest() != digest:
    raise SystemExit(f"Checksum mismatch: {archive_path}")
if not (tools / directory).is_dir():
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(tools, filter="data")
print(f"Verified official source: {directory}")
