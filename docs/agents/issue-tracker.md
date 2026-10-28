# Issue tracker: project-manager vault

Issues and specs for this repo live as **tasks** in the project-manager Obsidian vault, under project `shop-gym`. Load the `project-manager` skill first: it owns the vault path (`PROJECT_MANAGER_VAULT`), task claims, checkpoints, audits, and vault commits. Never edit vault files directly.

Every command below is `python3 <project-manager skill dir>/scripts/project_manager.py <command>`, written here as `pm <command>`. The skill is installed at `~/.claude/skills/project-manager`.

## Mapping

| Tracker concept | Vault representation |
| --- | --- |
| Issue | Task note in `Projects/shop-gym/Tasks/`. Its `id` (`task-...`) is the identifier. |
| Label | Entry in the task's `tags` list. Obsidian tags cannot contain `:`, so `wayfinder:map` is written `wayfinder/map`. |
| Issue body | Task sections `Goal`, `Context`, `Exit Criteria`, `Checklist`, `References`. |
| Long document (spec, agent brief) | Project note in `Notes/`, linked from the task through `context_notes`. |
| Comment | Worklog entry (one line, timestamped). |
| Sub-issue | `parent` field holding the parent task ID. |
| Blocking | `blocked_by` field listing task IDs. Native, so skills omit the "Blocked by" body section. |
| Assignee | Execution claim (`pm claim`). |
| Close | `status: done` with evidence, or `status: cancelled` for wontfix and out of scope. |

## Conventions

- **Create an issue**: `pm add-task --project shop-gym --title "..." --tag <label> --format json`. Repeat `--tag`. Add `--parent <id>` and `--blocked-by <id>` (repeatable) when known. The JSON reply carries `id`, `path`, and `revision`.
- **Write the body**: put a JSON patch in a temp file, then `pm checkpoint --project shop-gym --task <id> --expected-revision <revision> --patch-file <json>`. Section fields: `goal`, `context`, `exit_criteria`, `checklist`, `references`. Inside a section use `###` sub-headings; a `##` line would start a new task section.
- **Read an issue**: `pm task-context --project shop-gym --task <id> --format json`. The header lists tags, parent, and blockers; the body and linked `context_notes` follow. Add `--full` for the worklog (the comment history). A task reference may be an ID, an exact title, or the note filename.
- **List issues**: `pm list-tasks --project shop-gym --format json`. Filters: `--tag` (all must match), `--without-tag`, `--status`, `--parent <id>`, `--frontier`, `--include-terminal`. Rows carry `tags`, `parent`, `blocked_by`, `open_blockers`, and `claimed`.
- **Make an issue a sub-issue**: `--parent <id>` on create, or `"parent": "<id>"` in a checkpoint. `"parent": null` detaches it.
- **Comment**: `"worklog": "..."` in a checkpoint. Multi-line structured text (agent brief, triage notes) replaces the `context` section, with a one-line worklog entry saying what changed.
- **Apply / remove labels**: `"add_tags": ["..."]` and `"remove_tags": ["..."]` in a checkpoint.
- **Close**: `"status": "done"` plus `"evidence": "..."`. Completion needs a non-empty `Exit Criteria` section saved in an earlier checkpoint. Use `"status": "cancelled"` with a worklog reason for wontfix or out of scope.
- **Revisions**: every write needs the task's current `revision`. Re-read with `task-context` after any other write, including your own.
- **After writing**: run `pm audit`, then commit the vault as the project-manager skill describes.

## Body mapping

**Spec (`/to-spec`)**: store the full spec as a note, `pm add-note --project shop-gym --title "<Feature> spec" --body-file <spec.md>`; the reply carries a `link`. Create the task with `--tag ready-for-agent`, then checkpoint `goal` (Problem Statement and Solution, short), `exit_criteria` (what must be true when the spec is implemented), `context_notes: [<link>]`, and `references` (the same link, plus any `docs/specs/` page the spec belongs to).

**Tickets (`/to-tickets`)**: create tasks in dependency order, blockers first, each with `--parent <spec task id>`, `--blocked-by <id>` per edge, and `--tag ready-for-agent`. Checkpoint `goal` (What to build), `checklist` (acceptance criteria as `- [ ]` items), and `exit_criteria` (all criteria checked, tests green).

## Triage

Category roles (`bug`, `enhancement`) and state roles are tags; see `triage-labels.md`.

- **Unlabeled bucket**: `pm list-tasks --project shop-gym --format json --without-tag needs-triage --without-tag needs-info --without-tag ready-for-agent --without-tag ready-for-human --without-tag wontfix`.
- **Other buckets**: `--tag needs-triage`, `--tag needs-info`.
- **Disclaimer**: the triage disclaimer line is the first line of any `context` text and of each triage worklog entry.
- **Triage notes and agent briefs** go in `context`. A brief longer than a screen becomes a note (`pm add-note`) linked through `context_notes`.
- **wontfix**: `add_tags: ["wontfix"]`, the other state tag removed, `status: cancelled`, and a worklog reason.

## Pull requests as a triage surface

**PRs as a request surface: no.** The vault has no PR concept. Keep this `no`.

## When a skill says "publish to the issue tracker"

Create a task. Put a long body in a note and link it through `context_notes`.

## When a skill says "fetch the relevant ticket"

Read it with `task-context` by ID. State the task title before starting work, and claim the task before the first code change.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a task; its tickets are child tasks.

- **Map**: `pm add-task --project shop-gym --title "<effort>" --tag wayfinder/map --format json`. Its `context` holds the map body with `### Destination`, `### Notes`, `### Decisions so far`, `### Not yet specified`, and `### Out of scope`.
- **Child ticket**: `pm add-task --project shop-gym --title "<question>" --parent <map id> --tag wayfinder/<type> --format json`, with `<type>` one of `research`, `prototype`, `grilling`, `task`. Checkpoint `goal` with the question. Wire `blocked_by` in a second pass once IDs exist. Map tickets carry no triage tags.
- **Blocking**: `blocked_by`. A ticket is unblocked when every blocker is `done` or `cancelled`.
- **Frontier query**: `pm list-tasks --project shop-gym --parent <map id> --frontier --format json`. The first row wins.
- **Claim**: `pm claim --project shop-gym --task <id> --expected-revision <revision> --tool <agent> --working-directory <absolute repo path>`, with `<agent>` one of `claude-code`, `codex`, `pi`. This is the session's first write.
- **Resolve**: checkpoint the ticket with `context` (the answer), `exit_criteria` ("Question answered" if empty), `status: done`, and `evidence` (one-line gist). Then checkpoint the map's `context` to append `- [[<ticket note stem>|<title>]]: <gist>` under `### Decisions so far`.
- **Out of scope**: `status: cancelled` with a worklog reason, and a line under the map's `### Out of scope`.
