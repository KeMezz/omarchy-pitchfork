# Issue tracker: GitHub

Pitchfork's internal issues and specs live in the private
`KeMezz/omarchy-plugins` repository. This source checkout has a different,
public `origin`, so every `gh` command must name the private repository
explicitly. Never rely on repository inference here.

## Conventions

- **Create an issue**: `gh issue create --repo KeMezz/omarchy-plugins --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --repo KeMezz/omarchy-plugins --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo KeMezz/omarchy-plugins --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --repo KeMezz/omarchy-plugins --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo KeMezz/omarchy-plugins --add-label "..."` / `gh issue edit <number> --repo KeMezz/omarchy-plugins --remove-label "..."`
- **Close**: `gh issue close <number> --repo KeMezz/omarchy-plugins --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --repo KeMezz/omarchy-plugins --comments` and `gh pr diff <number> --repo KeMezz/omarchy-plugins` for the diff.
- **List external PRs for triage**: `gh pr list --repo KeMezz/omarchy-plugins --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: use `gh pr comment <number> --repo KeMezz/omarchy-plugins`, `gh pr edit <number> --repo KeMezz/omarchy-plugins --add-label/--remove-label`, and `gh pr close <number> --repo KeMezz/omarchy-plugins`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be
either: resolve with `gh pr view 42 --repo KeMezz/omarchy-plugins` and fall back
to `gh issue view 42 --repo KeMezz/omarchy-plugins`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo KeMezz/omarchy-plugins --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --repo KeMezz/omarchy-plugins --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api repos/KeMezz/omarchy-plugins/issues/<map>/sub_issues` with the appropriate method and fields). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/KeMezz/omarchy-plugins/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/KeMezz/omarchy-plugins/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --repo KeMezz/omarchy-plugins --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --repo KeMezz/omarchy-plugins --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --repo KeMezz/omarchy-plugins --body "<answer>"`, then `gh issue close <n> --repo KeMezz/omarchy-plugins`, then append a context pointer (gist + link) to the map's Decisions-so-far.
