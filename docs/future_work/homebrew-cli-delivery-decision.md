# Shipping the existing CLI through Homebrew — Option A decision record

Status: **selected**. On 2026-11-04 the owner chose Option A: keep the Python
codebase, make the existing command-line tools installable, and publish them
through the existing tap. No Go migration.

This is a delivery decision, not a change to feature 006. It does not authorize
live deployment, network changes, paid research or any new runtime behaviour.

This replaces the earlier Go-migration assessment and records Option A as the
selected path.

## 1. Decision

| Item | Decision |
| --- | --- |
| Language | Python stays. No Go component, no partial rewrite. |
| Scope | The existing `destination-report/tools/` command surface. |
| Packaging | One `household` console script plus a per-platform prebuilt bundle. |
| Distribution | `brew install nawodyaishan/tap/household-report`. |
| Server | Still a container built from this repository; unchanged. |
| Licence | MIT (to match the tap's other formulae), subject to the owner adding it. |
| First release | `v0.1.0`, after feature 006 passes its gates. |

**Why A:** there is no measured problem that a rewrite would solve. The CLI is
already written, already tested and already used by the operator. The only thing
missing is an installable artifact and a licence.

## 2. What "the existing CLI" means

All host-side tools live in `destination-report/tools/` (15 modules, 4,335 lines).
Most already expose `main(argv) -> int`, which makes them entry-point friendly.

### Command map

| Command | Source module | Portable | Needs the repo |
| --- | --- | --- | --- |
| `household stack <verb>` | `stack_cli.py` | Linux (Docker/systemd) | Yes — compose, Dockerfile, lock |
| `household campaign <verb>` | `campaign_cli.py` | Yes, against a store | No |
| `household export report` | `export_campaign_report.py` | Yes | No |
| `household export snapshot` | `export_snapshot.py` | Linux (FTL/DB) | No |
| `household import inputs` | `import_inputs.py` | Yes | No |
| `household import snapshot` | `import_snapshot.py` | Yes | No |
| `household presence` | `poll_presence.py` | LAN only | No |
| `household password` | `set_password.py` | Yes | No |
| `household healthcheck` | `healthcheck.py` | Yes | No |
| `household bridge units` | `render_bridge_units.py` | Linux | Yes — unit templates |
| `household release manifest` | `release_manifest.py` | Linux | Yes — Dockerfile, lock |
| `household campaign preflight` | `campaign_preflight.py` | Yes | No |

`campaign_benchmark.py`, `campaign_retirement.py` and `host_bridge.py` stay
repo-only: the first needs Docker and a synthetic dataset, the second is a
destructive maintenance tool that should not be one PATH lookup away, and the
third is a systemd entry point that reads private paths from the installed unit.

### The one structural problem

`stack_cli.py` resolves its world from `Path(__file__).parent`:

```text
TOOLS_DIR = .../destination-report/tools
APP_DIR   = .../destination-report
```

It then reads `compose.yaml`, `compose.lan.yaml`, `compose.ai.yaml`,
`Dockerfile`, `uv.lock`, `tools/host_bridge.py` and the bridge unit templates
from there. Installed from a formula, `APP_DIR` would be `site-packages` and
every lifecycle command would fail.

Two honest options:

1. **Ship it with `--stack-dir`** (recommended). Default to the current
   directory, refuse with a clear message if `compose.yaml` or `Dockerfile` is
   absent, and keep `start`/`upgrade` building from a checkout. The CLI is
   installable; the *source* stays a checkout.
2. **Vendor the app source** into `libexec` and build from there. Adds ~30 MB,
   duplicates the image build context and creates a second source of truth.
   Only do this if lifecycle commands must work without a checkout.

Option 1 is the decision here. The formula ships the CLI; the README says
`household stack start --stack-dir ~/src/starlink-monitoring/destination-report`
and the operator keeps one checkout.

## 3. Packaging mechanics

Three ways to put Python code behind a Homebrew formula. Only one matches this
tap.

| Approach | How it works | Cost | Verdict |
| --- | --- | --- | --- |
| **A1. Homebrew Python formula** | `include Language::Python::Virtualenv`, `depends_on "python@3.13"`, one `resource` block per dependency, `virtualenv_install_with_resources` | Homebrew installs resources with dependency resolution disabled, i.e. from sdists. `pydantic-core`, `jiter` and friends need Rust/maturin; a tap maintainer reports `--no-binary :all:` failing without `rust` + `pkg-config`. Slow installs, fragile. | No |
| **A2. Prebuilt PEX per platform** | CI resolves `uv.lock` and builds one `.pex` per target with `--console-script household`; the formula downloads and links it | 4 artifacts, ~20–40 MB each, Python 3.13 still required at runtime | **Yes** |
| **A3. PyInstaller** | One native binary per platform | Hidden imports for uvicorn/FastAPI/MCP, macOS signing questions, opaque failures | No |

A2 also matches the tap's existing shape exactly: prebuilt tarball, per-platform
`sha256`, `bin.install`, `--help`/`version` smoke test.

Facts this rests on:

- Homebrew's Python helper installs `resource` blocks with dependency resolution
  disabled and expects checksummed sources; `brew update-python-resources`
  generates them (`--print-only` to inspect).
- PEX supports `--console-script` and `--complete-platform`; it requires
  prebuilt wheels for each target platform, which all six runtime dependencies
  publish for `darwin`/`linux` on `amd64`/`arm64`.
- `uv` reads `[project.scripts]` and runs the command with `uv run`, so the same
  entry point works in development and in the bundle.

### Release artifacts

```text
household-0.1.0-darwin-arm64.tar.gz
household-0.1.0-darwin-amd64.tar.gz
household-0.1.0-linux-amd64.tar.gz
household-0.1.0-linux-arm64.tar.gz
SHA256SUMS
household_report-0.1.0-py3-none-any.whl
household_report-0.1.0.tar.gz
```

Each tarball contains one `household-*.pex`. The wheel stays the canonical
Python artifact (`uv tool install`); the PEX is the Homebrew artifact. Both come
from the same tag and `uv.lock`.

### Formula sketch

```ruby
class HouseholdReport < Formula
  desc "Operate and report on the household DNS observation stack"
  homepage "https://github.com/nawodyaishan/household-dns-insights-public"
  version "0.1.0"
  license "MIT"
  depends_on "python@3.13"

  on_macos do
    on_arm do
      url "https://github.com/nawodyaishan/household-dns-insights-public/releases/download/v0.1.0/household-0.1.0-darwin-arm64.tar.gz"
      sha256 "..."
    end
    on_intel do
      url ".../household-0.1.0-darwin-amd64.tar.gz"
      sha256 "..."
    end
  end

  on_linux do
    # same shape for linux/amd64 and linux/arm64
  end

  def install
    libexec.install Dir["*.pex"].first => "household.pex"
    (bin/"household").write <<~SH
      #!/bin/bash
      exec "#{Formula["python@3.13"].opt_bin}/python3.13" "#{libexec}/household.pex" "$@"
    SH
  end

  def caveats
    <<~EOS
      This formula installs the command only. Lifecycle commands need Docker and
      a checkout: household stack start --stack-dir <path>/destination-report
      Pi-hole, TLS material, the systemd bridge and nftables are not installed.
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/household --help")
    assert_match version.to_s, shell_output("#{bin}/household version")
  end
end
```

## 4. Plan

Each step has an exit criterion. Nothing below is authorized live work.

### Step 0 — licence and release identity (1–2 days)

- Add `LICENSE` (MIT) and a `SECURITY.md`.
- Confirm `version = "0.1.0"` in `pyproject.toml`; add a `version` command that
  prints it.
- Tag `v0.1.0` only after the 006 gates; the tag is the formula's anchor.

**Exit:** the repository can be redistributed and a version string exists.

### Step 1 — console scripts (3–5 days)

- Move `tools/*.py` into `household_report/cli/` (or add a `household_report.cli`
  package that imports them) so entry points can reference them.
- Add a thin `household` dispatcher: `household <group> <verb> [flags]` calls the
  existing `main(argv)` unchanged. Keep `python tools/x.py` working for one
  release.
- Refactor `stack_cli` from `APP_DIR` to `--stack-dir` with a safe default and an
  explicit error when the compose files are absent.
- Add `[project.scripts] household = "household_report.cli:main"`.
- Update the Makefile, tests and docs to call the new path.

**Exit:** `uv run household --help` and `uv run household export report --help`
work from a clean clone; `make quality` is green; CLI flags and exit codes are
unchanged (golden transcripts).

### Step 2 — release artifacts (2–3 days)

- `uv build` produces wheel and sdist.
- CI exports `uv.lock` to a pinned requirements file and builds four PEX files
  with `--console-script household --complete-platform ...`.
- CI writes `SHA256SUMS` and uploads everything to the GitHub release.
- Smoke-test each artifact on a matching runner: `--help`, `version`, and one
  offline export against a fixture store.

**Exit:** every artifact runs on a clean machine of its target platform.

### Step 3 — formula (2–3 days)

- Add `Formula/household-report.rb` following the tap's existing conventions.
- Pin version, platform URLs and checksums; no network during `install`.
- Add `caveats` (Docker, checkout path, Pi-hole/TLS/nftables boundary).
- Run `brew install nawodyaishan/tap/household-report`, `brew test`, and `brew
  audit --strict` (tap-level warnings acceptable, errors not).

**Exit:** `brew install nawodyaishan/tap/household-report` works on a clean
macOS arm64 and a clean Linux amd64 (the other two platforms are covered by CI);
`brew test` passes; `brew uninstall` removes only the command.

### Step 4 — documentation and handover (2 days)

- README install section, support matrix, data-retention note, uninstall note.
- Record the exact artifact hashes in the release notes.
- Have one other person install from scratch using only the docs.

**Exit:** a reader who has never cloned the repo can install, run `--help`, and
know which commands need a checkout.

**Total: 2–3 weeks**, single maintainer, excluding the 006 live gates.

## 5. Barriers and how they are handled

| # | Barrier | Severity | Handling |
| --- | --- | --- | --- |
| 1 | No licence | Blocker | Step 0; MIT matches the tap. Owner decision, not a technical one. |
| 2 | No tag or release | Blocker | Step 2; immutable tag, checksums, release notes. |
| 3 | `stack_cli` is repo-coupled | High | `--stack-dir`; lifecycle builds stay checkout-based; documented. |
| 4 | Homebrew Python formulae build from sdists | High | Avoid A1; ship a PEX built from wheels in CI. |
| 5 | Rust-extension deps (`pydantic-core`, `jiter`) | High | Never build them at install; bundle wheels; fail CI if a target wheel is missing. |
| 6 | Four platforms to verify | Medium | CI matrix; smoke test on each runner; checksums in `SHA256SUMS`. |
| 7 | Python 3.13 at runtime | Medium | `depends_on "python@3.13"`; wrapper pins the interpreter; document. |
| 8 | Root, systemd, nftables | Medium | Not installed by the formula; `caveats`; manual, reviewed steps remain. |
| 9 | macOS cannot collect household DNS | Medium | Formula value on macOS is offline/report/import; say so. |
| 10 | Two version sources (image vs CLI) | Medium | Same tag and lock; `household stack check` already compares release identity. |
| 11 | Private data and credentials | Medium | Never package config, keys, stores or evidence; CLI reads them at runtime only. |
| 12 | Tap maintenance per release | Low | Regenerate formula from release metadata; keep the tap's GoReleaser-style discipline. |
| 13 | `brew` refuses root and has no system units | Low | Already the design: root actions stay explicit owner interventions. |

## 6. Acceptance checklist

- [ ] `LICENSE` present; tap formula declares the same licence.
- [ ] `v0.1.0` tagged; wheel, sdist, four platform tarballs and `SHA256SUMS`
      attached.
- [ ] `uv tool install household_report-0.1.0-py3-none-any.whl` works.
- [ ] `brew install nawodyaishan/tap/household-report` works on clean
      macOS arm64, macOS amd64, Linux amd64, Linux arm64.
- [ ] `household --help`, `household version`, and one offline command succeed
      on each platform.
- [ ] `household stack start` fails with a clear message when `--stack-dir`
      points at a directory without `compose.yaml`.
- [ ] `brew uninstall` leaves private state untouched.
- [ ] `make quality` green; the offline suite still passes; no flag or
      exit-code change for existing tools.
- [ ] Documentation tested by a second person on a clean machine.

## 7. Out of scope

- Any Go migration or partial rewrite.
- Porting the FastAPI server, web UI, auth or SQLite layer.
- Replacing the Compose/Docker deployment model.
- Automatic root actions, firewall changes or DNS changes.
- `homebrew-core` submission (a tap is the chosen channel).
- PyPI publication unless separately approved (it would make `uv tool install`
  work by name, but `006` excludes registry publication today).
- Bundling the application source into the formula (option 2 above), unless the
  checkout requirement proves unacceptable in use.

## 8. Revisit triggers

Move to a different option only if one of these becomes true:

- the PEX approach cannot cover a required platform because a wheel is missing;
- install size or startup time becomes a measured problem;
- lifecycle commands must work without a checkout (then vendor the source, or
  publish an image and change `start` to pull it);
- Python 3.13 provisioning becomes a support burden on a target platform;
- Homebrew core is wanted (that reopens licence, source-build, notability and
  livecheck requirements).

## 9. Sources

- Homebrew, *Language-Specific Formulae* — `virtualenv_install_with_resources`,
  resource blocks, `brew update-python-resources`:
  https://docs.brew.sh/Language-Specific-Formulae
- Homebrew, *Formula Cookbook* — `bin.install`, `on_macos`/`on_linux`,
  platform conditionals: https://docs.brew.sh/Formula-Cookbook
- Homebrew, *Acceptable Formulae* — licence and source-build rules:
  https://docs.brew.sh/Acceptable-Formulae
- PEX — console scripts and `--complete-platform`:
  https://pex.readthedocs.io/ and https://github.com/pex-tool/pex
- uv — `[project.scripts]`, `uv run`, `uv build`:
  https://docs.astral.sh/uv/concepts/projects/config/
- Existing tap — https://github.com/nawodyaishan/homebrew-tap (six
  GoReleaser-generated formulae, MIT, prebuilt tarballs)
- Tap-maintainer report on sdists and Rust builds (evidence for avoiding A1,
  not an authority): `elkaix/Pythinker-ai`, commit `1772429`, "drop resource
  enumeration, let pip resolve wheels at install time".
