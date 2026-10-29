"""Build the small, dependency-free SDK wheel: python -m granum.compute.sdk_wheel DIR."""
from __future__ import annotations

import base64
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import granum_compute_sdk


def build_sdk_wheel(directory: Path) -> Path:
    version = granum_compute_sdk.__version__
    name = f"granum_compute_sdk-{version}"
    files = {f"granum_compute_sdk/{p.name}": p.read_bytes() for p in Path(granum_compute_sdk.__file__).parent.glob("*.py")}
    info = f"{name}.dist-info"
    files[f"{info}/METADATA"] = f"Metadata-Version: 2.1\nName: granum-compute-sdk\nVersion: {version}\nRequires-Python: >=3.10\n".encode()
    files[f"{info}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: granum\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    records = [f"{path},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},{len(data)}" for path, data in files.items()]
    files[f"{info}/RECORD"] = ("\n".join([*records, f"{info}/RECORD,,"]) + "\n").encode()
    # Fixed ZipInfo timestamps make the SDK fingerprint reproducible.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as wheel:
        for path, data in sorted(files.items()):
            wheel.writestr(zipfile.ZipInfo(path), data)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}-py3-none-any.whl"
    target.write_bytes(buffer.getvalue())
    return target


if __name__ == "__main__":
    print(build_sdk_wheel(Path(sys.argv[1])))
