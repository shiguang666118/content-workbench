"""平台适配的真实进程测试；不访问网络或正式知识库。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from file_lock import lock_exclusive
import knowledge_health as health
import knowledge_ingest as ingest


class PlatformTests(unittest.TestCase):
    def test_lock_contention_close_release_and_blocking_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "process.lock"
            handle = path.open("a+")
            lock_exclusive(handle.fileno())
            child = (
                "import sys; from file_lock import lock_exclusive; "
                "h=open(sys.argv[1], 'a+'); "
                "lock_exclusive(h.fileno(), blocking=sys.argv[2]=='yes'); "
                "print('acquired', flush=True)"
            )
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            cmd = [sys.executable, "-X", "utf8", "-c", child, str(path)]
            try:
                result = subprocess.run(cmd + ["no"], env=env, capture_output=True,
                                        text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("BlockingIOError", result.stderr)
                with subprocess.Popen(cmd + ["yes"], env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) as waiting:
                    try:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            waiting.communicate(timeout=0.3)
                        handle.close()
                        stdout, stderr = waiting.communicate(timeout=5)
                        self.assertEqual(waiting.returncode, 0, stderr)
                        self.assertEqual(stdout.strip(), "acquired")
                    finally:
                        if waiting.poll() is None:
                            waiting.kill()
                            waiting.wait()
            finally:
                handle.close()
            with path.open("a+") as reopened:
                lock_exclusive(reopened.fileno(), blocking=False)

    @unittest.skipUnless(os.name == "nt", "Windows 专用分支")
    def test_windows_mac_checks_are_not_applicable(self):
        with patch.object(health.subprocess, "run", side_effect=AssertionError("不可调用 Mac 命令")):
            self.assertEqual(health.icloud_status(), "不适用")
            self.assertEqual(health.fmt_automation_job(health.launch_status()), "不适用")
        with patch.object(ingest.os, "fstat", side_effect=AssertionError("不应检查日志")):
            ingest.rotate_stdout_log()

    def test_process_probe_preserves_current_process(self):
        self.assertTrue(health.process_is_running(os.getpid()))
        self.assertFalse(health.process_is_running(-1))


if __name__ == "__main__":
    unittest.main()
