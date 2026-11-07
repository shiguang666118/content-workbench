# 博主收录后台服务（2026-11-06）
#
# 「收录博主」按钮 → 这里：解析主页名片 → 调配置里的 account_batch.py
# 拉列表 / 下载转写 / 出作品表 → 收完调 DeepSeek（OpenAI 兼容接口）写账号拆解初稿。
#
# 配置读 <STATE_HOME>/account_jobs/config.json（不存在就用下面的 DEFAULTS），
# DeepSeek 的地址、模型名、密钥文件路径都在配置里，不写死；密钥只从文件读、不打印、不进代码和 Git。
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

STATE_HOME = Path(
    os.environ.get("RAYS_BRAIN_STATE", str(Path.home() / ".local/state/rays-brain"))
)
JOBS_HOME = STATE_HOME / "account_jobs"
JOBS_FILE = JOBS_HOME / "jobs.json"
CONFIG_FILE = JOBS_HOME / "config.json"

DEFAULTS = {
    "python": "",  # 空 = 用运行工作台的这个解释器
    "tool": "",  # 博主收录工具路径，见 README；不用就留空
    "tool_runs": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",
    "deepseek_api_key_file": "~/.config/deepseek/api_key",
}

SEC_RE = re.compile(r"(?:sec_uid=|/share/user/|/user/)(MS4wLjAB[\w-]+)")
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"

# 工具每跑完会打印一行机器可读的汇总：平台、ID、总数、已收、还缺、视频/图文、博主名
SUMMARY_RE = re.compile(
    r"SUMMARY platform=(\S+) id=(\S+) posts=(\d+) have=(\d+) missing=(\d+) "
    r"videos=(\d+) images=(\d+) nickname=(.*)"
)


def detect_platform(text: str) -> str:
    if re.search(r"(?:v\.douyin\.com|douyin\.com|iesdouyin\.com)", text or ""):
        return "douyin"
    if re.search(r"(?:xhslink\.cn|xhslink\.com|xiaohongshu\.com)", text or ""):
        return "xiaohongshu"
    return ""

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_QUEUE: list[str] = []
_WORKER: threading.Thread | None = None
_LOADED = False
_PATHS: dict[str, Path] = {
    "vault": Path("."),
    "video_dir": Path("."),
    "breakdown_dir": Path("."),
}


def configure(vault: Path, video_dir: Path, breakdown_dir: Path) -> None:
    _PATHS["vault"] = Path(vault)
    _PATHS["video_dir"] = Path(video_dir)
    _PATHS["breakdown_dir"] = Path(breakdown_dir)


def _config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.is_file():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not JOBS_FILE.is_file():
        return
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for job in data.get("jobs") or []:
        if isinstance(job, dict) and job.get("id"):
            _JOBS[str(job["id"])] = job


def _save() -> None:
    JOBS_HOME.mkdir(parents=True, exist_ok=True)
    payload = {
        "jobs": sorted(_JOBS.values(), key=lambda j: j.get("requested_at") or "", reverse=True)[:40]
    }
    tmp = JOBS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(JOBS_FILE)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|#^\[\]\n\r\t]+', " ", name or "").strip()[:40]
    return name or "博主"


def resolve_sec(url: str) -> str:
    """主页分享短链 / 主页网址 / sec_uid → sec_uid。认不出抛 ValueError。"""
    url = (url or "").strip()
    if not url:
        raise ValueError("没给主页链接")
    m = SEC_RE.search(url)
    if m:
        return m.group(1)
    if url.startswith("MS4wLjAB"):
        return url
    link = re.search(r"https?://\S+", url)
    if not link:
        raise ValueError(f"认不出主页链接：{url[:80]}")
    try:
        proc = subprocess.run(
            ["curl", "-sI", "-A", UA_MOBILE, link.group(0).rstrip("，。")],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"短链解析失败：{exc}")
    m = SEC_RE.search(proc.stdout or "")
    if not m:
        raise ValueError("短链没跳到博主主页（可能是单条视频链接，不是名片）")
    return m.group(1)


