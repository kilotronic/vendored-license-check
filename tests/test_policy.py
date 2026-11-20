# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""The policy end to end: defaults, CLI over manifest precedence, nesting, and the Action's own command."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from vendored_license_check.check import DEFAULT_ALLOWED_LICENSES, main

ROOT = Path(__file__).resolve().parent.parent


def _tree(tmp_path: Path, manifest: str, *files: str) -> Path:
    for rel in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("// stub\n", encoding="utf-8")
    (tmp_path / "vendored-assets.toml").write_text(manifest, encoding="utf-8")
    return tmp_path


def _asset(path: str, license_id: str) -> str:
    return f'[[asset]]\npath = "{path}"\nname = "lib"\nlicense = "{license_id}"\n'


@pytest.mark.parametrize(
    "license_id",
    ["GPL-2.0-only", "GPL-3.0-or-later", "LGPL-2.1-only", "AGPL-3.0-only", "", "mit"],
)
def test_the_default_policy_refuses_copyleft_and_unknown_ids(
    tmp_path: Path, license_id: str
) -> None:
    assert license_id not in DEFAULT_ALLOWED_LICENSES
    _tree(tmp_path, _asset("vendor/a.js", license_id), "vendor/a.js")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 1


def test_an_entry_without_a_license_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, '[[asset]]\npath = "vendor/a.js"\n', "vendor/a.js")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 1


