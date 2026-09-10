import base64
import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch


APP = runpy.run_path(str(Path(__file__).resolve().parents[1] / "agenttop"))
Monitor = APP["Monitor"]
Agent = APP["Agent"]
AID = "11111111-1111-1111-1111-111111111111"
CHILD = "22222222-2222-2222-2222-222222222222"


class VersionTests(unittest.TestCase):
    def tearDown(self):
        APP["version"].cache_clear()

    def test_revision_increases_with_each_commit_and_marks_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "agenttop"
            source.write_text("# synthetic version test\n")

            def git(*args):
                return subprocess.run(
                    ["git", "-C", directory, "-c", "user.name=Test",
                     "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                     *args], check=True, capture_output=True, text=True,
                ).stdout.strip()

            git("init", "--template=")
            git("add", "agenttop")
            git("commit", "-m", "Synthetic fixture\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>")
            with patch.dict(APP["version"].__wrapped__.__globals__, __file__=str(source)):
                APP["version"].cache_clear()
                first = APP["version"]()
                self.assertEqual(first, f"r1.{git('rev-parse', '--short=8', 'HEAD')}")
                git("commit", "--allow-empty", "-m", "Synthetic revision\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>")
                self.assertEqual(APP["version"](), first)
                APP["version"].cache_clear()
                self.assertEqual(APP["version"](), f"r2.{git('rev-parse', '--short=8', 'HEAD')}")
                source.write_text("# modified fixture\n")
                APP["version"].cache_clear()
                self.assertTrue(APP["version"]().endswith("-dirty"))

    def test_copy_without_git_has_explicit_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "agenttop"
            source.write_text("# standalone\n")
            with patch.dict(APP["version"].__wrapped__.__globals__, __file__=str(source)):
                APP["version"].cache_clear()
                self.assertRegex(APP["version"](), r"^unversioned\.[a-f0-9]{12}$")

    def test_missing_git_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".git").mkdir()
            with patch.dict(APP["version"].__wrapped__.__globals__, __file__=str(Path(directory) / "agenttop")):
                with patch("subprocess.run", side_effect=FileNotFoundError):
                    APP["version"].cache_clear()
                    self.assertEqual(APP["version"](), "unknown (Git unavailable)")


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agenttop update ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.seed = self.root / "seed"
        self.remote = self.root / "remote.git"
        self.client = self.root / "client"
        isolated = patch.dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        isolated.start()
        self.addCleanup(isolated.stop)
        self.git(self.root, "init", "--template=", "--initial-branch=main", str(self.seed))
        (self.seed / "agenttop").write_text("# initial synthetic executable\n")
        self.commit(self.seed, "Initial fixture")
        self.git(self.root, "clone", "--bare", "--template=", str(self.seed), str(self.remote))
        self.git(self.root, "clone", "--template=", str(self.remote), str(self.client))
        self.before = self.git(self.client, "rev-parse", "HEAD")
        self.git(self.seed, "remote", "add", "origin", str(self.remote))
        self.source = self.client / "agenttop"
        self.addCleanup(APP["version"].cache_clear)

    def git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
             *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    def commit(self, root, message):
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", message,
                 "-m", "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>")
        return self.git(root, "rev-parse", "HEAD")

    def publish(self):
        (self.seed / "agenttop").write_text("# updated synthetic executable\n")
        target = self.commit(self.seed, "New fixture version")
        self.git(self.seed, "push", "origin", "main")
        return target

    def update(self, source=None):
        output, error = io.StringIO(), io.StringIO()
        with patch.dict(APP["update_checkout"].__globals__, __file__=str(source or self.source)):
            APP["version"].cache_clear()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                result = APP["update_checkout"]()
        return result, output.getvalue(), error.getvalue()

    def check_update(self, loaded_revision=None):
        return APP["check_update"](
            str(self.client), lambda *args: self.git(self.client, *args),
            self.before if loaded_revision is None else loaded_revision,
        )

    def test_check_detects_available_update_without_changing_files(self):
        target = self.publish()
        notice = self.check_update()
        self.assertEqual(notice.status, "available")
        self.assertIn("agenttop -update", notice.text)
        self.assertIn(f"r2.{target[:8]}", notice.detail)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)
        self.assertEqual(self.source.read_text(), "# initial synthetic executable\n")

    def test_check_reports_current(self):
        self.assertEqual(self.check_update().status, "current")

    def test_check_distinguishes_local_ahead_from_available(self):
        self.source.write_text("# local work\n")
        local = self.commit(self.client, "Local revision")
        self.assertEqual(self.check_update(local).status, "ahead")

    def test_check_reports_history_rewrite_not_update(self):
        tree = self.git(self.seed, "rev-parse", "HEAD^{tree}")
        replacement = self.git(self.seed, "commit-tree", tree, "-m", "Unrelated synthetic root")
        self.git(self.seed, "push", "--force", "origin", f"{replacement}:refs/heads/main")
        notice = self.check_update()
        self.assertEqual(notice.status, "diverged")
        self.assertNotIn("-update", notice.text)

    def test_check_warns_about_local_changes_but_detects_update(self):
        self.publish()
        self.source.write_text("# local work\n")
        notice = self.check_update()
        self.assertEqual(notice.status, "available")
        self.assertIn("Save local changes", notice.detail)
        self.assertEqual(self.source.read_text(), "# local work\n")

    def test_check_detects_checkout_changed_since_startup(self):
        target = self.publish()
        self.git(self.client, "pull", "--ff-only")
        notice = self.check_update()
        self.assertEqual(notice.status, "restart")
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), target)

    def test_check_fetch_failure_is_not_up_to_date(self):
        self.git(self.client, "remote", "set-url", "origin", str(self.root / "missing"))
        notice = self.check_update()
        self.assertEqual(notice.status, "error")
        self.assertIn("failed", notice.text)

    def test_fast_forward_and_new_version(self):
        target = self.publish()
        result, output, error = self.update()
        self.assertEqual(result, 0, error)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), target)
        self.assertIn(f"r2.{target[:8]}", output)
        self.assertIn("Start agenttop again", output)
        self.assertEqual(self.source.read_text(), "# updated synthetic executable\n")
        self.assertEqual(self.git(self.client, "status", "--porcelain"), "")

    def test_real_cli_updates_and_next_launch_reports_new_version(self):
        shutil.copyfile(Path(__file__).resolve().parents[1] / "agenttop", self.seed / "agenttop")
        self.commit(self.seed, "Install actual updater in fixture")
        self.git(self.seed, "push", "origin", "main")
        self.git(self.client, "pull", "--ff-only")
        with (self.seed / "agenttop").open("a") as source:
            source.write("\n# Synthetic update fixture.\n")
        target = self.commit(self.seed, "Publish updater fixture revision")
        self.git(self.seed, "push", "origin", "main")
        result = subprocess.run([sys.executable, str(self.source), "-update"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"r3.{target[:8]}", result.stdout)
        launched = subprocess.run([sys.executable, str(self.source), "--version"],
                                  check=True, capture_output=True, text=True, timeout=10)
        self.assertEqual(launched.stdout.strip(), f"agenttop r3.{target[:8]}")

    @unittest.skipUnless(os.name == "posix", "Interactive PTY test requires POSIX")
    def test_live_tui_shows_available_update_and_can_disable_checks(self):
        import fcntl
        import pty
        import select
        import struct
        import termios

        shutil.copyfile(Path(__file__).resolve().parents[1] / "agenttop", self.seed / "agenttop")
        self.commit(self.seed, "Install TUI fixture")
        self.git(self.seed, "push", "origin", "main")
        self.git(self.client, "pull", "--ff-only")
        installed = self.git(self.client, "rev-parse", "HEAD")
        (self.seed / "example.txt").write_text("New synthetic release")
        available = self.commit(self.seed, "New TUI fixture release")
        self.git(self.seed, "push", "origin", "main")
        log = self.root / "events.jsonl"
        log.write_text(json.dumps({"type": "session.start", "id": "synthetic",
                                   "data": {"sessionId": "example"}}) + "\n")

        for extra, expected in ((["--no-update-check"], b"Updates off"),
                                ([], b"Update: agenttop -update")):
            with self.subTest(options=extra):
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 160, 0, 0))
                process = subprocess.Popen(
                    [sys.executable, str(self.source), "--log", str(log), *extra],
                    stdin=slave, stdout=slave, stderr=slave, env={**os.environ, "TERM": "xterm-256color"},
                )
                os.close(slave)
                output = bytearray()
                def drain(duration):
                    deadline = time.monotonic() + duration
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], 0.05)[0]:
                            try:
                                output.extend(os.read(master, 65536))
                            except OSError:
                                return
                try:
                    for _ in range(50):
                        drain(0.1)
                        if expected in output:
                            break
                    self.assertIn(expected, output)
                    self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), installed)
                    self.assertEqual(self.git(self.client, "rev-parse", "origin/main"),
                                     installed if extra else available)
                    os.write(master, b"q")
                    drain(0.5)
                    process.wait(timeout=3)
                    self.assertEqual(process.returncode, 0)
                finally:
                    os.close(master)
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=3)

    def test_up_to_date(self):
        result, output, error = self.update()
        self.assertEqual(result, 0, error)
        self.assertIn("Already up to date", output)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)

    def test_dirty_checkout_is_not_fetched_or_modified(self):
        self.publish()
        self.source.write_text("# local work\n")
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("Local changes", error)
        self.assertEqual(self.source.read_text(), "# local work\n")
        self.assertEqual(self.git(self.client, "rev-parse", "origin/main"), self.before)

    def test_untracked_files_are_preserved(self):
        self.publish()
        local = self.client / "notes.txt"
        local.write_text("Local notes")
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("untracked", error)
        self.assertEqual(local.read_text(), "Local notes")
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)

    def test_rewritten_history_is_rejected(self):
        tree = self.git(self.seed, "rev-parse", "HEAD^{tree}")
        replacement = self.git(self.seed, "commit-tree", tree, "-m", "Unrelated synthetic root")
        self.git(self.seed, "push", "--force", "origin", f"{replacement}:refs/heads/main")
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("not a fast-forward", error)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)
        self.assertEqual(self.source.read_text(), "# initial synthetic executable\n")

    def test_local_commits_are_not_reset(self):
        self.source.write_text("# local commit\n")
        local = self.commit(self.client, "Local work")
        self.publish()
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("not a fast-forward", error)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), local)

    def test_fetch_failure_is_reported(self):
        self.git(self.client, "remote", "set-url", "origin", str(self.root / "missing"))
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("Fetching origin/main failed", error)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)

    def test_non_main_branch_is_not_switched(self):
        self.git(self.client, "switch", "-c", "feature")
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("require branch main", error)
        self.assertEqual(self.git(self.client, "branch", "--show-current"), "feature")

    def test_detached_checkout_is_not_switched(self):
        self.git(self.client, "checkout", "--detach")
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("Detached HEAD", error)
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)

    def test_existing_git_operation_is_not_disturbed(self):
        merge_head = self.client / ".git" / "MERGE_HEAD"
        merge_head.write_text(self.before + "\n")
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("operation is in progress", error)
        self.assertTrue(merge_head.exists())

    def test_standalone_copy_is_not_replaced(self):
        source = self.root / "agenttop"
        source.write_text("# standalone copy\n")
        result, _, error = self.update(source)
        self.assertEqual(result, 1)
        self.assertIn("no Git metadata", error)
        self.assertEqual(source.read_text(), "# standalone copy\n")

    @unittest.skipIf(os.name == "nt", "Creating symlinks can require Windows privileges")
    def test_symlink_updates_installed_checkout_not_current_directory(self):
        target = self.publish()
        launcher = self.root / "launcher"
        launcher.symlink_to(self.source)
        result, _, error = self.update(launcher)
        self.assertEqual(result, 0, error)
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), target)

    def test_ignored_file_is_not_overwritten(self):
        self.git(self.client, "config", "merge.autoStash", "true")
        (self.client / ".git" / "info").mkdir(exist_ok=True)
        (self.client / ".git" / "info" / "exclude").write_text("settings.txt\n")
        (self.client / "settings.txt").write_text("Private local settings")
        (self.seed / "settings.txt").write_text("New tracked default")
        self.publish()
        result, _, error = self.update()
        self.assertEqual(result, 1)
        self.assertIn("Applying fast-forward failed", error)
        self.assertEqual((self.client / "settings.txt").read_text(), "Private local settings")
        self.assertEqual(self.git(self.client, "rev-parse", "HEAD"), self.before)

    def test_shallow_clone_is_not_updated(self):
        shallow = self.root / "shallow"
        self.git(self.root, "clone", "--depth=1", "--template=", self.remote.as_uri(), str(shallow))
        result, _, error = self.update(shallow / "agenttop")
        self.assertEqual(result, 1)
        self.assertIn("Shallow history", error)

    def test_timeout_and_missing_git_are_reported(self):
        for exception in (subprocess.TimeoutExpired("git", 10), FileNotFoundError("git")):
            with self.subTest(exception=type(exception).__name__):
                with patch.dict(APP["update_checkout"].__globals__, git_output=unittest.mock.Mock(side_effect=exception)):
                    result, _, error = self.update()
                self.assertEqual(result, 1)
                self.assertIn("Update stopped", error)

    def test_both_cli_aliases_exit_without_reading_sessions(self):
        with patch.dict(APP["main"].__globals__, update_checkout=unittest.mock.Mock(return_value=0)):
            with patch.object(Monitor, "refresh", side_effect=AssertionError("Must not read logs")):
                for flag in ("-update", "--update"):
                    self.assertEqual(APP["main"]([flag]), 0)

    def test_update_cannot_be_combined_with_snapshot_options(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                APP["main"](["--update", "--json"])
        self.assertEqual(exc.exception.code, 2)


class UpdateIndicatorTests(unittest.TestCase):
    def checker(self):
        checker = APP["UpdateChecker"](root="/synthetic-checkout")
        self.addCleanup(checker.close)
        return checker

    def test_checks_at_startup_then_only_after_eight_hours(self):
        checker = self.checker()
        notice = APP["UpdateNotice"]("current", "Up to date", "")
        with patch.object(checker, "work", side_effect=lambda: checker.results.put(notice)) as worker:
            with patch("time.monotonic", return_value=100):
                checker.poll()
                checker.thread.join(timeout=2)
                self.assertFalse(checker.thread.is_alive())
                self.assertEqual(checker.poll().status, "current")
            with patch("time.monotonic", return_value=100 + 8 * 60 * 60 - 1):
                checker.poll()
                self.assertEqual(worker.call_count, 1)
            with patch("time.monotonic", return_value=100 + 8 * 60 * 60):
                checker.poll()
                checker.thread.join(timeout=2)
                self.assertEqual(worker.call_count, 2)
        self.assertEqual(APP["UPDATE_CHECK_INTERVAL"], 28800)

    def test_slow_check_does_not_block_poll_or_spawn_duplicates(self):
        checker = self.checker()
        started, release = threading.Event(), threading.Event()
        def wait():
            started.set()
            release.wait(timeout=5)
        with patch.object(checker, "work", side_effect=wait) as worker:
            try:
                checker.poll()
                self.assertTrue(started.wait(timeout=2))
                self.assertTrue(checker.thread.is_alive())
                checker.next_check = 0
                checker.poll()
                self.assertEqual(worker.call_count, 1)
            finally:
                release.set()
                checker.thread.join(timeout=2)

    def test_failure_replaces_previous_available_notice(self):
        checker = self.checker()
        checker.next_check = float("inf")
        checker.notice = APP["UpdateNotice"]("available", "Update: agenttop -update", "")
        checker.results.put(APP["UpdateNotice"]("error", "Update check failed", "Authentication failed"))
        self.assertEqual(checker.poll().status, "error")

    def test_header_reserves_right_edge_at_different_widths(self):
        for width in (0, 1, 8, 40, 80, 160):
            with self.subTest(width=width):
                left, right = APP["header_parts"]("agenttop " + "statistics " * 50,
                                                 "Update: agenttop -update", width)
                self.assertEqual(len(left + right), max(0, width - 1))
                if width >= 40:
                    self.assertEqual(right, "Update: agenttop -update")
                    self.assertTrue((left + right).endswith("agenttop -update"))

    def test_background_git_cannot_prompt_on_terminal(self):
        checker = self.checker()
        process = Mock()
        process.communicate.return_value = ("result\n", "")
        process.returncode = 0
        with patch("subprocess.Popen", return_value=process) as popen:
            self.assertEqual(checker.git("rev-parse", "HEAD"), "result")
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GCM_INTERACTIVE"], "never")
        self.assertTrue(kwargs["start_new_session"])
        self.assertIsNone(checker.process)

    def test_close_cancels_owned_process_and_prevents_new_checks(self):
        checker = self.checker()
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   start_new_session=True)
        checker.process = process
        try:
            checker.close()
            process.wait(timeout=3)
            self.assertIsNotNone(process.returncode)
            checker.poll()
            self.assertIsNone(checker.thread)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            checker.process = None

    @unittest.skipUnless(os.name == "posix", "POSIX process-group regression")
    def test_timeout_cleans_helpers_after_git_parent_exits(self):
        checker = self.checker()
        code = ("import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])")
        process = subprocess.Popen([sys.executable, "-c", code],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        process.wait(timeout=3)
        self.assertEqual(process.returncode, 0)
        communicate = process.communicate
        errors = []
        def run():
            try:
                checker.git("fetch")
            except subprocess.TimeoutExpired as exc:
                errors.append(exc)
        def short_timeout(timeout=None):
            return communicate(timeout=0.1 if timeout == 30 else timeout)
        with patch("subprocess.Popen", return_value=process), patch.object(process, "communicate", side_effect=short_timeout):
            worker = threading.Thread(target=run, daemon=True)
            try:
                worker.start()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive(), "Exited parent left a helper holding the output pipes")
                self.assertEqual(len(errors), 1)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                worker.join(timeout=2)
                process.stdout.close()
                process.stderr.close()

    def test_unsupported_install_and_failures_are_explicit(self):
        git = Mock()
        notice = APP["check_update"]("/nonexistent-synthetic-checkout", git)
        self.assertEqual(notice.status, "unavailable")
        git.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".git").mkdir()
            for exception in (subprocess.TimeoutExpired("git", 5), FileNotFoundError("git")):
                notice = APP["check_update"](directory, Mock(side_effect=exception))
                self.assertEqual(notice.status, "error")

    def test_snapshots_and_version_do_not_start_background_checks(self):
        globals_ = APP["main"].__globals__
        with patch.dict(globals_, UpdateChecker=Mock(side_effect=AssertionError("Unexpected update check")),
                        run_once=Mock()):
            with patch.object(sys.stdout, "isatty", return_value=False):
                for args in ([], ["--once"], ["--json"]):
                    self.assertEqual(APP["main"](args), 0)
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exc:
                APP["main"](["--version"])
            self.assertEqual(exc.exception.code, 0)

    def test_no_update_check_is_forwarded_to_tui(self):
        tui = Mock()
        with patch.dict(APP["main"].__globals__, run_tui=tui):
            with patch.object(sys.stdout, "isatty", return_value=True):
                APP["main"](["--no-update-check"])
                self.assertFalse(tui.call_args.kwargs["check_updates"])
                APP["main"]([])
                self.assertTrue(tui.call_args.kwargs["check_updates"])


