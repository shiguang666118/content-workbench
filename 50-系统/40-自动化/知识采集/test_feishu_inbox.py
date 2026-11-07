"""本机加：feishu_inbox 模块及 sync 飞书分支的单元测试（完全离线、不联网、不调用真实飞书 API）。"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import feishu_inbox  # noqa: E402

SPEC = importlib.util.spec_from_file_location("knowledge_ingest", HERE / "knowledge_ingest.py")
assert SPEC and SPEC.loader
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)


class TestFeishuInbox(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_home = Path(self.temp_dir.name) / "state"
        self.state_home.mkdir(parents=True, exist_ok=True)
        self.vault = Path(self.temp_dir.name) / "vault"
        self.vault.mkdir(parents=True, exist_ok=True)
        self.inbox_file = self.vault / "链接收件箱.md"
        self.inbox_file.write_text("# 链接收件箱\n\n", encoding="utf-8")

        self.orig_state_home = feishu_inbox.STATE_HOME
        self.orig_token_file = feishu_inbox.TOKEN_FILE
        feishu_inbox.STATE_HOME = self.state_home
        feishu_inbox.TOKEN_FILE = self.state_home / "feishu-token.json"
        # 本机改：凭证的回退位置、采集状态文件和日志也指到临时目录，
        # 否则测试会读到真实凭证，并往真实状态目录写假数据
        self.isolation = [
            patch.object(feishu_inbox, "DEFAULT_STATE_HOME", self.state_home),
            patch.object(ingest, "STATE_FILE", self.state_home / "state.json"),
            patch.object(ingest, "LOG_DIR", self.state_home / "logs"),
        ]
        for item in self.isolation:
            item.start()

    def tearDown(self) -> None:
        for item in self.isolation:
            item.stop()
        feishu_inbox.STATE_HOME = self.orig_state_home
        feishu_inbox.TOKEN_FILE = self.orig_token_file
        self.temp_dir.cleanup()

    def test_credentials_missing_or_empty_silent_skip(self) -> None:
        # 当凭据文件不存在或 app_id / app_secret 为空时，抛出 FeishuSkipped
        with patch.object(feishu_inbox, "DEFAULT_STATE_HOME", self.state_home):
            with self.assertRaises(feishu_inbox.FeishuSkipped):
                feishu_inbox.load_credentials()

            # 存在文件但字段为空
            creds_file = self.state_home / "feishu.json"
            creds_file.write_text(json.dumps({"app_id": "", "app_secret": ""}), encoding="utf-8")
            with self.assertRaises(feishu_inbox.FeishuSkipped):
                feishu_inbox.load_credentials()

    def test_token_cache_reuse(self) -> None:
        # token 缓存未过期时不应重新请求网络
        token_data = {
            "token": "cached_access_token_123",
            "expires_at": 9999999999.0,
        }
        feishu_inbox.TOKEN_FILE.write_text(json.dumps(token_data), encoding="utf-8")

        creds = {"app_id": "test_id", "app_secret": "test_secret"}
        with patch("feishu_inbox._request_json") as mock_req:
            token = feishu_inbox.get_access_token(creds)
            self.assertEqual(token, "cached_access_token_123")
            mock_req.assert_not_called()

    def test_extract_urls_from_text_and_post(self) -> None:
        # text 消息类型
        text_content = json.dumps({"text": "推荐这个视频 https://v.douyin.com/abc/ 看看"})
        urls_text = feishu_inbox._extract_urls(text_content)
        self.assertEqual(urls_text, ["https://v.douyin.com/abc/"])

        # post 富文本消息类型（飞书 API 返回 content 时通常是 raw json 字符串，其中可能出现转义的 \/）
        post_content = r'{"title": "富文本分享", "content": [[{"tag": "a", "href": "https:\/\/mp.weixin.qq.com\/s\/xyz123"}]]}'
        urls_post = feishu_inbox._extract_urls(post_content)
        self.assertEqual(urls_post, ["https://mp.weixin.qq.com/s/xyz123"])

    def test_pull_messages_skip_bot_and_dedup(self) -> None:
        # 机器人自己发的消息跳过；同一条消息拉两次只处理一次
        state: dict = {"feishu": {"seen_ids": [], "last_message_ts": 0}}
        chat_id = "oc_test_chat_id"

        mock_messages_page = {
            "code": 0,
            "data": {
                "has_more": False,
                "items": [
                    {
                        "message_id": "om_bot_1",
                        "create_time": "1730000001000",
                        "sender": {"sender_type": "app"},
                        "body": {"content": json.dumps({"text": "https://example.com/bot"})},
                    },
                    {
                        "message_id": "om_user_1",
                        "create_time": "1730000002000",
                        "sender": {"sender_type": "user"},
                        "body": {"content": json.dumps({"text": "用户发了链接 https://v.douyin.com/test1/"})},
                    },
                ],
            },
        }

        with patch("feishu_inbox._api_get", return_value=mock_messages_page):
            entries, pending = feishu_inbox.pull_new_messages({}, "dummy_token", state, chat_id)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["url"], "https://v.douyin.com/test1/")
            self.assertEqual(state["feishu"], {"seen_ids": [], "last_message_ts": 0})
            self.assertIn("om_user_1", pending["seen_ids"])
            self.assertNotIn("om_bot_1", pending["seen_ids"])
            state["feishu"].update(pending)

            # 再次拉取相同的消息，去重后应返回空
            entries_again, _ = feishu_inbox.pull_new_messages({}, "dummy_token", state, chat_id)
            self.assertEqual(len(entries_again), 0)

    def test_first_run_uses_three_days_and_subsequent_uses_cursor(self) -> None:
        state: dict = {}
        chat_id = "oc_test_chat_id"

        captured_params: list[dict] = []

        def fake_api_get(endpoint: str, token: str, params: dict | None = None) -> dict:
            if params:
                captured_params.append(dict(params))
            return {
                "code": 0,
                "data": {
                    "has_more": False,
                    "items": [
                        {
                            "message_id": "om_1",
                            "create_time": "1730000005000",
                            "sender": {"sender_type": "user"},
                            "body": {"content": json.dumps({"text": "https://example.com/1"})},
                        }
                    ],
                },
            }

        with patch("feishu_inbox._api_get", side_effect=fake_api_get):
            # 第一次运行
            _, pending = feishu_inbox.pull_new_messages({}, "dummy_token", state, chat_id)
            state["feishu"] = pending
            self.assertEqual(len(captured_params), 1)
            first_start_time = int(captured_params[0]["start_time"])

            # 第二次运行：游标为 1730000005，减去 60 秒重叠
            feishu_inbox.pull_new_messages({}, "dummy_token", state, chat_id)
            self.assertEqual(len(captured_params), 2)
            second_start_time = int(captured_params[1]["start_time"])
            self.assertEqual(second_start_time, 1730000005 - 60)

    def test_append_to_inbox_formatting(self) -> None:
        entries = [
            {"note": "抖音视频测试", "url": "https://v.douyin.com/abc/", "time": "2026-10-27 21:05"}
        ]
        feishu_inbox.append_to_inbox(entries, self.inbox_file)

        content = self.inbox_file.read_text(encoding="utf-8")
        self.assertIn("- 飞书 2026-10-27 21:05 抖音视频测试 https://v.douyin.com/abc/", content)

    def test_收件箱写入失败不提交状态(self) -> None:
        state = {"feishu": {"seen_ids": ["旧消息"], "last_message_ts": 100}}
        page = {"data": {"items": [{"message_id": "新消息", "create_time": "200000",
                "sender": {"sender_type": "user"},
                "body": {"content": json.dumps({"text": "https://example.com/1"})}}]}}
        with patch.object(feishu_inbox, "load_credentials", return_value={}), \
             patch.object(feishu_inbox, "get_access_token", return_value="测试令牌"), \
             patch.object(feishu_inbox, "find_chat_id", return_value="群"), \
             patch.object(feishu_inbox, "_api_get", return_value=page), \
             patch.object(feishu_inbox, "append_to_inbox", side_effect=OSError("写入失败")):
            with self.assertRaises(OSError):
                feishu_inbox.sync_feishu_inbox(state, self.inbox_file)
        self.assertEqual(state["feishu"], {"seen_ids": ["旧消息"], "last_message_ts": 100})

    def test_成功写入后提交包含纯文字消息的状态(self) -> None:
        state = {"feishu": {"seen_ids": ["旧消息"], "last_message_ts": 100}}
        items = [
            {"message_id": "链接", "create_time": "200000", "sender": {"sender_type": "user"},
             "body": {"content": json.dumps({"text": "https://example.com/1"})}},
            {"message_id": "纯文字", "create_time": "201000", "sender": {"sender_type": "user"},
             "body": {"content": json.dumps({"text": "没有链接"})}},
        ]
        with patch.object(feishu_inbox, "load_credentials", return_value={}), \
             patch.object(feishu_inbox, "get_access_token", return_value="测试令牌"), \
             patch.object(feishu_inbox, "find_chat_id", return_value="群"), \
             patch.object(feishu_inbox, "_api_get", return_value={"data": {"items": items}}):
            self.assertEqual(feishu_inbox.sync_feishu_inbox(state, self.inbox_file), 1)
        self.assertIn("https://example.com/1", self.inbox_file.read_text(encoding="utf-8"))
        self.assertEqual(state["feishu"], {"seen_ids": ["旧消息", "链接", "纯文字"], "last_message_ts": 201})

    def test_只有纯文字时仍提交状态(self) -> None:
        state = {"feishu": {"seen_ids": [], "last_message_ts": 0}}
        items = [{"message_id": "文字", "create_time": "200000", "sender": {"sender_type": "user"},
                  "body": {"content": json.dumps({"text": "没有链接"})}}]
        with patch.object(feishu_inbox, "load_credentials", return_value={}), \
             patch.object(feishu_inbox, "get_access_token", return_value="测试令牌"), \
             patch.object(feishu_inbox, "find_chat_id", return_value="群"), \
             patch.object(feishu_inbox, "_api_get", return_value={"data": {"items": items}}):
            self.assertEqual(feishu_inbox.sync_feishu_inbox(state, self.inbox_file), 0)
        self.assertEqual(state["feishu"], {"seen_ids": ["文字"], "last_message_ts": 200})

    def test_消息去重列表只保留最近五百条(self) -> None:
        state = {"feishu": {"seen_ids": [str(i) for i in range(500)], "last_message_ts": 100}}
        items = [{"message_id": "新消息", "create_time": "200000", "sender": {"sender_type": "user"},
                  "body": {"content": json.dumps({"text": "纯文字"})}}]
        with patch.object(feishu_inbox, "_api_get", return_value={"data": {"items": items}}):
            _, pending = feishu_inbox.pull_new_messages({}, "测试令牌", state, "群")
        self.assertEqual(len(pending["seen_ids"]), 500)
        self.assertEqual(pending["seen_ids"][0], "1")
        self.assertEqual(pending["seen_ids"][-1], "新消息")
        self.assertEqual(state["feishu"]["seen_ids"][0], "0")

    def test_警告传给采集日志且不输出凭证(self) -> None:
        secret = "测试secret内容"
        token = "测试token内容"
        logs: list[str] = []
        creds = {"app_id": "测试", "app_secret": secret}
        state = ingest.default_state()
        with patch.object(feishu_inbox, "load_credentials", return_value=creds), \
             patch.object(feishu_inbox, "_get_access_token_new", side_effect=RuntimeError(secret)), \
             patch.object(feishu_inbox, "_get_access_token_legacy", return_value=(token, 7200)), \
             patch.object(feishu_inbox, "find_chat_id", return_value="群"), \
             patch.object(feishu_inbox, "_api_get", return_value={"data": {"items": []}}), \
             patch.object(ingest, "LINK_INBOX", self.inbox_file), \
             patch.object(ingest, "sync_mobile", return_value=0), \
             patch.object(ingest, "discover_web_clips", return_value=0), \
             patch.object(ingest, "discover_weread_cards", return_value=0), \
             patch.object(ingest, "log", side_effect=logs.append):
            ingest.sync_only(state, {"x_enabled": False, "feishu_enabled": True})
        self.assertTrue(any("飞书新版凭证接口失败，尝试旧版" in line for line in logs))
        self.assertNotIn(secret, "\n".join(logs))
        self.assertNotIn(token, "\n".join(logs))

    def test_抖音分享口令清理且保留普通备注(self) -> None:
        texts = [
            "1.23 复制打开抖音，看看【示例作者甲的作品】示例作品标题 # 短视频 # ... :2pm ABC:/ 01/01 A@b.CD 备注 测试 https://v.douyin.com/example/",
            "备注 测试 https://mp.weixin.qq.com/s/xxx",
        ]
        items = [{"message_id": str(i), "create_time": "200000", "sender": {"sender_type": "user"},
                  "body": {"content": json.dumps({"text": text})}} for i, text in enumerate(texts)]
        with patch.object(feishu_inbox, "_api_get", return_value={"data": {"items": items}}):
            entries, _ = feishu_inbox.pull_new_messages({}, "测试令牌", {}, "群")
        self.assertNotIn("复制打开抖音", entries[0]["note"])
        self.assertNotIn("A@b.CD", entries[0]["note"])
        self.assertIn("示例作品标题", entries[0]["note"])
        self.assertIn("备注 测试", entries[0]["note"])
        self.assertEqual(entries[1]["note"], "备注 测试")

    def test_抖音口令换了顺序也能清理_单个日期不误删(self) -> None:
        # 测试另一种分享格式：没有「复制打开抖音」前缀，口令顺序也不同
        note = feishu_inbox._strip_douyin_share_code(
            "【示例作者乙的作品】另一条示例标题 # a... c@d.ef :4pm 06/15 XYZ:/"
        )
        self.assertEqual(note, "【示例作者乙的作品】另一条示例标题 # a...")
        # 只有一个像日期的词，不当口令删
        self.assertEqual(feishu_inbox._strip_douyin_share_code("下周 06/15 再看"), "下周 06/15 再看")

    def test_sync_only_handles_feishu_error_gracefully(self) -> None:
        # 当飞书拉取发生错误时，不抛出异常，不影响其他流程，且日志/错误中不泄漏 secret
        secret_value = "SUPER_SECRET_VALUE_DO_NOT_LEAK"
        state = ingest.default_state()
        config = {"x_enabled": False, "feishu_enabled": True}

        with patch("feishu_inbox.sync_feishu_inbox", side_effect=RuntimeError(f"Network error with secret {secret_value}")):
            with patch.object(ingest, "LINK_INBOX", self.inbox_file):
                with patch.object(ingest, "sync_mobile", return_value=0) as mock_mobile, \
                     patch.object(ingest, "discover_web_clips", return_value=0), \
                     patch.object(ingest, "discover_weread_cards", return_value=0):
                    logs_captured: list[str] = []
                    with patch.object(ingest, "log", side_effect=logs_captured.append):
                        res = ingest.sync_only(state, config)
                        self.assertEqual(res["feishu"], 0)
                        mock_mobile.assert_called_once()
                        # 检查健康状态记录为 degraded
                        health = state.get("source_health", {}).get("feishu", {})
                        self.assertEqual(health.get("status"), "degraded")
                        # 验证 secret 没在日志中直接泄露
                        for line in logs_captured:
                            self.assertNotIn(secret_value, line)


if __name__ == "__main__":
    unittest.main()
