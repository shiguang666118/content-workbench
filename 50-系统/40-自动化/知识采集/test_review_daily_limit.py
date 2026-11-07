"""本机加：素材卡每日上限（review_daily_max）的测试，不调 Codex。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

SPEC = importlib.util.spec_from_file_location("knowledge_ingest", HERE / "knowledge_ingest.py")
assert SPEC and SPEC.loader
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)


class ReviewDailyLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp.name)
        web = self.vault / "web"
        web.mkdir()
        self.state = ingest.default_state()
        for i in range(3):
            path = web / f"clip-{i}.md"
            path.write_text(
                f"---\ntitle: \"资料{i}\"\ncapture_id: \"mobile:{i}\"\nprocessing_status: unprocessed\n---\n\n# 资料{i}\n\n正文{i}\n",
                encoding="utf-8",
            )
            self.state["pending_sources"].append(f"web/clip-{i}.md")
        self.calls: list[str] = []

        def fake_codex(prompt: str, config: dict) -> dict:
            self.calls.append(prompt)
            raise RuntimeError("模拟失败：不真的调 Codex")

        self.patches = [
            patch.object(ingest, "VAULT", self.vault),
            patch.object(ingest, "run_codex", side_effect=fake_codex),
            patch.object(ingest, "build_prompt", side_effect=lambda items, config: items[0]["id"]),
        ]
        for p in self.patches:
            p.start()
        self.logs: list[str] = []
        self.log_patch = patch.object(ingest, "log", side_effect=self.logs.append)
        self.log_patch.start()

    def tearDown(self) -> None:
        self.log_patch.stop()
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_daily_limit_counts_attempts_and_stops(self) -> None:
        config = {"review_batch_size": 3, "review_daily_max": 2}
        ingest.review_pending(self.state, config)
        self.assertEqual(len(self.calls), 2)  # 失败的调用也算次数
        self.assertEqual(self.state["review_daily"]["count"], 2)
        ingest.review_pending(self.state, config)
        ingest.review_pending(self.state, config)
        self.assertEqual(len(self.calls), 2)  # 当天到上限后不再调用
        limit_logs = [line for line in self.logs if line.startswith("review daily limit reached")]
        self.assertEqual(len(limit_logs), 1)  # 一天只提醒一次
        self.assertEqual(len(self.state["pending_sources"]), 3)  # 没审的留在队列

    def test_new_day_resets_count(self) -> None:
        config = {"review_batch_size": 3, "review_daily_max": 2}
        self.state["review_daily"] = {"date": "2000-01-01", "count": 99, "limit_logged": True}
        ingest.review_pending(self.state, config)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.state["review_daily"]["date"], datetime.now().strftime("%Y-%m-%d"))

    def test_no_limit_keeps_original_behavior(self) -> None:
        ingest.review_pending(self.state, {"review_batch_size": 3})
        self.assertEqual(len(self.calls), 3)


if __name__ == "__main__":
    unittest.main()
