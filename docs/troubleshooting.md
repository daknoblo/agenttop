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

1. Cycle `a` to `all` and clear search with Escape.
2. Cycle `f` back to all sessions.
3. Press `d` to include finished work.
4. Try `--max-age 72` for older logs.
5. Press `r` to rediscover recently created files.
6. Point `--log` at the exact history or log directory.

The tree can show sessions without subagents; the flat view cannot.
Chats hosted only on github.com are not a supported source.
Under WSL, Windows and Linux use separate home directories:
see [Windows-side logs](installation.md#windows-with-wsl).

## VS Code is shown with a CLI source symbol

The symbol identifies the event format, not the launching application.
VS Code can write CLI-format histories. For the same session ID, agenttop uses
that history and supplements it with AHP metadata and UI input requests.
Use `--source vscode` for an AHP-only view.

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
