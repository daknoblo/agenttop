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
AID = "11111111-1111-1111-1111-111111111111"


class InputWaitTests(unittest.TestCase):
    def setUp(self):
        self.mon = APP["Monitor"]()
        self.ts = time.time() - 60
        self.serial = 0
        self.sid = "example-session"
        self.cli("session.start")

    def cli(self, kind, data=None, aid=None, ts=None):
        self.serial += 1
        self.ts += 1
        event = {"type": kind, "data": data or {}, "id": f"event-{self.serial}",
                 "timestamp": datetime.fromtimestamp(self.ts if ts is None else ts, timezone.utc).isoformat()}
        if aid:
            event["agentId"] = aid
        self.mon.feed_cli(json.dumps(event), self.sid)

    def ahp(self, kind, data=None, chat=None, ts=None):
        self.ts += 1
        event = {"_ahpLog": {"ts": datetime.fromtimestamp(self.ts if ts is None else ts, timezone.utc).isoformat()},
                 "params": {"channel": chat or f"copilotcli:/{self.sid}",
                            "action": {"type": kind, **(data or {})}}}
        self.mon.feed(json.dumps(event))

    def agent(self, cli=True):
        call = f"{self.sid}/worker" if cli else "worker"
        agent = APP["Agent"](call, self.sid, self.ts)
        agent.agent_id = AID
        agent.status = "running"
        agent.launched = True
        agent.mode = "background"
        self.mon.agents[call] = agent
        self.mon.by_agent_id[AID] = agent
        return agent

    def request(self, request="question"):
        return {"id": request, "questions": [{"title": "Synthetic question"}], "_meta": {"purpose": "askUser"}}

    def payload(self, activity="all"):
        output = io.StringIO()
        with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
            APP["run_once"](self.mon, True, "runtime", True, activity=activity)
        return json.loads(output.getvalue())

    def test_cli_question_tool_sets_and_clears_main_input(self):
        self.cli("tool.execution_start", {"toolCallId": "q", "toolName": "ask_user"})
        state = self.mon.sessions[self.sid]
        self.assertEqual(APP["session_status"](state), "input")
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.assertEqual(self.payload()["sessions"][self.sid]["status"], "input")
        self.cli("tool.execution_complete", {"toolCallId": "q", "success": True})
        self.assertEqual(state["activity"], "ask_user")
        self.assertNotEqual(APP["session_status"](state), "input")
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_cli_subagent_wait_survives_parallel_tools_and_failed_answer_call_closes_it(self):
        agent = self.agent()
        self.cli("tool.execution_start", {"toolCallId": "q", "toolName": "functions.ask_user"}, AID)
        self.cli("tool.execution_start", {"toolCallId": "other", "toolName": "view"}, AID)
        self.cli("tool.execution_complete", {"toolCallId": "other", "success": True}, AID)
        self.assertEqual(agent.display_status, "input")
        self.assertEqual(self.mon.input_attention(), (1, 0))
        self.cli("tool.execution_complete", {"toolCallId": "q", "success": False}, AID)
        self.assertNotEqual(agent.display_status, "input")

    def test_native_request_alias_closes_on_tool_completion_when_ephemeral_event_is_absent(self):
        agent = self.agent()
        self.cli("tool.execution_start", {"toolCallId": "q", "toolName": "ask_user"}, AID)
        self.cli("user_input.requested", {"requestId": "request", "toolCallId": "q",
                                         "question": "Do not expose this question"}, AID)
        self.assertEqual(len(agent.inputs), 1)
        self.assertNotIn("Do not expose", json.dumps(self.payload()))
        self.cli("tool.execution_complete", {"toolCallId": "q", "success": True}, AID)
        self.assertFalse(agent.inputs)
        self.assertFalse(self.mon.input_aliases)

    def test_native_completion_only_closes_matching_request(self):
        for request in ("one", "two"):
            self.cli("user_input.requested", {"requestId": request, "question": "Synthetic"})
        self.cli("user_input.completed", {"requestId": "one", "answer": "Synthetic answer"})
        self.assertEqual(APP["session_status"](self.mon.sessions[self.sid]), "input")
        self.cli("user_input.completed", {"requestId": "two"})
        self.assertNotEqual(APP["session_status"](self.mon.sessions[self.sid]), "input")

    def test_multiple_native_requests_for_one_tool_require_all_answers(self):
        self.cli("tool.execution_start", {"toolCallId": "q", "toolName": "ask_user"})
        for request in ("one", "two"):
            self.cli("user_input.requested", {"requestId": request, "toolCallId": "q", "question": "Synthetic"})
        self.cli("user_input.completed", {"requestId": "one"})
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.cli("user_input.completed", {"requestId": "two"})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_ahp_chat_and_session_wrappers_are_deduplicated_and_resolved_by_outer_id(self):
        self.ahp("chat/inputRequested", {"request": self.request()})
        self.ahp("session/inputNeededSet", {"request": {
            "id": "outer", "kind": "chatInput", "chat": f"copilotcli:/{self.sid}",
            "request": self.request(),
        }})
        self.assertEqual(len(self.mon.sessions[self.sid]["inputs"]), 1)
        self.ahp("session/inputNeededRemoved", {"id": "outer"})
        self.ahp("chat/inputCompleted", {"requestId": "question"})
        self.assertFalse(self.mon.sessions[self.sid]["inputs"])
        self.assertFalse(self.mon.input_aliases)

    def test_ahp_chat_completion_before_session_removal_is_also_safe(self):
        self.ahp("session/inputNeededSet", {"request": {
            "id": "outer", "kind": "chatInput", "request": self.request(),
        }})
        self.ahp("chat/inputCompleted", {"requestId": "question"})
        self.ahp("session/inputNeededRemoved", {"id": "outer"})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_request_ids_are_scoped_to_sessions(self):
        self.ahp("chat/inputRequested", {"request": self.request()})
        self.ahp("chat/inputRequested", {"request": self.request()}, chat="copilotcli:/other-session")
        self.assertEqual(self.mon.input_attention(), (0, 2))
        self.ahp("chat/inputCompleted", {"requestId": "question"})
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.assertEqual(APP["session_status"](self.mon.sessions["other-session"]), "input")

    def test_ordinary_client_execution_is_not_user_input(self):
        for tool in ("task", "configurePythonEnvironment", "bash"):
            self.ahp("session/inputNeededSet", {"request": {
                "id": tool, "kind": "toolClientExecution", "toolCall": {"toolName": tool, "toolCallId": tool},
            }})
        self.assertFalse(self.mon.sessions[self.sid]["inputs"])
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_client_execution_of_question_tool_is_input(self):
        self.ahp("session/inputNeededSet", {"request": {
            "id": "outer", "kind": "toolClientExecution", "toolCall": {"toolName": "ask_user", "toolCallId": "q"},
        }})
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.ahp("session/inputNeededRemoved", {"id": "outer"})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_ahp_question_tool_fallback(self):
        self.ahp("chat/toolCallStart", {"toolName": "ask_user", "toolCallId": "q"})
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.ahp("chat/toolCallComplete", {"toolCallId": "q", "result": {}})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_ahp_controls_are_not_discarded_for_cli_backed_sessions(self):
        self.mon.cli_sessions.add(self.sid)
        self.ahp("chat/inputRequested", {"request": self.request()})
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.ahp("chat/usage", {"usage": {"_meta": {"copilotUsage": {"sessionTotalNanoAiu": 1000000000}}}})
        self.assertEqual(self.mon.sessions[self.sid]["session_aiu"], 0)
        self.ahp("chat/inputCompleted", {"requestId": "question"})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_switching_to_cli_source_preserves_open_ahp_input(self):
        self.ahp("chat/inputRequested", {"request": self.request()})
        self.mon.prefer_cli(self.sid)
        self.assertEqual(APP["session_status"](self.mon.sessions[self.sid]), "input")
        self.ahp("chat/inputCompleted", {"requestId": "question"})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_ahp_subagent_requests_route_to_cli_agent_not_main(self):
        agent = self.agent()
        self.mon.cli_sessions.add(self.sid)
        chat = "ahp-chat://subagent/worker"
        self.ahp("chat/inputRequested", {"request": self.request()}, chat=chat)
        self.ahp("session/inputNeededSet", {"request": {
            "id": "outer", "kind": "chatInput", "chat": chat, "request": self.request(),
        }})
        self.assertEqual(agent.display_status, "input")
        self.assertEqual(self.mon.input_attention(), (1, 0))
        self.assertEqual(len(agent.inputs), 1)
        self.ahp("session/inputNeededRemoved", {"id": "outer"})
        self.assertEqual(agent.display_status, "running")

    def test_switching_sources_preserves_subagent_input_ownership(self):
        old = self.agent(cli=False)
        self.ahp("chat/inputRequested", {"request": self.request()}, chat="ahp-chat://subagent/worker")
        self.assertTrue(old.inputs)
        self.mon.prefer_cli(self.sid)
        self.cli("tool.execution_start", {"toolCallId": "worker", "toolName": "task",
                                          "arguments": {"mode": "background"}})
        self.cli("subagent.started", {"toolCallId": "worker"}, AID)
        current = self.mon.by_agent_id[AID]
        self.assertIsNot(current, old)
        self.assertEqual(current.display_status, "input")
        self.ahp("chat/inputCompleted", {"requestId": "question"})
        self.assertEqual(current.display_status, "running")

    def test_unknown_subagent_is_not_misclassified_as_main(self):
        self.ahp("session/inputNeededSet", {"request": {
            "id": "outer", "kind": "chatInput", "chat": "ahp-chat://subagent/missing",
            "request": self.request(),
        }})
        self.assertEqual(self.mon.input_attention(), (0, 0))
        self.assertIn("unmapped subagent", self.mon.errors[0])

    def test_old_ahp_turn_completion_does_not_clear_newer_cli_question(self):
        self.mon.cli_sessions.add(self.sid)
        self.cli("tool.execution_start", {"toolName": "ask_user", "toolCallId": "q"})
        self.ahp("chat/turnComplete", ts=self.ts - 30)
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.ahp("chat/turnComplete")
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_agent_completion_and_session_shutdown_clear_waits(self):
        agent = self.agent()
        self.cli("tool.execution_start", {"toolName": "ask_user", "toolCallId": "q"}, AID)
        self.cli("subagent.completed", {"toolCallId": "worker"}, AID)
        self.assertEqual(agent.display_status, "idle")
        self.assertFalse(agent.inputs)
        self.cli("user_input.requested", {"requestId": "main-q", "question": "Synthetic"})
        self.cli("session.shutdown")
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_task_complete_does_not_dismiss_an_unanswered_question(self):
        self.cli("tool.execution_start", {"toolName": "ask_user", "toolCallId": "q"})
        self.cli("session.task_complete", {"success": True})
        self.assertEqual(self.mon.input_attention(), (0, 1))
        self.cli("tool.execution_complete", {"toolCallId": "q", "success": True})
        self.assertEqual(self.mon.input_attention(), (0, 0))

    def test_pending_child_colors_collapsed_session_and_has_wait_details(self):
        agent = self.agent()
        self.cli("tool.execution_start", {"toolName": "ask_user", "toolCallId": "q"}, AID)
        header, rows = APP["build_display"](self.mon, [agent], self.ts, 160, True, {self.sid})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "input")
        self.assertIn("INPUT", rows[0][3])
        self.assertIn("awaiting answer", dict(APP["detail_entries"](agent, self.ts)))
        self.assertIn("input_wait", self.payload()["agents"][0])

    def test_input_colors_remain_distinct_when_selected(self):
        import curses
        with patch("curses.color_pair", side_effect=lambda number: number << 8):
            normal = APP["table_row_style"]("agent", "input", False, True)
            selected = APP["table_row_style"]("agent", "input", True, True)
            self.assertEqual(normal, (7 << 8) | curses.A_BOLD)
            self.assertEqual(selected, (8 << 8) | curses.A_BOLD)
            self.assertNotEqual(selected, APP["table_row_style"]("agent", "running", True, True))
            self.assertTrue(APP["table_row_style"]("agent", "input", True, False) & curses.A_REVERSE)

    def test_hidden_waiting_session_still_has_header_attention_badge(self):
        import curses
        self.cli("tool.execution_start", {"toolName": "ask_user", "toolCallId": "q"})
        payload = self.payload("active")
        self.assertEqual(payload["sessions"], {})
        self.assertEqual(payload["attention"]["input_sessions"], 1)
        screen = Mock()
        screen.getmaxyx.return_value = (20, 160)
        screen.get_wch.return_value = "q"
        with contextlib.ExitStack() as stack:
            for name in ("curs_set", "set_escdelay", "start_color", "use_default_colors", "init_pair"):
                stack.enter_context(patch(f"curses.{name}"))
            stack.enter_context(patch("curses.wrapper", side_effect=lambda callback: callback(screen)))
            stack.enter_context(patch("curses.has_colors", return_value=True))
            stack.enter_context(patch("curses.color_pair", side_effect=lambda number: number << 8))
            stack.enter_context(patch.object(self.mon, "refresh"))
            APP["run_tui"](self.mon, 1, check_updates=False, activity="active")
        self.assertTrue(any(call.args[0] == 0 and call.args[2] == "INPUT 1"
                            and call.args[4] == (8 << 8) | curses.A_BOLD
                            for call in screen.addnstr.call_args_list))


if __name__ == "__main__":
    unittest.main()
