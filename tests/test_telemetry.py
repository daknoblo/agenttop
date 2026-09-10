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


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.mon = APP["Monitor"]()
        self.ts = time.time() - 100
        self.index = 0

    def feed(self, kind, data=None, aid=None, session="session-a", advance=1):
        self.index += 1
        self.ts += advance
        event = {"type": kind, "data": data or {}, "id": f"event-{self.index}",
                 "timestamp": datetime.fromtimestamp(self.ts, timezone.utc).isoformat()}
        if aid:
            event["agentId"] = aid
        line = json.dumps(event)
        self.mon.feed_cli(line, session)
        return line

    def launch(self, configuration=None):
        self.feed("session.start", {"selectedModel": "main-model"})
        if configuration:
            self.feed("subagent.configured", configuration, AID)
        self.feed("tool.execution_start", {
            "toolName": "task", "toolCallId": "launch",
            "arguments": {"description": "Synthetic task", "model": "requested-model",
                          "mode": "background", "agent_type": "explore"},
        })
        self.feed("subagent.started", {"toolCallId": "launch", "model": "start-model",
                                       "executionMode": "background", "resumable": True}, AID)
        return self.mon.by_agent_id[AID]

    def payload(self, activity="all"):
        output = io.StringIO()
        with patch.object(self.mon, "refresh"), contextlib.redirect_stdout(output):
            APP["run_once"](self.mon, True, "runtime", True, activity=activity)
        return json.loads(output.getvalue())

    def permission(self, request="approval", **extra):
        return self.feed("permission.requested", {
            "requestId": request, "permissionRequest": {"kind": "shell"}, **extra,
        }, AID)

    def test_permission_wait_state_and_duration(self):
        agent = self.launch()
        self.permission()
        started = self.ts
        self.assertEqual(agent.display_status, "waiting")
        self.assertEqual(self.mon.counts([agent])[0], 0)
        self.assertEqual(self.payload()["counts"]["waiting"], 1)
        self.assertEqual(self.payload()["agents"][0]["status"], "waiting")
        self.assertEqual(self.payload("active")["agents"], [])
        self.assertEqual(len(self.payload("recent")["agents"]), 1)
        self.feed("permission.completed", {"requestId": "approval", "result": {"kind": "approved"}}, advance=3)
        self.assertEqual(agent.display_status, "running")
        self.assertAlmostEqual(agent.permission_wait, self.ts - started)
        self.assertEqual(agent.permission_results["approved"], 1)

    def test_overlapping_permissions_do_not_resume_early(self):
        agent = self.launch()
        self.permission("one")
        self.permission("two")
        self.feed("tool.execution_start", {"toolCallId": "parallel", "toolName": "view"}, AID)
        self.assertEqual(agent.display_status, "waiting")
        self.feed("permission.completed", {"requestId": "one", "result": {"kind": "approved"}})
        self.assertEqual(agent.display_status, "waiting")
        self.feed("permission.completed", {"requestId": "two", "result": {"kind": "denied-by-rules"}})
        self.assertEqual(agent.display_status, "running")
        self.assertEqual(agent.permission_results["denied-by-rules"], 1)

    def test_hook_resolved_and_duplicate_permissions(self):
        agent = self.launch()
        self.permission(resolvedByHook=True)
        self.assertEqual(agent.permissions, {})
        line = self.permission()
        self.mon.feed_cli(line, "session-a")
        self.permission()
        self.assertEqual(len(agent.permissions), 1)
        self.feed("permission.completed", {"requestId": "approval", "result": {"kind": "approved"}})
        self.feed("permission.completed", {"requestId": "approval", "result": {"kind": "approved"}})
        self.assertEqual(agent.permission_results["approved"], 1)

    def test_permission_without_agent_id_uses_tool_correlation(self):
        agent = self.launch()
        self.feed("tool.execution_start", {"toolCallId": "tool", "toolName": "view"}, AID)
        self.feed("permission.requested", {"requestId": "root-envelope",
                                         "permissionRequest": {"kind": "read", "toolCallId": "tool"}})
        self.assertEqual(agent.display_status, "waiting")
        self.assertEqual(self.mon.sessions["session-a"]["permissions"], {})

    def test_main_permissions_are_session_scoped(self):
        self.feed("session.start")
        self.feed("session.start", session="session-b")
        for session in ("session-a", "session-b"):
            self.feed("permission.requested", {"requestId": "same", "permissionRequest": {"kind": "write"}},
                      session=session)
        self.feed("permission.completed", {"requestId": "same", "result": {"kind": "approved"}})
        self.assertNotEqual(APP["session_status"](self.mon.sessions["session-a"]), "waiting")
        self.assertEqual(APP["session_status"](self.mon.sessions["session-b"]), "waiting")

    def test_unmapped_subagent_permission_is_not_attributed_to_main(self):
        self.feed("session.start")
        self.permission()
        self.assertFalse(self.mon.sessions["session-a"]["permissions"])
        self.assertIn("unmapped subagent", self.mon.errors[0])

    def test_completion_clears_approval_without_late_resurrection(self):
        agent = self.launch()
        self.permission()
        self.feed("subagent.completed", {"toolCallId": "launch", "cancelled": True}, AID)
        self.feed("permission.completed", {"requestId": "approval", "result": {"kind": "approved"}})
        self.assertEqual(agent.display_status, "cancelled")
        self.assertFalse(agent.permissions)

    def test_tool_results_durations_and_duplicates(self):
        agent = self.launch()
        start = self.feed("tool.execution_start", {"toolCallId": "tool", "toolName": "view"}, AID)
        self.mon.feed_cli(start, "session-a")
        self.feed("tool.execution_start", {"toolCallId": "tool", "toolName": "view"}, AID)
        completed = self.feed("tool.execution_complete", {
            "toolCallId": "tool", "success": False, "error": {"message": "Synthetic failure"},
        }, AID, advance=0.5)
        self.mon.feed_cli(completed, "session-a")
        self.feed("tool.execution_complete", {"toolCallId": "tool", "success": False}, AID)
        self.assertEqual(agent.tools["view"], 1)
        self.assertEqual(agent.tool_results["failed"], 1)
        self.assertAlmostEqual(agent.tool_durations["view"], 1.5)
        self.assertEqual(agent.last_error, "Synthetic failure")
        self.assertEqual(agent.status, "running")
        self.assertEqual(agent.tool_samples["view"], 1)

    def test_tool_completion_without_start_does_not_guess_duration(self):
        agent = self.launch()
        self.feed("tool.execution_complete", {"toolCallId": "lost", "success": True}, AID)
        self.assertEqual(agent.tool_results["success"], 1)
        self.assertEqual(agent.tool_durations, {})
        self.assertNotIn("duration_seconds", agent.recent_results[0])

    def test_completed_tool_can_be_correlated_without_agent_id(self):
        agent = self.launch()
        self.feed("tool.execution_start", {"toolCallId": "tool", "toolName": "view"}, AID)
        self.feed("tool.execution_complete", {"toolCallId": "tool", "success": True})
        self.assertEqual(agent.tool_results["success"], 1)
        self.assertFalse(agent.pending_tools)

    def test_pending_configuration_and_model_changes(self):
        agent = self.launch({"model": "configured-model", "reasoningEffort": "high",
                             "contextTier": "long_context", "multiTurn": True})
        self.assertEqual(agent.model, "configured-model")
        self.assertEqual(agent.configuration["requested_model"], "requested-model")
        self.assertEqual(agent.configuration["reasoning_effort"], "high")
        self.feed("session.model_change", {"newModel": "fallback-model",
                                          "previousModel": "configured-model",
                                          "cause": "rate_limit_auto_switch"}, AID)
        self.assertEqual(agent.model, "fallback-model")
        self.assertEqual(agent.model_changes[-1]["cause"], "rate_limit_auto_switch")
        self.assertEqual(self.mon.sessions["session-a"]["model"], "main-model")
        self.feed("subagent.completed", {"toolCallId": "launch", "model": "fallback-model",
                                         "firstDispatchedModel": "configured-model",
                                         "configuredModelPreference": "preferred-model",
                                         "configuredModelMatchesActual": False,
                                         "modelOverrideReason": "Synthetic override"}, AID)
        self.assertFalse(agent.configuration["preferred_model_matched"])
        self.assertEqual(agent.configuration["first_dispatched_model"], "configured-model")

    def test_reported_totals_are_not_added_to_observed_usage(self):
        agent = self.launch()
        for _ in range(2):
            self.feed("model.model_call_success", {
                "responseUsage": {"prompt_tokens": 100, "completion_tokens": 10},
                "copilotUsage": {"total_nano_aiu": 2_000_000_000},
            }, AID)
        self.assertIsNone(agent.total_tokens)
        for _ in range(2):
            self.feed("subagent.completed", {"toolCallId": "launch", "durationMs": 500,
                                             "totalTokens": 1500, "totalToolCalls": 5}, AID)
        self.assertEqual(agent.in_tokens, 100)
        self.assertEqual(agent.out_tokens, 20)
        self.assertEqual(agent.total_tokens, 1500)
        self.assertEqual(agent.aic, 4)
        self.assertEqual(agent.completion["duration_ms"], 500)
        self.assertTrue(agent.tool_summary.startswith("5"))
        self.assertIn("sum 1k", APP["agent_line"](agent, self.ts, 180)[1])

    def test_final_aic_reconciles_instead_of_adding_and_global_sum_is_once(self):
        agent = self.launch()
        agent.observed_aic(4_000_000_000)
        metrics = {"totalNanoAiu": 3_000_000_000, "totalApiDurationMs": 500,
                   "modelMetrics": {"model": {"usage": {
                       "inputTokens": 1000, "outputTokens": 500,
                       "cacheReadTokens": 700, "cacheWriteTokens": 20, "reasoningTokens": 50,
                   }}}}
        for _ in range(2):
            self.feed("session.shutdown", {"totalNanoAiu": 10_000_000_000,
                                           "agentMetrics": {AID: metrics}})
        self.assertEqual(agent.aic, 3)
        self.assertEqual(agent.final_aiu, 3)
        self.assertEqual(agent.total_tokens, 1500)
        self.assertEqual(agent.usage_totals["cached_tokens"], 700)
        payload = self.payload()
        self.assertEqual(payload["totals"]["aic"], 10)
        self.assertEqual(payload["agents"][0]["usage"]["aic"], 3)
        self.assertTrue(payload["agents"][0]["usage"]["aic_final"])
        self.assertEqual(payload["agents"][0]["aiu"], 3)
        agent.observed_aic(1_000_000_000)
        self.assertIsNone(agent.final_aiu)
        self.assertEqual(agent.aic, 4)

    def test_final_token_breakdown_requires_all_models_for_each_field(self):
        agent = self.launch()
        agent.shutdown_usage({"modelMetrics": {
            "one": {"usage": {"inputTokens": 10, "outputTokens": 20}},
            "two": {"usage": {"inputTokens": 30}},
        }})
        self.assertEqual(agent.usage_totals["input_tokens"], 40)
        self.assertNotIn("output_tokens", agent.usage_totals)
        self.assertIsNone(agent.total_tokens)
        self.assertIsNone(agent.aic)

    def test_later_shutdown_does_not_mix_token_snapshots(self):
        agent = self.launch()
        agent.shutdown_usage({"totalNanoAiu": 1_000_000_000, "totalApiDurationMs": 100,
                              "modelMetrics": {"one": {"usage": {"inputTokens": 100, "outputTokens": 20}}}})
        self.assertEqual(agent.total_tokens, 120)
        agent.shutdown_usage({"modelMetrics": {
            "one": {"usage": {"inputTokens": 150, "outputTokens": 30}},
            "two": {"usage": {"inputTokens": 50}},
        }})
        self.assertEqual(agent.usage_totals["input_tokens"], 200)
        self.assertNotIn("output_tokens", agent.usage_totals)
        self.assertNotIn("api_duration_ms", agent.usage_totals)
        self.assertIsNone(agent.total_tokens)
        self.assertIsNone(agent.final_aiu)

    def test_resumed_agent_invalidates_old_final_usage(self):
        agent = self.launch()
        self.feed("subagent.completed", {"toolCallId": "launch", "totalTokens": 120}, AID)
        agent.shutdown_usage({"totalNanoAiu": 1_000_000_000, "modelMetrics": {
            "one": {"usage": {"inputTokens": 100, "outputTokens": 20}},
        }})
        self.feed("assistant.turn_start", {"turnId": "new-turn"}, AID)
        self.assertIsNone(agent.final_aiu)
        self.assertIsNone(agent.total_tokens)
        self.assertEqual(agent.usage_totals, {})
        self.assertEqual(agent.completion, {})

    def test_global_aic_sum_is_independent_of_display_filters(self):
        self.launch()
        self.feed("session.usage_checkpoint", {"totalNanoAiu": 10_000_000_000})
        state = self.mon.state_for("hidden", self.ts - 20000)
        state.update(session_aiu=5, session_aiu_known=True, status="done")
        self.assertEqual(self.payload("active")["totals"]["aic"], 15)
        self.assertIn("AIC total 15", APP["aic_summary"](self.mon))
        self.mon.state_for("missing-usage", self.ts)
        self.assertIn("AIC known 15", APP["aic_summary"](self.mon))
        self.assertFalse(self.payload()["totals"]["complete"])

    def test_missing_values_hidden_but_explicit_zero_is_kept(self):
        agent = APP["Agent"]("call", "session", None)
        entries = dict(APP["detail_entries"](agent, self.ts))
        self.assertNotIn("model", entries)
        self.assertNotIn("started", entries)
        self.assertNotIn("AIC observed", entries)
        self.assertNotIn("tokens total", entries)
        self.assertEqual(APP["agent_telemetry"](agent, self.ts), {})
        agent.observed_aic(0)
        agent.reported_completion({"totalTokens": 0, "totalToolCalls": 0}, self.ts)
        entries = dict(APP["detail_entries"](agent, self.ts))
        self.assertEqual(entries["AIC observed"], "0.0000")
        self.assertEqual(entries["tokens total"], "0")
        state = self.mon.state_for("zero", self.ts)
        state["session_aiu_known"] = True
        self.assertEqual(APP["aic_summary"](self.mon), "AIC total 0")
        self.assertEqual(APP["fmt_aic"](12.34), "12.34")
        self.assertEqual(APP["fmt_aic"](0.00001), "<0.0001")

    def test_native_cancel_and_error_survive_late_task_result(self):
        for event, data, status in (("subagent.completed", {"cancelled": False}, "done"),
                                    ("subagent.completed", {"cancelled": True}, "cancelled"),
                                    ("subagent.failed", {"error": "Synthetic error"}, "failed")):
            for success in (True, False):
                with self.subTest(status=status, outer_success=success):
                    agent = self.launch()
                    agent.resumable = False
                    self.feed(event, {"toolCallId": "launch", **data}, AID)
                    self.feed("tool.execution_complete", {"toolCallId": "launch", "success": success,
                                                          "result": {"content": "Outer task failed"}})
                    self.assertEqual(agent.status, status)
                    if status == "failed":
                        self.assertEqual(agent.last_error, "Synthetic error")

    def test_idle_notification_does_not_erase_native_failure(self):
        agent = self.launch()
        self.feed("subagent.failed", {"toolCallId": "launch", "error": "Synthetic error"}, AID)
        self.feed("system.notification", {"kind": {"type": "agent_idle", "agentId": AID}})
        self.assertEqual(agent.status, "failed")
        self.assertIsNotNone(agent.ended)
        self.feed("subagent.started", {"toolCallId": "launch", "executionMode": "background"}, AID)
        self.assertEqual(agent.status, "running")
        self.assertFalse(agent.native_terminal)

    def test_detail_scroll_and_model_column(self):
        agent = self.launch({"model": "configured-model", "reasoningEffort": "high", "multiTurn": False})
        agent.result_preview = "End of synthetic result"
        screen = Mock()
        maximum = APP["render_detail"](screen, agent, 8, 80)
        self.assertGreater(maximum, 0)
        screen.reset_mock()
        APP["render_detail"](screen, agent, 8, 80, maximum)
        values = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertIn("End of synthetic result", values)
        self.assertIn("MODEL", APP["table_header"](160))
        self.assertNotIn("MODEL", APP["table_header"](132))
        self.assertIn("configured-model", APP["agent_line"](agent, self.ts, 160)[1])
        self.assertIn("AIC", APP["table_header"](160))

    def test_ahp_tool_results_and_observed_aic(self):
        agent = APP["Agent"]("parent", "session-a", self.ts)
        self.mon.agents["parent"] = agent
        for action in (
            {"type": "chat/toolCallStart", "toolCallId": "tool", "toolName": "view"},
            {"type": "chat/toolCallComplete", "toolCallId": "tool",
             "result": {"isError": True, "content": [{"type": "text", "text": "Synthetic error"}]}},
            {"type": "chat/usage", "usage": {"inputTokens": 10, "outputTokens": 5,
                                            "_meta": {"copilotUsage": {"totalNanoAiu": 0}}}},
        ):
            self.mon.feed(json.dumps({"params": {"channel": "ahp-chat://subagent/parent", "action": action}}))
        self.assertEqual(agent.tool_results["failed"], 1)
        self.assertEqual(agent.last_error, "Synthetic error")
        self.assertTrue(agent.tokens_known)
        self.assertEqual(agent.aic, 0)

    def test_header_sum_and_detail_keyboard_scroll(self):
        import curses
        agent = self.launch({"model": "configured-model", "reasoningEffort": "high", "multiTurn": True})
        agent.result_preview = "Last result reached"
        self.feed("session.usage_checkpoint", {"totalNanoAiu": 10_000_000_000})
        screen = Mock()
        screen.getmaxyx.return_value = (12, 160)
        screen.get_wch.side_effect = ["j", "\n", curses.KEY_END, "q", "q"]
        with patch("curses.wrapper", side_effect=lambda callback: callback(screen)), \
                patch("curses.has_colors", return_value=False), patch("curses.curs_set"), \
                patch("curses.set_escdelay"), patch.object(self.mon, "refresh"):
            APP["run_tui"](self.mon, 1, check_updates=False)
        headers = [call.args[2] for call in screen.addnstr.call_args_list if call.args[0] == 0]
        self.assertTrue(any("AIC total 10" in text for text in headers))
        values = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertIn("Last result reached", values)

    def test_invalid_optional_metrics_are_not_exposed_as_values(self):
        agent = self.launch()
        self.feed("subagent.completed", {"toolCallId": "launch", "totalTokens": -1,
                                         "durationMs": True, "totalToolCalls": "unknown"}, AID)
        self.assertNotIn("total_tokens", agent.completion)
        self.assertNotIn("duration_ms", agent.completion)
        self.assertNotIn("total_tool_calls", agent.completion)
        self.assertNotIn("usage", APP["agent_telemetry"](agent, self.ts))


if __name__ == "__main__":
    unittest.main()
