#!/usr/bin/env python3
"""本机加：公众号文章抓取。

原版 fetch_url 有 2MB 上限，公众号页面塞了大量脚本（实测 3.6MB）会直接报 curl 63，正文一个字都拿不到。
这里单独抓：不截断页面，只取 id="js_content" 里的正文，标题、公众号名、发布时间从页面变量里读。
不需要登录、不花钱；被删除、违规、"环境异常"验证页都当失败处理。
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
MAX_BYTES = 20_000_000
BLOCKED_MARKERS = {
    "环境异常": "微信要求验证（环境异常），需要在浏览器里打开一次",
    "该内容已被发布者删除": "文章已被作者删除",
    "此内容因违规无法查看": "文章因违规无法查看",
    "此内容发送失败无法查看": "文章无法查看",
}


class WechatError(RuntimeError):
    pass


def is_wechat(url: str) -> bool:
    return urllib.parse.urlparse(url).netloc.lower() == "mp.weixin.qq.com"


def download(url: str) -> str:
    curl = shutil.which("curl") or "curl"
    proc = subprocess.run(
        [curl, "-fsSL", "--max-time", "40", "--max-filesize", str(MAX_BYTES), "-A", UA, url],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise WechatError(proc.stderr.decode(errors="replace").strip() or "curl failed")
    return proc.stdout.decode("utf-8", errors="replace")


def page_var(source: str, name: str) -> str:
    patterns = [
        rf"var\s+{name}\s*=\s*htmlDecode\(\s*\"((?:[^\"\\]|\\.)*)\"",
        rf"var\s+{name}\s*=\s*'((?:[^'\\]|\\.)*)'",
        rf"var\s+{name}\s*=\s*\"((?:[^\"\\]|\\.)*)\"",
    ]
    for pattern in patterns:
        match = re.search(pattern, source)
        if match:
            return html.unescape(match.group(1).replace("\\x26", "&").replace("\\'", "'")).strip()
    return ""


def meta_content(source: str, prop: str) -> str:
    match = re.search(rf'<meta[^>]+property="{prop}"[^>]+content="([^"]*)"', source)
    return html.unescape(match.group(1)).strip() if match else ""


class ContentExtractor(HTMLParser):
    """只收 id="js_content" 那个元素里的文字和图片，段落、标题、列表项各占一行。"""

    BLOCK = {"p", "section", "div", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "tr", "br"}
    SKIP = {"script", "style", "svg", "noscript"}
    VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "param", "track"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip = 0
        self.parts: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if not self.depth:
            if attr.get("id") == "js_content":
                self.depth = 1
            return
        if tag not in self.VOID:
            self.depth += 1
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3", "h4"}:
            self.parts.append("## ")
        if tag == "li":
            self.parts.append("- ")
        if tag == "img":
            src = attr.get("data-src") or attr.get("src") or ""
            if src.startswith("http"):
                self.images.append(src)
                self.parts.append(f"\n![图{len(self.images)}]({src})\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.depth or tag in self.VOID:
            return
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and not self.skip:
            value = re.sub(r"[ \t\r\f\v ]+", " ", data)
            if value.strip():
                self.parts.append(value)

    def text(self) -> str:
        value = "".join(self.parts)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n(## |- )\n", "\n", value)  # 空标题、空列表项
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def parse(source: str) -> dict[str, Any]:
    for marker, reason in BLOCKED_MARKERS.items():
        if marker in source and 'id="js_content"' not in source:
            raise WechatError(reason)
    extractor = ContentExtractor()
    extractor.feed(source)
    body = extractor.text()
    if len(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body).strip()) < 50:
        raise WechatError("没找到正文（页面结构可能变了，或是纯图片/视频文章）")
    title = meta_content(source, "og:title") or page_var(source, "msg_title")
    created = page_var(source, "ct")
    if not created.isdigit():
        match = re.search(r'var\s+create_time\s*=\s*"(\d+)"', source)
        created = match.group(1) if match else ""
    published = ""
    if str(created).isdigit():
        published = datetime.fromtimestamp(int(created), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    return {
        "title": title,
        "account": page_var(source, "nickname"),
        "author": meta_content(source, "og:article:author"),
        "published_at": published,
        "desc": page_var(source, "msg_desc") or meta_content(source, "og:description"),
        "body": body,
        "image_count": len(extractor.images),
    }


def fetch(url: str) -> dict[str, Any]:
    """返回 title、body、content_type、meta（写进来源卡 frontmatter 的附加字段）。"""
    info = parse(download(url))
    header = [
        f"- 公众号：{info['account'] or '未知'}" + (f"　作者：{info['author']}" if info["author"] else ""),
        f"- 发布：{info['published_at'][:16].replace('T', ' ') or '未知'}　图片：{info['image_count']} 张",
        "",
    ]
    if info["desc"]:
        header += [f"> 摘要：{info['desc']}", ""]
    meta = {
        "platform": "wechat",
        "account": info["account"],
        "author": info["author"],
        "source_published_at": info["published_at"],
    }
    return {
        "title": info["title"],
        "body": "\n".join(header + ["## 正文", "", info["body"]]),
        "content_type": "wechat-article",
        "meta": {key: value for key, value in meta.items() if value},
    }
