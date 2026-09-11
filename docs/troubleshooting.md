# Troubleshooting

[Overview](../README.md) | [Installation](installation.md) | [User guide](usage.md) | [Reference](reference.md)

## Installation stops

The Unix one-liner requires `python3` on PATH, an unused launcher path and a
clone destination that Git can create. The Windows installer requires `git`
and `py`, and refuses an existing installation directory.

If already installed, use `agenttop -update`. An interrupted install can leave
a checkout without a launcher; inspect the path shown in the error before retrying.

For GitHub authentication errors, verify access using your normal Git credentials.

## Command not found

Try the full launcher path:

```sh
"$HOME/.local/bin/agenttop" --version
```

```powershell
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --version
```

If that works, follow the [PATH setup instructions](installation.md).
On Unix, `command -v agenttop` identifies the selected executable.
In PowerShell, use `Get-Command agenttop`.

If Zsh reports `command not found: #` after pasting a command block, omit the
comment lines. The installation commands in this documentation contain no
leading shell comments.

## No sessions or agents appear

The default active view requires recent running/starting work in a session.
Its open subagents are then shown even without fresh events of their own.
If neither the main agent nor any subagent has a qualifying event within five
minutes, the session can be absent; this does not mean its work was stopped.

1. Cycle `a` to `all` and clear search with Escape.
2. Cycle `f` back to all sessions.
3. Press `d` to include finished work.
4. Try `--max-age 72` for older logs.
5. Press `r` to rediscover recently created files.
6. Point `--log` at the exact history or log directory.

Both views can show main agents without subagents. The tree additionally shows
session group headings and metadata-only sessions.
Chats hosted only on github.com are not a supported source.
Under WSL, Windows and Linux use separate home directories:
see [Windows-side logs](installation.md#windows-with-wsl).

## VS Code is shown with a CLI source label

The `CLI` / `VSC` label identifies the event format, not the launching application.
VS Code can write CLI-format histories. For the same session ID, agenttop uses
that history and supplements it with AHP metadata and UI input requests.
Use `--source vscode` for an AHP-only view.

## A session is working but no subagent is listed

The session's main agent can read files, run tools and produce responses without
delegating anything. Its work appears in the `Main:` row; delegated tasks appear
underneath. Main activity and subagent activity are tracked separately.

If only old delegation events exist, the five-minute filter can correctly hide
those subagents while the main agent remains visible. Choose `--activity all`
to inspect the older records. Fresh child events alone do not make a stale main
agent appear active, and session-wide usage checkpoints are not treated as main
work events.

## Interactive mode fails

Standard native Windows Python has no `curses` module. Use `--once` or `--json`,
or run the dashboard in WSL.

On macOS/Linux, use a Python distribution with `curses` and an actual terminal.
Redirecting output intentionally switches to snapshot mode.

For clipped fields, widen the window or open the agent's details. Some columns
are hidden on narrow terminals. Use a UTF-8 terminal/font for the symbols;
complex emoji widths can vary between terminals.

## A chat needs an answer but the row is hidden

Check the global `INPUT` badge. It includes filtered-out targets.
Cycle `a` to `all`: both `active` and `2h` can hide a waiting row.
Answer in Copilot/VS Code, not agenttop.

Use the default combined source mode for the broadest input-event coverage.
A stale `ask_user` activity label alone does not mean a question remains pending.
Normal client-tool execution is also not a question.

If request or completion records are missing, the monitor can only show the last
observed state. Verify the originating chat before assuming it is still waiting.

## Timing or consumption looks unexpected

- A dimmed `~` in `all`/`2h` is running/starting without a recent event, not
  confirmed idle or completed work. JSON retains the recorded lifecycle state.
- Runtime is wall-clock time, not CPU usage. Resumable idle agents keep their
  original start time.
- Quiet time measures the last recorded event, not process health.
- A crash or partial/rotated history can leave an old status visible.
- AHP subagent tool/usage details may require expanding the agent in VS Code
  so the host subscribes to its channel.
- Optional and live-only fields are not guaranteed in every CLI history.
- `sum N` tokens are a reported aggregate, not current context size.
- Header AIC includes hidden loaded sessions; `AIC known` indicates incomplete
  session-total coverage.

Missing values are not estimates of zero. Open details, scroll through the
available fields, and check `errors` in a JSON snapshot.
See [usage accounting](reference.md#usage-accounting) for scope differences.

### VS Code says "Working on it", but agenttop has no recent signal

The UI can retain a pending-task label without delivering fresh subagent events.
Look for a yellow `!` or the `VSC stream unavailable` footer message. Agent details
show matched subscription failures, such as JSON-RPC `-32001: Resource not found`.

That error means VS Code could not subscribe to the requested subagent channel.
agenttop may only have the original launch acknowledgement, so it cannot confirm
current work or report metrics that were never delivered. `no signal` is not
the same as the SDK's explicit `idle` state.

Open the subagent in VS Code to try subscribing to its details again. A successful
retry clears the stream warning; actual new events restore activity visibility.
If the error persists, investigate the VS Code/Copilot integration. Avoid
reloading or restarting active sessions merely to change the monitor display.
Use `--activity all` to keep the last known record visible in the meantime.

## Update stops

`agenttop -update` and `agenttop --update` must be used alone.

| Message/cause | Next step |
| --- | --- |
| Local changes or untracked files | Inspect `git status` and save your work |
| Not a fast-forward | Review local commits/history; a separate fresh clone may be needed |
| Different branch or detached HEAD | Switch to `main` manually after saving work |
| Shallow clone | Fetch complete history or use a full clone |
| Git operation in progress | Finish or abort that operation manually |
| No Git metadata | Install a Git checkout; standalone files cannot self-update |
| Fetch/authentication failure | Check `origin`, network and Git credentials |
| Timeout | Inspect Git status before retrying |

The updater does not discard local work to resolve these conditions.
Older versions without this flag need a [manual update](installation.md#updating).

## Update indicator says the check failed

The background check is noninteractive and runs at startup, then every eight
hours. A failure is not the same as "Up to date". Check authentication outside
the TUI. `r` refreshes logs only.

Use `--no-update-check` to disable the check. Snapshot and version-only modes
do not start one. After an update, quit and restart existing monitors.

## Report an issue

Include your OS, Python version, terminal, `agenttop --version`, command-line
options, expected behavior and the error message. A small reproducible example
is more useful than a full session history.
