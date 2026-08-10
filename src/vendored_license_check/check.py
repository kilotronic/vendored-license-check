#!/usr/bin/env python3
# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""Gate a repository on vendored (committed) third-party asset license policy.

For every file under the configured *vendored roots*, this checks that:

- the file is **declared** in a TOML manifest (by exact path or fnmatch glob), and
- every manifest entry carries an SPDX license that is on the **allow-list** and
  not on the **deny-list** (copyleft such as GPL/LGPL/AGPL is blocked by being
  absent from the default allow-list).

Unlike dependency license scanners (which read package manifests / lockfiles) or
per-file header tools (which cannot annotate binary assets like fonts), this gate
operates on *loose files committed into the repository* and enforces a license
*policy*, not just detection.

Configuration is resolved with the precedence: **CLI flag > manifest ``[config]``
table > built-in default**. The module is stdlib-only (``tomllib``, Python 3.11+)
so it needs no install to run.

``check()`` takes injectable ``root`` / ``manifest_path`` / policy arguments so it
can be unit-tested against ``tmp_path`` fixtures rather than a live tree.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Copyleft (GPL/LGPL/AGPL) is deliberately excluded so the gate rejects it
# unless a caller explicitly widens the policy via --allow / [config].allow.
DEFAULT_ALLOWED_LICENSES: tuple[str, ...] = (
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "OFL-1.1",
    "Unlicense",
    "0BSD",
    "CC0-1.0",
    "MPL-2.0",
    "Python-2.0",
)

# Legal/attribution files that ship beside vendored assets — a font's OFL.txt, a
# bundled LICENSE/NOTICE/COPYING, a README — are not themselves third-party
# assets, so they need no manifest entry.
_META_NAME_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "OFL", "README")
_SKIP_SUFFIXES = frozenset({".md", ".LICENSE"})


@dataclass(frozen=True)
class Config:
    """Resolved policy for a single check run."""

    root: Path
    manifest_path: Path
    roots: list[str]
    allow: frozenset[str]
    deny: frozenset[str] = field(default_factory=frozenset)


def load_manifest(manifest_path: Path) -> dict:
    """Parse the TOML manifest. Raises FileNotFoundError / TOMLDecodeError as-is."""
    with manifest_path.open("rb") as fh:
        return tomllib.load(fh)


def _is_meta_file(path: Path) -> bool:
    """Return True for attribution/legal files that need no manifest entry."""
    name = path.name
    if name.startswith("."):
        return True
    if path.suffix in _SKIP_SUFFIXES:
        return True
    return name.upper().startswith(_META_NAME_PREFIXES)


def enumerate_vendored(root: Path, roots: list[str]) -> list[Path]:
    """Enumerate real (non-meta) files under each vendored root, relative to *root*."""
    files: list[Path] = []
    for rel_root in roots:
        abs_root = root / rel_root
        if not abs_root.is_dir():
            continue
        files.extend(
            p for p in abs_root.rglob("*") if p.is_file() and not _is_meta_file(p)
        )
    return files


def _file_is_declared(rel_path: str, patterns: list[str]) -> bool:
    """Return True if *rel_path* matches any pattern (exact or fnmatch glob)."""
    return any(
        rel_path == pattern or fnmatch.fnmatch(rel_path, pattern)
        for pattern in patterns
    )


def check(
    root: Path,
    manifest_path: Path,
    roots: list[str],
    allow: frozenset[str],
    deny: frozenset[str] = frozenset(),
) -> tuple[list[str], list[Path]]:
    """Run the gate. Return ``(errors, enumerated_files)`` — empty errors == pass.

    Each error string describes one violation: a disallowed/denied license on a
    manifest entry, or a vendored file with no matching manifest entry.
    """
    manifest = load_manifest(manifest_path)
    assets: list[dict] = manifest.get("asset", [])

    errors: list[str] = []
    patterns: list[str] = []
    for asset in assets:
        path_pattern: str = asset["path"]
        patterns.append(path_pattern)
        license_id: str = asset.get("license", "")
        name = asset.get("name", path_pattern)
        if license_id in deny:
            errors.append(
                f"Denied license '{license_id}' on asset '{name}' "
                f"(path: {path_pattern}). It is on the deny-list."
            )
        elif license_id not in allow:
            errors.append(
                f"Disallowed license '{license_id}' on asset '{name}' "
                f"(path: {path_pattern}). Permitted: {', '.join(sorted(allow))}."
            )

    enumerated_files = enumerate_vendored(root, roots)
    for abs_path in enumerated_files:
        rel = str(abs_path.relative_to(root)).replace("\\", "/")
        if not _file_is_declared(rel, patterns):
            errors.append(
                f"Undeclared vendored file: {rel} — add an [[asset]] entry to "
                f"{manifest_path.name}."
            )

    return errors, enumerated_files


