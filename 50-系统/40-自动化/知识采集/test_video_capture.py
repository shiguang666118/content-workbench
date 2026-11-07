"""本机加：video_capture 和 sync_mobile 视频分支的测试（不联网、不调 TikHub、不转写）。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import video_capture  # noqa: E402

SPEC = importlib.util.spec_from_file_location("knowledge_ingest", HERE / "knowledge_ingest.py")
assert SPEC and SPEC.loader
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)

DOUYIN_RESPONSE = {
    "code": 200,
    "data": {
        "aweme_detail": {
            "aweme_id": "1000000000000000001",
            "desc": "这个示例展示了如何整理活动资料 #AI #agent",
            "create_time": 1792558925,
            "author": {"nickname": "测试作者甲"},
            "statistics": {"digg_count": 41, "comment_count": 3, "collect_count": 19, "share_count": 2},
            "video": {
                "duration": 438400,
                "play_addr_h264": {"url_list": ["https://a.example/1.mp4", "https://a.example/2.mp4"]},
                "play_addr": {"url_list": ["https://a.example/1.mp4", "https://a.example/3.mp4"]},
            },
        }
    },
}

XHS_RESPONSE = {
    "code": 200,
    "data": {
        "code": 0,
        "success": True,
        "data": [
            {"id": "aaaaaaaaaaaaaaaaaaaaaaaa", "title": "推荐笔记", "type": "video"},
            {
                "id": "cccccccccccccccccccccccc",
                "title": "笔记示例",
                "type": "video",
                "desc": "正文 #AI工具[话题]#",
                "time": 1791040898,
                "user": {"nickname": "测试作者乙"},
                "liked_count": 82,
                "comments_count": 209,
                "collected_count": 31,
                "shared_count": 8,
                "video_info_v2": {
                    "capa": {"duration": 95},
                    "media": {"stream": {"h264": [{"master_url": "http://x.example/a.mp4", "backup_urls": ["http://x.example/b.mp4"]}]}},
                },
            },
        ],
    },
}


class ParseTests(unittest.TestCase):
    def test_detect_platform(self) -> None:
        self.assertEqual(video_capture.detect_platform("https://v.douyin.com/example/"), "douyin")
        self.assertEqual(video_capture.detect_platform("https://www.douyin.com/video/1"), "douyin")
        self.assertEqual(video_capture.detect_platform("http://xhslink.com/a/abc"), "xiaohongshu")
        self.assertEqual(video_capture.detect_platform("https://www.xiaohongshu.com/explore/6ac1"), "xiaohongshu")
        self.assertEqual(video_capture.detect_platform("https://mp.weixin.qq.com/s/abc"), "")

    def test_parse_douyin(self) -> None:
        info = video_capture.parse_douyin(DOUYIN_RESPONSE)
        self.assertEqual(info["author"], "测试作者甲")
        self.assertEqual(info["duration_seconds"], 438)
        self.assertEqual(info["title"], "这个示例展示了如何整理活动资料")
        self.assertEqual(info["video_urls"], ["https://a.example/1.mp4", "https://a.example/2.mp4", "https://a.example/3.mp4"])
        self.assertEqual(video_capture.stats_text(info["stats"]), "41/3/19/2")

    def test_douyin_without_item_raises(self) -> None:
        with self.assertRaises(video_capture.VideoCaptureError):
            video_capture.parse_douyin({"code": 200, "data": {"filter_list": [{"reason": "8"}]}})

    def test_xhs_picks_item_matching_note_id(self) -> None:
        item = video_capture.pick_xhs_item(XHS_RESPONSE, "cccccccccccccccccccccccc")
        info = video_capture.parse_xhs(item)
        self.assertEqual(info["author"], "测试作者乙")
        self.assertEqual(info["video_urls"], ["http://x.example/a.mp4", "http://x.example/b.mp4"])
        self.assertEqual(info["duration_seconds"], 95)

    def test_xhs_without_matching_note_raises_instead_of_taking_recommendation(self) -> None:
        with self.assertRaises(video_capture.VideoCaptureError):
            video_capture.pick_xhs_item(XHS_RESPONSE, "6ad9d914000000002c0242e0")

    def test_funasr_srt_falls_back_when_unavailable_or_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "video.mp4"
            video.write_bytes(b"x")
            self.assertFalse(video_capture.run_funasr_srt(video, {"asr_engine": "whisper"}))
            self.assertFalse(video_capture.run_funasr_srt(video, {"funasr_python": str(Path(temp) / "没有.exe")}))

            def fake_run(cmd, **kwargs):
                Path(cmd[cmd.index("--out") + 1]).write_text("1\n00:00:00,000 --> 00:00:01,000\n你好。\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            def broken_run(cmd, **kwargs):
                Path(cmd[cmd.index("--out") + 1]).write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 1)

            exe = Path(temp) / "python.exe"
            exe.write_bytes(b"")
            config = {"funasr_python": str(exe), "funasr_script": str(video)}
            with patch.object(video_capture.subprocess, "run", broken_run):
                self.assertFalse(video_capture.run_funasr_srt(video, config))
                self.assertFalse(video.with_suffix(".srt").exists())  # 失败不留半截字幕，交给 Whisper
            with patch.object(video_capture.subprocess, "run", fake_run):
                self.assertTrue(video_capture.run_funasr_srt(video, config))
                self.assertIn("你好", video.with_suffix(".srt").read_text(encoding="utf-8"))

            def silent_run(cmd, **kwargs):
                Path(cmd[cmd.index("--out") + 1]).write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(video_capture.subprocess, "run", silent_run):
                self.assertTrue(video_capture.run_funasr_srt(video, config))  # 没人说话：空字幕照用，不退回 Whisper
                self.assertTrue(video.with_suffix(".srt").exists())

    def test_asr_hallucinations_are_removed(self) -> None:
        self.assertEqual(video_capture.clean_asr_text("使用简体中文和标点，"), "")
        self.assertEqual(video_capture.clean_asr_text("MINGPAOCANADAM，INGPAOTORONTO，"), "")
        self.assertEqual(video_capture.clean_asr_text("我让100个AI传一句话，"), "我让100个AI传一句话，")
        self.assertEqual(video_capture.clean_asr_text("使用简体中文和标点，大家好欢迎观看"), "大家好欢迎观看")
        brief = "\n".join([
            "# 标题", "", "- 字数：约 63", "", "## 开头 8 秒原文（钩子）", "", "使用简体中文和标点", "",
            "## 带时间稿（每 10 秒一段；自动识别，可能有错字）", "",
            "[00:03] 使用简体中文和标点，", "[00:45] MINGPAOCANADAM，INGPAOTORONTO，", "[01:00] 真的有人说话。",
            "", "## 画面墙", "", "图",
        ])
        out = video_capture.transcript_from_brief(brief)
        self.assertNotIn("使用简体中文", out)
        self.assertNotIn("MINGPAO", out)
        self.assertIn("[01:00] 真的有人说话。", out)
        self.assertIn("【没识别到口播】", out)

    def test_xhs_image_endpoint_note_list_is_unwrapped(self) -> None:
        note = {"id": "6ada1f60000000002c0183de", "type": "normal", "title": "试过了 充满人味儿", "desc": "正文",
                "user": {"nickname": "momo"}, "time": 1792679776, "liked_count": 2852}
        response = {"data": {"data": [{"note_list": [note], "user": {"nickname": "momo"}, "comment_list": []}]}}
        info = video_capture.parse_xhs(video_capture.pick_xhs_item(response, "6ada1f60000000002c0183de"))
        self.assertEqual((info["title"], info["author"], info["video_urls"]), ("试过了 充满人味儿", "momo", []))

    def test_xhs_image_note_falls_back_to_image_endpoint(self) -> None:
        calls: list[str] = []
        image_only = json.loads(json.dumps(XHS_RESPONSE))
        image_only["data"]["data"][1]["video_info_v2"] = {}
        image_only["data"]["data"][1]["type"] = "normal"

        def fake_call(endpoint: str, params: dict, tikhub: dict) -> dict:
            calls.append(endpoint)
            self.assertEqual(params, {"note_id": "cccccccccccccccccccccccc"})
            return image_only

        with tempfile.TemporaryDirectory() as temp, patch.object(video_capture, "COST_LOG", Path(temp) / "cost.jsonl"):
            info, cost = video_capture.fetch_info(
                "https://www.xiaohongshu.com/explore/cccccccccccccccccccccccc?xsec_token=x", {}, fake_call
            )
            logged = (Path(temp) / "cost.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls, [video_capture.XHS_VIDEO_NOTE, video_capture.XHS_IMAGE_NOTE])
        self.assertEqual(info["video_urls"], [])
        self.assertAlmostEqual(cost, 0.02)
        self.assertEqual(len(logged), 2)

    def test_title_takes_leading_phrase(self) -> None:
        desc = "这个示例展示了如何整理活动资料 这是一段用于测试标题提取的示例文字"
        self.assertEqual(video_capture.first_line_title(desc), "这个示例展示了如何整理活动资料")
        self.assertEqual(video_capture.first_line_title("一句很长的话没有空格" * 5), ("一句很长的话没有空格" * 3))
        # 短标题示例：中文后面的空格太靠前，不截
        self.assertEqual(video_capture.first_line_title("示例标题 用 A 工具整理 #示例"), "示例标题 用 A 工具整理")

    def test_file_safe_drops_emoji(self) -> None:
        self.assertEqual(video_capture.file_safe("发现搞💰天赋的7️⃣个提示词"), "发现搞天赋的7个提示词")

    def test_transcript_from_brief_drops_title_and_wall(self) -> None:
        text = "# 标题\n\n- 时长：1 秒\n\n## 带时间稿\n\n[00:00] 你好\n\n## 画面墙\n\nwall.jpg：说明\n"
        self.assertEqual(video_capture.transcript_from_brief(text), "- 时长：1 秒\n\n## 带时间稿\n\n[00:00] 你好")


class SyncMobileVideoTests(unittest.TestCase):
    def run_sync(self, vault: Path, state: dict, capture) -> int:
        with (
            patch.object(ingest, "VAULT", vault),
            patch.object(ingest, "WEB_DIR", vault / "web"),
            patch.object(ingest, "VIDEO_DIR", vault / "video"),
            patch.object(ingest, "mobile_lines", return_value=["https://v.douyin.com/abc/"]),
            patch.object(ingest, "log"),
            patch.object(ingest, "fetch_url", side_effect=AssertionError("视频链接不该走网页抓取")),
            patch.object(ingest.video_capture, "capture", side_effect=capture),
        ):
            return ingest.sync_mobile(state, {})

    def test_video_link_goes_to_video_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            (vault / "web").mkdir()
            (vault / "video").mkdir()

            def capture(url, folder, name_for, vault_arg, config):
                return {
                    "title": "测试视频", "body": "## 文字稿\n\n[00:00] 你好", "content_type": "video-transcript",
                    "meta": {"platform": "douyin", "author": "某人"}, "cost_usd": 0.001, "stem": name_for("测试视频"),
                }

            state = ingest.default_state()
            self.assertEqual(self.run_sync(vault, state, capture), 1)
            cards = list((vault / "video").glob("*.md"))
            self.assertEqual(len(cards), 1)
            text = cards[0].read_text(encoding="utf-8")
            self.assertIn('platform: "douyin"', text)
            self.assertIn("原链接：https://v.douyin.com/abc/", text)
            self.assertIn("[00:00] 你好", text)
            self.assertEqual(list((vault / "web").glob("*.md")), [])
            self.assertIn("video/" + cards[0].name, state["pending_sources"])

    def test_failure_retries_then_writes_failed_card(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            (vault / "web").mkdir()
            (vault / "video").mkdir()

            def capture(*args, **kwargs):
                raise video_capture.VideoCaptureError("下载失败")

            state = ingest.default_state()
            self.assertEqual(self.run_sync(vault, state, capture), 0)
            self.assertEqual(self.run_sync(vault, state, capture), 0)
            self.assertEqual(state["mobile_line_hashes"], [])
            self.assertEqual(self.run_sync(vault, state, capture), 1)
            text = next((vault / "video").glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("fetch_status: failed", text)
            self.assertEqual(len(state["mobile_line_hashes"]), 1)
            self.assertEqual(state["video_attempts"], {})


if __name__ == "__main__":
    unittest.main()
