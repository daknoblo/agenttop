# User guide

[Back to README](../README.md) | [Installation](installation.md) | [Troubleshooting](troubleshooting.md)

## Quick start

Launch `agenttop` in an interactive terminal on macOS, Linux or WSL.
The default view combines locally available Copilot CLI histories and VS Code
AHP logs modified within the last 24 hours.

```sh
agenttop
agenttop --once
agenttop --json
```

The first command is interactive; the other two take one snapshot and exit.
When standard output is redirected, the program defaults to a text snapshot.
Use `--json` explicitly for structured output.

Session monitoring reads files only. It does not contact Copilot, execute agent
tasks, subscribe to VS Code channels or modify session history.
The TUI additionally checks the configured Git remote at startup and every
eight hours without changing program files; disable this with
`agenttop --no-update-check`. Snapshot modes do not perform that check.
The separate `agenttop -update` / `agenttop --update` mode fetches the configured
Git remote and fast-forwards the application checkout, then exits without
reading session logs. See [updating](installation.md#updating).

## Reading the display

- **Header:** local program version, visible agent counts, session count,
  number of input logs, sort order and display mode. The top-right corner shows
  update availability independently of the left-hand statistics.
- **Session rows:** data source, project/directory label, shortened session ID,
  recorded status, model, activity/title and available usage.
- **Agent rows:** recorded lifecycle state, local start date/time, runtime,
  quiet time, shortened ID, agent type, execution mode and tool activity.
- **Wide terminals:** token and AIU columns appear at 132 columns or more.
- **Footer:** usage for up to three matching sessions with usage data, plus
  read/parse warnings and update-check details when present.

When the header says `Update: agenttop -update`, quit with `q`, run
`agenttop -update`, then start the monitor again. `Up to date` refers to the
last successful check, not a continuous live comparison. A failed check is
shown explicitly rather than treated as "no update"; retries occur after eight
hours. Local-only commits and rewritten history are distinguished from an
available fast-forward update.

The `>_` symbol means the session is reconstructed from a CLI-format `events.jsonl`;
it does not prove the session was started from a terminal. VS Code can persist
the same format. If both formats are available, the CLI history supplies state
and AHP can supplement repository/branch information.
The white diamond (U+25C7) denotes an AHP-only VS Code source. Press `?` for the
symbol legend. Agent details and JSON keep the text names `cli` and `vscode`;
no special icon font is required.

## Find the work you need

```sh
agenttop --source cli
agenttop --source vscode
agenttop --session aaaaaaaa
agenttop --search parser
agenttop --sort idle
agenttop --sort start
agenttop --all-done
```

`aaaaaaaa` is an illustrative ID prefix, not a real session.
Search is case-insensitive and matches session labels/titles, model names,
agent descriptions/names, agent type and identifiers.

In the TUI:

| Key | Action |
| --- | --- |
| Up/Down or `k`/`j` | Move selection |
| Enter | Expand/collapse a session or open agent details |
| `q` | Close details/help, or quit the main view |
| `/` | Edit the live search text; Enter finishes editing |
| Escape | Clear search; leave detail/help when open |
| `f` | Cycle session focus, then return to all sessions |
| `d` | Include/exclude terminal sessions and agents |
| `s` | Cycle runtime, start, idle, status and name sorting |
| `t` | Toggle session tree / flat agent list |
| `r` | Force an immediate refresh and source discovery |
| `?` | Open keyboard help |
| Page Up/Down, Home/End | Navigate longer lists |

Use the tree view to see sessions that have not delegated any tasks.
The flat view contains agents only.

## Status and time

| State | Interpretation |
| --- | --- |
| `starting` | A delegation was observed but launch is not yet confirmed |
| `running` | The latest relevant events indicate active work |
| `idle` | Waiting between turns; a resumable agent can be used again |
| `done` | Completion recorded for a terminal agent/session |
| `failed` | A failure was recorded |
| `cancelled` | Cancellation observed, or an active CLI agent closed at session shutdown |
| `unknown` / orphan | Insufficient events to reconstruct state reliably |

Runtime is wall-clock time since delegation, not CPU time. It continues for idle
resumable agents until they are closed. Quiet time is the time since the last
recorded event, not proof that the underlying process is hung.

The `STARTED (local)` column shows `YYYY-MM-DD HH:MM` in the monitor's local
timezone, including the date for agents that have been running across days.
Open agent details with Enter for seconds and an explicit UTC offset; the
completion timestamp there also includes its full date. Text snapshots and
both tree/flat views use the same start column. On narrow terminals, later
columns are clipped so rows do not wrap.

This timestamp is the first observed delegation/start, not an OS process
creation measurement. A resumed agent keeps its original start. If the log
starts mid-session, earlier history cannot be inferred. An unavailable timestamp
is `-` in the table and `null` in JSON; `started_at` in JSON otherwise stays UTC.
Use `--sort start` (or cycle `s` to `start`) to list newest agents first.

One-shot background agents finish when completion is recorded. Resumable agents
can become idle and return to running on an accepted follow-up message.
Process crashes without final log events can leave stale-looking states.

## Custom log locations

```sh
agenttop --cli-dir /path/to/session-state
agenttop --log /path/to/session/events.jsonl
agenttop --log /path/to/ahp-log.jsonl --log /path/to/session-state
agenttop --max-age 72 --interval 2
```

`--cli-dir` is a root containing per-session directories. `--log` accepts files
or recursively searched directories, is repeatable, and replaces automatic
discovery. Explicit log inputs are not restricted by `--max-age`.

Existing files are read incrementally. New-file discovery normally happens
every five seconds even if `--interval` is shorter.

## JSON snapshots

```sh
agenttop --json --source cli --session aaaaaaaa > snapshot.json
```

JSON includes finished entries automatically. Session/text filters apply to
the session object, agents array and agent counts. `logs` describes the input
files independently of the display filter.

Top-level fields:

| Field | Contents |
| --- | --- |
| `version` | Local revision/fingerprint and any dirty/shallow marker |
| `generated_at` | UTC snapshot timestamp |
| `logs` | Local source file paths |
| `counts` | Visible running, starting, idle and terminal agent counts |
| `agents` | Agent state, identifiers, timing, source, tools and usage |
| `sessions` | Session-ID-keyed metadata, status and usage |
| `errors` | Read/parse warnings; check this before treating a snapshot as complete |

`counts.done` includes failed and cancelled agents. Inspect each agent's `status`
when the distinction matters.

Missing self/subagent cost attribution is represented as `null`, not an estimated
split. Other missing numerical metrics may remain zero; zero is not proof of free
usage. AIU are usage units, not a monetary bill. See
[accounting details](../README.md#how-it-works).

**Treat snapshots and screenshots as private:** paths, titles, activity,
identifiers and usage figures can expose work context. Do not commit real
snapshots, publish them in issues or upload them without reviewing/redacting them.
