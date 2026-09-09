import base64
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


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
        self.assertIn("[cli]", display[0][3])
        self.assertIn("project", display[0][3])
        self.assertEqual(self.mon.sessions["session-a"]["title"], "Build something useful")

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
