# 内容工作台

一个跑在你自己电脑上的自媒体内容工作台：看板、视频文案、素材卡甄选、博主收录、选题洞察，都在一个本地网页里。所有数据都是你文件夹里的 Markdown，没有数据库、不上云。

本项目 fork 自开源的 **rays-brain-kit**（MIT，Copyright 2026 Ray），在它的基础上做了本机适配和功能扩展，详见 `NOTICE.md`。

## 需要什么

- **Python 3.10 以上**（Windows 安装时勾选 Add to PATH）
- 其他都是可选：TikHub key（选题洞察、博主收录）、Codex CLI（素材卡审核）、飞书应用（飞书收录）、本地转写环境（视频转文字）

## 快速开始

1. 双击 `启动工作台.bat`
2. 浏览器自动打开 http://localhost:8771

第一次打开是空看板，因为 `vault/` 里还没有内容。往 `vault/` 里写 Markdown，或者用可选功能往里收。

## 目录

| 路径 | 是什么 |
|---|---|
| `50-系统/` | 程序代码 |
| `vault/` | 你的知识库（所有内容都在这里，也可以换成你自己的文件夹） |
| `config.json` | 目录映射：程序按它去 vault 里找各个文件夹 |
| `state/` | 运行时状态（自动生成，不进 Git） |

## 可选功能怎么配

### 博主收录（抖音 / 小红书主页 → 全部作品）

需要另一个开源工具：`account_batch.py`（见 [douyin-account-collector](https://github.com/shiguang666118/douyin-account-collector)）。下载后，把 `50-系统/40-自动化/知识仪表盘/account_service.py` 里 `DEFAULTS` 的 `tool` 改成那个工具的路径（`python` 留空就用当前解释器）。另外需要 TikHub key。

### 选题洞察（爆款雷达）

1. 去 TikHub 注册、充值、拿 API key
2. 新建 `state/tikhub.json`：
   ```json
   {"api_key": "你的key", "base_url": "https://api.tikhub.io"}
   ```
3. `50-系统/40-自动化/爆款雷达/radar_config.json` 里换成你想盯的关键词（仓库里放的是示例，复制一份改）

### 素材卡审核

需要装 Codex CLI，然后在 `50-系统/40-自动化/知识采集/config.json` 里把 `review_enabled` 改成 `true`，`codex_path` 指向 codex 可执行文件。

### 飞书收录（把链接发到飞书群自动收）

需要建一个飞书自建应用，拿 `app_id` / `app_secret`，新建 `state/feishu.json`：
```json
{"app_id": "xxx", "app_secret": "xxx", "chat_name": "你的群名"}
```
再把 `知识采集/config.json` 里 `feishu_enabled` 改成 `true`。

### 视频转文字

需要本地有 whisperX 或 FunASR 的字幕脚本，然后在 `知识采集/config.json` 里填 `brief_python`（解释器）和 `brief_script`（字幕脚本路径）。

## 隐私

- 这个包里**没有任何密钥、没有个人信息**；密钥只从 `state/` 目录读，`state/` 默认不进 Git
- 所有数据都在你自己的 `vault/` 文件夹里，程序不联网上传（除了你主动启用的 TikHub / DeepSeek / 飞书接口）

## 许可

MIT。基于 rays-brain-kit（MIT, Copyright (c) 2026 Ray），见 `NOTICE.md`。
