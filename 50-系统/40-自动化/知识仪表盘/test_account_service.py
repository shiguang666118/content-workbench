# 博主收录服务的单元测试（2026-11-06）
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import account_service as svc


class ResolveTests(unittest.TestCase):
    def test_sec_uid_passthrough(self) -> None:
        self.assertEqual(svc.resolve_sec("MS4wLjABabc123"), "MS4wLjABabc123")

    def test_profile_url_with_sec_uid(self) -> None:
        url = "https://www.iesdouyin.com/share/user/MS4wLjABabc123def456"
        self.assertEqual(svc.resolve_sec(url), "MS4wLjABabc123def456")

    def test_short_link_resolves_via_curl(self) -> None:
        proc = mock.Mock()
        proc.stdout = "HTTP/2 302\nlocation: https://www.iesdouyin.com/share/user/MS4wLjABxyz\n"
        with mock.patch("account_service.subprocess.run", return_value=proc):
            self.assertEqual(svc.resolve_sec("https://v.douyin.com/AbCdEfG/"), "MS4wLjABxyz")

    def test_short_link_not_profile(self) -> None:
        proc = mock.Mock()
        proc.stdout = "HTTP/2 302\nlocation: https://www.iesdouyin.com/share/video/123\n"
        with mock.patch("account_service.subprocess.run", return_value=proc):
            with self.assertRaises(ValueError):
                svc.resolve_sec("https://v.douyin.com/AbCdEfG/")


class ModeTests(unittest.TestCase):
    def test_mode_flags(self) -> None:
        self.assertEqual(svc._mode_flags({}), [])
        self.assertEqual(svc._mode_flags({"top": 10}), ["--top", "10"])
        self.assertEqual(svc._mode_flags({"recent": 30}), ["--recent", "30"])
        self.assertEqual(svc._mode_flags({"max": 8}), ["--max", "8"])
        # top 优先于 recent 优先于 max
        self.assertEqual(svc._mode_flags({"top": 5, "recent": 9}), ["--top", "5"])


class PlatformTests(unittest.TestCase):
    def test_detect_platform(self) -> None:
        self.assertEqual(svc.detect_platform("https://v.douyin.com/abc/"), "douyin")
        self.assertEqual(svc.detect_platform("https://xhslink.cn/o/example"), "xiaohongshu")
        self.assertEqual(svc.detect_platform("https://www.xiaohongshu.com/user/profile/bbbbbbbbbbbbbbbbbbbbbbbb"), "xiaohongshu")
        self.assertEqual(svc.detect_platform("https://example.com/x"), "")


class ResolveTargetTests(unittest.TestCase):
    def test_resolve_target_reads_summary(self) -> None:
        def fake_run_tool(args, on_line=None):
            on_line("SUMMARY platform=xiaohongshu id=bbbbbbbbbbbbbbbbbbbbbbbb posts=0 have=0 missing=0 videos=0 images=0 nickname=")
            return 0
        with mock.patch.object(svc, "_run_tool", side_effect=fake_run_tool):
            out = svc.resolve_target("https://xhslink.cn/o/example")
        self.assertEqual(out["platform"], "xiaohongshu")
        self.assertEqual(out["id"], "bbbbbbbbbbbbbbbbbbbbbbbb")


class PreviewTests(unittest.TestCase):
    def test_preview_parses_summary(self) -> None:
        def fake_run_tool(args, on_line=None):
            on_line("SUMMARY platform=douyin id=MS4wLjABsec posts=31 have=31 missing=0 videos=31 images=0 nickname=示例作者甲")
            return 0
        with mock.patch.object(svc, "_run_tool", side_effect=fake_run_tool):
            out = svc.preview("https://v.douyin.com/xxx/")
        self.assertEqual(out["nickname"], "示例作者甲")
        self.assertEqual(out["posts"], 31)
        self.assertEqual(out["missing"], 0)
        self.assertEqual(out["estimate_minutes"], 1)

    def test_preview_xhs_counts_and_estimate(self) -> None:
        def fake_run_tool(args, on_line=None):
            on_line("SUMMARY platform=xiaohongshu id=bbbbbbbbbbbbbbbbbbbbbbbb posts=45 have=6 missing=39 videos=35 images=4 nickname=示例作者乙")
            return 0
        with mock.patch.object(svc, "_run_tool", side_effect=fake_run_tool):
            out = svc.preview("https://xhslink.cn/o/example")
        self.assertEqual(out["platform"], "xiaohongshu")
        self.assertEqual((out["videos"], out["images"]), (35, 4))
        self.assertEqual(out["missing"], 39)
        self.assertEqual(out["estimate_minutes"], 58)


class CardTextTests(unittest.TestCase):
    def test_card_texts_filters_by_sec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.md").write_text(
                '---\naccount_sec_uid: "MS4wLjABsec"\ntitle: "甲"\n---\n\n# 甲\n这是正文甲\n', encoding="utf-8"
            )
            (folder / "b.md").write_text(
                '---\naccount_sec_uid: "MS4wLjABother"\ntitle: "乙"\n---\n\n# 乙\n这是正文乙\n', encoding="utf-8"
            )
            svc.configure(Path(tmp), folder, Path(tmp))
            texts = svc._card_texts("MS4wLjABsec")
            self.assertEqual(len(texts), 1)
            self.assertIn("这是正文甲", texts[0])
            self.assertNotIn("正文乙", texts[0])


class ConfigTests(unittest.TestCase):
    def test_config_file_overrides_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_file = Path(tmp) / "config.json"
            cfg_file.write_text(json.dumps({"deepseek_model": "deepseek-reasoner"}), encoding="utf-8")
            with mock.patch.object(svc, "CONFIG_FILE", cfg_file):
                cfg = svc._config()
            self.assertEqual(cfg["deepseek_model"], "deepseek-reasoner")
            self.assertEqual(cfg["deepseek_base_url"], svc.DEFAULTS["deepseek_base_url"])


if __name__ == "__main__":
    unittest.main()
