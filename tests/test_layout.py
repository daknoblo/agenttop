import contextlib
from pathlib import Path
import runpy
import time
import unittest
from unittest.mock import Mock, patch


APP = runpy.run_path(str(Path(__file__).resolve().parents[1] / "agenttop"))


class TableLayoutTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.mon = APP["Monitor"]()
        self.agents = []
        for index, (sid, label) in enumerate((
            ("aaaaaaaa", "short"),
            ("bbbbbbbb", "a-very-long-example-project-and-branch-name"),
        )):
            state = self.mon.state_for(sid, self.now)
            state.update(repo=label, branch="main", model="example-model", status="running",
                         session_aiu_known=True, session_aiu=0.5 + index * 12345,
                         turn_started=self.now - 500, activity="Synthetic activity")
            state["tools"]["view"] = 2 + index * 5000
            agent = APP["Agent"](f"call_{index}", sid, self.now - 60)
            agent.launched = True
            agent.status = "running"
            agent.description = "TASK-MARKER"
            agent.agent_type = "general-purpose"
            agent.model = "example-model"
            self.mon.agents[agent.call_id] = agent
            self.agents.append(agent)

    def test_fixed_columns_and_numeric_alignment(self):
        agent = self.agents[0]
        agent.aiu = 123456789012345
        agent.aiu_known = True
        agent.tokens_known = True
        agent.in_tokens = 100
        agent.tools["an-extremely-long-tool-name"] = 123456789
        agent.model = "a-model-name-that-does-not-fit"
        for width in (80, 100, 120, 132, 160, 240):
            with self.subTest(width=width):
                header = APP["table_header"](width)
                _, row = APP["agent_line"](agent, self.now, width)
                offset = 0
                widths = APP["column_widths"](width)
                separator = APP["COLUMN_SEPARATOR"]
                columns = APP["table_columns"](width)
                task_offset = None
                for index, key in enumerate(columns):
                    cell = widths[key]
                    if index < len(columns) - 1:
                        self.assertEqual(row[offset + cell:offset + cell + len(separator)], separator)
                    if key in APP["RIGHT_ALIGNED"]:
                        self.assertNotEqual(row[offset + cell - 1], " ")
                    if key == "task":
                        task_offset = offset
                    offset += cell + (len(separator) if index < len(columns) - 1 else 0)
                self.assertEqual(columns[:2], ["status", "task"])
                self.assertEqual(header.index("TASK"), task_offset)
                self.assertEqual(row.index("TASK-MARKER"), task_offset)
                self.assertEqual(offset, width - 1)
                self.assertLessEqual(len(row), width - 1)

    def test_narrow_tables_reserve_room_for_task(self):
        for width in (60, 80, 100, 120, 132, 160):
            with self.subTest(width=width):
                self.assertGreaterEqual(APP["column_widths"](width)["task"], 16)
                self.assertIn("TASK-MARKER", APP["agent_line"](self.agents[0], self.now, width)[1])
        self.assertNotIn("tools", APP["table_columns"](80))
        self.assertIn("model", APP["table_columns"](160))
        self.assertIn("tok", APP["table_columns"](132))

    def test_wide_tables_expand_fields_and_clarify_execution_mode(self):
        self.assertGreater(APP["column_widths"](240)["model"], APP["column_widths"](160)["model"])
        self.assertGreater(APP["column_widths"](240)["tools"], APP["column_widths"](160)["tools"])
        agent = self.agents[0]
        agent.mode = "background"
        agent.model = "claude-sonnet-example-model"
        header = APP["table_header"](240)
        row = APP["agent_line"](agent, self.now, 240)[1]
        self.assertIn("EXEC", header)
        self.assertNotIn("MOD ", header)
        self.assertIn("background", row)
        self.assertIn(agent.model, row)
        self.assertEqual(agent.mode, "background")
        agent.mode = "sync"
        self.assertIn("sync", APP["agent_line"](agent, self.now, 240)[1])

    def test_empty_fields_keep_visible_boundaries_between_alternating_rows(self):
        first, second = self.agents
        first.model = "example-model"
        first.tokens_known = True
        first.in_tokens, first.out_tokens = 10, 2
        second.model = ""
        second.tools["view"] = 10
        second.aiu, second.aiu_known = 4.5, True
        rows = [APP["agent_line"](agent, self.now, 240)[1] for agent in (first, second)]
        boundaries = [[i for i, char in enumerate(row) if char == "\u2502"] for row in rows]
        self.assertEqual(boundaries[0], boundaries[1])
        self.assertEqual(boundaries[0], [i for i, char in enumerate(APP["table_header"](240)) if char == "\u2502"])
        keys = APP["table_columns"](240)
        model_index = keys.index("model")
        cells = rows[1].split(APP["COLUMN_SEPARATOR"])
        self.assertEqual(cells[model_index], " " * APP["column_widths"](240)["model"])
        self.assertIn("10", cells[keys.index("tools")])
        self.assertEqual(cells[keys.index("tok")].strip(), "")
        self.assertEqual(cells[keys.index("aiu")].strip(), "4.50")
        first_cells = rows[0].split(APP["COLUMN_SEPARATOR"])
        self.assertEqual(first_cells[keys.index("tok")].strip(), "10/2")
        self.assertEqual(first_cells[keys.index("aiu")].strip(), "")

    def test_wide_and_combining_text_keeps_task_column_aligned(self):
        agent = self.agents[0]
        agent.agent_type = "\u7814\u7a76e\u0301"
        agent.model = "\u6a21\u578b-model"
        for width in (80, 132, 160, 240):
            header = APP["table_header"](width)
            _, row = APP["agent_line"](agent, self.now, width)
            self.assertEqual(APP["text_width"](row[:row.index("TASK-MARKER")]), header.index("TASK"))
            self.assertLessEqual(APP["text_width"](row), width - 1)

    def test_cell_clipping_and_padding(self):
        self.assertEqual(APP["text_width"]("e\u0301"), 1)
        self.assertEqual(APP["text_width"]("\u7814\u7a76"), 4)
        self.assertEqual(APP["clip"]("\u7814\u7a76", 3), "\u7814\u2026")
        self.assertEqual(APP["clip"]("e\u0301", 1), "e\u0301")
        self.assertEqual(APP["slice_cells"]("\u0301", 0), "")
        for text in ("short", "a long example " * 10, "\u7814\u7a76 e\u0301"):
            for width in (0, 1, 5, 80):
                self.assertEqual(APP["text_width"](APP["pad_line"](text, width)), width)

    def test_session_fields_align_despite_label_and_value_lengths(self):
        first = APP["session_header"](self.mon, "aaaaaaaa", [self.agents[0]], self.now, set(), 240)
        second = APP["session_header"](self.mon, "bbbbbbbb", self.agents * 5, self.now, set(), 240)
        for marker in ("[", " AIC"):
            self.assertEqual(first.index(marker), second.index(marker), marker)
        self.assertEqual([len(cell) for cell in first.split(APP["COLUMN_SEPARATOR"])],
                         [len(cell) for cell in second.split(APP["COLUMN_SEPARATOR"])])
        self.assertIn("1 active", first)
        self.assertIn("10 active", second)
        for header in (first, second):
            for removed in ("example-model", " tools", "turn", "Synthetic activity"):
                self.assertNotIn(removed, header)

    def test_task_tree_and_unicode_do_not_shift_following_metadata(self):
        agent = self.agents[0]
        agent.description = "\u7814\u7a76e\u0301 task with a longer description"
        prefix = "   \u2502  \u2514\u2500 "
        for width in (120, 132, 160, 240):
            header = APP["table_header"](width)
            row = APP["agent_line"](agent, self.now, width, prefix)[1]
            self.assertIn(prefix, row)
            started = APP["fmt_timestamp"](agent.started)
            self.assertEqual(APP["text_width"](row[:row.index(started)]), header.index("STARTED (local)"))
            self.assertEqual(APP["text_width"](row), width - 1)

    def test_reduced_session_header_keeps_attention_and_empty_session_state(self):
        state = self.mon.sessions["aaaaaaaa"]
        state["inputs"]["request"] = {"started": self.now}
        header = APP["session_header"](self.mon, "aaaaaaaa", [], self.now, set(), 120)
        self.assertIn("INPUT", header)
        self.assertIn("AIC", header)
        state["inputs"].clear()
        state["status"] = "idle"
        header = APP["session_header"](self.mon, "aaaaaaaa", [], self.now, set(), 120)
        self.assertIn("idle", header)
        self.assertNotIn("0/0", header)
        for width in (0, 1, 20, 40, 60, 80, 120, 200):
            header = APP["session_header"](self.mon, "aaaaaaaa", self.agents, self.now, set(), width)
            self.assertLessEqual(APP["text_width"](header), max(0, width - 1))

    def test_session_summary_counts_active_idle_and_finished_agents(self):
        self.agents[1].status = "idle"
        done = APP["Agent"]("finished", "aaaaaaaa", self.now)
        done.finish(self.now, "cancelled")
        header = APP["session_header"](self.mon, "aaaaaaaa", [*self.agents, done], self.now, set(), 200)
        self.assertIn("1 active", header)
        self.assertIn("1 idle", header)
        self.assertIn("1 finished", header)

    def test_selection_style_is_consistent_for_sessions_and_agents(self):
        import curses
        with patch("curses.color_pair", side_effect=lambda number: number << 8):
            for colors in (False, True):
                session = APP["table_row_style"]("session", "session", True, colors)
                agent = APP["table_row_style"]("agent", "running", True, colors)
                self.assertEqual(session, agent)
                self.assertTrue(session & curses.A_BOLD)
                self.assertEqual(bool(session & curses.A_REVERSE), not colors)
            normal = APP["table_row_style"]("session", "session", False, True)
            self.assertTrue(normal & curses.A_UNDERLINE)
            self.assertFalse(normal & curses.A_REVERSE)
            self.assertNotEqual(normal, session)

    def test_tui_paints_every_body_row_across_the_same_width(self):
        screen = Mock()
        screen.getmaxyx.return_value = (20, 160)
        screen.get_wch.side_effect = ["j", "j", "q"]
        with contextlib.ExitStack() as stack:
            for function in ("curs_set", "set_escdelay", "start_color", "use_default_colors", "init_pair"):
                stack.enter_context(patch(f"curses.{function}"))
            stack.enter_context(patch("curses.wrapper", side_effect=lambda callback: callback(screen)))
            stack.enter_context(patch("curses.has_colors", return_value=True))
            stack.enter_context(patch("curses.color_pair", side_effect=lambda number: number << 8))
            stack.enter_context(patch.object(self.mon, "refresh"))
            APP["run_tui"](self.mon, 1, check_updates=False)
        body = [call.args for call in screen.addnstr.call_args_list if 2 <= call.args[0] < 6]
        self.assertEqual(len(body), 12)
        for args in body:
            self.assertEqual(APP["text_width"](args[2]), 159)
            self.assertEqual(args[3], len(args[2]))


if __name__ == "__main__":
    unittest.main()
