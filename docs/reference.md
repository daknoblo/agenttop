# Reference

[Overview](../README.md) | [Installation](installation.md) | [User guide](usage.md) | [Troubleshooting](troubleshooting.md)

## Command-line options

```sh
agenttop --help
```

| Option | Default | Description |
| --- | --- | --- |
| `--log PATH` | Automatic discovery | Read a file or recursively searched directory; repeatable |
| `--source all\|cli\|vscode` | `all` | Select input formats |
| `--cli-dir PATH` | `~/.copilot/session-state` | CLI root containing per-session directories |
| `--max-age HOURS` | `24` | Modification-time window for automatic log discovery |
| `--interval SECONDS` | `1` | Poll existing log files |
| `--session ID` | All sessions | Filter by session ID prefix |
| `--search TEXT` | No search | Case-insensitive session/task/model search |
| `--activity all\|active\|recent` | `active` (JSON: `all`) | No activity restriction; running/starting with an event within five minutes; last event within two hours |
| `--all-done` | On for JSON | Include finished, failed and cancelled entries |
| `--hide-done` | On for TUI/text | Exclude terminal entries, including in JSON |
| `--sort runtime\|start\|idle\|status\|name` | `runtime` | Initial ordering |
| `--flat` | Off | Show agents without session group rows |
| `--once` | Off | Print one text snapshot and exit |
| `--json` | Off | Print one JSON snapshot and exit |
| `--no-update-check` | Off | Disable background checks in the TUI |
| `-update`, `--update` | Off | Fast-forward the installation from `origin/main`, then exit |
| `--version` | - | Print the local version without reading sessions |
| `-h`, `--help` | - | Print command help |

`--all-done` and `--hide-done` are mutually exclusive.
Use the update flag on its own.
`--interval` and `--max-age` must be finite numbers greater than zero.

`--log` overrides automatic discovery, including `--cli-dir`. Explicit paths
are not restricted by `--max-age`; `--source` still restricts the input format.
Directory discovery normally runs every five seconds. The `r` key forces it
immediately and does not trigger an update check.

The active filter requires a last event at or after the five-minute cutoff.
It does not infer completion or delete older records. In broader views, dimmed
`~` entries and the session summary's `quiet` count identify running/starting
records without a recent signal. Their JSON lifecycle status is unchanged.
The JSON default remains `all`; opt into the active filter explicitly when needed.

## Event sources

### Copilot CLI

```text
~/.copilot/session-state/<session-id>/events.jsonl
```

The parser follows delegation, subagent lifecycle, tool execution, model,
permission, user-input and usage events. Subagent-scoped events are associated
with the appropriate agent rather than the main session.

The recorded `session.start` ID identifies copied/exported histories too.
The containing directory is a fallback when that identity record is missing.
Keep the filename `events.jsonl` for CLI histories; other JSONL input files are
treated as AHP traces.

### VS Code

Typical AHP trace locations:

```text
~/Library/Application Support/Code*/logs/<launch>/ahp/*.jsonl
~/.config/Code*/logs/<launch>/ahp/*.jsonl
~/AppData/Roaming/Code*/logs/<launch>/ahp/*.jsonl
```

The UI labels these sources `CLI` and `VSC`; command-line values and JSON source
values remain `cli` and `vscode`.

For the same session ID, CLI history supplies lifecycle and usage while AHP
can add repository metadata and UI input requests. This avoids counting the
same session's events twice.
Different recorded session IDs remain separate even when their project names
match; the monitor does not infer identity from a project label.

Both formats are read incrementally. Partial lines are retried, rotation keeps
the reconstructed state, and repeated event IDs/identical AHP records are
deduplicated.

These formats are implementation details that can change between versions.
Public SDK schemas describe events, but optional or live-only events are not
guaranteed to exist in every on-disk history. AHP subagent details can also depend
on VS Code subscribing to the channel.

Further reading:

