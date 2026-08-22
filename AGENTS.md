# Repository guidance

This repository is the Omarchy Quattro **Tuner** plugin: an instrument tuner
for guitar and bass. Treat the repository root as the plugin source and
`~/.config/omarchy/plugins/dev.hyeongjin.tuner/` only as a generated
development install.

One plugin per repository is deliberate. `omarchy plugin add <git-url>` clones
a repository and reads `manifest.json` from the clone root, and the shell
discovers user plugins exactly one directory deep under
`~/.config/omarchy/plugins/`. A repository that holds two plugins is not
installable.

## Workflow

- Keep `manifest.json` at the repository root.
- Run `make check` after changing the manifest, QML, or JavaScript.
- Run `make sync` to copy a validated change into the local Omarchy install.
- After a **QML** change, `make sync` is not enough: run `omarchy-restart-shell`.
  This Omarchy build has no hot reload for local plugin components, so the
  shell keeps serving the copy it loaded at startup. Never substitute
  `omarchy refresh shell` -- it resets `shell.json` to defaults.
- Never read `PwNode.properties`. This plugin holds a capture stream open while
  its panel is up, which is the exact condition the built-in audio panel warns
  destabilises Quickshell's Pipewire service.
- Never edit files under `/usr/share/omarchy/`; they are packaged references.
- Do not start a second Quickshell process. Use `omarchy-shell` IPC and the
  existing Omarchy shell.
- Keep the plugin free of symlinks and document every external dependency,
  privileged action, service, installer, and network dependency.
- `CLAUDE.md` is a local, ignored symlink to this file. Development sync and
  package validation intentionally exclude it because Omarchy rejects symlinks.

## Audio

- `scripts/pitch-detect.py` is the only component that may touch audio. The QML
  side treats it as a line-oriented subprocess and nothing more.
- The detector runs only while the panel is open. Never hold a capture stream
  open in the background.
- Read `README.md` before changing the detector; the line protocol between the
  detector and `Panel.qml` is the contract that keeps the two replaceable.

## State

The chosen input lives in `~/.config/omarchy-tuner/input.json`. Never store
state under `~/.config/omarchy/plugins/`: `make sync` rsyncs that directory
with `--delete`.

## Toolchain

`Makefile` and `scripts/*.sh` are a **copy** of the shared playground
toolchain, not a shared dependency. Fixes worth having in both places have to
be ported by hand.

## Agent skills

### Issue tracker

Issues live as GitHub issues in the private `KeMezz/omarchy-plugins`
repository, driven through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repository root. See
`docs/agents/domain.md`.
