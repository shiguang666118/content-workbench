"""本机加：公众号抓取和 sync_mobile 公众号分支的测试（不联网）。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import wechat_article  # noqa: E402

SPEC = importlib.util.spec_from_file_location("knowledge_ingest", HERE / "knowledge_ingest.py")
assert SPEC and SPEC.loader
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)

PAGE = """<html><head>
<meta property="og:title" content="Obsidian + Claude Code：搭建个人知识库" />
<meta property="og:article:author" content="作者甲" />
<script>
var nickname = htmlDecode("智能思辨录");
var msg_desc = htmlDecode("讨论为什么要建立自己的知识库");
var ct = "1774710394";
var create_time = "1774710394" * 1;
</script></head><body>
<div id="page"><div class="rich_media_content" id="js_content" style="visibility: hidden;">
<section><p>前一周跟大家分享了较多 Claude Code 的实践和感受，这一篇讲知识库为什么要放在本地，以及怎么开始。</p></section>
<section><h2>▍ 怎么开始？</h2>
<p><img data-src="https://mmbiz.qpic.cn/a/640?wx_fmt=png" /></p>
<section/>
<ul><li>摒弃云端知识库</li><li>降低维护成本</li></ul>
<script>var x = "不该出现";</script>
<p>Obsidian 是一款基于本地 Markdown 文件的双向链接笔记软件。</p></section>
</div><div id="js_tags">页尾推荐，不该出现</div></div></body></html>"""


class ParseTests(unittest.TestCase):
    def test_is_wechat(self) -> None:
        self.assertTrue(wechat_article.is_wechat("https://mp.weixin.qq.com/s/AbCdEf"))
        self.assertFalse(wechat_article.is_wechat("https://weixin.sogou.com/link?url=x"))

    def test_parse_article(self) -> None:
        info = wechat_article.parse(PAGE)
        self.assertEqual(info["title"], "Obsidian + Claude Code：搭建个人知识库")
        self.assertEqual(info["account"], "智能思辨录")
        self.assertEqual(info["author"], "作者甲")
        self.assertTrue(info["published_at"].startswith("2026-03-28"))
        self.assertEqual(info["image_count"], 1)
        body = info["body"]
        self.assertIn("## ▍ 怎么开始？", body)
        self.assertIn("- 摒弃云端知识库", body)
        self.assertIn("![图1](https://mmbiz.qpic.cn/a/640?wx_fmt=png)", body)
        self.assertTrue(body.rstrip().endswith("双向链接笔记软件。"))
        self.assertNotIn("不该出现", body)

    def test_blocked_page_raises(self) -> None:
        with self.assertRaises(wechat_article.WechatError) as ctx:
            wechat_article.parse("<html><body>当前环境异常，完成验证后即可继续访问。</body></html>")
        self.assertIn("验证", str(ctx.exception))

    def test_page_without_body_raises(self) -> None:
        with self.assertRaises(wechat_article.WechatError):
            wechat_article.parse('<html><div id="js_content"><p>短</p></div></html>')


class SyncMobileWechatTests(unittest.TestCase):
    def run_sync(self, vault: Path, state: dict, fetch) -> int:
        with (
            patch.object(ingest, "VAULT", vault),
            patch.object(ingest, "WEB_DIR", vault / "web"),
            patch.object(ingest, "VIDEO_DIR", vault / "video"),
            patch.object(ingest, "mobile_lines", return_value=["https://mp.weixin.qq.com/s/AbCdEf"]),
            patch.object(ingest, "log"),
            patch.object(ingest, "fetch_url", side_effect=AssertionError("公众号不该走原版网页抓取")),
            patch.object(ingest.wechat_article, "download", side_effect=fetch),
        ):
            return ingest.sync_mobile(state, {})

    def test_wechat_link_goes_to_web_dir_with_meta(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            (vault / "web").mkdir()
            (vault / "video").mkdir()
            state = ingest.default_state()
            self.assertEqual(self.run_sync(vault, state, lambda url: PAGE), 1)
            cards = list((vault / "web").glob("*.md"))
            self.assertEqual(len(cards), 1)
            text = cards[0].read_text(encoding="utf-8")
            self.assertIn('content_type: "wechat-article"', text)
            self.assertIn('account: "智能思辨录"', text)
            self.assertIn("原链接：https://mp.weixin.qq.com/s/AbCdEf", text)
            self.assertIn("- 公众号：智能思辨录", text)

    def test_wechat_failure_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            (vault / "web").mkdir()
            (vault / "video").mkdir()
            state = ingest.default_state()

            def blocked(url: str) -> str:
                return "<html>环境异常</html>"

            self.assertEqual(self.run_sync(vault, state, blocked), 0)
            self.assertEqual(list((vault / "web").glob("*.md")), [])
            self.assertEqual(self.run_sync(vault, state, lambda url: PAGE), 1)
            self.assertEqual(state["video_attempts"], {})


if __name__ == "__main__":
    unittest.main()