def attributions_csv(manifest_path: Path) -> str:
    """Return CSV rows (Name, Version, License, URL) for every manifest entry."""
    manifest = load_manifest(manifest_path)
    lines = ['"Name","Version","License","URL"']
    for asset in manifest.get("asset", []):
        name = asset.get("name", "")
        version = asset.get("version", "")
        license_id = asset.get("license", "")
        url = asset.get("url", "")
        lines.append(f'"{name}","{version}","{license_id}","{url}"')
    return "\n".join(lines)


def _split(values: list[str] | None) -> list[str]:
    """Flatten repeated flags and split comma/whitespace-separated values.

    ``--root a,b --root c`` and ``--root "a b"`` both yield ``["a", "b", "c"]``.
    Lets one Action string input map cleanly to a repeatable CLI flag.
    """
    out: list[str] = []
    for value in values or []:
        out.extend(part for chunk in value.split(",") for part in chunk.split())
    return out


def resolve_config(args: argparse.Namespace) -> Config:
    """Resolve policy from CLI flags, then manifest ``[config]``, then defaults."""
    root = Path(args.root_dir).resolve()
    manifest_path = (
        Path(args.manifest)
        if Path(args.manifest).is_absolute()
        else root / args.manifest
    )
    manifest_cfg = load_manifest(manifest_path).get("config", {})

    roots = _split(args.roots) or list(manifest_cfg.get("roots", []))
    allow = (
        _split(args.allow)
        or list(manifest_cfg.get("allow", []))
        or list(DEFAULT_ALLOWED_LICENSES)
    )
    deny = _split(args.deny) or list(manifest_cfg.get("deny", []))

    return Config(
        root=root,
        manifest_path=manifest_path,
        roots=roots,
        allow=frozenset(allow),
        deny=frozenset(deny),
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vendored-license-check",
        description="Enforce declared, allow-listed licenses on vendored asset files.",
    )
    p.add_argument(
        "--root-dir",
        default=".",
        help="Repository root the roots/manifest are relative to (default: CWD).",
    )
    p.add_argument(
        "--manifest",
        default="vendored-assets.toml",
        help="Path to the TOML manifest (default: vendored-assets.toml).",
    )
    p.add_argument(
        "--root",
        dest="roots",
        action="append",
        metavar="DIR",
        help="Vendored root directory to scan (repeatable / comma-separated). "
        "Falls back to manifest [config].roots.",
    )
    p.add_argument(
        "--allow",
        action="append",
        metavar="SPDX",
        help="Allowed SPDX id (repeatable / comma-separated). Falls back to "
        "manifest [config].allow, then a built-in permissive set.",
    )
    p.add_argument(
        "--deny",
        action="append",
        metavar="SPDX",
        help="Explicitly denied SPDX id (repeatable / comma-separated). Falls "
        "back to manifest [config].deny.",
    )
    p.add_argument(
        "--attributions",
        action="store_true",
        help="Print a CSV of (Name, Version, License, URL) and exit without gating.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point for the console script, pre-commit hook, and CLI."""
    args = _build_parser().parse_args(argv)

    if args.attributions:
        root = Path(args.root_dir).resolve()
        manifest_path = (
            Path(args.manifest)
            if Path(args.manifest).is_absolute()
            else root / args.manifest
        )
        print(attributions_csv(manifest_path))
        return 0

    cfg = resolve_config(args)
    if not cfg.roots:
        print(
            "vendored-license-check: no vendored roots configured. Pass --root or "
            "add [config].roots to the manifest.",
            file=sys.stderr,
        )
        return 2

    errors, enumerated_files = check(
        cfg.root, cfg.manifest_path, cfg.roots, cfg.allow, cfg.deny
    )
    if errors:
        print("vendored-license-check: FAILED\n", file=sys.stderr)
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        print(
            f"\nFix: update {cfg.manifest_path.name} to declare every vendored "
            "file with a permitted SPDX license.",
            file=sys.stderr,
        )
        return 1

    print(
        f"vendored-license-check: OK ({len(enumerated_files)} vendored file(s) checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
