"""Build a deterministic local review/install archive containing runtime files."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
component = ROOT / "custom_components/vegvesen"
version = json.loads((component / "manifest.json").read_text())["version"]
output = ROOT / ".tools/packages" / f"vegvesen-{version}.zip"
output.parent.mkdir(parents=True, exist_ok=True)
count = 0
with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(component.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"Package contains a symlink: {path}")
        if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.name != "LICENSE" and path.suffix not in {
            ".py",
            ".json",
            ".png",
            ".svg",
            ".md",
            ".yaml",
        }:
            raise SystemExit(f"Unexpected runtime package file: {path}")
        info = ZipInfo(str(path.relative_to(ROOT)), date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, path.read_bytes())
        count += 1
checksum = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n")
print(f"Built {output.relative_to(ROOT)}: {count} runtime files, SHA256 {checksum}")
