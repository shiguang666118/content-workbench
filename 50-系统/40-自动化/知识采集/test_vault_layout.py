"""共用配置与真实自定义目录流程（只使用临时库，不调用外部服务）。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
from vault_layout import DEFAULT_LAYOUT, load_layout


class LayoutTests(unittest.TestCase):
    def test_missing_config_keeps_defaults_and_partial_config_is_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "layout.json"
            with patch.dict(os.environ, {"RAYS_BRAIN_CONFIG": str(config)}):
                self.assertEqual(load_layout(), DEFAULT_LAYOUT)
                config.write_text('{"knowledge_dir": "知识"}', encoding="utf-8")
                layout = load_layout()
                self.assertEqual(layout["knowledge_dir"], "知识")
                self.assertEqual(layout["people_dir"], DEFAULT_LAYOUT["people_dir"])

    def test_bad_config_fails_before_any_vault_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "layout.json"
            invalid = [[], {"unknown": "x"}]
            invalid += [{"review_dir": value} for value in
                        ("", "/absolute", "~/home", "../outside", "a/../b",
                         "C:/outside", "C:outside", "\\\\host\\share", "a\\..\\b")]
            with patch.dict(os.environ, {"RAYS_BRAIN_CONFIG": str(config)}):
                for value in invalid:
                    with self.subTest(value=value):
                        config.write_text(json.dumps(value), encoding="utf-8")
                        with self.assertRaises(SystemExit):
                            load_layout()

    def test_example_has_every_default(self):
        example = json.loads((AUTOMATION / "知识仪表盘/config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example, DEFAULT_LAYOUT)

    def test_custom_layout_ingest_maps_health_and_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            layout = {key: "自定义/" + value for key, value in DEFAULT_LAYOUT.items()}
            layout["people_dir"] = "自定义/20-知识/人物"
            layout["products_dir"] = "自定义/20-知识/产品"
            layout["viewpoints_dir"] = "自定义/20-知识/观点"
            config.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
            env = {**os.environ, "RAYS_BRAIN": str(root / "vault"),
                   "RAYS_BRAIN_STATE": str(root / "state"), "RAYS_BRAIN_CONFIG": str(config)}
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", CUSTOM_FLOW, str(AUTOMATION)],
                env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("custom layout flow OK", result.stdout)


CUSTOM_FLOW = r'''
import os, re, sys
from pathlib import Path
from datetime import datetime, timezone
automation = Path(sys.argv[1])
sys.path[:0] = [str(automation), str(automation / "知识采集"),
                str(automation / "发布归档"), str(automation / "知识仪表盘")]
import knowledge_ingest as ingest
import knowledge_health as health
import topic_map_candidates as candidates
import map_digest as digest
import record_published as record
import server
import fake_vault
from vault_layout import DEFAULT_LAYOUT, load_layout
layout = load_layout()
assert all(module.LAYOUT == layout for module in (ingest, health, candidates, digest, record, server))
vault = Path(os.environ["RAYS_BRAIN"])
vault.mkdir()
ingest.initialize()
assert ingest.X_DIR == vault / layout["x_bookmarks_dir"] and ingest.X_DIR.is_dir()
assert ingest.REVIEW_DIR == vault / layout["review_dir"] and ingest.REVIEW_DIR.is_dir()
assert ingest.entity_root_for_type("人物") == vault / layout["people_dir"]
assert ingest.entity_root_for_type("产品") == vault / layout["products_dir"]
assert ingest.knowledge_destination({"suggested_kind": "观点"}) == vault / layout["viewpoints_dir"]
assert ingest.KIND_BY_FOLDER["观点"] == "viewpoint"
assert ingest.knowledge_origin(layout["weread_dir"] + "/书.md") == "weread"
source = layout["web_clips_dir"] + "/来源.md"
assert health.declared_source_paths('---\nsource_file: "' + source + '"\n---\n') == [source]
# One genuine note and map; both inventories and generated links must use the new root.
note = vault / layout["viewpoints_dir"] / "验证观点.md"
note.parent.mkdir(parents=True)
note.write_text('---\nkind: viewpoint\nstatus: seed\nsource_file: "' + source + '"\n---\n\n# 验证观点\n', encoding="utf-8")
assert "验证观点" in candidates.knowledge_inventory(vault)["notes"]
now = datetime(2026, 10, 27, tzinfo=timezone.utc)
candidates.refresh_topic_map_candidates(vault, ingest.TOPIC_MAP_CANDIDATE_STATE, now=now)
digest.refresh_weekly_map_digest(vault, ingest.MAP_DIGEST_STATE, now=now)
assert (vault / layout["topic_map_candidates_file"]).is_file()
assert (vault / layout["map_digest_file"]).is_file()
latest = vault / layout["map_digest_weekly_dir"] / digest.LATEST_REPORT_NAME
assert layout["map_digest_weekly_dir"] in latest.read_text(encoding="utf-8")
# Reuse existing publication fixtures, relocating files and their references in one pass.
fixture = vault.parent / "fixture"
fake_vault.build(fixture)
mapping = {old: layout[key] for key, old in DEFAULT_LAYOUT.items()}
pattern = re.compile("|".join(re.escape(old) for old in sorted(mapping, key=len, reverse=True)))
def translate(value):
    return pattern.sub(lambda match: mapping[match.group()], value)
for original in fixture.rglob("*"):
    if original.is_file():
        target = vault / translate(original.relative_to(fixture).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        if original.suffix in {".md", ".json", ".base"}:
            target.write_text(translate(original.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            target.write_bytes(original.read_bytes())
article = layout["published_articles_dir"] + "/2026-07-19-测试长文.md"
record.record(article_arg=article, platform="x", url="https://x.com/tester/status/2079091643693863273",
              published_at="2026-07-19T23:30:50-07:00", now=now, dry_run=False)
assert list((vault / layout["feedback_dir"]).glob("*.md"))
assert list((vault / layout["archived_article_drafts_dir"]).rglob("*.md"))
assert list((vault / layout["archived_writing_tasks_dir"]).rglob("*.md"))
assert not (vault / "10-创作").exists()
assert not (vault / "20-知识").exists()
assert not (vault / "40-发布").exists()
print("custom layout flow OK")
'''


if __name__ == "__main__":
    unittest.main()
