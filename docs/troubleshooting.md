# Troubleshooting

[Back to README](../README.md) | [Installation](installation.md) | [User guide](usage.md)

## Installation cannot find the remote branch

Check that the repository URL and `main` branch name match the
installation instructions. For a private repository, configure authorized Git
access separately rather than embedding a token in the URL. Use a local checkout
when remote access is unavailable.

## The installer exits without installing

The Unix command requires `python3` on Path and an unused launcher path.
Git will also refuse a nonempty checkout destination. Windows explicitly refuses
an existing installation directory.

Check the installation paths in the [installation guide](installation.md).
An interrupted install can leave a checkout without a launcher. Preserve any
local work and inspect the directory before deciding to repair or remove it.
For an existing working installation, use the update instructions instead.

## Command not found

Try the fully qualified launcher:

- macOS/Linux/WSL: `~/.local/bin/agenttop`
- PowerShell: `& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --once`

If that works, add the installation directory to your user Path and open a new
terminal. The installers intentionally do not edit shell profiles or system Path.
On Unix, `command -v agenttop` shows which installation a shell resolves.
In PowerShell, use `Get-Command agenttop`.

## No sessions, or an expected session is missing

1. Confirm that this OS user can read the relevant session/log files.
2. Remove `--search`, `--session` and source restrictions.
3. Press `d` or use `--all-done` to include completed entries.
4. Increase the discovery window with `--max-age 72`.
5. Use `--log` with the exact file/directory to bypass automatic discovery.
6. Press `r` to discover recently created files immediately.

The default tree can show sessions without subagents; a flat view cannot.
Sessions hosted only on github.com are not supported.
Under WSL, Windows and Linux have separate home directories; point explicitly
at Windows-side logs when needed.

## A session is labeled CLI even though it came from VS Code

Labels identify the input format, not the launching application. CLI histories
are preferred when the same session also appears in AHP logs to avoid duplicate
agents and usage. Use `--source vscode` to inspect the AHP-only interpretation.

## `curses` is missing, or the terminal view does not start

Standard native Windows Python does not ship `curses`. Use `--once`/`--json`
there, or run the TUI inside WSL. On macOS/Linux, check that the selected Python
distribution provides `curses` and that you are running in an actual terminal.

Use a UTF-8-capable terminal for status symbols and tree drawing. Resize a very
small terminal; token/AIU columns need at least 132 columns.
Redirected output is deliberately a snapshot, not an interactive display.

## Status, runtime or usage looks wrong

- Status is reconstructed from logs, not queried from live processes.
- Idle resumable agents continue to accumulate wall-clock runtime.
- An application crash or missing final event can leave the last status visible.
- Old/rotated logs can be missing launch events; `--all-done` reveals orphan entries.
- AHP-only tool/token details may be absent until VS Code subscribes to the
  subagent channel, usually after expanding it in the chat UI.
- CLI token/cost details depend on the events persisted by that CLI version.
- CLI turn totals depend on available cumulative checkpoints; delayed checkpoints
  make turn-level attribution approximate.

Blank metrics or unknown attribution are not proof of zero usage.
Check `errors` in JSON and any terminal warnings before trusting completeness.
Changing an interval or source filter cannot recover events that were never logged.

## The version is unexpected

- `rN.<hash>` identifies your local checkout, not the latest GitHub release.
- `-dirty` means local modifications or non-ignored untracked files exist.
- `-shallow` means Git history is incomplete.
- `unversioned.<fingerprint>` means the program was copied without Git metadata.
- `unknown (Git unavailable)` means Git could not read the checkout.

Check which executable your shell resolves and run it with `--version`.
After updating, restart the monitor. Revision counts can change after branch
switches or history rewrites; the commit hash is the precise identifier.

## Reporting an issue safely

Include OS, Python version, terminal, `agenttop --version`, source mode,
expected behavior and a minimal synthetic reproduction.
Do not attach raw Copilot histories, snapshots or screenshots from work sessions
without reviewing them. They can contain private task text, project paths,
identifiers and operational details.
