# Installation

[Overview](../README.md) | [User guide](usage.md) | [Reference](reference.md) | [Troubleshooting](troubleshooting.md)

## Requirements

| Platform | Python and shell | Available modes |
| --- | --- | --- |
| macOS | Python 3.9+, Bash or Zsh | Interactive, text, JSON |
| Linux | Python 3.9+, Bash | Interactive, text, JSON |
| Windows with WSL | Python 3.9+ in the Linux distribution | Interactive, text, JSON |
| Native Windows | Python 3.9+ through `py -3`, PowerShell 5.1+ | Text and JSON with standard Windows Python |

Interactive mode needs Python's `curses` module, normally available on macOS
and Linux. Native Windows Python does not include it; use WSL for the TUI.
No third-party Python packages are required.

The installers require Git and clone the `main` branch. Python and Git must
already be installed. If GitHub requests authentication, use your normal Git
credentials.

## macOS and Linux

Run this one line:

```sh
(command -v python3 >/dev/null && test ! -e "$HOME/.local/bin/agenttop" && test ! -L "$HOME/.local/bin/agenttop" && git clone --single-branch --branch main https://github.com/daknoblo/agenttop.git "$HOME/.local/share/agenttop" && mkdir -p "$HOME/.local/bin" && ln -s "$HOME/.local/share/agenttop/agenttop" "$HOME/.local/bin/agenttop" && "$HOME/.local/bin/agenttop" --version)
```

It creates:

| Location | Purpose |
| --- | --- |
| `~/.local/share/agenttop` | Git checkout used for execution and updates |
| `~/.local/bin/agenttop` | Launcher symlink |

Start the dashboard:

```sh
"$HOME/.local/bin/agenttop"
```

To make `agenttop` available by name in the current shell:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Add that line once to your shell configuration for future terminals, typically
`~/.zshrc` for Zsh or `~/.bashrc` for Bash. The installer does not edit these files.
Keep the checkout in its installation directory so the symlink remains valid.

If the command stops because a launcher or checkout already exists, follow
[updating](#updating) or [installation troubleshooting](troubleshooting.md#installation-stops).

## Windows PowerShell

With `git` and `py -3` available, run:

```powershell
& { $ErrorActionPreference = 'Stop'; Get-Command git, py -ErrorAction Stop | Out-Null; $dest = Join-Path $env:LOCALAPPDATA 'agenttop'; if (Test-Path -LiteralPath $dest) { throw 'agenttop already exists; follow the update instructions.' }; $src = Join-Path $dest 'src'; git clone --single-branch --branch main https://github.com/daknoblo/agenttop.git $src; if ($LASTEXITCODE -ne 0) { throw 'Clone failed; installation stopped.' }; Set-Content -LiteralPath (Join-Path $dest 'agenttop.cmd') -Encoding Ascii -Value '@py -3 "%~dp0src\agenttop" %*'; & (Join-Path $dest 'agenttop.cmd') --version; if ($LASTEXITCODE -ne 0) { throw 'Version check failed; check Python 3.9+ and the installation path.' } }
```

The checkout is installed at `%LOCALAPPDATA%\agenttop\src`, with a launcher at
`%LOCALAPPDATA%\agenttop\agenttop.cmd`.

Take a snapshot:

```powershell
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --once
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --json
```

Use `--once` or `--json` in a native Windows terminal. Standard Windows Python
cannot run the interactive `curses` view.

Optionally add the launcher directory to the current PowerShell's PATH:

```powershell
$env:Path = "$env:LOCALAPPDATA\agenttop;$env:Path"
```

For future terminals, add `%LOCALAPPDATA%\agenttop` to your user Path in Windows
Environment Variables. No administrator access or execution-policy change is needed.

## Windows with WSL

Inside WSL, follow the [Linux installation](#macos-and-linux).
By default, agenttop reads that Linux user's local sessions.

To read Windows-side CLI sessions, replace `WINDOWS_USER`:

```sh
agenttop --cli-dir "/mnt/c/Users/WINDOWS_USER/.copilot/session-state"
```

To read both Windows CLI and VS Code logs:

```sh
agenttop --log "/mnt/c/Users/WINDOWS_USER/.copilot/session-state" --log "/mnt/c/Users/WINDOWS_USER/AppData/Roaming/Code/logs"
```

Adjust the drive, user directory and VS Code edition as needed.
`--log` replaces automatic discovery, including `--cli-dir`.

## Existing checkout or standalone copy

From a local checkout on macOS/Linux:

```sh
make install
```

This links the executable into `~/.local/bin`. A custom installation prefix
can be supplied with `make install PREFIX="$HOME/tools"`.

You can also run the file directly:

```sh
python3 /path/to/agenttop/agenttop --once
```

On Windows, replace `python3` with `py -3`.
A standalone copy or source archive works without Git metadata, but cannot
self-update and displays a source fingerprint instead of a commit-based version.

## Updating

```sh
agenttop -update
```

Use the full launcher path if it is not on PATH:

```sh
"$HOME/.local/bin/agenttop" -update
```

```powershell
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" -update
```

The updater:

1. Locates the Git checkout behind the executable or symlink.
2. Requires a clean, full-history checkout on `main`.
3. Fetches `origin/main` using your configured Git authentication.
4. Applies a fast-forward and prints the resulting version.

It exits without opening the TUI. Restart any running monitor afterwards.
`-update` and `--update` must be used on their own.

Local changes, untracked files, an in-progress Git operation, detached HEAD,
shallow history or a non-fast-forward update cause an error. Nothing is
automatically reset, stashed or reinstalled.

For a version that does not yet support the updater, run:

```sh
git -C "$HOME/.local/share/agenttop" pull --ff-only origin main
```

For Windows, use `"$env:LOCALAPPDATA\agenttop\src"` as the checkout path.
See [update troubleshooting](troubleshooting.md#update-stops) if Git refuses.

### Background update checks

The TUI checks at startup and every eight hours per running monitor. Checks
fetch Git metadata but do not install changes or show credential prompts.

```sh
agenttop --no-update-check
```

Snapshot and version-only modes never start a background check.

## Uninstalling

Quit the monitor, then remove its launcher.

macOS / Linux / WSL:

```sh
unlink "$HOME/.local/bin/agenttop"
```

Windows:

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\agenttop\agenttop.cmd"
```

For a `make install` installation, `make uninstall` removes the symlink.
Use the same `PREFIX` if you customized it.

The checkout remains in place and can be removed separately after checking for
local work. Remove a PATH entry only if you added it for agenttop.
Copilot session histories and VS Code logs are not part of the installation.
