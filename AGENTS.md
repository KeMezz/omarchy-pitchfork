# Repository guidance

This repository is **Pitchfork**, an Omarchy Quattro plugin: an instrument tuner
for guitar and bass. Treat the repository root as the plugin source and
`~/.config/omarchy/plugins/io.github.kemezz.pitchfork/` only as a generated
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
- Read `docs/design.md` before changing the detector; the line protocol between the
  detector and `Panel.qml` is the contract that keeps the two replaceable.

## Pitch mathematics

- Every pitch calculation the panel makes lives in `Tunings.js`: the family,
  instrument and tuning tables, note-name parsing and spelling, string
  frequencies, and the string a reading resolves to. Two implementations of the
  same arithmetic will eventually disagree about a note, so the QML keeps none
  of its own.
- `normalize()` is the only judge of whether a family, instrument and tuning
  combination is legal. Every path goes through it -- reading the state file,
  the family chips, both dropdowns -- so a state the three controls cannot
  render is unreachable by clicking. Do not let a caller assign the three
  properties directly.
- A tuning reference is a transform (`shift`, `drop`, `voicing`) over an
  instrument's strings, never a second table of note names. Adding half-step
  down to a new instrument must stay a zero-row change.
- Concert pitch is the `CONCERT_A_HZ` constant, not a parameter. An adjustable
  reference existed and was removed; do not reintroduce it as a dead argument
  that no caller passes.
- `tests/tunings.test.mjs` covers that file and runs under plain node with
  nothing installed. `make check` runs it, via `make test`, which also
  `node --check`s every module -- qmllint never opens a `.js` file, so without
  that a wrong string table or an unparseable `Tunings.js` passes the whole gate.
- `Tunings.js` is loaded by QML and by node both, so it stays CommonJS-shaped
  and must never gain a `.pragma library` line, which node rejects as a syntax
  error.
- The note naming in `scripts/pitch-detect.py` is deliberately separate. The
  detector's contract is `hz`; its own naming exists for the terminal
  diagnostics and must not learn about tunings.

## Panel chrome

- Build from `qs.Ui`. The one local component is `PitchDropdown.qml`, which
  exists because the kit's `Dropdown` sizes its popup's outer box and so clips
  the list by its own padding. Read the `Panel chrome` section of
  `docs/design.md` before touching either.
- A plugin file that uses `BorderSurface` must `import qs.Ui` explicitly.
  `qmllint` resolves it through `-I` and passes; the shell then fails at runtime
  with `BorderSurface is not a type`, which `make check` cannot catch.
- No hex colour literals in QML. Everything comes from `Color`, `Style` or the
  bar's own foreground, so a theme switch carries the panel with it.

## State

The chosen input, family, instrument and tuning live in
`~/.config/omarchy-pitchfork/settings.json`. Never store state under
`~/.config/omarchy/plugins/`: `make sync` rsyncs that directory with
`--delete`.

## Toolchain

`Makefile` and `scripts/*.sh` are a **copy** of the shared playground
toolchain, not a shared dependency. Fixes worth having in both places have to
be ported by hand.

## Releasing

Published at https://github.com/KeMezz/omarchy-pitchfork. There is no
marketplace in this Omarchy build: distribution is `omarchy plugin add
<git-url>`, which clones the repository and runs `omarchy plugin validate` on
the clone. So the gate for a release is that a **fresh clone** validates --
notably with no symlink anywhere outside `.git`, which is why `CLAUDE.md` is
gitignored rather than committed.

`main` is the release channel. `omarchy plugin update` does `git fetch origin
HEAD` and `merge --ff-only`, showing the user a diff before it merges. Two
consequences:

- **Never rewrite `main`.** A force-push breaks `--ff-only` for everyone who
  has already installed, and their update fails rather than degrading.
- Anything committed to `main` is shipped. There is no separate release step to
  catch a mistake, and the diff the user is shown is the commit history.

### The community marketplace

Listed at https://omarchyplugins.com, whose registry is the
`HANCORE-linux/omarchy-plugin-marketplace` repository. Submission and updates go
through its issue forms; read its `SUBMISSION.md` before touching anything
below.

- **`manifest.json`'s `id` is permanent.** The marketplace uses it as the
  listing identifier, and an id is never reusable once listed -- not even after
  a retirement or a rename. `io.github.kemezz.pitchfork` is now fixed.
- **`manifest.json`'s `description` is the site's search index.** The catalog
  copies `name`, `description` and `author` straight out of the manifest
  (`build-catalog.mjs`), and the site searches over exactly those plus the
  publisher login, the id, the category and the tags. `category` and `tags` are
  *derived from `kinds`* -- a `bar-widget` becomes `Widgets` and
  `["bar-widget"]` -- so they cannot carry a search term. Shortening the
  description therefore removes the only words a search can match; keep
  `tuner`, `tuning`, `chromatic`, `guitar`, `bass`, `pitch` and `cents` in it.
- A root `preview.png` (or `.jpg`/`.webp`/`.avif`) is what the site turns into
  the card and detail images. `docs/` is not scanned for one.
- The README must document **installation and removal**, and the repository
  must carry a root license file. Both are validated, not advisory.
- Publishing an update means opening a verification issue for a specific
  40-character commit SHA. The listing keeps pointing at the previously approved
  snapshot until a maintainer approves the new one, so pushing to `main` alone
  does not update the listing.

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
