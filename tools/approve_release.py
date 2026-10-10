"""Check the files of one build of main and describe them for the website's download page.

Run by the *publish-download* workflow on the files of the ``main-build`` pre-release. The
installers must be the bytes their checksums and manifests describe, built from one clean
commit. What is written (``release.json``) is what the website reads to offer the build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

#: Platform -> the ending of its installer's file name.
INSTALLERS = {"linux": ".AppImage", "windows": "-Setup.exe"}


class NotPublishable(ValueError):
    """The files do not prove what they are."""


def describe(folder: Path, *, revision: str | None = None) -> dict:
    """``release.json`` for the build in ``folder``; raises NotPublishable if it cannot be vouched for."""
    files: dict[str, dict[str, str]] = {}
    builds = []
    for platform, ending in INSTALLERS.items():
        found = sorted(p for p in folder.iterdir() if p.name.endswith(ending))
        if len(found) != 1:
            raise NotPublishable(f"expected one {platform} installer (*{ending}), found {len(found)}")
        installer = found[0]
        manifest_path = installer.with_name(installer.name + ".manifest.json")
        checksum_path = installer.with_name(installer.name + ".sha256")
        if not manifest_path.is_file() or not checksum_path.is_file():
            raise NotPublishable(f"{installer.name} has no manifest or checksum beside it")
        digest = hashlib.sha256()
        with installer.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        manifest = json.loads(manifest_path.read_text())
        if checksum_path.read_text().split()[:1] != [sha256] or manifest.get("sha256") != sha256:
            raise NotPublishable(f"{installer.name} is not the file its checksum and manifest describe")
        if manifest.get("artifact") != installer.name or not isinstance(manifest.get("build"), dict):
            raise NotPublishable(f"{manifest_path.name} describes another file")
        builds.append(manifest["build"])
        files[platform] = {"name": installer.name, "sha256": sha256, "manifest": manifest_path.name}

    first = builds[0]
    for key in ("version", "source_revision", "channel"):
        if len({build.get(key) for build in builds}) != 1 or not isinstance(first.get(key), str) or not first[key]:
            raise NotPublishable(f"the installers disagree on their {key.replace('_', ' ')}")
    if not re.fullmatch(r"[0-9a-f]{40}", first["source_revision"]):
        raise NotPublishable("the build does not name the commit it was made from")
    if any(build.get("source_dirty") is not False for build in builds):
        raise NotPublishable("the build was not made from a clean tree")
    if revision and first["source_revision"] != revision:
        raise NotPublishable(f"the files were built from {first['source_revision'][:12]}, not from {revision[:12]}")
    return {
        "format_version": 1,
        "tag": f"build-{first['version']}-{first['source_revision'][:12]}",
        "version": first["version"],
        "channel": first["channel"],
        "source_revision": first["source_revision"],
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="folder holding both installers, their manifests and checksums")
    parser.add_argument("--out", type=Path, required=True, help="where to write release.json")
    parser.add_argument("--revision", help="the commit the files must have been built from")
    args = parser.parse_args()
    try:
        release = describe(args.dir, revision=args.revision)
    except NotPublishable as problem:
        raise SystemExit(f"Not publishable: {problem}") from problem
    args.out.write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps(release, indent=2))


if __name__ == "__main__":
    main()
