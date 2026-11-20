# vendored-license-check

A tiny, stdlib-only gate that enforces a **license policy on vendored asset files**
— the loose third-party files (JS libraries, fonts, icons, images) you commit
directly into your repository rather than pulling from a package manager.

For every file under your configured _vendored roots_, it checks that:

1. the file is **declared** in a TOML manifest (by exact path or glob), and
2. every manifest entry's SPDX license is on your **allow-list** and not on your
   **deny-list** (copyleft such as GPL/LGPL/AGPL is blocked by default).

It also emits an **attribution CSV** for building a `NOTICE`/attributions file.

Ships as both a **pre-commit hook** and a **GitHub Action**.

## Why this exists

Existing tooling doesn't cover this exact job:

- **Dependency scanners** (`pip-licenses`, npm `license-checker`, `trivy`) read
  package manifests / lockfiles — they never see loose files committed to the tree.
- **License-header tools** (`addlicense`, header pre-commit hooks) insert a header
  into source files — they can't annotate a binary `.woff2` font, and they don't
  enforce a policy.
- **[REUSE](https://reuse.software/)** is the closest standard and handles binaries
  via `REUSE.toml` globs, but `reuse lint` deliberately **won't enforce an
  allow/deny policy** (it only validates that SPDX ids are well-formed) and expects
  _every_ file in the repo to carry license info.

This tool fills the gap: a scoped, manifest-driven, policy-enforcing gate over just
your vendored roots.

## The manifest

Create `vendored-assets.toml` at your repo root:

```toml
[config]
roots = ["ui/vendor", "assets/fonts"]   # directories to scan
# allow = ["MIT", "Apache-2.0", "OFL-1.1"]   # optional; defaults to a permissive set
# deny  = ["MPL-2.0"]                         # optional explicit blocklist

[[asset]]
path = "ui/vendor/qrcode-generator.js"
name = "qrcode-generator"
version = "1.0.0"
license = "MIT"                          # must be an allow-listed SPDX id
url = "https://github.com/kazuhikoarase/qrcode-generator"

[[asset]]
path = "assets/fonts/Outfit-*.woff2"     # globs cover many files with one entry
name = "Outfit"
version = "as bundled"
license = "OFL-1.1"
url = "https://github.com/Outfitio/Outfit-Fonts"
```

- A **glob with zero current matches is valid** (forward-declare a font family you
  haven't added yet).
- Meta files are ignored automatically: dotfiles, `*.md`, and legal or readme files. Those are
  named `LICENSE`, `LICENCE`, `COPYING`, `NOTICE`, `OFL` or `README` (any case), optionally
  with a qualifier (upper case after `-` or `_`, as in `LICENSE-MIT` or `OFL-1.1`; a version
  or licence name after `.`, as in `COPYING.LESSER` or `LICENSE.MIT`) and a document
  extension: `.txt`, `.markdown`, `.rst`, `.pdf` or `.rtf`.
  Anything else needs an entry, including a library whose name merely starts with one of
  those words (`readme-viewer.js`, `license-checker`, `notice-banner.html`) and a legal file
  with a lower-case qualifier (`COPYING.lib`, `README-fonts`).
- If `[config]` is omitted, pass `--root`/`--allow`/`--deny` on the CLI or via the
  Action inputs instead.

## Use as a pre-commit or prek hook

Works with [prek](https://github.com/j178/prek) and [pre-commit](https://pre-commit.com). In your
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/kilotronic/vendored-license-check
    rev: c6c0673f419d7ff89ff75bc4e86708278ded490d  # v1.1.0
    hooks:
      - id: vendored-license-check
        # Optional: only run when vendored files or the manifest change.
        files: '^(ui/vendor/.*|assets/fonts/.*|vendored-assets\.toml)$'
```

The hook id is `vendored-license-check`, at the `pre-commit` stage (also `pre-merge-commit` and
`manual`). It is a stdlib-only Python package, which prek installs with uv. The hook walks the roots
itself (`pass_filenames: false`); the `files:` filter just controls _when_ it runs.

## Use as a GitHub Action

```yaml
- uses: actions/checkout@v4
- uses: kilotronic/vendored-license-check@v1
  # All inputs are optional and fall back to the manifest [config] table:
  with:
    manifest: vendored-assets.toml
    roots: "ui/vendor, assets/fonts"
    allow: "MIT, Apache-2.0, OFL-1.1"
    deny: "MPL-2.0"
    root-dir: "."
```

## Use as a CLI

```bash
pip install vendored-license-check

vendored-license-check                      # reads ./vendored-assets.toml
vendored-license-check --root ui/vendor --allow MIT,Apache-2.0
vendored-license-check --attributions       # print attribution CSV, no gating
```

Configuration precedence is **CLI flag → manifest `[config]` → built-in default**.
Exit codes: `0` pass, `1` policy violation, `2` misconfiguration (including a missing or
unreadable manifest).

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

## License

MIT — see [LICENSE](LICENSE).
