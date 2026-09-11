import contextlib
import io
import json
from pathlib import Path
import runpy
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch


APP = runpy.run_path(str(Path(__file__).resolve().parents[1] / "agenttop"))


class MainAgentTests(unittest.TestCase):
    def setUp(self):
        self.mon = APP["Monitor"]()
        self.now = float(int(time.time()))
        self.serial = 0
        self.sid = "example-session"

    def cli(self, kind, data=None, age=10, aid=None):
        self.serial += 1
        event = {"type": kind, "id": f"event-{self.serial}", "data": data or {},
                 "timestamp": datetime.fromtimestamp(self.now - age, timezone.utc).isoformat()}
        if aid:
            event["agentId"] = aid
        self.mon.feed_cli(json.dumps(event), self.sid)

    def ahp(self, kind, data=None, age=10, subagent=None):
        self.mon.feed(json.dumps({
            "_ahpLog": {"ts": datetime.fromtimestamp(self.now - age, timezone.utc).isoformat()},
            "params": {"channel": f"ahp-chat://subagent/{subagent}" if subagent else f"copilotcli:/{self.sid}",
                       "action": {"type": kind, **(data or {})}},
        }))

    def start(self, age=120):
        self.cli("session.start", {"selectedModel": "main-model"}, age=age + 1)
        self.cli("user.message", {"content": "Synthetic main task"}, age=age)
        self.cli("tool.execution_start", {"toolCallId": "read", "toolName": "view"}, age=10)

    def views(self, activity="active", query="", show_done=False):
        with patch("time.time", return_value=self.now):
            children, now, sessions = self.mon.select(show_done, "runtime", query=query, activity=activity)
            mains = self.mon.main_views(sessions, show_done, activity, query, now)
        return children, mains, sessions

    def payload(self, activity="active", show_done=False):
        output = io.StringIO()
        with patch.object(self.mon, "refresh"), patch("time.time", return_value=self.now), contextlib.redirect_stdout(output):
            APP["run_once"](self.mon, show_done, "runtime", True, activity=activity)
        return json.loads(output.getvalue())

    def test_working_cli_main_is_visible_without_any_subagents(self):
        self.start()
        children, mains, sessions = self.views()
        self.assertEqual(children, [])
        self.assertEqual(len(mains), 1)
        self.assertEqual(mains[0].label, "Main: view")
        _, rows = APP["build_display"](self.mon, children, self.now, 200, True, set(), sessions, mains)
        self.assertEqual([row[0] for row in rows], ["session", "main"])
        self.assertIn("Main: view", rows[1][3])
        self.assertIn("main-model", rows[1][3])
        self.assertEqual(self.mon.agents, {})

    def test_working_vsc_main_is_visible(self):
        self.ahp("chat/turnStarted", {"turnId": "turn"}, age=120)
        self.ahp("chat/toolCallStart", {"toolCallId": "read", "toolName": "view"})
        self.ahp("session/activityChanged", {"activity": "Inspecting example files"}, age=5)
        children, mains, _ = self.views()
        self.assertFalse(children)
        self.assertEqual(mains[0].source, "vscode")
        self.assertIn("Inspecting example files", mains[0].label)

    def test_vsc_tool_start_recovers_main_activity_after_missing_turn_start(self):
        self.ahp("chat/toolCallStart", {"toolCallId": "read", "toolName": "view"})
        _, mains, _ = self.views()
        self.assertEqual(len(mains), 1)
        self.assertEqual(mains[0].display_status, "running")
        self.assertEqual(mains[0].label, "Main: view")
        self.assertIsNone(mains[0].started)

    def test_metadata_only_does_not_invent_a_main_agent(self):
        self.mon.state_for(self.sid, self.now)["repo"] = "example/project"
        self.assertEqual(self.views("all")[1], [])

    def test_main_precedes_children_and_flat_view_includes_it(self):
        self.start()
        self.cli("subagent.started", {"toolCallId": "worker", "agentDisplayName": "Worker"}, aid="worker")
        children, mains, sessions = self.views()
        for tree, expected in ((True, ["session", "main", "agent"]), (False, ["main", "agent"])):
            _, rows = APP["build_display"](self.mon, children, self.now, 180, tree, set(), sessions, mains)
            self.assertEqual([row[0] for row in rows], expected)
        _, collapsed = APP["build_display"](self.mon, children, self.now, 180, True, {self.sid}, sessions, mains)
        self.assertEqual(len(collapsed), 1)

    def test_main_and_subagent_counts_and_aic_are_not_combined(self):
        self.start()
        self.cli("subagent.started", {"toolCallId": "worker"}, aid="worker")
        self.cli("session.usage_checkpoint", {"totalNanoAiu": 10_000_000_000})
        payload = self.payload()
        self.assertEqual(payload["counts"]["running"], 1)
        self.assertEqual(payload["main_counts"]["running"], 1)
        self.assertEqual(len(payload["agents"]), 1)
        self.assertEqual(len(payload["main_agents"]), 1)
        self.assertEqual(payload["totals"]["aic"], 10)
        self.assertNotIn("usage", payload["main_agents"][0])

    def test_main_only_uses_known_direct_usage(self):
        self.ahp("chat/turnStarted", {"turnId": "turn"}, age=120)
        self.ahp("chat/usage", {"usage": {"model": "main-model", "_meta": {
            "copilotUsage": {"totalNanoAiu": 5_000_000_000, "sessionTotalNanoAiu": 10_000_000_000},
        }}})
        self.assertNotIn("usage", self.payload()["main_agents"][0])
        self.ahp("chat/usage", {"usage": {"_meta": {"directCopilotUsage": {"totalNanoAiu": 3_000_000_000}}}}, age=5)
        self.assertEqual(self.payload()["main_agents"][0]["usage"], {"aic_self": 3, "scope": "turn"})
        self.assertEqual(self.payload()["totals"]["aic"], 10)
        self.ahp("chat/turnStarted", {"turnId": "next"}, age=1)
        self.assertNotIn("usage", self.payload()["main_agents"][0])

    def test_cli_shutdown_main_usage_has_session_scope(self):
        self.start()
        self.cli("session.shutdown", {"totalNanoAiu": 8_000_000_000,
                                      "agentMetrics": {"main": {"totalNanoAiu": 5_000_000_000}}})
        payload = self.payload("all", True)
        self.assertEqual(payload["main_agents"][0]["usage"], {"aic_self": 5, "scope": "session"})
        self.assertEqual(payload["totals"]["aic"], 8)
        self.assertEqual(payload["main_counts"]["done"], 1)
        self.assertFalse(self.payload()["main_agents"])

    def test_fresh_child_events_do_not_refresh_stale_main(self):
        self.start()
        self.mon.sessions[self.sid]["main_last_event"] = self.now - 600
        self.cli("subagent.started", {"toolCallId": "worker"}, age=5, aid="worker")
        self.cli("assistant.message", {"model": "child-model"}, age=2, aid="worker")
        children, mains, _ = self.views()
        self.assertEqual(len(children), 1)
        self.assertEqual(mains, [])
        self.assertEqual(self.mon.sessions[self.sid]["main_last_event"], self.now - 600)

    def test_global_usage_checkpoint_is_not_main_work(self):
        self.start()
        self.mon.sessions[self.sid]["main_last_event"] = self.now - 600
        self.cli("session.usage_checkpoint", {"totalNanoAiu": 10_000_000_000}, age=1)
        self.assertFalse(self.views()[1])

    def test_main_filter_expiry_and_search(self):
        self.start()
        self.assertEqual(len(self.views(query="view")[1]), 1)
        self.assertEqual(self.views(query="missing")[1], [])
        self.mon.sessions[self.sid]["main_last_event"] = self.now - 300
        self.assertEqual(len(self.views()[1]), 1)
        self.now += 0.01
        self.assertEqual(self.views()[1], [])
        self.assertEqual(len(self.views("all")[1]), 1)

    def test_details_refresh_after_new_session_events(self):
        self.start()
        main = self.views()[1][0]
        self.cli("session.model_change", {"newModel": "next-model"}, age=2)
        self.cli("tool.execution_start", {"toolCallId": "test", "toolName": "bash"}, age=1)
        entries = dict(APP["detail_entries"](main, self.now))
        self.assertEqual(entries["model"], "next-model")
        self.assertEqual(entries["latest activity"], "bash")
        self.assertIn("turn started", entries)
        self.assertNotIn("call_id", entries)
        self.assertNotIn("agent_id", entries)

    def test_input_main_is_not_double_counted_in_attention(self):
        self.start()
        self.cli("tool.execution_start", {"toolCallId": "q", "toolName": "ask_user"})
        payload = self.payload("all")
        self.assertEqual(payload["main_counts"]["input"], 1)
        self.assertEqual(payload["counts"]["input"], 0)
        self.assertEqual(payload["attention"]["input_sessions"], 1)
        self.assertEqual(payload["attention"]["input_agents"], 0)
        self.assertIn("input_wait", payload["main_agents"][0])
        self.assertEqual(self.views()[1], [])

    def test_older_ahp_input_does_not_move_main_clock_backwards(self):
        self.start()
        last = self.mon.sessions[self.sid]["main_last_event"]
        self.mon.cli_sessions.add(self.sid)
        self.ahp("chat/inputRequested", {"request": {"id": "old", "questions": []}}, age=500)
        self.ahp("chat/inputCompleted", {"requestId": "old"}, age=400)
        self.assertEqual(self.mon.sessions[self.sid]["main_last_event"], last)

    def test_turn_runtime_stops_when_idle_and_counts_waiting_time(self):
        self.start(age=120)
        self.cli("tool.execution_complete", {"toolCallId": "read", "success": True}, age=60)
        self.cli("assistant.turn_end", {}, age=50)
        main = self.views("all")[1][0]
        self.assertAlmostEqual(main.runtime(self.now), 70)
        self.cli("user_input.requested", {"requestId": "q", "question": "Synthetic question"}, age=5)
        main.sync()
        self.assertAlmostEqual(main.runtime(self.now), 120)

    def test_main_details_open_in_tui_without_subagents(self):
        self.start()
        screen = Mock()
        screen.getmaxyx.return_value = (24, 160)
        screen.get_wch.side_effect = ["j", "\n", "q", "q"]
        with patch("curses.wrapper", side_effect=lambda callback: callback(screen)), \
                patch("curses.has_colors", return_value=False), patch("curses.curs_set"), \
                patch("curses.set_escdelay"), patch.object(self.mon, "refresh"), \
                patch("time.time", return_value=self.now):
            APP["run_tui"](self.mon, 1, check_updates=False)
        values = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertIn("Main agent / running", values)
        self.assertIn("latest activity", values)


if __name__ == "__main__":
    unittest.main()
