"""Deterministic local artifact packaging with an internal checksum manifest."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zlib
from typing import Any

from .experiment import verify_run_set


ROOT_FILES = (
    "AGENTS.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "REPRODUCING.md",
    "pyproject.toml",
)
ROOT_DIRECTORIES = ("src", "tests", "docs", "data", "experiments/configs")
# Paths never packaged. `data/raw` holds third-party datasets we download but do
# not redistribute, and compiled bytecode is noise that also breaks byte
# determinism across interpreters.
EXCLUDED_PARTS = ("__pycache__", ".pytest_cache", ".ruff_cache")
EXCLUDED_PREFIXES = ("data/raw",)


def create_artifact_archive(root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite: {output}")
    accepted_manifest = root / "experiments" / "accepted-runs.json"
    runs_root = root / "experiments" / "runs"
    if not verify_run_set(runs_root, accepted_manifest):
        raise ValueError("accepted experiment runs failed verification")
    accepted = json.loads(accepted_manifest.read_text(encoding="utf-8"))[
        "accepted_runs"
    ]
    paths = [root / name for name in ROOT_FILES]
    for directory in ROOT_DIRECTORIES:
        paths.extend(_files(root / directory))
    paths.append(accepted_manifest)
    for run_id in accepted:
        paths.extend(_files(runs_root / run_id))
    files = tuple(
        sorted(
            (
                path
                for path in set(paths)
                if not str(path.relative_to(root)).startswith(EXCLUDED_PREFIXES)
            ),
            key=lambda path: str(path.relative_to(root)),
        )
    )
    files = tuple(path for path in files if path not in _git_ignored(root, files))
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("artifact inputs must be regular files")
    file_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "redistribution_status": "permitted_under_apache_2_0",
        "accepted_runs": accepted,
        "files": file_hashes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in files:
                    _add_bytes(tar, str(path.relative_to(root)), path.read_bytes())
                _add_bytes(
                    tar,
                    "ARTIFACT-MANIFEST.json",
                    (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
                )
    return manifest


def _gzip_envelope_intact(archive: Path) -> bool:
    """Decode the whole gzip stream so its trailing CRC is actually checked.

    Verifying member checksums alone only proves *content* integrity: a byte
    flipped in tar padding or gzip framing can leave every member unchanged and
    pass. Reading the stream to completion forces gzip's CRC32/length check, so
    envelope corruption is reported rather than silently accepted.
    """
    try:
        with gzip.open(archive, "rb") as stream:
            while stream.read(1 << 20):
                pass
    except (OSError, EOFError, zlib.error):
        return False
    return True


def verify_artifact_archive(archive: Path) -> bool:
    if not _gzip_envelope_intact(archive):
        return False
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            if any(not member.isfile() for member in members):
                return False
            names = [member.name for member in members]
            if len(names) != len(set(names)) or "ARTIFACT-MANIFEST.json" not in names:
                return False
            manifest_file = tar.extractfile("ARTIFACT-MANIFEST.json")
            if manifest_file is None:
                return False
            manifest = json.loads(manifest_file.read())
            recorded = manifest["files"]
            actual = {}
            for name in names:
                if name == "ARTIFACT-MANIFEST.json":
                    continue
                stream = tar.extractfile(name)
                if stream is None:
                    return False
                actual[name] = hashlib.sha256(stream.read()).hexdigest()
            return recorded == actual
    except (KeyError, OSError, tarfile.TarError, json.JSONDecodeError):
        return False


def _git_ignored(root: Path, paths: tuple[Path, ...]) -> set[Path]:
    """Paths git ignores in ``root``; empty when ``root`` is not a work tree.

    The packager walks the filesystem, so anything sitting under a packaged
    directory goes in unless excluded. Excluding by prefix failed twice: first
    data/raw, then the LongMemEval labelling sheets, which quote the corpus and
    are ignored for exactly that reason. Deferring to .gitignore means a file
    kept out of the public repository is kept out of the artifact too, without
    a second list to maintain.
    """
    import subprocess

    if not (root / ".git").exists() or not paths:
        return set()
    relative = "\0".join(str(path.relative_to(root)) for path in paths)
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin", "-z"],
        input=relative.encode(), capture_output=True, check=False,
    )
    # exit 1 means "nothing ignored"; anything above it is a real failure
    if result.returncode > 1:
        raise RuntimeError(f"git check-ignore failed: {result.stderr.decode()}")
    return {root / name for name in result.stdout.decode().split("\0") if name}


def _files(directory: Path) -> list[Path]:
    return [
        path
        for path in directory.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)
    ]


def _add_bytes(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tar.addfile(info, io.BytesIO(payload))
