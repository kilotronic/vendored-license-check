# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""Tests for the vendored-license-check gate, exercised via tmp_path fixtures."""

from __future__ import annotations

from pathlib import Path

from vendored_license_check.check import (
    DEFAULT_ALLOWED_LICENSES,
    attributions_csv,
    check,
    main,
)

ALLOW = frozenset(DEFAULT_ALLOWED_LICENSES)
ROOTS = ["vendor"]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _vendored(root: Path, rel: str) -> Path:
    full = root / rel
    _write(full, "// stub\n")
    return full


def _manifest(root: Path, body: str) -> Path:
    path = root / "vendored-assets.toml"
    _write(path, body)
    return path


def test_all_declared_allowed_passes(tmp_path: Path) -> None:
    _vendored(tmp_path, "vendor/qrcode-generator.js")
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/qrcode-generator.js"
name = "qrcode-generator"
license = "MIT"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW)
    assert errors == [], errors


def test_undeclared_file_fails(tmp_path: Path) -> None:
    _vendored(tmp_path, "vendor/qrcode-generator.js")
    _vendored(tmp_path, "vendor/surprise.js")
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/qrcode-generator.js"
name = "qrcode-generator"
license = "MIT"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW)
    assert len(errors) == 1
    assert "surprise.js" in errors[0]


def test_disallowed_license_fails(tmp_path: Path) -> None:
    _vendored(tmp_path, "vendor/gpl-thing.js")
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/gpl-thing.js"
name = "gpl-thing"
license = "GPL-3.0-only"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW)
    assert len(errors) == 1
    assert "GPL-3.0-only" in errors[0]
    assert "gpl-thing" in errors[0]


def test_deny_list_overrides_allow(tmp_path: Path) -> None:
    """An id on both allow and deny is rejected, with the deny message."""
    _vendored(tmp_path, "vendor/mpl-thing.js")
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/mpl-thing.js"
name = "mpl-thing"
license = "MPL-2.0"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW, deny=frozenset({"MPL-2.0"}))
    assert len(errors) == 1
    assert "Denied" in errors[0]
    assert "MPL-2.0" in errors[0]


def test_glob_match_covers_multiple_files(tmp_path: Path) -> None:
    _vendored(tmp_path, "vendor/fonts/Outfit-Regular.woff2")
    _vendored(tmp_path, "vendor/fonts/Outfit-Bold.woff2")
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/fonts/Outfit-*.woff2"
name = "Outfit"
license = "OFL-1.1"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW)
    assert errors == [], errors


def test_glob_with_no_current_matches_is_valid(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/fonts/Outfit-*.woff2"
name = "Outfit"
license = "OFL-1.1"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW)
    assert errors == [], errors


def test_legal_and_doc_files_are_meta(tmp_path: Path) -> None:
    """LICENSE/README/COPYING/NOTICE, a font's OFL.txt, and *.md need no entry."""
    _vendored(tmp_path, "vendor/LICENSE-MIT")
    _vendored(tmp_path, "vendor/README-FONTS")
    _vendored(tmp_path, "vendor/OFL.txt")
    _vendored(tmp_path, "vendor/COPYING")
    _vendored(tmp_path, "vendor/NOTICE")
    _vendored(tmp_path, "vendor/notes.md")
    _vendored(tmp_path, "vendor/qrcode-generator.js")
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/qrcode-generator.js"
name = "qrcode-generator"
license = "MIT"
""",
    )
    errors, _ = check(tmp_path, manifest, ROOTS, ALLOW)
    assert errors == [], errors


def test_attributions_csv(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        """
[[asset]]
path = "vendor/qrcode-generator.js"
name = "qrcode-generator"
version = "1.0.0"
license = "MIT"
url = "https://example.com"
""",
    )
    csv = attributions_csv(manifest)
    assert csv.splitlines()[0] == '"Name","Version","License","URL"'
    assert '"qrcode-generator","1.0.0","MIT","https://example.com"' in csv


def test_main_reads_config_from_manifest(tmp_path: Path) -> None:
    """End-to-end: roots + allow resolved from the manifest [config] table."""
    _vendored(tmp_path, "vendor/thing.js")
    _manifest(
        tmp_path,
        """
[config]
roots = ["vendor"]
allow = ["MIT"]

[[asset]]
path = "vendor/thing.js"
name = "thing"
license = "MIT"
""",
    )
    rc = main(["--root-dir", str(tmp_path)])
    assert rc == 0


def test_main_fails_on_undeclared(tmp_path: Path) -> None:
    _vendored(tmp_path, "vendor/thing.js")
    _vendored(tmp_path, "vendor/undeclared.js")
    _manifest(
        tmp_path,
        """
[config]
roots = ["vendor"]

[[asset]]
path = "vendor/thing.js"
name = "thing"
license = "MIT"
""",
    )
    rc = main(["--root-dir", str(tmp_path)])
    assert rc == 1


def test_main_errors_without_roots(tmp_path: Path) -> None:
    """No roots on CLI or in manifest → configuration error (exit 2)."""
    _manifest(tmp_path, "")
    rc = main(["--root-dir", str(tmp_path)])
    assert rc == 2
