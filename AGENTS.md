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
- Run `make check` after changing the manifest, QML, or JavaScript, and
  `node tests/tunings.test.mjs` after changing `Tunings.js`.
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

## Pitch mathematics

- Every pitch calculation the panel makes lives in `Tunings.js`: the preset
  list, note-name parsing and spelling, the frequency of a target under a given
  A4 reference, and the target a reading resolves to. Two implementations of
  the same arithmetic will eventually disagree about a note, so the QML keeps
  none of its own.
- `tests/tunings.test.mjs` covers that file and runs under plain node with
  nothing installed. A change to `Tunings.js` has to leave
  `node tests/tunings.test.mjs` green; `make check` does not run it.
- `Tunings.js` is loaded by QML and by node both, so it stays CommonJS-shaped
  and must never gain a `.pragma library` line, which node rejects as a syntax
  error.
- The note naming in `scripts/pitch-detect.py` is deliberately separate and
  fixed at A4 = 440. The detector's contract is `hz`; its own naming exists for
  the terminal diagnostics and must not learn about tunings or the reference.

## State

The chosen input, tuning, and A4 reference live in
`~/.config/omarchy-tuner/settings.json`. Never store state under
`~/.config/omarchy/plugins/`: `make sync` rsyncs that directory with
`--delete`.

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