- [Copilot SDK event documentation](https://github.com/github/copilot-sdk/blob/eb38014b8293cb93687dc81212f94a85bed950a8/docs/features/streaming-events.md)
- [Public generated event schema](https://github.com/github/copilot-sdk/blob/09210291cac77d58bbdf2a0c582fd57dc49cf1d0/nodejs/src/generated/session-events.ts)

## Usage accounting

The interface uses **AIC** for the consumption units formerly displayed as AIU.
The calculation remains `totalNanoAiu / 1e9`; legacy JSON keys containing `aiu`
retain their names.

| Value | Scope and interpretation |
| --- | --- |
| Header AIC | Known cumulative totals across all loaded sessions, independent of display filters |
| Session AIC | Reported cumulative session usage; already includes its subagents |
| Observed agent AIC | Recorded per-request usage accumulated for that agent |
| Final agent AIC | Authoritative `session.shutdown.agentMetrics` value |
| Main-row AIC | Direct main usage only, with explicit `turn` or `session` scope; never the combined session total |
| Observed context/output | Context observation and accumulated recorded output, not a final token total |
| Reported total tokens | Latest completion summary or final input+output breakdown |
| Tool timings | Start/completion timestamp differences for matched calls |

Final agent consumption replaces an observed sum; the two are never added.
Each shutdown breakdown replaces the previous one. New work clears stale
completion/final-token summaries.

A final token field is aggregated across models only if every included model
provides that field. Cached/reasoning tokens are not added again to input+output.
Missing start/end pairs do not produce estimated tool durations.

CLI turn AIC depends on the last cumulative checkpoint available when a user
message arrived. Delayed checkpoints can make turn attribution approximate.
The self/subagent split is only available when the required direct-usage values
and baseline are known.

## JSON output

```sh
agenttop --json --activity recent --hide-done
```

### Top-level fields

| Field | Contents |
| --- | --- |
| `version` | Local checkout revision or standalone fingerprint |
| `generated_at` | UTC snapshot timestamp |
| `logs` | Input file paths, independent of display filters |
| `counts` | Filtered subagent counts: `running`, `starting`, `idle`, `done`, `waiting`, `input` |
| `agents` | Filtered delegated-subagent records, unchanged by the main-row feature |
| `main_counts` | Separate filtered counts for main agents |
| `main_agents` | Filtered main-agent views of the session records |
| `sessions` | Filtered session-ID-keyed records |
| `errors` | Read/parse warnings |
| `totals` | When known: `aic`, `complete` and `scope: "loaded_sessions"` |
| `attention` | `input_agents`, `input_sessions` and `scope: "loaded_sessions"` |

`counts.done` includes failed and cancelled agents.
`totals` and `attention` deliberately include loaded sessions hidden by filters.
An empty `agents` array can coexist with visible session-only work.
In that case, `main_agents` can contain the session's working main agent.

Main-agent records contain the session ID, role, source, status, activity,
model, last main-event timestamp, current-turn timing and observed tool counts.
Known direct consumption appears as `usage.aic_self` with `scope` set to
`turn` or `session`. Main input waits are counted once as session attention;
they are not also inserted into the subagent registry.

### Agent records

Core fields include identity, parent call, description, type, model, execution
mode, status, start/end timestamps, runtime, quiet time, tool histogram, tokens,
usage and message/read counters.

Optional telemetry objects:

| Field | Contents |
| --- | --- |
| `configuration` | Requested/resolved/preferred models, reasoning, context tier and multi-turn flags |
| `model_changes` | Recorded model transitions and available causes |
| `completion` | Latest reported duration, token/tool totals and outcome details |
| `usage` | Available final token breakdown, `total_tokens`, `aic` and `aic_final` |
| `tool_stats` | Observed calls, outcomes, timing samples and recent results |
| `permissions` | Outstanding approvals, outcomes and recorded wait time |
| `input_wait` | UTC `since` and elapsed `wait_seconds` for an unanswered request |
| `last_error` | Latest recorded diagnostic |

New optional fields are omitted when unavailable. Some legacy numeric fields
still use zero when no value was captured; inspect the optional usage objects
before treating such a zero as a reported measurement.

Core `started_at`/`ended_at` and `input_wait.since` timestamps are UTC ISO 8601.
Pending permission `started_at` values are ISO 8601 with an explicit local offset.
Nested event `at` values use Unix seconds. Durations specify seconds or
milliseconds in their field names. The terminal itself shows local time.

### Session records

Records include source, project/branch, working directory, title/activity, model,
status, last event, main-agent tool counts and available usage. An unanswered
session-level question adds `input_wait`.

The added input metadata contains timing, not the question or answer text.

## Version identification

A Git installation displays a version such as `r10.0123abcd`:

- `r10`: number of commits reachable from the checked-out revision.
- `0123abcd`: abbreviated commit hash.
- `-dirty`: local changes or non-ignored untracked files.
- `-shallow`: incomplete history, so the count is partial.

The hash is the precise identifier across branches and rewritten histories.
The version is captured when the process starts.

A standalone copy shows `unversioned.<source-fingerprint>`. Git/read failures
produce an explicit `unknown` label. `--version` does not query GitHub;
the TUI's separate update check does.
