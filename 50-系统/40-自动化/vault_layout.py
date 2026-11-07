"""仪表盘与知识采集共用的 vault 相对路径配置。"""
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

DEFAULT_LAYOUT = {
    "review_dir": "10-创作/10-灵感/10-待评估/剪藏复核",
    "topics_dir": "10-创作/10-灵感/20-候选选题",
    "topic_reserve_dir": "10-创作/10-灵感/90-选题储备",
    "inbox_file": "10-创作/10-灵感/inbox.md",
    "link_inbox_file": "30-资料/00-待抓取/链接收件箱.md",
    "create_dir": "10-创作",
    "writing_tasks_dir": "10-创作/20-写作任务",
    "drafts_dir": "10-创作/30-文章草稿",
    "oral_scripts_dir": "10-创作/25-口播草稿",
    "knowledge_dir": "20-知识",
    "sources_dir": "30-资料",
    "published_dir": "40-发布",
    "feedback_dir": "40-发布/00-内容反馈",
    "archive_dir": "90-归档",
    "x_bookmarks_dir": "30-资料/30-X书签",
    "web_clips_dir": "30-资料/40-网页剪藏",
    "video_clips_dir": "30-资料/45-视频剪藏",
    "weread_dir": "30-资料/50-读书划线",
    "person_corpus_dir": "30-资料/70-人物语料",
    "cleanup_dir": "90-归档/90-待清理",
    "review_records_dir": "90-归档/20-审核记录/剪藏复核",
    "legacy_review_dir": "10-创作/10-灵感/10-待评估/存量知识复核",
    "concepts_dir": "20-知识/10-概念",
    "people_dir": "20-知识/20-人物与组织",
    "products_dir": "20-知识/25-产品与模型",
    "questions_dir": "20-知识/30-问题",
    "viewpoints_dir": "20-知识/40-观点",
    "cases_dir": "20-知识/50-案例",
    "methods_dir": "20-知识/60-方法",
    "maps_dir": "20-知识/70-知识地图",
    "metadata_dir": "20-知识/90-元数据",
    "map_index_file": "20-知识/70-知识地图/知识地图索引.md",
    "people_index_file": "20-知识/70-知识地图/人物与思想索引.md",
    "products_index_file": "20-知识/70-知识地图/产品与模型索引.md",
    "topic_map_candidates_file": "00-入口/10-工作台/主题地图候选.md",
    "map_digest_file": "00-入口/10-工作台/知识地图整理.md",
    "map_digest_weekly_dir": "00-入口/20-日报/知识地图整理",
    "health_daily_dir": "00-入口/20-日报/知识库健康日报",
    "health_weekly_dir": "00-入口/20-日报/知识库周报",
    "system_reports_archive_dir": "90-归档/40-系统报告",
    "knowledge_workbench_file": "00-入口/10-工作台/知识工作台.md",
    "creation_workbench_file": "00-入口/10-工作台/创作工作台.md",
    "published_articles_dir": "40-发布/10-X长文",
    "published_posts_dir": "40-发布/20-X短帖",
    "published_videos_dir": "40-发布/50-口播视频",
    "archived_writing_tasks_dir": "90-归档/30-创作记录/旧成稿包",
    "archived_article_drafts_dir": "90-归档/30-创作记录/旧文章草稿",
    "archived_oral_drafts_dir": "90-归档/30-创作记录/旧口播草稿",
    "current_focus_file": "70-思考/当前关注.md",
    "principles_file": "70-思考/原则.md"
}


def load_layout() -> dict[str, str]:
    """vault 目录布局，可用 config.json（或 RAYS_BRAIN_CONFIG 指定的文件）覆盖。
    审核卡的状态值与五个选项是管线协议，不属于布局配置。"""
    path = Path(os.environ.get("RAYS_BRAIN_CONFIG", str(Path(__file__).resolve().parent / "知识仪表盘" / "config.json")))
    layout = dict(DEFAULT_LAYOUT)
    if not path.exists():
        return layout
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"配置文件无法解析：{path}（{exc}）")
    if not isinstance(loaded, dict):
        raise SystemExit(f"配置文件必须是 JSON 对象：{path}")
    unknown = sorted(set(loaded) - set(DEFAULT_LAYOUT))
    if unknown:
        raise SystemExit(
            f"配置文件包含未知键：{'、'.join(unknown)}。可用键：{'、'.join(sorted(DEFAULT_LAYOUT))}"
        )
    for key, value in loaded.items():
        raw = str(value).strip()
        if (not raw or raw.startswith(("/", "~", "\\"))
                or PureWindowsPath(raw).drive
                or ".." in PurePosixPath(raw).parts
                or ".." in PureWindowsPath(raw).parts):
            raise SystemExit(f"配置 {key} 必须是 vault 内的相对路径，现在是：{raw!r}")
        layout[key] = raw.strip("/")
    return layout
