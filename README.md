# agenttop

An `htop`-style terminal monitor for GitHub Copilot CLI and VS Code sessions
and their background agents.

When a Copilot session delegates work with the `task` tool, several agents can run in
parallel in the background. The chat UI does not tell you how many are alive, what they
are doing, or how long you have been waiting. `agenttop` reconstructs that activity
from local Copilot CLI event histories and the Agent Host Protocol (AHP) traces
that VS Code writes to disk. Sessions are visible even before they delegate a task.

Illustrative display with entirely synthetic project names, identifiers, tasks
and usage figures (not a captured session):

```text
 agenttop r42.0123abcd | AIC total 12  12:00:00  running 1  starting 0  idle 1  done 1  waiting 0 | sessions 1  logs 1  sort:runtime  tree activity:all +finished
S  STARTED (local)       RUNTIME      QUIET AGENT    TYPE            MOD  MODEL            TOOLS         TOKENS           AIC TASK
▼ >_ example-app@main [aaaaaaaa] running example-model · Update example documentation · 3 agents (2 live, 1 running)
●  2026-01-01 11:58      2m 00s         3s 11111111 general-purpose bg   example-model    4 · view      12k/1k         1.00 ├─ Update example documentation
◌  2026-01-01 11:58      1m 30s        30s 22222222 explore         bg   example-model    2 · glob       6k/1k         0.50 ├─ Find example files
✓  2026-01-01 11:59         45s          - 33333333 code-review     sync example-model    3 · view       sum 9k        0.50 └─ Review example tests

aaaaaaaa example-model ctx 16k/128k (8k cached) turn 32k in / 4k out AIC turn 4.00 (self 2.00 + agents 2.00) AIC session 12
 q quit  d finished:show  a activity:all  t tree  s sort  f focus  / search  ? help
```

## Install

Single executable file, Python 3.9+ standard library only, no third-party dependencies.
The interactive UI requires a Python build with `curses` (normally available on
macOS and Linux). Text and JSON snapshots do not require `curses`.

The following commands install the `main` branch from
`https://github.com/daknoblo/agenttop`. While the repository is private,
authorized GitHub access is required. For offline use, follow the local-checkout
instructions below.

### macOS / Linux / WSL

With Git and Python 3.9+ installed, run this one line in Bash or Zsh:

```sh
(command -v python3 >/dev/null && test ! -e "$HOME/.local/bin/agenttop" && test ! -L "$HOME/.local/bin/agenttop" && git clone --single-branch --branch main https://github.com/daknoblo/agenttop.git "$HOME/.local/share/agenttop" && mkdir -p "$HOME/.local/bin" && ln -s "$HOME/.local/share/agenttop/agenttop" "$HOME/.local/bin/agenttop" && "$HOME/.local/bin/agenttop" --version)
```

