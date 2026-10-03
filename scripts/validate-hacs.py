"""Validate local packaging using official HACS schemas, without GitHub writes."""

import importlib
import json
import sys
import types
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
source = ROOT / ".tools/integration-2.0.5/custom_components/hacs"
# Load the official schemas without importing HACS's integration startup code.
package = types.ModuleType("_hacs_packaging")
package.__path__ = [str(source)]
sys.modules[package.__name__] = package
schemas = importlib.import_module("_hacs_packaging.utils.validate")
manifest = json.loads((ROOT / "custom_components/vegvesen/manifest.json").read_text())
hacs = json.loads((ROOT / "hacs.json").read_text())
schemas.INTEGRATION_MANIFEST_JSON_SCHEMA(manifest)
schemas.HACS_MANIFEST_JSON_SCHEMA(hacs)
directories = sorted(
    path.name
    for path in (ROOT / "custom_components").iterdir()
    if path.is_dir() and path.name != "__pycache__"
)
if directories != [manifest["domain"]] or manifest["name"] != hacs["name"]:
    raise SystemExit("Expected one integration and matching manifest names")
for filename in ("LICENSE", "README.md", "custom_components/vegvesen/__init__.py"):
    if not (ROOT / filename).is_file():
        raise SystemExit(f"Missing package file: {filename}")
component = ROOT / "custom_components/vegvesen"
if (component / "LICENSE").read_bytes() != (ROOT / "LICENSE").read_bytes():
    raise SystemExit("Installed package must preserve the original MIT license")
if not (component / "NOTICE.md").is_file():
    raise SystemExit("Installed package must include data attribution")
for filename, size in (("icon.png", 256), ("icon@2x.png", 512)):
    with Image.open(ROOT / "custom_components/vegvesen/brand" / filename) as icon:
        if icon.format != "PNG" or icon.size != (size, size):
            raise SystemExit(f"Invalid brand image: {filename}")
print("Local HACS manifest schemas, package structure and brand images pass")
print("Remote repository metadata, releases and HACS action are separate checks")
