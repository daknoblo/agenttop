import base64
import json
from pathlib import Path
import runpy
import time
import unittest
from datetime import datetime, timezone


APP = runpy.run_path(str(Path(__file__).resolve().parents[1] / "agenttop"))
AID = "11111111-1111-4111-8111-111111111111"


class StreamDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.mon = APP["Monitor"]()
        self.now = float(int(time.time()))
        self.start = self.now - 600
        self.parent = "front-session"
        self.backend = "cli-session"
        for sid in (self.parent, self.backend):
            self.mon.state_for(sid, self.start)
        self.vsc = APP["Agent"]("call_worker", self.parent, self.start)
        self.cli = APP["Agent"](f"{self.backend}/call_worker", self.backend, self.start)
        self.cli.source = "cli"
        for agent in (self.cli, self.vsc):
            agent.agent_id = AID
            agent.status = "running"
            agent.launched = True
            self.mon.agents[agent.call_id] = agent
            self.mon.by_agent_id[AID] = agent
        encoded = base64.urlsafe_b64encode(f"copilotcli:/{self.parent}".encode()).decode().rstrip("=")
        self.channel = f"ahp-chat://subagent/{encoded}/call_worker"

    def rpc(self, identity, *, connection="connection-a", method=None, params=None, result=None, error=None, age=590, source=None):
        message = {"jsonrpc": "2.0", "id": identity,
                   "_ahpLog": {"connectionId": connection,
                               "ts": datetime.fromtimestamp(self.now - age, timezone.utc).isoformat()}}
        if method:
            message.update(method=method, params=params)
        elif error is not None:
            message["error"] = error
        else:
            message["result"] = result
        self.mon.feed(json.dumps(message), source=source)

    def fail(self):
        self.rpc(1, method="subscribe", params={"channel": self.channel})
        self.rpc(1, error={"code": -32001, "message": f"Resource not found: {self.channel}"}, age=580)

    def action(self, kind, data=None, age=1):
        self.mon.feed(json.dumps({
            "params": {"channel": self.channel, "action": {"type": kind, **(data or {})}},
            "_ahpLog": {"ts": datetime.fromtimestamp(self.now - age, timezone.utc).isoformat()},
        }))

    def test_subscription_failure_is_scoped_and_does_not_fake_activity(self):
        self.fail()
        self.assertEqual(self.vsc.stream_error["error_code"], -32001)
        self.assertEqual(self.vsc.stream_error["message"], "Resource not found")
        self.assertIsNone(self.cli.stream_error)
        self.assertEqual(self.vsc.last_event, self.start)
        self.assertEqual(self.vsc.status, "running")
        self.assertIsNone(self.vsc.ended)
        self.assertTrue(self.vsc.is_unconfirmed(self.now))
        self.assertIsNone(self.mon.sessions[self.parent]["main_last_event"])
        self.assertNotIn(self.channel, json.dumps(APP["agent_telemetry"](self.vsc, self.now)))

    def test_reply_id_is_correlated_with_connection(self):
        self.rpc(1, method="subscribe", params={"channel": self.channel})
        self.rpc(1, connection="other-connection", error={"code": -32001, "message": "Resource not found"})
        self.assertIsNone(self.vsc.stream_error)
        self.rpc(1, error={"code": -32001, "message": "Resource not found"}, age=580)
        self.assertIsNotNone(self.vsc.stream_error)

    def test_rpc_identifiers_are_also_scoped_to_the_log_file(self):
        self.rpc(1, method="subscribe", params={"channel": self.channel}, source="first-log")
        error = {"code": -32001, "message": "Resource not found"}
        self.rpc(1, error=error, source="second-log", age=580)
        self.assertIsNone(self.vsc.stream_error)
        self.rpc(1, error=error, source="first-log", age=580)
        self.assertIsNotNone(self.vsc.stream_error)

    def test_successful_retry_clears_error_without_claiming_work(self):
        self.fail()
        self.rpc(2, method="subscribe", params={"channel": self.channel}, age=2)
        self.rpc(2, result={"state": {}}, age=1)
        self.assertIsNone(self.vsc.stream_error)
        self.assertEqual(self.vsc.last_event, self.start)
        self.assertTrue(self.vsc.is_unconfirmed(self.now))

    def test_error_before_launch_is_attached_when_agent_becomes_known(self):
        del self.mon.agents[self.vsc.call_id]
        self.fail()
        self.mon.on_start(self.parent, {"toolName": "task", "toolCallId": "call_worker"}, self.now - 1)
        agent = self.mon.agents["call_worker"]
        self.assertEqual(agent.stream_error["error_code"], -32001)
        self.assertEqual(agent.status, "starting")

    def test_tool_event_recovers_stream_and_routes_to_encoded_parent(self):
        self.fail()
        self.action("chat/toolCallStart", {"toolCallId": "read", "toolName": "view"})
        self.assertIsNone(self.vsc.stream_error)
        self.assertEqual(self.vsc.tools["view"], 1)
        self.assertFalse(self.vsc.is_unconfirmed(self.now))
        self.assertEqual(self.cli.tools["view"], 0)

    def test_delta_is_a_heartbeat_without_storing_content_or_counting_tokens(self):
        self.fail()
        self.action("chat/delta", {"content": "Do not retain this synthetic streaming text"})
        self.assertIsNone(self.vsc.stream_error)
        self.assertEqual(self.vsc.last_event, self.now - 1)
        self.assertEqual(self.vsc.in_tokens, 0)
        self.assertEqual(self.vsc.out_tokens, 0)
        self.assertEqual(self.vsc.tools, {})
        self.assertNotIn("Do not retain", json.dumps(APP["agent_telemetry"](self.vsc, self.now)))

    def test_late_delta_does_not_reopen_completed_or_idle_agent(self):
        self.vsc.finish(self.start + 10, native=True)
        self.action("chat/delta", {"content": "Late output"})
        self.assertEqual(self.vsc.status, "done")
        self.assertEqual(self.vsc.last_event, self.start)
        self.vsc.native_terminal = False
        self.vsc.ended = None
        self.vsc.status = "idle"
        self.action("chat/delta", {"content": "Last response part"}, age=0)
        self.assertEqual(self.vsc.status, "idle")

    def test_tool_argument_delta_does_not_revive_completed_call(self):
        self.vsc.status = "idle"
        self.vsc.completed_tools.add("old-tool")
        self.action("chat/toolCallDelta", {"toolCallId": "old-tool", "content": "old args"})
        self.assertEqual(self.vsc.status, "idle")
        self.assertEqual(self.vsc.last_event, self.start)

    def test_cli_child_events_are_not_lost_when_global_id_points_to_vsc(self):
        self.assertIs(self.mon.by_agent_id[AID], self.vsc)
        self.mon.feed_cli(json.dumps({
            "type": "tool.execution_start", "id": "cli-event", "agentId": AID,
            "timestamp": datetime.fromtimestamp(self.now - 1, timezone.utc).isoformat(),
            "data": {"toolCallId": "native-read", "toolName": "view"},
        }), self.backend)
        self.assertEqual(self.cli.tools["view"], 1)
        self.assertEqual(self.vsc.tools["view"], 0)
        self.assertEqual(self.cli.last_event, self.now - 1)

    def test_older_error_does_not_replace_newer_recovery(self):
        self.action("chat/toolCallStart", {"toolCallId": "read", "toolName": "view"}, age=1)
        self.fail()
        self.assertIsNone(self.vsc.stream_error)

    def test_details_json_and_footer_expose_stream_error_without_changing_status(self):
        self.fail()
        style, line = APP["agent_line"](self.vsc, self.now, 160)
        self.assertEqual(style, "stream_error")
        self.assertTrue(line.startswith("!"))
        self.assertEqual(self.vsc.display_status, "running")
        details = dict(APP["detail_entries"](self.vsc, self.now))
        self.assertIn("Resource not found", details["VSC event stream"])
        self.assertEqual(details["stream error code"], "-32001")
        self.assertIn("telemetry", APP["agent_telemetry"](self.vsc, self.now))
        self.assertTrue(any("VSC stream unavailable" in line for line in APP["footer_lines"](self.mon, 180)))
        self.vsc.finish(self.now)
        self.assertFalse(any("VSC stream unavailable" in line for line in APP["footer_lines"](self.mon, 180)))

    def test_root_deltas_do_not_renew_main_or_subagent_activity(self):
        self.mon.feed(json.dumps({
            "params": {"channel": f"copilotcli:/{self.parent}", "action": {
                "type": "chat/delta", "content": "main text",
            }},
        }))
        self.assertEqual(self.vsc.last_event, self.start)
        self.assertIsNone(self.mon.sessions[self.parent]["main_last_event"])

    def test_cli_primary_can_use_ahp_heartbeat_without_double_counting_metrics(self):
        self.mon.cli_sessions.add(self.backend)
        encoded = base64.urlsafe_b64encode(f"copilotcli:/{self.backend}".encode()).decode().rstrip("=")
        self.channel = f"ahp-chat://subagent/{encoded}/call_worker"
        self.action("chat/toolCallStart", {"toolCallId": "native-read", "toolName": "view"}, age=2)
        self.action("chat/delta", {"content": "streaming"}, age=1)
        self.assertEqual(self.cli.tools["view"], 0)
        self.assertEqual(self.cli.last_event, self.now - 1)
        self.assertEqual(self.cli.status, "running")


if __name__ == "__main__":
    unittest.main()