Start with `~/.local/bin/agenttop`, or add `~/.local/bin` to your `PATH` to use
`agenttop` directly. Existing installations are not overwritten; see
[updating](docs/installation.md#updating).

### Windows (PowerShell)

With Git and Python 3.9+ available through `py -3`, run this one line in PowerShell:

```powershell
& { $ErrorActionPreference = 'Stop'; Get-Command git, py -ErrorAction Stop | Out-Null; $dest = Join-Path $env:LOCALAPPDATA 'agenttop'; if (Test-Path -LiteralPath $dest) { throw 'agenttop already exists; follow the update instructions.' }; $src = Join-Path $dest 'src'; git clone --single-branch --branch main https://github.com/daknoblo/agenttop.git $src; if ($LASTEXITCODE -ne 0) { throw 'Clone failed; installation stopped.' }; Set-Content -LiteralPath (Join-Path $dest 'agenttop.cmd') -Encoding Ascii -Value '@py -3 "%~dp0src\agenttop" %*'; & (Join-Path $dest 'agenttop.cmd') --version; if ($LASTEXITCODE -ne 0) { throw 'Version check failed; check Python 3.9+ and the installation path.' } }
```

Start a native Windows snapshot with
`& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --once` or use `--json`.
The standard Windows Python distribution does not include `curses`;
**use WSL for the interactive TUI**. See the
[platform-specific installation guide](docs/installation.md), including how to
read Windows session logs from WSL.

### From a local checkout

```sh
make install          # symlinks ./agenttop into ~/.local/bin
```

Or just copy it anywhere on your `PATH`:

```sh
cp agenttop ~/.local/bin/ && chmod +x ~/.local/bin/agenttop
```

## Documentation

- [Installation](docs/installation.md): platform support, prerequisites,
  PATH setup, updates, uninstalling and offline installation.
- [User guide](docs/usage.md): daily workflows, filters, keyboard controls
  and JSON integration.
- [Troubleshooting](docs/troubleshooting.md): missing sessions, terminal issues,
  unknown metrics and version differences.
- [Data sources and accounting](#how-it-works): how local events become session
  and agent state.
- [Publishing safely](#publishing-safely): keeping private history and logs out
  of public releases.

## Usage

```sh
agenttop                      # combined CLI + VS Code session tree
agenttop -update              # fast-forward this installation from origin/main
agenttop --no-update-check    # disable background update checks in the TUI
agenttop --source cli         # only Copilot events.jsonl histories
agenttop --source vscode      # only VS Code AHP logs (previous behavior)
agenttop --once               # one plain-text snapshot
agenttop --json               # one snapshot as JSON, for scripts or a status bar
agenttop --flat               # flat list instead of the per-session tree
agenttop --all-done           # include finished sessions and agents
agenttop --hide-done          # exclude done/failed/cancelled (also works with --json)
agenttop --activity active    # only running or starting, not idle
agenttop --activity recent    # last recorded activity within two hours
agenttop --session aaaaaaaa   # restrict to one session (example id prefix)
agenttop --search parser      # case-insensitive session/task/model search
agenttop --sort start         # newest delegated agents first
agenttop --sort status        # choose initial sort in TUI or snapshots
agenttop --log <file|dir>     # AHP log, CLI events.jsonl, or a containing directory
agenttop --cli-dir ~/my-copilot/session-state
agenttop --max-age 72         # discover logs modified within the last 72 hours
```

By default, both sources are discovered using a 24-hour modification-time window.
`--log` is repeatable and overrides automatic discovery; explicitly selected files
are not restricted by `--max-age`. `--cli-dir` changes the CLI discovery root.
`--interval` controls polling (default: one second). Directory discovery runs every
five seconds; `r` forces an immediate rescan.

The `>_` (CLI) / `◇` (VS Code) symbol identifies the **data source**, not necessarily the
application that launched the chat. VS Code can also write Copilot CLI session
histories. When both sources cover the same session, the CLI history supplies
the lifecycle and usage, while AHP supplies repository/branch metadata. This avoids
double-counting agents and consumption. A copied `events.jsonl` retains the session
ID recorded in its `session.start` event; the containing folder is only a fallback.
These compact symbols need no icon font. The help view (`?`) explains them;
agent details and JSON retain the source names `cli` and `vscode`.

### Activity and finished filters

The bottom controls show the current state of both filters:

- `d finished:hide` / `d finished:show`: press `d` to hide/show terminal entries,
  including **done, failed and cancelled**.
- `a activity:all` / `active` / `2h`: press `a` to cycle between no activity
  restriction, **running/starting only**, and a last recorded event within
  the previous **two hours**.

These filters combine with each other, search, session focus and source selection.
The recent filter can include idle or finished agents, but finished agents remain
hidden unless `d` is set to `show` (or `--all-done` is given). For example:

```sh
agenttop --activity recent --all-done
agenttop --json --activity recent --hide-done
```

Recency is based on the last logged event, not the start time or OS process
activity. A long-running agent with no recent events is included by `active`
but can be excluded by `2h`. The cutoff moves while the TUI is open.
Sessions without matching children are filtered by their own status/activity;
a matching child keeps its session visible for context.

The default remains `activity:all` with finished entries hidden in TUI/text.
JSON keeps its existing include-finished default unless `--hide-done` is given.
No data is deleted by these display filters.

### Version identification

The TUI header, text snapshots and JSON `version` field show the running checkout,
for example `r42.0123abcd`:

- `r42` is the number of commits reachable from `HEAD`; each ordinary new commit
  increases it automatically, without Git hooks or a manually maintained counter.
- The short commit hash identifies the exact revision across branches.
- `-dirty` marks uncommitted changes, including untracked, non-ignored files.
- `-shallow` means the checkout has incomplete history and its count is partial.

Use `agenttop --version` to print this information without reading session logs.
The version is captured at startup: restart an already running monitor after an
update. The version label identifies the local revision; `--version` itself
does not query GitHub for updates.
Counts are not a globally monotonic release number across rebases, history rewrites
or branch switches, so compare the commit hash as well.

`make install` uses a symlink and retains access to Git metadata. A standalone copy
without that metadata shows `unversioned.<source-fingerprint>` instead of inventing
a commit number. An unavailable Git executable is reported as `unknown`.

### Self-update

Run `agenttop -update` (or `agenttop --update`) on its own, then start the monitor
again. It fetches `origin/main` and applies a fast-forward to the Git checkout
containing the executable, including when launched through a symlink.

Updates require a clean, full-history checkout on `main`. Local changes,
non-ignored untracked files, local commits ahead of/diverging from the remote,
rewritten history, detached HEAD, an in-progress Git operation, and standalone
copies stop the update with an error. Nothing is reset, stashed or reinstalled.
Ignored files that would be overwritten also stop the update.

The updater uses the configured `origin` and your existing Git authentication;
it does not upload session logs. Git/network errors return a nonzero exit code.
Monitoring never updates itself automatically. See
[updating and older installations](docs/installation.md#updating).

### Update indicator

The interactive TUI checks `origin/main` at startup and then **every eight hours**
per running monitor. The check runs in a background thread; the terminal remains
responsive. It fetches Git objects and remote-tracking metadata but never changes
the checkout's branch, program files or session logs.

The top-right corner reserves space for the result, independently of the
statistics on the left:

| Indicator | Meaning |
| --- | --- |
| `Checking updates...` | Initial check is running |
| `Up to date` | The last successful check found the same commit |
| `Update: agenttop -update` | A newer fast-forward revision is available |
| `Local commits ahead` / `History differs` | Not an automatically applicable update |
| `Restart agenttop` | The checkout changed since this process started |
| `Update check failed` | Git/network/authentication failed; not proof of being current |
| `Updates: unavailable` | The installation cannot be checked, for example a standalone copy |
| `Updates off` | Background checking was disabled |

Details, including an available revision and any local-change warning, appear
in the footer and help view. To apply an update, quit and run `agenttop -update`,
then restart. Checks do not bypass the updater's fast-forward and clean-checkout
requirements.

Use `--no-update-check` for offline/read-only monitoring. `--once`, `--json`,
redirected snapshots and `--version` never start background checks. Background
authentication is noninteractive; configure Git access separately if needed.
Failed checks are retried at the next eight-hour interval, not continuously.
The `r` key refreshes logs only and does not trigger extra update checks.

### Keys

| Key | Action |
| --- | --- |
| `↑` / `↓` (or `k` / `j`) | move the cursor |
| `Enter` on a session | collapse / expand |
| `Enter` on an agent | scrollable details: model/configuration, approvals, tool results, tokens, AIC |
| `↑` / `↓`, `Page Up` / `Page Down`, `Home` / `End` in details | scroll through all available fields |
| `f` | cycle the session focus filter |
| `t` | toggle tree / flat |
| `d` | show or hide done, failed and cancelled sessions/agents; footer shows current state |
| `a` | cycle activity filter: all, running/starting only, last activity within 2h |
| `s` | cycle sort: runtime, start, idle, status, name |
| `/` | edit a live text filter; Enter applies, Escape clears |
| `Esc` | clear the text filter outside detail/help views |
| `?` | show keyboard help |
| `r` | refresh and rediscover log files immediately |
| `Page Up` / `Page Down`, `Home` / `End` | navigate longer lists |
| `q` | back from detail, or quit |

### Columns

| Column | Meaning |
| --- | --- |
| `S` | status: `⏸` awaiting approval, `●` running, `○` starting, `◌` idle, `✓` done, `✗` failed, `⊘` cancelled, `?` unknown |
| `STARTED (local)` | first observed delegation/start time as `YYYY-MM-DD HH:MM` in your local timezone; details include seconds and UTC offset |
| `RUNTIME` | wall clock since the agent was delegated |
| `QUIET` | time since the last event for this agent — how long you have been waiting |
| `AGENT` | short `agent_id` (background) or tool call id (sync) |
| `TYPE` | agent type: `general-purpose`, `code-review`, `research`, `explore`, … |
| `MOD` | `bg` for background agents, `sync` for blocking delegations |
| `MODEL` | current recorded model (shown from 160 columns) |
| `TOOLS` | reported completion tool count when available, otherwise observed calls; most frequently observed tool |
| `TOKENS` | `sum N` for reported total input+output usage, otherwise observed context / output; shown from 132 columns |
| `AIC` | known agent consumption; an authoritative shutdown value replaces observed request sums |

The start column is present in tree, flat and text snapshots. It retains the
original observed start when a resumable agent receives another turn.
If earlier log events are missing, it is the earliest start/delegation event
available to this monitor, not a reconstructed OS process creation time.
JSON `started_at` remains an ISO-8601 UTC timestamp; unknown timestamps remain
`null` (shown as `-` in the table). Use `--sort start` for newest-first ordering.

### Agent telemetry and total consumption

Enter opens a scrollable detail view. Missing optional values are omitted,
not filled with estimates; explicitly reported zero values remain visible.

- **Approval waits:** CLI `permission.requested` / `permission.completed` events
  produce `waiting` status, permission kind, pending wait time and resolution
  counts. Requests already resolved by hooks do not appear as user waits.
  `active` still means running/starting only: use `all` or `2h` to see waiting agents.
- **Tool results:** successes/failures, last error, pending tools and measured
  average/maximum durations. Duration requires a matching start and completion.
  Overlapping calls are independent; summed tool time is not wall-clock runtime.
- **Model/configuration:** requested and resolved models, first dispatched model,
  configured preference, override reason, reasoning effort, context tier and
  multi-turn/resumability flags when recorded. Model changes retain their recorded
  cause rather than guessing why a switch occurred.
- **Completion:** reported execution duration, total tokens and total tool calls.
  These are the latest completion summary, not values added to the observed
  counters. Native cancellation and errors remain distinct.
- **Final usage:** `session.shutdown.agentMetrics` supplies authoritative per-agent
  AIC and token breakdowns when present. Final input+output totals do not add
  cached or reasoning tokens again. Before such a record, observed AIC is labeled
  accordingly; it is not presented as final billing. Each shutdown record replaces
  the previous breakdown instead of mixing values from different snapshots.
  New work clears stale completion/final-token summaries.

The top-line **AIC total** sums cumulative reported consumption across all loaded
sessions once, including sessions hidden by display filters. Agent consumption
is already included and is not added again. **AIC known** means some loaded
sessions have no reported total, so the sum is incomplete. No total is shown if
none is known. Source/discovery options still determine which sessions are loaded.

The display uses **AIC** for the consumption units previously labeled AIU.
The underlying `totalNanoAiu / 1e9` calculation is unchanged; this is not a
currency conversion or a monetary invoice. Existing JSON `aiu` fields retain
their names for compatibility.

Availability is source/version-dependent. The public SDK
[event documentation](https://github.com/github/copilot-sdk/blob/eb38014b8293cb93687dc81212f94a85bed950a8/docs/features/streaming-events.md)
and [generated schema](https://github.com/github/copilot-sdk/blob/09210291cac77d58bbdf2a0c582fd57dc49cf1d0/nodejs/src/generated/session-events.ts)
describe these fields, but optional or live-only events need not occur in local
histories. AHP-only sources provide observed tool/usage data when streamed;
CLI-native approval/configuration/completion fields are not invented for them.

## How it works

### Copilot CLI histories

The CLI writes a per-session JSONL event history:

```
~/.copilot/session-state/<session-id>/events.jsonl
```

`session.start` / `session.resume` supply identity, working directory and model.
`user.message` supplies a short session title. `tool.execution_start`,
`tool.execution_complete`, `subagent.started`, `subagent.completed` and structured
notifications reconstruct agent activity, including nested delegations and
follow-up messages. Events scoped by `agentId` update the corresponding subagent
rather than the main session.

One-shot background agents finish on completion. Resumable background agents become
idle and can return to running on follow-up work. Session shutdown closes idle
agents and marks still-running agents as cancelled. Status reflects the recorded
events, not an OS process-health probe: if a process dies without recording a final
event, its last observed status can remain visible.

`session.usage_checkpoint` and `session.shutdown` supply cumulative AIC totals.
Model-call events, when recorded, provide token and per-agent usage information.
CLI turn AIC is the difference from the last cumulative checkpoint available when
the user message arrived; delayed checkpoints can make that attribution approximate.
The self/subagent split is only emitted when a direct-usage total and a matching
turn baseline are known. Otherwise the JSON fields are `null`, not a guessed split.

### VS Code AHP traces

VS Code writes a JSONL trace of the Agent Host Protocol while a Copilot session runs:

```
~/Library/Application Support/Code*/logs/<launch>/ahp/ahp-*.jsonl   # macOS
~/.config/Code*/logs/<launch>/ahp/ahp-*.jsonl                       # Linux
```

For sessions without an available CLI history, these signals rebuild the lifecycle:

| Signal | Event |
| --- | --- |
| delegation | `chat/toolCallStart` with `toolName: "task"` and `_meta.toolKind: "subagent"` |
| launch arguments | `chat/toolCallReady.toolInput` — name, description, agent type, mode, prompt |
| agent id | `chat/toolCallComplete` result text `Agent started in background with agent_id: <uuid>` |
| completion | system notification `Background agent <uuid> is completed` or `` `<description>` completed `` |
| liveness | `read_agent` results (`still running` / `is idle`) |
| tools, tokens | `chat/toolCallStart` and `chat/usage` on the agent's own `ahp-chat://subagent/...` channel |
| session context | `session/metaChanged` (repo, branch), `session/activityChanged`, `chat/usage` |

AIC is derived from `copilotUsage.totalNanoAiu / 1e9`. For the main session that field is
cumulative per turn, so the maximum is kept and reset on `chat/turnStarted`; for subagents
it arrives per request and is summed. `directCopilotUsage` gives the share spent by the
main agent itself, so the panel can split a turn into `self` and `agents`.

Both formats are tailed incrementally with byte offsets. Partial lines are retried;
rotation preserves reconstructed state. Replayed CLI event IDs and identical AHP
records are deduplicated, so replaying a history does not add the same usage twice.
Unreadable files and malformed relevant JSON records are surfaced as warnings.

Session monitoring never writes to session histories or calls Copilot APIs.
The TUI's optional background version check fetches from the configured Git
remote without changing program files. The explicit `--update` mode applies
a fast-forward to the application checkout, without reading session logs.

### JSON output

`--json` includes finished entries by default; use `--hide-done` to exclude them.
`--activity`, `--session` and `--search` consistently filter the agent array,
session object and agent counts. Counts refer
to the visible agents; `done` counts all terminal agents, including failed and
cancelled ones. Individual `status` fields preserve these distinctions.
`counts.waiting` counts visible agents with outstanding approval requests.

Optional per-agent `configuration`, `model_changes`, `completion`, `usage`,
`tool_stats`, `permissions` and `last_error` fields expose the added telemetry.
`usage.aic_final` distinguishes authoritative shutdown consumption from observed
request sums. These optional fields are omitted when unavailable; legacy
fields keep their existing zero/null behavior for compatibility.

When consumption is known, top-level `totals` contains `aic`, `complete` and
`scope: "loaded_sessions"`. Unlike filtered agent counts, this total deliberately
includes hidden loaded sessions.

The snapshot includes:

- `agents`: lifecycle, source, parent, tool histogram, tokens and usage.
- `sessions`: source, state, title, working directory, model, main-agent tool
  histogram, last event timestamp and usage.
- `errors`: warnings encountered while reading the snapshot.
- `logs`: the input files, independent of the session/text display filter.

## Known limitations

For **AHP-only** sessions, `TOOLS`, `TOKENS` and `AIC` stay empty for a background agent until VS Code
subscribes to that agent's channel, which happens when you expand the agent once in the
chat UI. The host does not stream a subagent's tool events to unsubscribed clients.
CLI histories can supply tool activity independently of that subscription, but token
and AIU details still depend on which events that CLI version persists. Missing
metrics are not estimated.

If an AHP log rotates mid-delegation, the launch arguments can be lost. Such entries are
shown as `?` / `(unknown – launch args lost to log rotation)` and hidden unless
`--all-done` is given.

Log formats are implementation details of Copilot and VS Code and may change.
The default tree is session-oriented; `--flat` is an agent-only table.
Only locally available histories are read, not chats hosted on github.com.

## Development

```sh
make test             # standard-library unittest regression suite; synthetic logs only
make check            # syntax, regression suite, and a local JSON snapshot
make test PYTHON=/path/to/python3
```

The tests cover CLI/AHP source selection, lifecycle transitions, nested agents,
usage accounting, filtering, duplicate events, partial writes and log rotation.

## Publishing safely

Examples and test fixtures must remain synthetic. Do not commit captured session
logs, screenshots of private sessions or generated JSON snapshots: they can contain
prompts, project paths, identifiers and usage data.

Use `git archive` for source bundles rather than archiving the working directory.
An archive excludes untracked environments, editor settings, bytecode and the Git
database. It includes the committed revision, not uncommitted changes.

Review commit identities and messages as well as file contents before publishing.
A cleanup commit does not remove sensitive data from earlier commits. Push only
the intended branches and tags; do not use `git push --mirror` to publish local
agent checkpoint refs. Preserve license and copyright attribution.

## License

MIT
