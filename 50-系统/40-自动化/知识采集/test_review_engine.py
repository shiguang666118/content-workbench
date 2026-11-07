"""本机加（10-28）：素材卡审核可在 Codex 和 agy（Antigravity CLI）之间切换。"""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import knowledge_ingest as ingest


def agy_stdout(status: str = "SUCCESS", output: object = None, error: str = "") -> str:
    lines = [
        {"event": "init", "conversation_id": "c", "init": {"model": "gemini-3.8-flash-medium"}},
        {"event": "result", "result": {
            "status": status, "structured_output": output, "error": error,
            "duration_seconds": 12.3, "usage": {"input_tokens": 9000, "output_tokens": 800, "thinking_tokens": 300},
        }},
    ]
    return "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"


class ReviewEngineTest(unittest.TestCase):
    def test_default_engine_is_codex(self) -> None:
        with patch.object(ingest, "run_codex", return_value={"reviews": []}) as codex, \
                patch.object(ingest, "run_agy") as agy:
            self.assertEqual(ingest.run_reviewer("提示", {}), {"reviews": []})
        codex.assert_called_once()
        agy.assert_not_called()

    def test_agy_engine_sends_stream_json_and_reads_structured_output(self) -> None:
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"], seen["kwargs"] = cmd, kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout=agy_stdout(output={"reviews": [{"id": "x"}]}), stderr="")

        with patch.object(ingest.subprocess, "run", fake_run), patch.object(ingest, "log"):
            result = ingest.run_reviewer("中文提示", {"review_engine": "agy", "agy_model": "gemini-3.8-flash-high"})
        self.assertEqual(result, {"reviews": [{"id": "x"}]})
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-3.8-flash-high")
        self.assertIn("--sandbox", cmd)
        self.assertEqual(cmd[cmd.index("--json-schema") + 1], str(ingest.SCHEMA_FILE))
        sent = json.loads(seen["kwargs"]["input"])
        self.assertEqual(sent, {"event": "user", "message": {"role": "user", "content": "中文提示"}})
        self.assertTrue(seen["kwargs"]["input"].isascii())  # 中文转义成 ASCII，不受 Windows 管道编码影响

    def test_agy_failure_raises(self) -> None:
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 3, stdout=agy_stdout("ERROR", None, "quota exhausted"), stderr="")

        with patch.object(ingest.subprocess, "run", fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                ingest.run_reviewer("提示", {"review_engine": "agy"})
        self.assertIn("quota exhausted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
