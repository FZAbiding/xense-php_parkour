#!/usr/bin/env python3
"""Prepare a workspace-local copy of Holosoma's installer, without installing.

Only the installer's workspace path and redundant system apt invocation change.
The pinned Holosoma source used for training remains the Git submodule itself.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "thirdparty/holosoma"
WORKSPACE = ROOT / "outputs/training_setup"
OVERLAY = WORKSPACE / "holosoma_overlay"
EXPECTED_COMMIT = "4a0bf04cde5930af5ed59da797568d32be972525"
OLD_COMMON = b"WORKSPACE_DIR=$HOME/.holosoma_deps\nCONDA_ROOT=$WORKSPACE_DIR/miniconda3\n"
NEW_COMMON = (
    b': "${PHP_TRAIN_WORKSPACE:?Set PHP_TRAIN_WORKSPACE to a workspace-local path}"\n'
    b'WORKSPACE_DIR="$PHP_TRAIN_WORKSPACE"\n'
    b'CONDA_ROOT="$WORKSPACE_DIR/miniconda3"\n'
)
OLD_APT = b"  sudo apt install -y cmake build-essential\n"
NEW_APT = (b"  command -v cmake >/dev/null\n"
           b"  command -v make >/dev/null\n"
           b"  command -v g++ >/dev/null\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    commit = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                                     text=True).strip()
    if commit != EXPECTED_COMMIT:
        raise RuntimeError(f"Holosoma pin changed: {commit}")
    if OVERLAY.exists():
        manifest_path = WORKSPACE / "overlay_manifest.json"
        if not manifest_path.exists():
            raise FileExistsError(f"overlay exists without manifest: {OVERLAY}")
        existing = json.loads(manifest_path.read_text())
        if existing.get("source_commit") != commit or not (OVERLAY / "src").is_symlink() \
                or (OVERLAY / "src").resolve() != (SOURCE / "src").resolve():
            raise RuntimeError("existing overlay does not match the pinned source")
        for name, hashes in existing["changes"].items():
            if sha256(SOURCE / "scripts" / name) != hashes["source_sha256"] or \
                    sha256(OVERLAY / "scripts" / name) != hashes["overlay_sha256"]:
                raise RuntimeError(f"existing overlay changed: {name}")
        print(json.dumps({"already_prepared_and_verified": str(OVERLAY),
                          "source_commit": commit}, indent=2))
        return
    common_source = SOURCE / "scripts/source_common.sh"
    setup_source = SOURCE / "scripts/setup_isaacsim.sh"
    if common_source.read_bytes() != OLD_COMMON:
        raise RuntimeError("source_common.sh changed; review its path handling")
    if setup_source.read_bytes().count(OLD_APT) != 1:
        raise RuntimeError("setup_isaacsim.sh changed; review system package commands")
    scripts = OVERLAY / "scripts"
    scripts.parent.mkdir(parents=True, exist_ok=False)
    shutil.copytree(SOURCE / "scripts", scripts)
    (OVERLAY / "src").symlink_to(SOURCE / "src", target_is_directory=True)
    (scripts / "source_common.sh").write_bytes(NEW_COMMON)
    (scripts / "setup_isaacsim.sh").write_bytes(
        setup_source.read_bytes().replace(OLD_APT, NEW_APT))
    manifest = {
        "source_commit": commit,
        "source_root": str(SOURCE),
        "workspace": str(WORKSPACE),
        "overlay": str(OVERLAY),
        "changes": {
            "source_common.sh": {"source_sha256": sha256(common_source),
                                 "overlay_sha256": sha256(scripts / "source_common.sh")},
            "setup_isaacsim.sh": {"source_sha256": sha256(setup_source),
                                  "overlay_sha256": sha256(scripts / "setup_isaacsim.sh")},
        },
        "installation_started": False,
    }
    (WORKSPACE / "overlay_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