def _run_tool(args: list[str], on_line=None) -> int:
    """调 account_batch.py（子进程，Python 3.12）。on_line 逐行收到 stdout。返回退出码。"""
    cfg = _config()
    proc = subprocess.Popen(
        [cfg["python"] or sys.executable, "-X", "utf8", cfg["tool"], *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        if on_line:
            on_line(line)
    proc.wait()
    return proc.returncode


def feishu_cards(days: int = 3) -> list[dict]:
    """列飞书群最近的主页名片，给「收录博主」选。"""
    found: list[dict] = []
    def grab(line: str) -> None:
        m = re.search(r"^\s*(\d{2}-\d{2} \d{2}:\d{2})\s+(https?://v\.douyin\.com/\S+)", line)
        if m:
            found.append({"at": m.group(1), "url": m.group(2)})
    _run_tool(["--feishu", "--days", str(days)], on_line=grab)
    return found


def resolve_target(url: str) -> dict:
    """问工具要平台和 ID。--resolve-only 只解析链接，不调收费接口。"""
    found: dict = {}

    def grab(line: str) -> None:
        m = SUMMARY_RE.search(line)
        if m:
            found.update(platform=m.group(1), id=m.group(2))

    rc = _run_tool([url, "--resolve-only"], on_line=grab)
    if rc != 0 or not found:
        raise ValueError("认不出这个主页链接（支持抖音、小红书）")
    return found


def preview(url: str) -> dict:
    """拉作品列表，返回数量和时间预估，不下载。"""
    seen: dict = {}

    def grab(line: str) -> None:
        m = SUMMARY_RE.search(line)
        if m:
            seen.update(
                platform=m.group(1),
                sec=m.group(2),
                nickname=m.group(8).strip(),
                posts=int(m.group(3)),
                have=int(m.group(4)),
                missing=int(m.group(5)),
                videos=int(m.group(6)),
                images=int(m.group(7)),
            )

    _run_tool([url, "--list-only"], on_line=grab)
    if "posts" not in seen:
        raise ValueError("没拉到作品列表（TikHub 没返回或链接不对）")
    seen["estimate_minutes"] = max(1, round(seen["missing"] * 1.5))
    return seen


def _mode_flags(mode: dict) -> list[str]:
    flags: list[str] = []
    if not isinstance(mode, dict):
        return flags
    if mode.get("top"):
        flags += ["--top", str(int(mode["top"]))]
    elif mode.get("recent"):
        flags += ["--recent", str(int(mode["recent"]))]
    elif mode.get("max"):
        flags += ["--max", str(int(mode["max"]))]
    return flags


def start(url: str, mode: dict | None = None) -> dict:
    target = resolve_target(url)
    sec, platform = target["id"], target["platform"]
    job_id = sec[-12:]
    _load()
    with _LOCK:
        existing = _JOBS.get(job_id)
        if existing and existing.get("status") in ("queued", "running"):
            return dict(existing)
        _JOBS[job_id] = {
            "id": job_id,
            "sec_uid": sec,
            "platform": platform,
            "url": url,
            "mode": mode or {},
            "nickname": (existing or {}).get("nickname", ""),
            "status": "queued",
            "requested_at": _now(),
            "started_at": "",
            "finished_at": "",
            "posts": 0,
            "missing": 0,
            "done": 0,
            "failed": 0,
            "current": "",
            "list_path": "",
            "analysis_path": "",
            "error": "",
        }
        _QUEUE.append(job_id)
        _save()
    _ensure_worker()
    with _LOCK:
        return dict(_JOBS[job_id])


def _ensure_worker() -> None:
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    _WORKER = threading.Thread(target=_worker, name="account-batch", daemon=True)
    _WORKER.start()


def _worker() -> None:
    while True:
        with _LOCK:
            if not _QUEUE:
                return
            job_id = _QUEUE.pop(0)
            job = _JOBS.get(job_id)
            if not job:
                continue
            job["status"] = "running"
            job["started_at"] = _now()
            _save()
        try:
            _run_job(job)
        except Exception as exc:  # 整条任务失败
            with _LOCK:
                job["status"] = "failed"
                job["error"] = str(exc)[:300]
                job["finished_at"] = _now()
                _save()


def _run_job(job: dict) -> None:
    # 抖音的评论每次 $0.001，小红书每次 $0.01，小红书少拉几条
    comments = 5 if job.get("platform") == "douyin" else 3
    flags = [job["url"]] + _mode_flags(job.get("mode") or {}) + ["--comments", str(comments)]

    def on_line(line: str) -> None:
        with _LOCK:
            m = re.search(r"博主：(.*?)\s+粉丝 (\d+)", line)
            if m:
                job["nickname"] = job["nickname"] or m.group(1).strip()
            m = re.search(r"要新收：(\d+) 条", line)
            if m:
                job["missing"] = int(m.group(1))
            m = re.search(r"\[(\d+)/(\d+)\] 完成 (.*?)（", line)
            if m:
                job["done"] = int(m.group(1))
                job["current"] = m.group(3)[:40]
            m = re.search(r"\[(\d+)/(\d+)\] 失败", line)
            if m:
                job["failed"] = int(job.get("failed") or 0) + 1
            _save()

    rc = _run_tool(flags, on_line=on_line)
    with _LOCK:
        if rc != 0:
            job["status"] = "failed"
            job["error"] = f"收录工具退出码 {rc}"
            job["finished_at"] = _now()
            _save()
            return
        job["list_path"] = str(Path(_config()["tool_runs"]) / job["id"] / "list.md")
        _save()
    try:
        _write_analysis(job)
    except Exception as exc:
        with _LOCK:
            job["status"] = "done"
            job["analysis_error"] = str(exc)[:300]
            job["finished_at"] = _now()
            _save()
        return
    with _LOCK:
        job["status"] = "done"
        job["finished_at"] = _now()
        _save()


def _read_key() -> str:
    path = Path(_config()["deepseek_api_key_file"])
    return path.read_text(encoding="utf-8").strip()


def _deepseek_chat(messages: list[dict]) -> str:
    cfg = _config()
    url = cfg["deepseek_base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": cfg["deepseek_model"],
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 8000,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + _read_key(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"DeepSeek 接口返回 {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"连不上 DeepSeek 接口：{exc.reason}") from exc
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _card_texts(sec: str) -> list[str]:
    folder = _PATHS["video_dir"]
    out: list[str] = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f'account_sec_uid: "{sec}"' not in text:
            continue
        body = text.split("---", 2)[-1].strip()
        title_match = re.search(r"^# (.+)$", body, re.M)
        title = title_match.group(1).strip() if title_match else path.stem
        transcript = re.sub(r"^# .*$", "", body, flags=re.M).strip()
        out.append(f"### {title}\n{transcript[:1500]}")
    return out


def _platform_name(platform: str) -> str:
    return {"douyin": "抖音", "xiaohongshu": "小红书"}.get(platform or "", "抖音")


def _write_analysis(job: dict) -> None:
    cfg = _config()
    runs = Path(cfg["tool_runs"]) / job["id"]
    list_md = (
        (runs / "list.md").read_text(encoding="utf-8", errors="replace")
        if (runs / "list.md").is_file() else "（作品表未生成）"
    )
    comments_md = (
        (runs / "comments.md").read_text(encoding="utf-8", errors="replace")
        if (runs / "comments.md").is_file() else "（没拉评论）"
    )
    cards = _card_texts(job["sec_uid"])
    cards_block = "\n\n".join(cards[:20]) if cards else "（没找到来源卡）"
    nickname = job.get("nickname") or "博主"

    user_content = (
        f"博主：{nickname}\n\n"
        f"=== 作品列表（含数据）===\n{list_md[:20000]}\n\n"
        f"=== 高赞视频评论 ===\n{comments_md[:8000]}\n\n"
        f"=== 各条视频文字稿（自动转写，有错字）===\n{cards_block[:50000]}\n"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    draft = _deepseek_chat(messages)
    if not draft.strip():
        raise ValueError("DeepSeek 没返回内容")
    day = datetime.now().strftime("%Y-%m-%d")
    path = _PATHS["breakdown_dir"] / f"拆解_{_safe(nickname)}_{day}.md"
    if path.exists():  # 同一天重复收同一个号：不覆盖已有拆解，加时分
        path = _PATHS["breakdown_dir"] / f"拆解_{_safe(nickname)}_{day}_{datetime.now():%H%M}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 拆解：{nickname}（{_platform_name(job.get('platform', ''))}）{day}\n\n"
        f"> AI 初稿，待审。数据来自自动收录，引用和判断未经人工核对；画面、剪辑部分要人看画面墙（wall.jpg）补。\n\n"
        f"{draft.strip()}\n",
        encoding="utf-8",
    )
    with _LOCK:
        job["analysis_path"] = str(path)


def payload() -> dict:
    _load()
    with _LOCK:
        jobs = sorted(_JOBS.values(), key=lambda j: j.get("requested_at") or "", reverse=True)
        running = any(j.get("status") in ("queued", "running") for j in jobs)
        return {"running": running, "jobs": [dict(job) for job in jobs[:20]]}


_SYSTEM_PROMPT = """根据提供的作品列表、文字稿和评论，用 Markdown 汇总账号内容。注明资料范围，区分观察结果与推测。"""


if __name__ == "__main__":
    import sys
    print(json.dumps(preview(sys.argv[1]), ensure_ascii=False, indent=1))
