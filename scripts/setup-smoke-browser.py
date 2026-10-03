"""Extract Debian 12 amd64 browser dependencies locally; never install on host."""

import hashlib
import json
import subprocess
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
tools = ROOT / ".tools"
packages = tools / "native/packages"
packages.mkdir(parents=True, exist_ok=True)
for item in json.loads((ROOT / "environments/browser-packages.json").read_text()):
    path = packages / item["filename"]
    if not path.exists():
        with urlopen(item["url"], timeout=60) as response:
            path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(f"Checksum mismatch: {path}")
    subprocess.run(["dpkg-deb", "-x", str(path), str(tools / "native")], check=True)
(tools / "fonts.conf").write_text(
    '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
    f"<fontconfig><dir>{tools}/native/usr/share/fonts</dir>"
    f"<cachedir>{ROOT}/.cache/fonts</cachedir></fontconfig>"
)
print("Verified and extracted 19 browser dependency packages inside .tools")
