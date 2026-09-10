# Contributing

Thanks for helping improve agenttop. This is a small personal project with a
deliberately lightweight workflow.

## Report a problem or suggest a feature

Use the repository's issue templates. For bugs, include the version, platform
and a short reproduction. See [troubleshooting](docs/troubleshooting.md) first.
For security-sensitive reports, follow [SECURITY.md](SECURITY.md).

## Work on a change

You need Git and Python 3.9+. No third-party Python packages are required.
Use macOS or Linux for the full test suite, which exercises curses and
pseudo-terminals.

```sh
make test
make check
```

`make check` runs syntax validation, the regression suite and one local JSON
snapshot. To choose an interpreter:

```sh
make check PYTHON=/path/to/python3
```

Keep changes focused, follow the existing standard-library approach, and add
synthetic regression cases for parser or behavior changes. Update the relevant
guide when CLI options or visible behavior change. Documentation-only changes
do not need an application test run.

## Send a pull request

For external contributions, fork the repository, make a small branch and open
a PR against `main`. Explain the change and how it was checked. UI changes can
include a screenshot made with example sessions.

There is no mandatory review count, CLA or elaborate branching model.
The maintainer may push directly to `main`. GitHub Actions checks pushes to
`main` and PRs targeting it; these checks are not a branch-protection gate.
Accepted PRs use squash merging, and merged branches are deleted automatically
where GitHub permits it.

## Releases

Releases are occasional, manually created tags with release notes. The built-in
updater continues to follow `main`; tags do not select a separate update channel.

Contributions use the project's [MIT license](LICENSE).
