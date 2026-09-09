# Installation

[Back to README](../README.md) | [User guide](usage.md) | [Troubleshooting](troubleshooting.md)

## Release availability

The installation commands in the [README](../README.md#install) target
`https://github.com/daknoblo/agenttop.git`, branch `main`.
The commands explicitly select the project's main branch.
While the repository is private, Git requires authorized access; never put an
access token into a shared command or URL.

The installers clone one branch with its complete ancestry, not a shallow
checkout, so the displayed revision count remains available. No `curl | sh`,
administrator privileges, background service or automatic shell-profile edits
are involved. The commands execute the downloaded program for a version check;
review the repository before running them.

## Supported environments

| Environment | Requirements | Interactive TUI | Text / JSON |
| --- | --- | --- | --- |
| macOS | Git, Python 3.9+ with `curses`, Bash or Zsh | Yes | Yes |
| Linux | Git, Python 3.9+ with `curses`, Bash | Yes | Yes |
| Windows via WSL | A Linux distribution with the same prerequisites | Yes | Yes |
| Native Windows | Git, Python 3.9+ available as `py -3`, PowerShell 5.1+ | Not with standard Windows Python | Yes |

The one-liners do not install Python or Git. Obtain them from your platform's
package manager or the official [Python](https://www.python.org/downloads/) and
[Git](https://git-scm.com/downloads) distributions. Use the same Python environment
for installation checks and subsequent runs.

## macOS and Linux

Use the Unix one-liner in the [README](../README.md#macos--linux--wsl). It installs:

| Path | Purpose |
| --- | --- |
| `~/.local/share/agenttop/` | Git checkout, retained for updates and version identification |
| `~/.local/bin/agenttop` | Symlink to the executable in that checkout |

The command stops if a launcher already exists or Git cannot clone the destination.
It does not replace an existing installation. A failed installation can leave a
checkout behind; inspect it rather than repeatedly running the installer.

Verify and start:

```sh
"$HOME/.local/bin/agenttop" --version
"$HOME/.local/bin/agenttop"
```

To use the shorter command name in the current shell:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

For future shells, add that line once to your shell configuration, typically
`~/.zshrc` for Zsh or `~/.bashrc` for interactive Bash. Open a new terminal.
Do not move the checkout after installing its symlink.

## Native Windows

Use the PowerShell one-liner in the [README](../README.md#windows-powershell).
It creates a checkout at `%LOCALAPPDATA%\agenttop\src` and an ASCII command
launcher at `%LOCALAPPDATA%\agenttop\agenttop.cmd`. The launcher is outside the
checkout so it does not mark the version as dirty.

```powershell
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --version
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --once
& "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --json
```

Always pass `--once` or `--json` in a native interactive Windows terminal unless
your Python environment independently provides a compatible `curses` module.
Installing such a module is not required for snapshot modes and is not performed
by these instructions.

The installer does not change `PATH`. To use `agenttop` in the current PowerShell:

```powershell
$env:Path = "$env:LOCALAPPDATA\agenttop;$env:Path"
agenttop --once
```

For persistent use, add `%LOCALAPPDATA%\agenttop` to your **user** Path through
Windows Environment Variables, then open a new terminal. No machine-wide Path
or execution-policy changes are needed.

Git failures are checked through `$LASTEXITCODE`, including on Windows PowerShell
5.1, where a native program's failure is not made terminating by
`$ErrorActionPreference = 'Stop'` alone.

## Windows via WSL

Inside an existing WSL Linux terminal, install using the Unix one-liner.
Automatic discovery sees that Linux user's home directory. It does **not**
automatically discover the Windows user's separate Copilot histories.

To monitor Windows-side CLI sessions, replace `WINDOWS_USER`:

```sh
agenttop --cli-dir "/mnt/c/Users/WINDOWS_USER/.copilot/session-state"
```

To monitor a Windows VS Code log tree explicitly:

```sh
agenttop --log "/mnt/c/Users/WINDOWS_USER/AppData/Roaming/Code/logs"
```

To combine both explicit locations:

```sh
agenttop --log "/mnt/c/Users/WINDOWS_USER/.copilot/session-state" --log "/mnt/c/Users/WINDOWS_USER/AppData/Roaming/Code/logs"
```

`--log` overrides automatic discovery, including `--cli-dir`. Adjust the drive,
user directory and VS Code edition to the installation you actually use.
Only read logs you are authorized to access.

## Updating

Update the installed checkout, then restart any running monitor. A running
process deliberately retains the version it started with.

macOS / Linux / WSL:

```sh
git -C "$HOME/.local/share/agenttop" pull --ff-only
"$HOME/.local/bin/agenttop" --version
```

Windows PowerShell:

```powershell
& { git -C "$env:LOCALAPPDATA\agenttop\src" pull --ff-only; if ($LASTEXITCODE -ne 0) { throw 'Update failed; inspect the checkout before retrying.' }; & "$env:LOCALAPPDATA\agenttop\agenttop.cmd" --version }
```

Do not use a hard reset to get around local changes or diverging branches.
Inspect `git status` and preserve your changes first. If the public branch
history was replaced rather than extended, keep the old installation and
install into a separate directory for comparison.

`rN.<hash>` identifies the local revision. A `-dirty` suffix means the checkout
has local changes; `-shallow` means its commit count is incomplete. The command
does not check whether a newer release exists on GitHub.

## Uninstalling

Stop any running monitor first.

For the Unix one-liner, remove only the launcher symlink:

```sh
unlink "$HOME/.local/bin/agenttop"
```

For a local `make install`, run `make uninstall` from that checkout, passing the
same `PREFIX` if you customized it. On Windows, remove the launcher:

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\agenttop\agenttop.cmd"
```

Remove a user Path entry only if you added it specifically for this installation.
The checkout is deliberately left in place. After checking for local work,
you can remove its exact installation folder using your file manager.
**Do not delete `~/.copilot/session-state` or VS Code logs**: they belong to
Copilot/VS Code, not this application.

## Local and offline installation

From an existing checkout on macOS/Linux:

```sh
make install
make install PREFIX="$HOME/tools"
```

Run only one of the above commands, depending on the desired destination.
Add its `bin` directory to your Path. Git metadata must remain next to the source
for revision-based version identification.

Alternatively, extract a trusted source archive and run the executable directly:

```sh
python3 /path/to/agenttop/agenttop --once
```

On Windows, use `py -3` instead of `python3`.
An archive or standalone copy without `.git` displays
`unversioned.<source-fingerprint>`; it cannot reconstruct a commit count.
Keep the archive's published commit identifier alongside it if provenance matters.