def test_files_in_nested_directories_must_be_declared(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js", "vendor/deep/er/b.js")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 1


def test_every_root_is_scanned(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("ui/a.js", "MIT"), "ui/a.js", "fonts/b.woff2")
    assert main(["--root-dir", str(tmp_path), "--root", "ui"]) == 0
    assert main(["--root-dir", str(tmp_path), "--root", "ui,fonts"]) == 1
    assert main(["--root-dir", str(tmp_path), "--root", "ui fonts"]) == 1
    assert main(["--root-dir", str(tmp_path), "--root", "ui", "--root", "fonts"]) == 1


@pytest.mark.parametrize(
    "name", ["licensed-widget.js", "noticeboard.js", "readme-viewer.js", "x.LICENSE.js"]
)
def test_an_asset_named_like_a_legal_file_still_needs_an_entry(
    tmp_path: Path, name: str
) -> None:
    """Only the file name's start marks a legal file; a library with LICENSE elsewhere in its name is checked."""
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js", f"vendor/lib-{name}")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 1


def test_cli_allow_overrides_the_manifest(tmp_path: Path) -> None:
    manifest = '[config]\nroots = ["vendor"]\nallow = ["MIT"]\n' + _asset(
        "vendor/a.js", "Apache-2.0"
    )
    _tree(tmp_path, manifest, "vendor/a.js")
    assert main(["--root-dir", str(tmp_path)]) == 1
    assert main(["--root-dir", str(tmp_path), "--allow", "MIT,Apache-2.0"]) == 0
    assert main(["--root-dir", str(tmp_path), "--allow", "ISC"]) == 1


def test_manifest_allow_replaces_the_default(tmp_path: Path) -> None:
    manifest = '[config]\nroots = ["vendor"]\nallow = ["ISC"]\n' + _asset(
        "vendor/a.js", "MIT"
    )
    _tree(tmp_path, manifest, "vendor/a.js")
    assert main(["--root-dir", str(tmp_path)]) == 1


def test_manifest_deny_refuses_an_allowed_license(tmp_path: Path) -> None:
    manifest = '[config]\nroots = ["vendor"]\ndeny = ["MPL-2.0"]\n' + _asset(
        "vendor/a.js", "MPL-2.0"
    )
    _tree(tmp_path, manifest, "vendor/a.js")
    assert main(["--root-dir", str(tmp_path)]) == 1


def test_cli_deny_refuses_an_allowed_license(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MPL-2.0"), "vendor/a.js")
    args = ["--root-dir", str(tmp_path), "--root", "vendor"]
    assert main(args) == 0
    assert main([*args, "--deny", "GPL-3.0-only, MPL-2.0"]) == 1


def test_cli_roots_override_the_manifest(tmp_path: Path) -> None:
    manifest = '[config]\nroots = ["clean"]\n' + _asset("clean/a.js", "MIT")
    _tree(tmp_path, manifest, "clean/a.js", "other/b.js")
    assert main(["--root-dir", str(tmp_path)]) == 0
    assert main(["--root-dir", str(tmp_path), "--root", "other"]) == 1


def test_a_disallowed_license_fails_even_with_no_files(tmp_path: Path) -> None:
    """A forward-declared entry is still held to the policy."""
    _tree(tmp_path, _asset("vendor/fonts/*.woff2", "GPL-3.0-only"))
    (tmp_path / "vendor").mkdir()
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 1


# --- The Action's run step, with its inputs filled in, against a tree.


def _action(tree: Path, **inputs: str) -> subprocess.CompletedProcess:
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    script = text.split("name: Run vendored-license-check", 1)[1].split("run: |", 1)[1]
    values = {"root-dir": str(tree), "manifest": "vendored-assets.toml", "roots": ""}
    values.update({"allow": "", "deny": "", **inputs})
    script = re.sub(r"\$\{\{ inputs\.([a-z-]+) \}\}", lambda m: values[m[1]], script)
    env = dict(os.environ, GITHUB_ACTION_PATH=str(ROOT))
    return subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )


def test_action_passes_a_clean_tree(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js")
    run = _action(tmp_path, roots="vendor")
    assert run.returncode == 0, run.stderr


def test_action_refuses_an_undeclared_file(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js", "vendor/b.js")
    run = _action(tmp_path, roots="vendor")
    assert run.returncode == 1
    assert "vendored-license-check: FAILED" in run.stderr


def test_action_passes_the_allow_input(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js")
    run = _action(tmp_path, roots="vendor", allow="ISC")
    assert run.returncode == 1
    assert "vendored-license-check: FAILED" in run.stderr


def test_action_passes_the_deny_input(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js")
    run = _action(tmp_path, roots="vendor", deny="MIT")
    assert run.returncode == 1
    assert "vendored-license-check: FAILED" in run.stderr


def test_action_reads_the_manifest_config_when_inputs_are_empty(tmp_path: Path) -> None:
    manifest = '[config]\nroots = ["vendor"]\n' + _asset("vendor/a.js", "MIT")
    _tree(tmp_path, manifest, "vendor/a.js", "vendor/b.js")
    run = _action(tmp_path)
    assert run.returncode == 1
    assert "vendored-license-check: FAILED" in run.stderr


def test_action_uses_the_manifest_input(tmp_path: Path) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js")
    (tmp_path / "vendored-assets.toml").rename(tmp_path / "other.toml")
    assert _action(tmp_path, roots="vendor", manifest="other.toml").returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        "readme-viewer.js",
        "licensed-widget.js",
        "license-checker.min.js",
        "noticeboard.js",
        "notice.js",
        "OFLine.woff2",
        "copying-helper.js",
        "Readme.js",
        "readme-viewer.html",
        "notice-banner.htm",
        "license-checker",
        "copying-tool",
        "readme_widget",
        "README-fonts",
        "OFL.WOFF2",
        "README.JS",
        "COPYING.lib",
        "LICENSE.PY",
        "README.SH",
        "NOTICE.EXE",
        "OFL.TTC",
        "README.SCSS",
        "LICENSE.WOFF2.TXT",
        "README.tsx",
        "OFL.ttc",
        "LICENSE-MIT.PY",
        "OFL-1.1.EXE",
        "README-X.SH",
        "LICENSE_A.DLL",
        "LICENSE-MIT.TXT.EXE",
    ],
)
def test_a_library_named_like_a_legal_file_still_needs_an_entry(
    tmp_path: Path, name: str
) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js", f"vendor/{name}")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 1


@pytest.mark.parametrize(
    "name",
    [
        "LICENSE",
        "LICENSE.txt",
        "LICENSE-MIT",
        "LICENSE-MIT.txt",
        "license.md",
        "LICENCE",
        "COPYING",
        "COPYING.LESSER",
        "NOTICE",
        "NOTICE.txt",
        "OFL.txt",
        "OFL-1.1.txt",
        "README",
        "README-FONTS",
        "README.rst",
        "README.markdown",
        "LICENSE.pdf",
        "LICENSE.rtf",
        "LICENSE-APACHE-2.0",
        "OFL-1.1",
        "OFL.1.1",
        "LICENSE.MIT",
    ],
)
def test_a_legal_or_readme_file_needs_no_entry(tmp_path: Path, name: str) -> None:
    _tree(tmp_path, _asset("vendor/a.js", "MIT"), "vendor/a.js", f"vendor/{name}")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 0


def test_a_missing_manifest_is_a_configuration_error(tmp_path: Path, capsys) -> None:
    (tmp_path / "vendor").mkdir()
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 2
    assert "vendored-assets.toml" in capsys.readouterr().err


def test_a_manifest_that_is_not_toml_is_a_configuration_error(tmp_path: Path) -> None:
    (tmp_path / "vendored-assets.toml").write_text("[[asset\n", encoding="utf-8")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 2


def test_attributions_without_a_manifest_is_a_configuration_error(
    tmp_path: Path,
) -> None:
    assert main(["--root-dir", str(tmp_path), "--attributions"]) == 2


def test_a_manifest_that_is_not_utf8_is_a_configuration_error(tmp_path: Path) -> None:
    (tmp_path / "vendored-assets.toml").write_bytes(b"\xff\xfe[config]\n")
    assert main(["--root-dir", str(tmp_path), "--root", "vendor"]) == 2