class StartTimeTests(unittest.TestCase):
    def setUp(self):
        self.started = datetime(2026, 9, 10, 9, 24, 7).timestamp()
        self.now = self.started + 180
        self.agent = Agent("call_example", "example-session", self.started)
        self.agent.description = "An example task with a longer description"
        self.agent.agent_type = "explore"
        self.agent.launched = True
        self.mon = Monitor()
        self.mon.agents[self.agent.call_id] = self.agent
        self.mon.state_for(self.agent.session, self.started)

    def test_started_column_has_local_date_and_time(self):
        header = APP["table_header"](132)
        _, row = APP["agent_line"](self.agent, self.now, 132)
        start = header.index("STARTED (local)")
        self.assertEqual(row[start:start + 16], "2026-09-10 09:24")
        self.assertIn("RUNTIME", header)
        self.assertIn("TOKENS in/out", header)
        self.assertIn("An example", row)

    def test_width_limits_and_tree_indentation(self):
        for width in (0, 1, 20, 60, 80, 100, 120, 132, 160, 200):
            with self.subTest(width=width):
                header = APP["table_header"](width)
                _, row = APP["agent_line"](self.agent, self.now, width, "   \u2514\u2500 ")
                self.assertLessEqual(len(header), max(0, width - 1))
                self.assertLessEqual(len(row), max(0, width - 1))
                if width >= 120:
                    self.assertIn("   \u2514\u2500 ", row)
                    self.assertIn("2026-09-10 09:24", row)

    def test_tree_flat_and_plain_output_include_start(self):
        for tree in (False, True):
            with self.subTest(tree=tree):
                header, rows = APP["build_display"](self.mon, [self.agent], self.now, 160, tree, set())
                self.assertIn("STARTED (local)", header)
                agent_rows = [row for row in rows if row[0] == "agent"]
                self.assertIn("2026-09-10 09:24", agent_rows[0][3])
                output = io.StringIO()
                with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
                    APP["run_once"](self.mon, True, "start", False, tree=tree)
                self.assertIn("STARTED (local)", output.getvalue())
                self.assertIn("2026-09-10 09:24", output.getvalue())

    def test_details_include_seconds_offset_and_end_date(self):
        self.agent.finish(datetime(2026, 9, 11, 10, 25, 8).timestamp())
        screen = Mock()
        APP["render_detail"](screen, self.agent, 40, 160)
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertTrue(any(re.match(r"2026-09-10 09:24:07[+-]\d\d:\d\d$", text) for text in rendered))
        self.assertTrue(any(re.match(r"2026-09-11 10:25:08[+-]\d\d:\d\d$", text) for text in rendered))

    def test_json_keeps_utc_and_missing_start_is_not_invented(self):
        for started in (self.started, 0, None):
            with self.subTest(started=started):
                self.agent.started = started
                output = io.StringIO()
                with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
                    APP["run_once"](self.mon, True, "start", True)
                value = json.loads(output.getvalue())["agents"][0]["started_at"]
                if started is None:
                    self.assertIsNone(value)
                    self.assertEqual(APP["fmt_timestamp"](started), "-")
                else:
                    self.assertEqual(datetime.fromisoformat(value).timestamp(), started)
                    self.assertTrue(value.endswith("+00:00"))

    def test_start_sort_is_newest_first(self):
        newer = Agent("call_newer", self.agent.session, self.started + 30)
        self.mon.agents[newer.call_id] = newer
        rows, _ = self.mon.snapshot(True, "start")
        self.assertEqual([a.call_id for a in rows], [newer.call_id, self.agent.call_id])

    def test_runtime_accepts_epoch_zero_but_does_not_guess_unknown_start(self):
        self.agent.started = 0
        self.agent.ended = 60
        self.assertEqual(self.agent.runtime(120), 60)
        self.agent.started = None
        self.assertEqual(self.agent.runtime(120), 0)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.mon = Monitor()
        self.sequence = 0
        self.now = time.time()

    def event(self, kind, data=None, aid=None, sid="session-a", event_id=None):
        self.sequence += 1
        event = {
            "type": kind, "data": data or {},
            "timestamp": datetime.fromtimestamp(self.now + self.sequence, timezone.utc).isoformat(),
            "id": event_id or f"event-{self.sequence}",
        }
        if aid:
            event["agentId"] = aid
        return json.dumps(event) + "\n"

    def feed(self, kind, data=None, aid=None, sid="session-a"):
        self.mon.feed_cli(self.event(kind, data, aid), sid)

    def launch(self, mode="background"):
        self.feed("session.start", {"selectedModel": "model-a", "context": {"cwd": "/project"}})
        self.feed("tool.execution_start", {
            "toolName": "task", "toolCallId": "call_task",
            "arguments": {"description": "Review parser", "mode": mode, "agent_type": "explore"},
        })
        self.feed("subagent.started", {"toolCallId": "call_task", "executionMode": mode}, AID)
        return self.mon.by_agent_id[AID]

    def test_session_without_agents_is_visible(self):
        self.feed("session.start", {"context": {"cwd": "/my/project"}, "selectedModel": "model"})
        self.feed("user.message", {"content": "Build something useful"})
        rows, now, sessions = self.mon.select(False, "runtime")
        _, display = APP["build_display"](self.mon, rows, now, 240, True, set(), sessions)
        self.assertEqual(len(display), 1)
        self.assertEqual(display[0][0], "session")
        self.assertTrue(display[0][3].startswith("\u25bc >_ "))
        self.assertIn("project", display[0][3])
        self.assertEqual(self.mon.sessions["session-a"]["title"], "Build something useful")

    def test_source_symbols_in_session_headers_and_text_not_json(self):
        for source, glyph in (("cli", ">_"), ("vscode", "\u25c7")):
            with self.subTest(source=source):
                state = self.mon.state_for("session-a", self.now)
                state["source"] = source
                for collapsed, mark in ((set(), "\u25bc"), ({"session-a"}, "\u25b6")):
                    header = APP["session_header"](self.mon, "session-a", [], self.now, collapsed, 120)
                    self.assertTrue(header.startswith(f"{mark} {glyph} "))
                    self.assertNotIn(f"[{source}]", header)
                text, payload = io.StringIO(), io.StringIO()
                with patch.object(self.mon, "refresh"):
                    with contextlib.redirect_stdout(text):
                        APP["run_once"](self.mon, True, "runtime", False)
                    with contextlib.redirect_stdout(payload):
                        APP["run_once"](self.mon, True, "runtime", True)
                self.assertIn(f"\u25bc {glyph} ", text.getvalue())
                self.assertEqual(json.loads(payload.getvalue())["sessions"]["session-a"]["source"], source)

    def test_background_lifecycle_and_followup(self):
        agent = self.launch()
        self.feed("tool.execution_complete", {
            "toolCallId": "call_task", "success": True,
            "result": {"content": f"Agent started in background with agent_id: {AID}."},
        })
        self.feed("tool.execution_start", {"toolCallId": "call_read", "toolName": "view"}, AID)
        self.feed("subagent.completed", {"toolCallId": "call_task"}, AID)
        self.assertEqual(agent.status, "idle")
        self.assertIsNone(agent.ended)
        self.assertEqual(agent.tools["view"], 1)
        self.feed("tool.execution_start", {
            "toolCallId": "call_write", "toolName": "write_agent",
            "arguments": {"agent_id": AID, "message": "Continue"},
        })
        self.feed("tool.execution_complete", {"toolCallId": "call_write", "success": True})
        self.assertEqual(agent.status, "running")
        self.assertEqual(agent.messages, 1)
        self.feed("tool.execution_start", {
            "toolCallId": "call_status", "toolName": "read_agent",
            "arguments": {"agent_id": AID},
        })
        self.feed("tool.execution_complete", {
            "toolCallId": "call_status", "result": {"content": "Agent is idle"},
        })
        self.assertEqual(agent.status, "idle")
        self.assertEqual(agent.reads, 1)
        self.feed("session.shutdown", {"totalNanoAiu": 4_000_000_000})
        self.assertEqual(agent.status, "done")
        self.assertIsNotNone(agent.ended)
        self.assertEqual(self.mon.sessions["session-a"]["session_aiu"], 4)

    def test_agent_start_is_preserved_when_resumed(self):
        agent = self.launch()
        started = agent.started
        self.feed("subagent.completed", {"toolCallId": "call_task"}, AID)
        self.feed("subagent.started", {"toolCallId": "call_task", "executionMode": "background"}, AID)
        self.assertEqual(agent.started, started)

    def test_completion_without_launch_does_not_invent_start_time(self):
        self.feed("subagent.completed", {"toolCallId": "call_unknown"}, AID)
        agent = self.mon.by_agent_id[AID]
        self.assertIsNone(agent.started)
        self.assertEqual(agent.runtime(self.now + 100), 0)
        self.assertEqual(APP["fmt_timestamp"](agent.started), "-")

    def test_launch_ack_does_not_reopen_idle_agent(self):
        agent = self.launch()
        self.feed("subagent.completed", {"toolCallId": "call_task"}, AID)
        self.feed("tool.execution_complete", {
            "toolCallId": "call_task",
            "result": {"content": f"Agent started in background with agent_id: {AID}"},
        })
        self.assertEqual(agent.status, "idle")

    def test_failed_sync_task_stays_failed_in_all_outputs(self):
        agent = self.launch("sync")
        self.feed("tool.execution_complete", {
            "toolCallId": "call_task", "success": False, "error": {"message": "Tool failed"},
        })
        self.assertEqual(agent.status, "failed")
        self.assertEqual(APP["agent_line"](agent, self.now, 160)[0], "failed")
        output = io.StringIO()
        with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
            APP["run_once"](self.mon, True, "runtime", True)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["agents"][0]["status"], "failed")

    def test_nested_agents_keep_parent_and_tools(self):
        parent = self.launch()
        self.feed("tool.execution_start", {
            "toolName": "task", "toolCallId": "call_child",
            "arguments": {"description": "Nested task", "mode": "sync"},
        }, AID)
        self.feed("subagent.started", {"toolCallId": "call_child"}, CHILD)
        child = self.mon.by_agent_id[CHILD]
        self.assertEqual(child.parent, parent.call_id)
        self.assertEqual(parent.tools["task"], 1)
        self.feed("tool.execution_complete", {
            "toolCallId": "call_child", "success": True, "result": {"content": "Completed"},
        }, AID)
        self.assertEqual(child.status, "done")
        self.assertEqual(parent.status, "running")

    def test_native_idle_notification(self):
        agent = self.launch()
        self.feed("system.notification", {"kind": {"type": "agent_idle", "agentId": AID}})
        self.assertEqual(agent.status, "idle")
        self.assertIsNone(agent.ended)

    def test_failed_followup_does_not_reopen_agent(self):
        agent = self.launch()
        self.feed("subagent.completed", {"toolCallId": "call_task"}, AID)
        self.feed("tool.execution_start", {
            "toolCallId": "call_write", "toolName": "write_agent",
            "arguments": {"agent_id": AID, "message": "Continue"},
        })
        self.feed("tool.execution_complete", {
            "toolCallId": "call_write", "success": False, "error": {"message": "Cannot write"},
        })
        self.assertEqual(agent.status, "idle")

    def test_parent_error_does_not_hide_live_background_agent(self):
        self.launch()
        self.feed("session.error", {"message": "Main request failed"})
        self.assertEqual(len(self.mon.select(False, "runtime")[0]), 1)

    def test_session_shutdown_cancels_running_agents(self):
        agent = self.launch()
        self.feed("session.shutdown")
        self.assertEqual(agent.status, "cancelled")
        self.assertFalse(self.mon.select(False, "runtime")[2])
        self.feed("session.resume")
        self.assertEqual(self.mon.sessions["session-a"]["status"], "idle")

    def test_usage_checkpoint_is_cumulative_and_scoped(self):
        agent = self.launch()
        self.feed("session.usage_checkpoint", {"totalNanoAiu": 2_000_000_000})
        self.feed("user.message", {"content": "Next"})
        self.feed("session.usage_checkpoint", {"totalNanoAiu": 5_000_000_000})
        self.feed("session.usage_checkpoint", {"totalNanoAiu": 5_000_000_000})
        self.feed("model.model_call_success", {
            "responseUsage": {"prompt_tokens": 120, "completion_tokens": 10},
            "copilotUsage": {"total_nano_aiu": 1_000_000_000},
        }, AID)
        state = self.mon.sessions["session-a"]
        self.assertEqual(state["session_aiu"], 5)
        self.assertEqual(state["turn_aiu"], 3)
        self.assertEqual(agent.aiu, 1)
        self.assertEqual(agent.out_tokens, 10)

    def test_duplicate_events_are_not_counted_twice(self):
        agent = self.launch()
        event = self.event("tool.execution_start", {"toolName": "view", "toolCallId": "call_view"}, AID)
        self.mon.feed_cli(event, "session-a")
        self.mon.feed_cli(event, "session-a")
        self.assertEqual(agent.tools["view"], 1)

    def test_same_call_id_in_different_sessions(self):
        for sid in ("session-a", "session-b"):
            self.feed("tool.execution_start", {
                "toolCallId": "call_same", "toolName": "task", "arguments": {"description": sid},
            }, sid=sid)
        self.assertEqual(len(self.mon.agents), 2)

    def test_filtered_json_has_matching_sessions_and_counts(self):
        self.launch()
        self.feed("session.start", {"context": {"cwd": "/unrelated"}}, sid="session-b")
        output = io.StringIO()
        with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
            APP["run_once"](self.mon, True, "runtime", True, sess_filter="session-a")
        payload = json.loads(output.getvalue())
        self.assertEqual(list(payload["sessions"]), ["session-a"])
        self.assertEqual(payload["counts"]["running"], 1)
        self.assertEqual(payload["agents"][0]["source"], "cli")
        self.assertEqual(self.mon.select(True, "runtime", query="PARSER")[2], {"session-a"})
        self.assertEqual(self.mon.select(True, "runtime", query="unmatched")[2], set())

    def test_binary_tail_partial_lines_and_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            first = self.event("session.start")
            tool = self.event("tool.execution_start", {"toolName": "view", "toolCallId": "call_view"})
            path.write_bytes(first.encode() + tool[:20].encode())
            mon = Monitor(targets=[str(path)])
            mon.refresh()
            sid = Path(directory).name
            self.assertEqual(sum(mon.sessions[sid]["tools"].values()), 0)
            with path.open("ab") as f:
                f.write(tool[20:].encode())
                f.write(b'{"type":"user.message","data":{"content":"bad \xff and UTF-8 \xc3\xa4"},"id":"unicode"}\n')
            mon.refresh()
            mon.refresh()
            self.assertEqual(mon.sessions[sid]["tools"]["view"], 1)
            self.assertEqual(mon.offsets[str(path.resolve())][1], path.stat().st_size)
            replacement = Path(directory) / "replacement"
            replacement.write_text(first + tool)
            replacement.replace(path)
            mon.refresh()
            self.assertEqual(mon.sessions[sid]["tools"]["view"], 1)
            path.write_text(first)
            mon.refresh()
            self.assertEqual(mon.sessions[sid]["tools"]["view"], 1)

    def test_rotation_with_only_new_events_preserves_live_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(self.event("subagent.started", {
                "toolCallId": "call_task", "executionMode": "background",
            }, AID))
            mon = Monitor(targets=[str(path)])
            mon.refresh()
            replacement = Path(directory) / "rotated"
            replacement.write_text(self.event("tool.execution_start", {
                "toolCallId": "call_tool", "toolName": "view",
            }, AID))
            replacement.replace(path)
            mon.refresh()
            self.assertEqual(mon.by_agent_id[AID].tools["view"], 1)
            self.assertEqual(mon.by_agent_id[AID].status, "running")

    def test_one_shot_background_completion_is_terminal(self):
        agent = self.launch()
        self.feed("subagent.started", {
            "toolCallId": "call_task", "executionMode": "background", "resumable": False,
        }, AID)
        self.feed("subagent.completed", {"toolCallId": "call_task"}, AID)
        self.feed("system.notification", {"kind": {"type": "agent_idle", "agentId": AID}})
        self.assertEqual(agent.status, "done")
        self.assertIsNotNone(agent.ended)
        self.assertFalse(self.mon.select(False, "runtime")[0])

    def test_unknown_usage_split_is_null_not_all_subagents(self):
        self.feed("session.start")
        self.feed("user.message", {"content": "First"})
        self.feed("session.usage_checkpoint", {"totalNanoAiu": 2_000_000_000})
        self.feed("user.message", {"content": "Second"})
        self.feed("session.shutdown", {
            "totalNanoAiu": 5_000_000_000,
            "agentMetrics": {"main": {"totalNanoAiu": 5_000_000_000}},
        })
        output = io.StringIO()
        with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
            APP["run_once"](self.mon, True, "runtime", True)
        state = json.loads(output.getvalue())["sessions"]["session-a"]
        self.assertIsNone(state["turn_aiu_self"])
        self.assertIsNone(state["turn_aiu_subagents"])
        self.assertEqual(state["session_aiu_self"], 5)

    def test_known_usage_split_uses_main_metrics(self):
        self.feed("session.start")
        self.feed("user.message", {"content": "Only turn"})
        self.feed("session.shutdown", {
            "totalNanoAiu": 5_000_000_000,
            "agentMetrics": {"main": {"totalNanoAiu": 4_000_000_000}},
        })
        self.assertEqual(self.mon.sessions["session-a"]["direct_aiu"], 4)

    def test_exported_cli_log_uses_native_session_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(self.event("session.start", {"sessionId": "native-id"}))
            mon = Monitor(targets=[str(path)])
            mon.refresh()
            self.assertEqual(mon.cli_sessions, {"native-id"})
            self.assertEqual(set(mon.sessions), {"native-id"})

    def test_late_cli_discovery_replaces_only_overlapping_ahp_session(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            ahp = folder / "ahp-test.jsonl"
            ahp.write_text(json.dumps({"params": {"channel": "copilotcli:/native-id", "action": {
                "type": "chat/toolCallStart", "toolName": "task", "toolCallId": "call_task",
            }}}) + "\n")
            mon = Monitor(targets=[directory])
            mon.refresh()
            self.assertEqual(next(iter(mon.agents.values())).source, "vscode")
            cli = folder / "events.jsonl"
            cli.write_text(self.event("session.start", {"sessionId": "native-id"})
                           + self.event("tool.execution_start", {
                               "toolName": "task", "toolCallId": "call_task",
                               "arguments": {"description": "CLI"},
                           }))
            mon.last_discovery = None
            mon.refresh()
            self.assertEqual(set(mon.sessions), {"native-id"})
            self.assertEqual(len(mon.agents), 1)
            self.assertEqual(next(iter(mon.agents.values())).source, "cli")

    def test_ahp_replay_does_not_double_count_usage(self):
        self.mon.agents["call_task"] = Agent("call_task", "session-a", self.now)
        event = json.dumps({"params": {"channel": "ahp-chat://subagent/call_task", "action": {
            "type": "chat/usage", "usage": {"outputTokens": 10, "_meta": {
                "copilotUsage": {"totalNanoAiu": 1_000_000_000},
            }},
        }}})
        self.mon.feed(event)
        self.mon.feed(event)
        self.assertEqual(self.mon.agents["call_task"].out_tokens, 10)
        self.assertEqual(self.mon.agents["call_task"].aiu, 1)

    def test_ahp_main_usage_remains_cumulative_per_turn(self):
        def feed(action):
            self.mon.feed(json.dumps({"params": {"channel": "copilotcli:/session-a", "action": action}}))
        feed({"type": "chat/turnStarted", "turnId": "first"})
        for total in (2, 5, 3):
            feed({"type": "chat/usage", "usage": {"_meta": {
                "copilotUsage": {"totalNanoAiu": total * 1_000_000_000},
                "directCopilotUsage": {"totalNanoAiu": 1_000_000_000},
            }}})
        self.assertEqual(self.mon.sessions["session-a"]["turn_aiu"], 5)
        self.assertEqual(self.mon.sessions["session-a"]["direct_aiu"], 1)
        feed({"type": "chat/turnStarted", "turnId": "second"})
        self.assertEqual(self.mon.sessions["session-a"]["turn_aiu"], 0)

    def test_ahp_nested_ready_and_complete_are_routed(self):
        parent = Agent("call_parent", "session-a", self.now)
        self.mon.agents[parent.call_id] = parent
        actions = [
            {"type": "chat/toolCallStart", "toolName": "task", "toolCallId": "call_child"},
            {"type": "chat/toolCallReady", "toolCallId": "call_child",
             "toolInput": json.dumps({"description": "Nested AHP", "mode": "sync"})},
            {"type": "chat/toolCallComplete", "toolCallId": "call_child",
             "result": {"content": [{"type": "text", "text": "Done"}]}},
        ]
        for action in actions:
            self.mon.feed(json.dumps({"params": {"channel": "ahp-chat://subagent/call_parent", "action": action}}))
        child = self.mon.agents["call_child"]
        self.assertEqual(child.description, "Nested AHP")
        self.assertEqual(child.parent, parent.call_id)
        self.assertEqual(child.status, "done")

    def test_discovery_combines_sources_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            session = folder / "session-a"
            session.mkdir()
            cli = session / "events.jsonl"
            cli.write_text(self.event("session.start") + self.event("tool.execution_start", {
                "toolName": "task", "toolCallId": "call_task", "arguments": {"description": "CLI version"},
            }))
            channel = "ahp-chat://default/" + base64.urlsafe_b64encode(b"copilotcli:/session-a").decode().rstrip("=")
            ahp = folder / "ahp-one.jsonl"
            ahp.write_text(json.dumps({"params": {"channel": channel, "action": {
                "type": "chat/toolCallStart", "toolName": "task", "toolCallId": "call_task",
            }}}) + "\n")
            mon = Monitor(targets=[directory])
            mon.refresh()
            self.assertEqual(len(mon.files), 2)
            self.assertEqual(len(mon.agents), 1)
            self.assertEqual(next(iter(mon.agents.values())).description, "CLI version")
            ahp_only = Monitor(targets=[directory], source="vscode")
            ahp_only.refresh()
            self.assertEqual(len(ahp_only.files), 1)
            self.assertEqual(next(iter(ahp_only.agents.values())).source, "vscode")
            cli_only = Monitor(targets=[directory], source="cli")
            cli_only.refresh()
            self.assertEqual(len(cli_only.files), 1)
            self.assertEqual(next(iter(cli_only.agents.values())).source, "cli")

    def test_discovery_is_throttled(self):
        with patch.dict(APP["discover_logs"].__globals__, discover_logs=lambda *args: []):
            with patch("time.monotonic", side_effect=[10, 11, 16]):
                self.mon.refresh()
                self.assertEqual(self.mon.last_discovery, 10)
                self.mon.refresh()
                self.assertEqual(self.mon.last_discovery, 10)
                self.mon.refresh()
                self.assertEqual(self.mon.last_discovery, 16)

    def test_missing_log_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            mon = Monitor(targets=[str(Path(directory) / "missing.jsonl")])
            mon.refresh()
            self.assertTrue(mon.errors)
            self.assertIn("missing.jsonl", mon.errors[0])

    def test_malformed_events_are_reported_not_fatal(self):
        self.mon.feed_cli('{"type":"session.start",broken}\n', "session-a")
        self.mon.feed('{"params":"chat/toolCallStart",broken}\n')
        self.mon.feed_cli('[]\n', "session-a")
        self.assertEqual(len(self.mon.errors), 2)

    def test_tiny_detail_window_does_not_hang(self):
        class Screen:
            def addnstr(self, *args):
                pass
        agent = Agent("call", "session", self.now)
        agent.prompt = "Long prompt"
        APP["render_detail"](Screen(), agent, 30, 5)

    def test_invalid_intervals_are_rejected(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    APP["main"](["--interval", value])
                self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
