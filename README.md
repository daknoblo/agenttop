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
 agenttop r42.0123abcd  12:00:00  running 1  starting 0  idle 1  done 1  | AIU total 12  | sessions 1  logs 1  sort:runtime  tree +done
S      RUNTIME      QUIET AGENT    TYPE            MOD  TOOLS         TOKENS in/out     AIU TASK
▼ [cli] example-app@main [aaaaaaaa] running example-model · Update example documentation · 3 agents (2 live, 1 running)
●      2m 00s         3s 11111111 general-purpose bg   4 · view      12k/1k         1.00 ├─ Update example documentation
◌      1m 30s        30s 22222222 explore         bg   2 · glob       6k/1k         0.50 ├─ Find example files
✓         45s          - 33333333 code-review     sync 3 · view       8k/1k         0.50 └─ Review example tests

aaaaaaaa example-model ctx 16k/128k (8k cached) turn 32k in / 4k out AIU turn 4.00 (self 2.00 + agents 2.00) session 12
 q quit  d done  t tree  s sort  f focus  / search  ? help  enter open  ↑↓ move
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
agenttop --source cli         # only Copilot events.jsonl histories
agenttop --source vscode      # only VS Code AHP logs (previous behavior)
agenttop --once               # one plain-text snapshot
agenttop --json               # one snapshot as JSON, for scripts or a status bar
agenttop --flat               # flat list instead of the per-session tree
agenttop --all-done           # include finished sessions and agents
agenttop --session aaaaaaaa   # restrict to one session (example id prefix)
agenttop --search parser      # case-insensitive session/task/model search
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

The `[cli]` / `[vscode]` label identifies the **data source**, not necessarily the
application that launched the chat. VS Code can also write Copilot CLI session
histories. When both sources cover the same session, the CLI history supplies
the lifecycle and usage, while AHP supplies repository/branch metadata. This avoids
double-counting agents and consumption. A copied `events.jsonl` retains the session
ID recorded in its `session.start` event; the containing folder is only a fallback.

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
update. This identifies the local revision; it does not query GitHub for updates.
Counts are not a globally monotonic release number across rebases, history rewrites
or branch switches, so compare the commit hash as well.

`make install` uses a symlink and retains access to Git metadata. A standalone copy
without that metadata shows `unversioned.<source-fingerprint>` instead of inventing
a commit number. An unavailable Git executable is reported as `unknown`.

### Keys

| Key | Action |
| --- | --- |
| `↑` / `↓` (or `k` / `j`) | move the cursor |
| `Enter` on a session | collapse / expand |
| `Enter` on an agent | detail view: prompt, tool histogram, tokens, AIU |
| `f` | cycle the session focus filter |
| `t` | toggle tree / flat |
| `d` | show or hide finished sessions and agents |
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
| `S` | status: `●` running, `○` starting, `◌` idle, `✓` done, `✗` failed, `⊘` cancelled, `?` unknown |
| `RUNTIME` | wall clock since the agent was delegated |
| `QUIET` | time since the last event for this agent — how long you have been waiting |
| `AGENT` | short `agent_id` (background) or tool call id (sync) |
| `TYPE` | agent type: `general-purpose`, `code-review`, `research`, `explore`, … |
| `MOD` | `bg` for background agents, `sync` for blocking delegations |
| `TOOLS` | total tool calls and the most used tool |
| `TOKENS` | context / output tokens (shown from 132 columns of width) |
| `AIU` | AI units consumed by that agent |

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

`session.usage_checkpoint` and `session.shutdown` supply cumulative AIU totals.
Model-call events, when recorded, provide token and per-agent usage information.
CLI turn AIU is the difference from the last cumulative checkpoint available when
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

AIU is derived from `copilotUsage.totalNanoAiu / 1e9`. For the main session that field is
cumulative per turn, so the maximum is kept and reset on `chat/turnStarted`; for subagents
it arrives per request and is summed. `directCopilotUsage` gives the share spent by the
main agent itself, so the panel can split a turn into `self` and `agents`.

Both formats are tailed incrementally with byte offsets. Partial lines are retried;
rotation preserves reconstructed state. Replayed CLI event IDs and identical AHP
records are deduplicated, so replaying a history does not add the same usage twice.
Unreadable files and malformed relevant JSON records are surfaced as warnings.

Nothing is written back and no API is called — the tool only reads local log files.

### JSON output

`--json` includes finished entries automatically. `--session` and `--search`
consistently filter the agent array, session object and agent counts. Counts refer
to the visible agents; `done` counts all terminal agents, including failed and
cancelled ones. Individual `status` fields preserve these distinctions.

The snapshot includes:

- `agents`: lifecycle, source, parent, tool histogram, tokens and usage.
- `sessions`: source, state, title, working directory, model, main-agent tool
  histogram, last event timestamp and usage.
- `errors`: warnings encountered while reading the snapshot.
- `logs`: the input files, independent of the session/text display filter.

## Known limitations

For **AHP-only** sessions, `TOOLS`, `TOKENS` and `AIU` stay empty for a background agent until VS Code
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
