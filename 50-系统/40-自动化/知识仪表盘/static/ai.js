// 内容中枢前端（本机改版，2026-10-27）
// 只用工作台已有的接口：/api/dashboard、/api/radar、/api/search、/api/note/transition、
// /api/capture、/api/radar/action、/api/radar/run、/api/events。不新增后端逻辑。
// 例外（10-28）：视频文案页用的 /api/videos、/api/video 是在 server.py 里新加的（只读）。
// CSP 不允许内联样式：HTML 字符串里不写 style，动态值一律用 el.style.setProperty。
"use strict";

const ACTIVITY = { name: "「AI替我说」活动", start: "2026-10-16", end: "2026-11-30" };
// 「和我们相关」= 命中当前搜索关键词（11-02 改：原来写死一组词，现在跟着「搜索关键词」面板走）
function ourKeywords() { const k = state.radar && state.radar.keywords; return k ? [...k.douyin, ...k.xiaohongshu] : []; }
const SEARCH_TIPS = ["搜：都江堰", "搜：skill", "搜：口播稿", "搜：复盘", "搜：对标拆解", "搜：西门"];
const CAPTURE_TIPS = ["刚刷到一个好选题……", "粘贴一个链接，会进链接收件箱", "评论区有人问……", "下一条可以试试……"];
const WRITING = new Set(["active", "researching", "drafting", "drafted", "draft-complete", "validated"]);
const STATUS_PILL = {
  active: ["已立项", "gray"], researching: ["调研中", "gray"], drafting: ["起草中", "gray"],
  drafted: ["等你看稿", "amber"], "draft-complete": ["成片待看", "violet"], validated: ["待发布", "green"],
  recording: ["已定稿", "blue"], candidate: ["候选", "gray"], pending: ["待复盘", "red"],
};
const COLS = [
  { key: "cand", name: "候选选题", hint: "7 天没推进就收起", cls: "c-cand" },
  { key: "writing", name: "写作中", hint: "写稿、做片、等你看", cls: "c-writing" },
  { key: "recording", name: "待录制", hint: "稿子定了，就差录", cls: "c-recording" },
  { key: "published", name: "已发布", hint: "发了就建复盘卡", cls: "c-published" },
  { key: "review", name: "待复盘", hint: "24 小时、7 天各一次", cls: "c-review" },
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { dash: null, radar: null, cols: null, radarFilter: "ours", radarSort: "mult" };

// ---------- 数据 ----------
async function getJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `请求失败 ${res.status}`);
  return res.json();
}
async function postJSON(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `操作失败 ${res.status}`);
  return data;
}
async function load() {
  try {
    const [dash, radar] = await Promise.all([getJSON("/api/dashboard"), getJSON("/api/radar").catch(() => null)]);
    state.dash = dash; state.radar = radar;
    state.cols = buildCols(dash);
    renderAll();
    pollTranscripts();
  } catch (e) { toast(e.message, true); }
}
function buildCols(d) {
  const tasks = d.writing_tasks || [];
  return {
    cand: d.topic_candidates || [],
    writing: tasks.filter((t) => WRITING.has(t.status)),
    recording: tasks.filter((t) => t.status === "recording"),
    published: d.published || [],
    review: (d.feedback || []).filter((f) => f.pending),
  };
}

// ---------- 小工具 ----------
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const md = (iso) => (iso || "").slice(5, 10).replace(/^0/, "");
function dueText(due) {
  if (!due) return ["", ""];
  const t = today();
  if (due < t) return ["已过期", "red"];
  if (due === t) return ["今天截止", "red"];
  return [`${md(due)} 截止`, "amber"];
}
function shortTitle(s, n = 12) { s = String(s || "").replace(/^口播稿：/, "").replace(/[（(][^）)]*[）)]/g, "").replace(/^用\s*/, "").trim(); return s.length > n ? s.slice(0, n) + "…" : s; }
const cut = (s, n) => { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; };
function fmtNum(n) { if (n == null) return "–"; return n >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, "") + "万" : n.toLocaleString("en-US"); }
let toastTimer;
function toast(msg, err) { const t = $("toast"); t.textContent = msg; t.classList.toggle("err", !!err); t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 3200); }

// ---------- 渲染 ----------
function renderAll() {
  const c = state.cols;
  const boardCount = Object.values(c).reduce((a, l) => a + l.length, 0);
  $("navBoard").textContent = boardCount;
  $("navRadar").textContent = state.radar ? radarList("all").length : "–";
  $("navReview").textContent = (state.dash.reviews || []).length;
  $("bellDot").hidden = !c.review.some((f) => f.due_at && f.due_at <= today());
  renderToday(); renderBoard(); renderRadarAll(); renderReview();
  requestAnimationFrame(moveNavPill);
}

function renderToday() {
  const c = state.cols;
  $("todayDate").textContent = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  // 今天先做哪一件：到期复盘 > 待录制 > 等你看的稿 > 挑候选
  const due = c.review.filter((f) => f.due_at && f.due_at <= today());
  const queue = [];
  due.forEach((f) => queue.push({ title: f.title, desc: `${dueText(f.due_at)[0]}。截一张平台后台的数据图，复盘就能写完。`, href: f.obsidian_uri, go: "去复盘 →", short: `复盘：${shortTitle(f.title)}` }));
  const rvN = (state.dash.reviews || []).length;
  if (rvN) queue.push({ title: `甄选：${rvN} 张素材卡待处理`, desc: "AI 已读完资料并写好素材卡，选择收入知识库、列为候选选题，或归档清理。", href: "#review", go: "去甄选 →", short: `甄选 ${rvN} 张素材卡` });
  c.recording.forEach((t) => queue.push({ title: `录：${t.title}`, desc: t.summary || "稿子已经定了，先试录开头 30 秒。", href: t.obsidian_uri, go: "打开稿子 →", short: `录：${shortTitle(t.title)}` }));
  c.writing.filter((t) => t.status === "drafted" || t.status === "draft-complete").forEach((t) => queue.push({ title: `看：${t.title}`, desc: t.summary || "稿子或成片在等你看。", href: t.obsidian_uri, go: "打开 →", short: `看：${shortTitle(t.title)}` }));
  if (!queue.length && c.cand.length) queue.push({ title: "从候选里挑一个立项", desc: `还有 ${c.cand.length} 个候选选题。`, href: "#board", go: "去进程 →", short: "" });
  const f = queue[0] || { title: "今天没有待办", desc: "可以刷新选题洞察，或者记下一个灵感。", href: "#radar", go: "去选题洞察 →", short: "" };
  $("focusTitle").textContent = f.title; $("focusDesc").textContent = f.desc;
  $("focusGo").textContent = f.go; $("focusGo").href = f.href || "#board";
  $("focusAlso").textContent = queue[1] ? `做完再${queue[1].short.replace(/^录：/, "录：")}` : "";

  $("sCand").textContent = c.cand.length; $("sCandS").textContent = "7 天没推进会先收起来";
  $("sWriting").textContent = c.writing.length; $("sWritingS").textContent = c.writing.map((t) => shortTitle(t.title, 9)).join(" · ") || "没有";
  $("sRecording").textContent = c.recording.length; $("sRecordingS").textContent = c.recording.map((t) => shortTitle(t.title, 12)).join(" · ") || "没有";
  $("sReview").textContent = c.review.length;
  const rs = $("sReviewS"); const first = c.review.slice().sort((a, b) => (a.due_at || "9").localeCompare(b.due_at || "9"))[0];
  rs.textContent = first ? `● ${dueText(first.due_at)[0] || "待补数据"}` : "没有"; rs.classList.toggle("warn", !!(first && first.due_at && first.due_at <= today()));

  // 流水线
  const max = Math.max(1, ...COLS.map((k) => c[k.key].length));
  const hotKey = c.recording.length ? "recording" : c.writing.length ? "writing" : "";
  const pipe = $("pipe"); pipe.innerHTML = "";
  COLS.forEach((k) => {
    const list = c[k.key];
    const row = document.createElement("div"); row.className = "stage"; row.dataset.go = "board";
    row.innerHTML = `<span class="name">${k.name}</span><div class="bar"><b class="${k.key === hotKey ? "hot" : k.key === "review" ? "warn" : ""}">${esc(list.map((t) => shortTitle(t.title, 12)).join(" · "))}</b></div><span class="c">${list.length}</span>`;
    pipe.appendChild(row);
    const b = row.querySelector("b"); requestAnimationFrame(() => b.style.setProperty("width", `${Math.max(list.length ? 18 : 0, (list.length / max) * 100)}%`));
  });
  $("pipeNote").textContent = hotKey === "recording" ? `${c.recording.map((t) => shortTitle(t.title, 10)).join("、")}已经定稿还没录，是现在最卡的一步。`
    : hotKey === "writing" ? `有 ${c.writing.length} 样东西在写作中，先把等你看的看掉。` : "流水线是空的，从候选里挑一个立项。";

  // 活动倒计时
  const s = new Date(ACTIVITY.start), e = new Date(ACTIVITY.end), now = new Date(today());
  const total = Math.max(1, (e - s) / 864e5), left = Math.max(0, Math.round((e - now) / 864e5));
  const done = Math.min(1, Math.max(0, (now - s) / 864e5 / total));
  $("actName").innerHTML = `${esc(ACTIVITY.name)}<span class="hint">${md(ACTIVITY.start)} ～ ${md(ACTIVITY.end)}</span>`;
  $("actDays").textContent = left;
  $("ring").setAttribute("stroke-dasharray", `${(done * 439.8).toFixed(1)} 439.8`);
  $("actRange").textContent = "已发";
  $("actPub").textContent = c.published.map((p) => shortTitle(p.title, 9)).join(" · ") || "还没有";

  renderRadarRows($("radarToday"), radarList("ours").slice(0, 6));
  const lr = state.radar && state.radar.last_run;
  $("radarMeta").textContent = lr ? `上次拉取 ${md(lr.at)} ${lr.at.slice(11, 16)} · 选题洞察共 ${radarList("all").length} 条，这里只列和我们方向相关的` : "选题洞察还没刷新过";
}

function pillHTML(label, cls) { return `<span class="pill ${cls}">${esc(label)}</span>`; }

function taskCard(item, colKey) {
  const el = document.createElement("div");
  el.className = "task";
  let pills = "", when = "";
  if (colKey === "published") { const plat = item.platform && item.platform !== "已发布" ? item.platform : "平台待补"; pills = pillHTML(plat, plat === "小红书" ? "xhs" : "gray"); }
  else if (colKey === "review") { const [t, cls] = dueText(item.due_at); pills = pillHTML(t || "待补数据", cls || "gray"); if (item.due_at && item.due_at <= today()) el.classList.add("urgent"); when = md(item.due_at); }
  else { const p = STATUS_PILL[item.status] || [item.status || "", "gray"]; pills = pillHTML(p[0], p[1]); when = md(item.modified); }
  el.innerHTML = `<h4><a href="${esc(item.obsidian_uri)}" title="在 Obsidian 打开">${esc(item.title)}</a></h4>
    <div class="meta">${pills}<span class="when">${esc(when)}</span></div>
    ${item.priority_score ? `<div class="prio">优先<div class="track"><b></b></div>${item.priority_score}</div>` : ""}
    ${item.summary ? `<div class="next">${esc(item.summary.slice(0, 60))}</div>` : ""}
    <div class="ops"></div>`;
  const bar = el.querySelector(".track b"); if (bar) bar.style.setProperty("width", `${Math.min(100, item.priority_score)}%`);
  const proto = state.dash.board_protocol && state.dash.board_protocol[item.kind];
  const ops = el.querySelector(".ops");
  if (proto) {
    proto.transitions.filter((t) => t.from === item.status || t.from === "*").forEach((t) => {
      const b = document.createElement("button"); b.type = "button";
      b.className = "btn sm" + (t.to === "cancelled" || t.to === "closed" ? " ghost" : "");
      b.textContent = t.label;
      b.addEventListener("click", async () => {
        if (t.confirm && !confirm(t.confirm)) return;
        b.disabled = true;
        try { await postJSON("/api/note/transition", { path: item.path, to: t.to }); toast(`已改成「${proto.status_labels[t.to] || t.to}」`); await load(); }
        catch (e) { toast(e.message, true); b.disabled = false; }
      });
      ops.appendChild(b);
    });
  }
  if (!ops.children.length) ops.remove();
  return el;
}

function renderBoard() {
  const c = state.cols, board = $("board"); board.innerHTML = "";
  const hotKey = c.recording.length ? "recording" : "";
  COLS.forEach((k) => {
    const col = document.createElement("div");
    col.className = "col hz" + (k.key === hotKey ? " now" : "");
    col.innerHTML = `<span class="hl"></span><div class="col-h"><i class="${k.cls}"></i><div>${k.name}<small>${k.hint}</small></div><span class="c">${c[k.key].length}</span></div>`;
    if (!c[k.key].length) { const n = document.createElement("div"); n.className = "none"; n.textContent = "暂时没有"; col.appendChild(n); }
    c[k.key].forEach((it) => col.appendChild(taskCard(it, k.key)));
    board.appendChild(col);
    setupHover(col, ".task");
  });
}

// ---------- 雷达 ----------
// 本机加：「本次新增」= 最近一次刷新新拉到的（first_seen 落在最近一轮完成时间前 15 分钟以内）。
// 列表是累积的、按爆款指数排，不标出来的话刷新后看不出变化
function radarIsNew(i) {
  const lr = state.radar && state.radar.last_run;
  if (!lr || !lr.at || !i.first_seen) return false;
  return Date.parse(i.first_seen) >= Date.parse(lr.at) - 15 * 60 * 1000;
}
// 本机加（10-28）：选题洞察页可按 爆款指数 / 发布时间（新的在前）/ 获赞 排；概览页的列表固定按爆款指数
const RADAR_SORT = {
  mult: (a, b) => (b.multiplier || 0) - (a.multiplier || 0),
  time: (a, b) => (Date.parse(b.published_at) || 0) - (Date.parse(a.published_at) || 0),
  likes: (a, b) => (b.likes || 0) - (a.likes || 0),
};
function radarList(filter, sort = "mult") {
  const items = (state.radar && state.radar.items) || [];
  return items.filter((i) => {
    if (filter === "adopted") return i.status === "adopted" || i.candidate;
    // passed 为 null = 小红书互动和时效已过门槛、作者粉丝还没补查到（后端标「待定」，原版界面也显示），照样列出
    if (i.status === "rejected" || i.excluded || i.passed === false) return false;
    if (i.status === "adopted" || i.candidate) return false;
    if (filter === "douyin" || filter === "xiaohongshu") return i.platform === filter;
    if (filter === "ours") { const ours = ourKeywords(); return (i.keywords || []).some((k) => ours.includes(k)); }
    if (filter === "latest") return radarIsNew(i);
    return true;
  }).sort(RADAR_SORT[sort] || RADAR_SORT.mult);
}
// 本机加（10-28）：「取文案」——点了后台下载 + 本地转写，只出文案、不出素材卡，好了变「看文案」跳到视频文案页
function transcriptOf(i) { return ((state.radar && state.radar.transcripts) || {})[i.id] || {}; }
function transcriptButton(i) {
  const t = transcriptOf(i);
  if (t.status === "done") return `<button class="btn sm primary" data-t="open" type="button">看文案</button>`;
  if (t.status === "queued" || t.status === "running") return `<button class="btn sm" data-t="wait" type="button" disabled><i class="spin"></i>${t.status === "running" ? "转写中" : "排队中"}</button>`;
  if (t.status === "failed") return `<button class="btn sm" data-t="get" type="button" title="${esc(t.error || "")}">重试取文案</button>`;
  return `<button class="btn sm" data-t="get" type="button">取文案</button>`;
}
async function transcriptClick(i, btn) {
  const t = transcriptOf(i);
  if (btn.dataset.t === "open" && t.path) { location.hash = "#videos"; await loadVideos(); openVideo(t.path); return; }
  btn.disabled = true;
  try {
    const r = await postJSON("/api/radar/transcript", { id: i.id });
    state.radar.transcripts = { ...(state.radar.transcripts || {}), [i.id]: r };
    if (r.status === "done" && r.path) { location.hash = "#videos"; await loadVideos(); openVideo(r.path); return; }
    toast("开始下载转写，好了按钮会变成「看文案」");
    renderRadarViews(); pollTranscripts();
  } catch (e) { toast(e.message, true); btn.disabled = false; }
}
let transcriptTimer = 0;
function pollTranscripts() {
  clearTimeout(transcriptTimer);
  const busy = () => Object.values((state.radar && state.radar.transcripts) || {}).some((t) => t.status === "queued" || t.status === "running");
  if (!busy()) return;
  transcriptTimer = setTimeout(async () => {
    try {
      const before = state.radar.transcripts || {};
      const r = await getJSON("/api/radar"); state.radar = r; renderRadarViews();
      Object.entries(r.transcripts || {}).forEach(([id, t]) => {
        const was = before[id] && before[id].status;
        if ((was === "queued" || was === "running") && t.status === "done") { toast("文案好了，点「看文案」查看"); loadVideos(); }
        if ((was === "queued" || was === "running") && t.status === "failed") toast(`取文案失败：${t.error || "原因不明"}`, true);
      });
    } catch (_) { /* 下一轮再试 */ }
    pollTranscripts();
  }, 4000);
}
function renderRadarViews() {
  renderRadarAll();
  renderRadarRows($("radarToday"), radarList("ours").slice(0, 6));
}
const KW_CLS = (k) => (/Vibe|vibe/.test(k) ? "violet" : /科普/.test(k) ? "amber" : /Skill|Codex|Claude Code|Obsidian|提示词/.test(k) ? "green" : "gray");
function renderRadarRows(tbody, list) {
  tbody.innerHTML = "";
  if (!list.length) { tbody.innerHTML = `<tr class="empty-row"><td colspan="7">这里还没有东西，刷新一次选题洞察试试</td></tr>`; return; }
  list.forEach((i) => {
    const tr = document.createElement("tr");
    const kws = (i.keywords || []).map((k) => pillHTML(k, KW_CLS(k))).join("") + (i.listicle ? pillHTML("清单", "gray") : "");
    const adopted = i.status === "adopted" || i.candidate;
    tr.innerHTML = `<td class="t"><a href="${esc(i.url)}" target="_blank" rel="noopener" title="${esc(i.title)}">${esc(cut(i.title || "（无标题）", 40))}</a><small>${radarIsNew(i) ? pillHTML("本次新增", "blue") : ""}${esc(i.author)} · ${esc(md(i.published_at))}</small></td>
      <td><span class="plat ${i.platform === "xiaohongshu" ? "xhs" : ""}">${i.platform === "xiaohongshu" ? "书" : "抖"}</span></td>
      <td class="n">${i.fans == null && i.platform === "xiaohongshu" ? `<span title="粉丝还没补查到。每次刷新按互动从高到低最多查 20 位作者，没轮到的下次接着查">待查</span>` : fmtNum(i.fans)}</td><td class="n">${fmtNum(i.likes)}</td><td class="x">${i.multiplier != null ? i.multiplier + "×" : "待定"}</td>
      <td>${kws}</td>
      <td class="ops">${transcriptButton(i)} ${adopted ? pillHTML("已列入", "green") : `<button class="btn sm" data-a="adopt">列为候选</button> <button class="btn sm ghost" data-a="reject">忽略</button>`}</td>`;
    tr.querySelectorAll("button[data-a]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { await postJSON("/api/radar/action", { id: i.id, action: b.dataset.a, angle: "" }); toast(b.dataset.a === "adopt" ? "已列为候选选题" : "已忽略，以后不再出现"); await load(); }
      catch (e) { toast(e.message, true); b.disabled = false; }
    }));
    const tb = tr.querySelector("button[data-t]");
    if (tb) tb.addEventListener("click", () => transcriptClick(i, tb));
    tbody.appendChild(tr);
  });
}
function renderRadarAll() {
  renderRadarRows($("radarAll"), radarList(state.radarFilter, state.radarSort));
  document.querySelectorAll("#radarSort span").forEach((s) => s.classList.toggle("on", s.dataset.s === state.radarSort));
  const lr = state.radar && state.radar.last_run;
  $("radarSub").textContent = lr ? `上次拉取 ${md(lr.at)} ${lr.at.slice(11, 16)} · 本次新增 ${radarList("latest").length} 条 · ${lr.calls} 次调用 · $${lr.cost_usd}` : "还没拉过";
  document.querySelectorAll("#radarFilters span").forEach((s) => s.classList.toggle("on", s.dataset.f === state.radarFilter));
}

// ---------- 视频文案（本机加，10-28；接口 /api/videos、/api/video 是同日新增的） ----------
const VD = { items: null, folder: "", filter: "all", q: "", cur: "", detail: null, timed: false };
const PLAT_NAME = { douyin: "抖音", xiaohongshu: "小红书" };
const dur = (s) => (s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "–");
async function loadVideos() {
  try { const r = await getJSON("/api/videos"); VD.items = r.items; VD.folder = r.folder; }
  catch (e) { VD.items = VD.items || []; toast(e.message, true); }
  $("navVideos").textContent = VD.items.length;
  if (!VD.items.some((i) => i.path === VD.cur)) { VD.cur = ""; VD.detail = null; }
  renderVideoList();
  if (!VD.cur && VD.items.length) openVideo(VD.items[0].path);
  else if (!VD.items.length) renderVideoDetail();
}
function videoRows() {
  const q = VD.q.trim().toLowerCase();
  return (VD.items || []).filter((i) => (VD.filter === "all" || i.platform === VD.filter)
    && (!q || `${i.title} ${i.author}`.toLowerCase().includes(q)));
}
function renderVideoList() {
  const rows = videoRows(), all = VD.items || [];
  $("vdSub").textContent = `共 ${all.length} 条 · 文件在 ${VD.folder || "02_内容素材/视频"} · 数据是收录那一刻的`;
  $("vdList").innerHTML = rows.length ? rows.map((i) => `<a class="vd-item${i.path === VD.cur ? " on" : ""}" data-path="${esc(i.path)}">
      <b>${esc(cut(i.title, 40))}</b>
      <small><span class="plat ${i.platform === "xiaohongshu" ? "xhs" : ""}">${i.platform === "xiaohongshu" ? "书" : "抖"}</span>${esc(i.author || "未知作者")} · 收录 ${esc(md(i.captured_at))} · ${i.has_transcript ? `${dur(i.duration)} · ${i.chars} 字` : i.note_type === "video" || i.duration > 0 ? `${dur(i.duration)} · 没识别到口播` : "只有文字描述"}</small>
      <div class="nums">赞 ${fmtNum(i.stats.like)}　评 ${fmtNum(i.stats.comment)}　藏 ${fmtNum(i.stats.collect)}　转 ${fmtNum(i.stats.share)}</div></a>`).join("")
    : `<div class="vd-none">${all.length ? "没有符合条件的" : "还没有视频文案"}</div>`;
  document.querySelectorAll("#vdFilters span").forEach((s) => s.classList.toggle("on", s.dataset.f === VD.filter));
}
async function openVideo(path) {
  VD.cur = path; renderVideoList();
  try { VD.detail = await getJSON(`/api/video?path=${encodeURIComponent(path)}`); }
  catch (e) { VD.detail = null; toast(e.message, true); }
  renderVideoDetail();
}
function minuteOf(t) { const p = String(t).split(":").map(Number); return p.length === 3 ? p[0] * 60 + p[1] : p[0]; }
function videoParagraphs(lines) {
  // 每 10 秒一段太碎，按分钟并成一段
  const out = [];
  lines.forEach((l) => { const m = minuteOf(l.t); if (!out.length || out[out.length - 1].m !== m) out.push({ m, text: "" }); out[out.length - 1].text += l.text; });
  return out.map((p) => p.text);
}
function videoCopyText(d) { return d.lines.length ? videoParagraphs(d.lines).join("\n\n") : (d.desc || ""); }
function renderVideoDetail() {
  const box = $("vdCard"), d = VD.detail;
  if (!d) { box.innerHTML = `<div class="vd-empty">${(VD.items || []).length ? "在左边选一条" : "还没有视频文案。把抖音、小红书链接发到已配置的飞书群，下载转写好后会出现在这里。"}</div>`; return; }
  const s = d.stats || {};
  const isVideo = d.note_type === "video" || d.duration > 0;
  const text = !d.lines.length ? `<p class="vd-none">${isVideo ? "没识别到口播：这条可能是纯音乐，或者文案只在画面字幕里，看下面的画面墙。" : "这条是图文笔记或没拿到视频，只有下面的作品描述（正文）。"}</p>`
    : VD.timed ? d.lines.map((l) => `<p class="tl"><em>${esc(l.t)}</em><span>${esc(l.text)}</span></p>`).join("")
    : videoParagraphs(d.lines).map((p) => `<p>${esc(p)}</p>`).join("");
  box.innerHTML = `<div class="rv-swap">
    <div class="vd-meta"><span class="pill ${d.platform === "xiaohongshu" ? "xhs" : "gray"}">${esc(PLAT_NAME[d.platform] || d.platform)}</span>${d.from_radar ? pillHTML("来自选题洞察", "blue") : ""}${esc(d.author || "未知作者")} · 发布 ${esc((d.published_at || "").slice(0, 10) || "未知")} · 时长 ${dur(d.duration)} · 收录 ${esc((d.captured_at || "").slice(0, 16).replace("T", " "))}</div>
    <h2 class="vd-title">${esc(d.title)}</h2>
    <div class="vd-stats">${d.fans != null ? `<div><span>账号粉丝</span><b>${fmtNum(d.fans)}</b></div>` : ""}<div><span>点赞</span><b>${fmtNum(s.like)}</b></div><div><span>评论</span><b>${fmtNum(s.comment)}</b></div><div><span>收藏</span><b>${fmtNum(s.collect)}</b></div><div><span>转发</span><b>${fmtNum(s.share)}</b></div><div><span>文案字数</span><b>${d.lines.length ? d.chars : "–"}</b></div></div>
    <div class="vd-actions">
      ${d.lines.length ? `<button class="btn primary sm" id="vdCopy" type="button">复制全文</button><button class="btn sm" id="vdTimed" type="button">${VD.timed ? "不看时间" : "带时间看"}</button>` : d.desc ? `<button class="btn primary sm" id="vdCopy" type="button">${isVideo ? "复制作品描述" : "复制正文"}</button>` : ""}
      ${d.url ? `<a class="btn sm" href="${esc(d.url)}" target="_blank" rel="noopener">打开原视频 ↗</a>` : ""}
      <a class="btn sm" href="${esc(d.obsidian_uri)}">在 Obsidian 打开</a>
    </div>
    ${d.hook ? `<div class="vd-sec"><h4>开头 8 秒（钩子）</h4><p class="vd-hook">${esc(d.hook)}</p></div>` : ""}
    <div class="vd-sec"><h4>文案<small>本地自动识别，可能有错字；引用原话前对一下视频</small></h4><div class="vd-text">${text}</div></div>
    ${d.desc ? `<div class="vd-sec"><h4>作品描述</h4><div class="vd-desc">${esc(d.desc)}</div></div>` : ""}
    ${d.wall ? `<div class="vd-sec"><h4>画面墙<small>左上到右下 9 格：前 3 格是开头 0.5 / 1.5 / 3 秒，其余均匀分布</small></h4><img class="vd-wall" alt="画面墙" loading="lazy" src="/api/asset?path=${encodeURIComponent(d.wall)}"></div>` : ""}
  </div>`;
  const copy = $("vdCopy");
  if (copy) copy.addEventListener("click", async () => {
    const all = videoCopyText(d);
    try { await navigator.clipboard.writeText(all); toast("已复制全文"); return; } catch (_) { /* 有的浏览器不给剪贴板权限，退回选中复制 */ }
    const ta = document.createElement("textarea");
    ta.value = all; ta.setAttribute("readonly", "");
    ta.style.setProperty("position", "fixed"); ta.style.setProperty("left", "-9999px");
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    if (ok) toast("已复制全文"); else toast("复制没成功，可以在 Obsidian 里打开复制", true);
  });
  const timed = $("vdTimed");
  if (timed) timed.addEventListener("click", () => { VD.timed = !VD.timed; renderVideoDetail(); });
}

// ---------- 搜索关键词面板（本机加，11-02） ----------
const KW = { douyin: [], xiaohongshu: [] };
function openKeywords() {
  const k = (state.radar && state.radar.keywords) || { douyin: [], xiaohongshu: [] };
  KW.douyin = [...k.douyin]; KW.xiaohongshu = [...k.xiaohongshu];
  $("kwPanel").hidden = false; renderKeywords();
}
function renderKeywords() {
  const chips = (p) => KW[p].length ? KW[p].map((w, n) => `<span class="kw-chip">${esc(w)}<button type="button" data-p="${p}" data-n="${n}" title="删掉这个词">×</button></span>`).join("") : `<span class="kw-none">还没有词，刷新时这个平台不搜</span>`;
  $("kwDouyin").innerHTML = chips("douyin"); $("kwXhs").innerHTML = chips("xiaohongshu");
  const est = state.radar && state.radar.keywords && state.radar.keywords.estimate;
  $("kwEst").textContent = `抖音 ${KW.douyin.length} 个词、小红书 ${KW.xiaohongshu.length} 个词。每个小红书词每次刷新约 $0.01，抖音词约 $0.002`
    + (est ? `；按已保存的词，每次刷新最多约 $${est.max_cost_usd}` : "") + "。改了要点保存，下次刷新才用新词";
}
async function saveKeywords() {
  const btn = $("kwSave"); btn.disabled = true;
  try {
    const r = await postJSON("/api/radar/keywords", { douyin: KW.douyin, xiaohongshu: KW.xiaohongshu });
    state.radar.keywords = r; renderRadarAll(); $("kwPanel").hidden = true;
    toast(`已保存，下次刷新每次最多约 $${r.estimate.max_cost_usd}`);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

// ---------- 动效 1：边缘流光 ----------
document.addEventListener("pointermove", (ev) => {
  document.querySelectorAll(".glow").forEach((el) => {
    const r = el.getBoundingClientRect();
    const near = ev.clientX > r.left - 80 && ev.clientX < r.right + 80 && ev.clientY > r.top - 80 && ev.clientY < r.bottom + 80;
    el.style.setProperty("--gx", `${ev.clientX - r.left}px`); el.style.setProperty("--gy", `${ev.clientY - r.top}px`);
    el.style.setProperty("--ga", near ? "1" : "0");
  });
});

// ---------- 动效 2：悬停底色滑动 ----------
function setupHover(zone, selector) {
  const hl = zone.querySelector(":scope > .hl"); if (!hl) return;
  zone.addEventListener("pointerover", (ev) => {
    const target = ev.target.closest(selector); if (!target || !zone.contains(target)) return;
    const zr = zone.getBoundingClientRect(), tr = target.getBoundingClientRect();
    hl.style.setProperty("width", `${tr.width + 8}px`); hl.style.setProperty("height", `${tr.height + 8}px`);
    hl.style.setProperty("transform", `translate(${tr.left - zr.left - 4}px, ${tr.top - zr.top - 4}px)`);
    hl.style.setProperty("opacity", "1");
  });
  zone.addEventListener("pointerleave", () => hl.style.setProperty("opacity", "0"));
}

// ---------- 动效 3：轮播提示 + 文字散开 ----------
function rotatePlaceholder(ph, input, tips) {
  let i = 0; ph.textContent = tips[0];
  const sync = () => ph.classList.toggle("hide", !!input.value);
  input.addEventListener("input", sync);
  setInterval(() => {
    if (input.value || document.activeElement === input && input.value) return;
    ph.classList.add("out");
    setTimeout(() => { i = (i + 1) % tips.length; ph.textContent = tips[i]; ph.classList.remove("out"); ph.classList.add("in");
      requestAnimationFrame(() => requestAnimationFrame(() => ph.classList.remove("in"))); }, 350);
  }, 3000);
}
function vanish(input, box) {
  const text = input.value; box.innerHTML = "";
  [...text].forEach((ch) => { const s = document.createElement("span"); s.textContent = ch; box.appendChild(s); });
  input.classList.add("vanishing");
  requestAnimationFrame(() => requestAnimationFrame(() => box.querySelectorAll("span").forEach((s) => {
    s.style.setProperty("transform", `translate(${(Math.random() * 60 - 10).toFixed(0)}px, ${(Math.random() * 40 - 30).toFixed(0)}px) rotate(${(Math.random() * 40 - 20).toFixed(0)}deg)`);
    s.style.setProperty("opacity", "0"); s.style.setProperty("filter", "blur(2px)");
  })));
  setTimeout(() => { box.innerHTML = ""; input.value = ""; input.classList.remove("vanishing"); input.dispatchEvent(new Event("input")); }, 720);
}

// ---------- 动效 4：带状态的按钮（拉雷达） ----------
async function runRadar(btn, doneEl) {
  if (btn.classList.contains("loading")) return;
  btn.classList.remove("done", "fail"); btn.classList.add("loading");
  const before = (state.radar && state.radar.last_run && state.radar.last_run.at) || "";
  try {
    await postJSON("/api/radar/run", {});
    for (;;) {
      await new Promise((r) => setTimeout(r, 2500));
      const r = await getJSON("/api/radar");
      if (!r.running) { state.radar = r; break; }
    }
    const lr = state.radar.last_run || {};
    if (!lr.at || lr.at === before) {
      // 跑完却没有新的一轮记录：多半是缺 key 或网络问题，别拿上一轮的结果冒充
      doneEl.textContent = "没跑成"; btn.classList.remove("loading"); btn.classList.add("fail");
      toast("选题洞察这次没刷新成功（可能缺 TikHub key 或网络不通），日志在状态目录 logs/radar-run.log", true);
    } else {
      doneEl.textContent = lr.errors && lr.errors.length ? `完成，有 ${lr.errors.length} 个错误` : `✓ 新增 ${radarList("latest").length} 条 · $${lr.cost_usd ?? 0}`;
      btn.classList.remove("loading"); btn.classList.add(lr.errors && lr.errors.length ? "fail" : "done");
    }
    await load();
  } catch (e) { btn.classList.remove("loading"); btn.classList.add("fail"); doneEl.textContent = "失败"; toast(e.message, true); }
  setTimeout(() => btn.classList.remove("done", "fail"), 5000);
}

// 本机加（10-28）：「立即收录飞书群」——不等 30 分钟定时任务，马上跑一轮采集（拉飞书群 → 下载转写 → 素材卡）。
// 用工作台原有的 /api/pipeline/run，和定时任务共用一把锁：定时任务正在跑时这轮会安全跳过，它那轮照样会收。
async function runIngestNow() {
  const btn = $("ingestBtn"), doneEl = $("ingestDone"), loadEl = $("ingestLoad");
  if (btn.classList.contains("loading")) return;
  btn.classList.remove("done", "fail"); btn.classList.add("loading");
  const before = new Set((VD.items || []).map((i) => i.path));
  const t0 = Date.now();
  let shown = 0;
  try {
    await postJSON("/api/pipeline/run", {});
    for (;;) {
      await new Promise((r) => setTimeout(r, 3000));
      const secs = Math.round((Date.now() - t0) / 1000);
      loadEl.textContent = `收录中… ${secs} 秒`;
      await loadVideos();
      const fresh = (VD.items || []).filter((i) => !before.has(i.path));
      if (fresh.length > shown) { shown = fresh.length; openVideo(fresh[0].path); toast(`收到新视频：${cut(fresh[0].title, 20)}`); }
      const p = await getJSON("/api/pipeline");
      if (!p.manual_run_running) break;
    }
    await loadVideos();
    const fresh = (VD.items || []).filter((i) => !before.has(i.path));
    doneEl.textContent = fresh.length ? `✓ 新增 ${fresh.length} 条` : "✓ 群里没有新链接";
    btn.classList.remove("loading"); btn.classList.add("done");
    if (!fresh.length) toast("这次没有新视频：群里没有新链接，或者定时收录刚好在跑、已经收走了");
  } catch (e) { btn.classList.remove("loading"); btn.classList.add("fail"); toast(e.message, true); }
  loadEl.textContent = "收录中…";
  setTimeout(() => btn.classList.remove("done", "fail"), 6000);
}

// 本机加（11-06）：收录博主 —— 发名片 / 贴链接 → 预览数量 → 选范围 → 后台收全部作品 → 写账号拆解初稿
const AC = { jobs: [], timer: null, seen: {}, preview: null };
function acctLine(j) {
  if (j.status === "queued") return `排队中${j.nickname ? "：" + j.nickname : ""}`;
  if (j.status === "running") {
    const n = (j.done || 0) + (j.failed || 0), total = j.missing || j.posts || 0;
    return `收录中：${j.nickname || "…"} ${n}/${total || "?"}${j.current ? " · " + j.current : ""}`;
  }
  if (j.status === "done") {
    if (j.analysis_error) return `${j.nickname || "博主"} 收完了，但拆解没写成：${j.analysis_error}`;
    return `✓ ${j.nickname || "博主"} 收完 ${j.posts || 0} 条 · 拆解初稿已写`;
  }
  if (j.status === "failed") return `失败：${j.nickname || "博主"} ${j.error || ""}`;
  return "";
}
function renderAccount() {
  const strip = $("acctStrip"), job = (AC.jobs || [])[0];
  if (!strip) return;
  if (!job) { strip.hidden = true; return; }
  strip.hidden = false;
  $("acctDetail").textContent = acctLine(job);
  strip.classList.toggle("on", job.status === "running" || job.status === "queued");
  strip.classList.toggle("bad", job.status === "failed");
}
async function pollAccount() {
  clearTimeout(AC.timer);
  try {
    const r = await getJSON("/api/account/jobs");
    AC.jobs = r.jobs || [];
    renderAccount();
    const fresh = AC.jobs.filter((j) => j.status === "done" && !AC.seen[j.id]);
    fresh.forEach((j) => { AC.seen[j.id] = 1; });
    if (fresh.length) { await loadVideos(); toast(`博主 ${fresh[0].nickname || ""} 收完了`); }
    if (r.running) AC.timer = setTimeout(pollAccount, 4000);
  } catch (e) { AC.timer = setTimeout(pollAccount, 15000); }
}
async function openAcct() {
  $("acctDlg").hidden = false; $("acctScrim").hidden = false;
  $("acctPreview").innerHTML = ""; $("acctUrl").value = ""; AC.preview = null;
  const box = $("acctFeishu");
  box.innerHTML = "读飞书名片中…";
  try {
    const r = await getJSON("/api/account/feishu");
    box.innerHTML = r.cards.length ? r.cards.map((c) => `<a data-url="${esc(c.url)}">${esc(c.at)} · ${esc(c.url)}</a>`).join("")
      : `<div class="none">飞书群最近 3 天没有名片，直接粘贴链接。</div>`;
    box.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => { $("acctUrl").value = a.dataset.url; }));
  } catch (e) { box.innerHTML = `<div class="none">${esc(e.message)}</div>`; }
}
function closeAcct() { $("acctDlg").hidden = true; $("acctScrim").hidden = true; }
async function acctPreview() {
  const url = $("acctUrl").value.trim();
  if (!url) return toast("先填或选一个主页链接", true);
  const btn = $("acctPreviewBtn"); btn.disabled = true; btn.textContent = "查询中…";
  try {
    const r = await postJSON("/api/account/preview", { url });
    AC.preview = r;
    const mix = (r.videos !== undefined && r.images !== undefined) ? `（视频 ${r.videos} / 图文 ${r.images}）` : "";
    $("acctPreview").innerHTML = `博主 <b>${esc(r.nickname || "?")}</b>：共 <b>${r.posts}</b> 条${mix}，已收 ${r.have}，还缺 <b>${r.missing}</b>，预计约 <b>${r.estimate_minutes}</b> 分钟`;
  } catch (e) { $("acctPreview").innerHTML = `<span style="color:#b3261e">${esc(e.message)}</span>`; AC.preview = null; }
  btn.disabled = false; btn.textContent = "查看数量";
}
function acctMode() {
  const m = document.querySelector('input[name="acctMode"]:checked').value;
  if (m === "recent") return { recent: parseInt($("acctN").value || "30", 10) || 30 };
  if (m === "top") return { top: parseInt($("acctNTop").value || "10", 10) || 10 };
  return {};
}
async function acctStart() {
  const url = $("acctUrl").value.trim();
  if (!url) return toast("先填或选一个主页链接", true);
  if (!AC.preview) return toast("先点「查看数量」", true);
  const mode = acctMode();
  const count = Object.values(mode)[0] || AC.preview.missing;
  if (Object.keys(mode).length === 0 && AC.preview.missing > 50) {
    if (!confirm(`这个号还缺 ${AC.preview.missing} 条，全收约 ${AC.preview.estimate_minutes} 分钟，确定全部收录？`)) return;
  }
  try {
    await postJSON("/api/account/start", { url, mode });
    closeAcct(); pollAccount();
    toast(`开始收录 ${AC.preview.nickname || "博主"}（约 ${count} 条）`);
  } catch (e) { toast(e.message, true); }
}

// ---------- 甄选页（第 8 步）：一次一张，键盘 1～5，选完进「待执行」，点「执行」才真正写文件 ----------
const RV = { idx: 0, last: null, notes: {} };
const REC_CLS = { 保留: "green", 待观察: "amber", 清理: "red" };
// 五个选项只换界面上显示的名字；提交给服务端的仍是原协议的 key，审核卡文件里的写法不变
const ACTION_LABELS = { knowledge: "收入知识库", topic: "列为候选选题", both: "收录并立题", paused: "暂缓", cleanup: "归档清理" };
const actionLabel = (key, fallback) => ACTION_LABELS[key] || fallback || key;
function mdSection(body, heading) {
  const m = body.match(new RegExp(`(?:^|\\n)## ${heading}\\s*\\n([\\s\\S]*?)(?=\\n## |$)`));
  return m ? m[1].trim() : "";
}
const bullets = (txt) => txt.split("\n").map((l) => l.replace(/^\s*[-*]\s+/, "").trim()).filter((l) => l && !l.startsWith("#") && !l.startsWith(">"));
async function reviewNote(path) {
  if (!RV.notes[path]) RV.notes[path] = await getJSON(`/api/note?path=${encodeURIComponent(path)}`);
  return RV.notes[path];
}
function renderReview() {
  const pend = (state.dash && state.dash.reviews) || [], queued = (state.dash && state.dash.queued_reviews) || [];
  if (RV.idx >= pend.length) RV.idx = Math.max(0, pend.length - 1);
  $("rvPendN").textContent = pend.length ? `${pend.length} 张` : "";
  $("rvQueueN").textContent = queued.length ? `${queued.length} 张` : "";
  $("applyIdle").textContent = queued.length ? `执行（${queued.length}）` : "执行";
  $("applyBtn").disabled = !queued.length;
  // 右侧两个列表
  const pl = $("rvPend"); pl.innerHTML = pend.length ? "" : `<div class="none">没有</div>`;
  pend.forEach((r, i) => {
    const a = document.createElement("div"); a.className = "rv-item" + (i === RV.idx ? " on" : "");
    a.innerHTML = `<b>${esc(r.title)}</b><small>${pillHTML(r.recommendation || "待判断", REC_CLS[r.recommendation] || "gray")}知识 ${esc(r.knowledge_value || "–")} · 写作 ${esc(r.writing_value || "–")}</small>`;
    a.addEventListener("click", () => { RV.idx = i; renderReview(); });
    pl.appendChild(a);
  });
  const ql = $("rvQueue"); ql.innerHTML = queued.length ? "" : `<div class="none">没有</div>`;
  const labelOf = actionLabel;
  queued.forEach((r) => {
    const a = document.createElement("div"); a.className = "rv-item";
    a.innerHTML = `<b>${esc(r.title)}</b><small>${pillHTML(labelOf(r.selected_action), "blue")}<button class="btn sm ghost undo" type="button">撤回</button></small>`;
    a.querySelector(".undo").addEventListener("click", (e) => { e.stopPropagation(); pickAction(r, null); });
    ql.appendChild(a);
  });
  // 主卡
  const cur = pend[RV.idx];
  $("rvEmpty").hidden = !!cur; $("rvBody").hidden = !cur;
  if (!cur) return;
  const badges = [pillHTML(cur.recommendation || "待判断", REC_CLS[cur.recommendation] || "gray"),
    pillHTML(`知识 ${cur.knowledge_value || "–"}`, "violet"), pillHTML(`写作 ${cur.writing_value || "–"}`, "blue")];
  if (cur.timeliness) badges.push(pillHTML(cur.timeliness, cur.timeliness === "强时效" ? "red" : "gray"));
  if (cur.confidence) badges.push(pillHTML(`把握 ${cur.confidence}`, "gray"));
  if (cur.knowledge_unit_count) badges.push(pillHTML(`${cur.knowledge_unit_count} 个知识点`, "gray"));
  $("rvBadges").innerHTML = badges.join("");
  $("rvCount").textContent = `第 ${RV.idx + 1} / ${pend.length} 张`;
  $("rvTitle").textContent = cur.title; $("rvTitle").href = cur.obsidian_uri;
  $("rvSummary").textContent = cur.summary || "";
  $("rvReader").textContent = "…"; $("rvAngles").innerHTML = ""; $("rvHoles").innerHTML = "";
  const src = $("rvSrc"); src.innerHTML = "";
  if (cur.source_url) src.insertAdjacentHTML("beforeend", `<a href="${esc(cur.source_url)}" target="_blank" rel="noopener">看原帖 ↗</a>`);
  src.insertAdjacentHTML("beforeend", `<a href="${esc(cur.obsidian_uri)}">打开素材卡</a>`);
  const acts = $("rvActions"); acts.innerHTML = "";
  (state.dash.review_actions || []).slice().sort((a, b) => a.shortcut - b.shortcut).forEach((x) => {
    const b = document.createElement("button"); b.type = "button";
    b.className = "btn" + (x.key === "knowledge" || x.key === "both" ? " primary" : x.key === "cleanup" ? " ghost" : "");
    b.innerHTML = `<kbd>${x.shortcut}</kbd>${esc(actionLabel(x.key, x.ui_label))}`;
    b.addEventListener("click", () => pickAction(cur, x.key));
    acts.appendChild(b);
  });
  $("rvCard").classList.remove("rv-swap"); void $("rvCard").offsetWidth; $("rvCard").classList.add("rv-swap");
  // 读者收益、可写角度、漏洞：从审核卡正文里取
  const path = cur.path;
  reviewNote(path).then((n) => {
    if (((state.dash.reviews || [])[RV.idx] || {}).path !== path) return;
    const body = n.body || "";
    $("rvReader").textContent = mdSection(body, "读者收益") || "卡片里没写";
    $("rvAngles").innerHTML = bullets(mdSection(body, "可写角度")).map((l) => `<li>${esc(l)}</li>`).join("") || "<li>卡片里没写</li>";
    $("rvHoles").innerHTML = bullets(mdSection(body, "漏洞与反例")).slice(0, 4).map((l) => `<li>${esc(l)}</li>`).join("") || "<li>卡片里没写</li>";
  }).catch((e) => toast(e.message, true));
}
async function pickAction(card, key) {
  try {
    const r = await postJSON("/api/reviews/action", { path: card.path, action: key });
    RV.last = key ? card.path : null;
    toast(key ? `已选「${actionLabel(key, r.label)}」，点「执行」后生效` : "已撤回，回到待甄选");
    delete RV.notes[card.path];
    await load();
  } catch (e) { toast(e.message, true); }
}
async function applyReviews() {
  const btn = $("applyBtn"); if (btn.classList.contains("loading")) return;
  btn.classList.remove("done", "fail"); btn.classList.add("loading");
  try {
    await postJSON("/api/reviews/apply", {});
    for (;;) { await new Promise((r) => setTimeout(r, 2000)); const p = await getJSON("/api/pipeline"); if (!p.manual_run_running) break; }
    btn.classList.remove("loading"); btn.classList.add("done");
    await load();
  } catch (e) { btn.classList.remove("loading"); btn.classList.add("fail"); $("applyDone").textContent = "失败"; toast(e.message, true); }
  setTimeout(() => { btn.classList.remove("done", "fail"); $("applyDone").textContent = "✓ 已执行"; }, 4000);
}
function reviewKeys(e) {
  if (currentView() !== "review" || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.target.closest("input, textarea")) return;
  const pend = (state.dash && state.dash.reviews) || [], cur = pend[RV.idx];
  const k = e.key.toLowerCase();
  const act = (state.dash.review_actions || []).find((x) => String(x.shortcut) === k);
  if (act && cur) { e.preventDefault(); pickAction(cur, act.key); return; }
  if ((k === "j" || k === "arrowright") && RV.idx < pend.length - 1) { RV.idx++; renderReview(); }
  if ((k === "k" || k === "arrowleft") && RV.idx > 0) { RV.idx--; renderReview(); }
  if (k === "o" && cur && cur.source_url) window.open(cur.source_url, "_blank", "noopener");
  if (k === "u" && RV.last) { const q = (state.dash.queued_reviews || []).find((x) => x.path === RV.last); if (q) pickAction(q, null); }
}

// ---------- 路由、导航、搜索、记灵感 ----------
const VIEWS = ["today", "review", "board", "radar", "videos"];
function currentView() { const h = location.hash.replace("#", ""); return VIEWS.includes(h) ? h : "today"; }
function showView() {
  const v = currentView();
  VIEWS.forEach((k) => ($(`view-${k}`).hidden = k !== v));
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === v));
  moveNavPill();
  if (v === "videos") pollAccount();
}
function moveNavPill() {
  const a = document.querySelector("#nav a.on"), pill = $("navPill"); if (!a) return;
  pill.style.setProperty("width", `${a.offsetWidth}px`); pill.style.setProperty("transform", `translateX(${a.offsetLeft}px)`);
}

let searchTimer;
async function doSearch(q) {
  const box = $("searchResults");
  if (!q.trim()) { box.hidden = true; return; }
  try {
    const r = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
    box.innerHTML = r.results.length ? r.results.slice(0, 8).map((x) => `<a href="${esc(x.obsidian_uri)}"><b>${esc(x.title)}</b><small>${esc(x.path)}</small></a>`).join("") : `<div class="empty">没找到「${esc(q)}」</div>`;
    box.hidden = false;
  } catch (e) { toast(e.message, true); }
}

document.addEventListener("DOMContentLoaded", () => {
  window.addEventListener("hashchange", showView); window.addEventListener("resize", moveNavPill);
  showView();
  rotatePlaceholder($("searchPh"), $("searchInput"), SEARCH_TIPS);
  rotatePlaceholder($("capturePh"), $("captureInput"), CAPTURE_TIPS);
  $("searchInput").addEventListener("input", (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => doSearch(e.target.value), 250); });
  $("searchForm").addEventListener("submit", (e) => { e.preventDefault(); const a = $("searchResults").querySelector("a"); if (a) location.href = a.href; });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("searchInput").focus(); }
    if (e.key === "Escape") { $("searchResults").hidden = true; $("captureForm").hidden = true; }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#searchForm")) $("searchResults").hidden = true; });
  $("captureBtn").addEventListener("click", () => { const f = $("captureForm"); f.hidden = !f.hidden; if (!f.hidden) $("captureInput").focus(); });
  $("captureForm").addEventListener("submit", async (e) => {
    e.preventDefault(); const input = $("captureInput"), msg = $("captureMsg"); const text = input.value.trim(); if (!text) return;
    msg.classList.remove("err"); msg.textContent = "";
    try {
      const r = await postJSON("/api/capture", { text });
      vanish(input, $("vanish"));
      msg.textContent = r.target === "link-inbox" ? "✓ 链接已进收件箱" : "✓ 已记进灵感箱";
      setTimeout(() => (msg.textContent = ""), 3000);
    } catch (err) { msg.classList.add("err"); msg.textContent = err.message; }
  });
  $("radarBtn").addEventListener("click", () => runRadar($("radarBtn"), $("radarDone")));
  $("radarBtn2").addEventListener("click", () => runRadar($("radarBtn2"), $("radarDone2")));
  $("radarFilters").addEventListener("click", (e) => { const s = e.target.closest("span[data-f]"); if (!s) return; state.radarFilter = s.dataset.f; renderRadarAll(); });
  $("radarSort").addEventListener("click", (e) => { const s = e.target.closest("span[data-s]"); if (!s) return; state.radarSort = s.dataset.s; renderRadarAll(); });
  $("kwBtn").addEventListener("click", () => ($("kwPanel").hidden ? openKeywords() : ($("kwPanel").hidden = true)));
  $("kwCancel").addEventListener("click", () => ($("kwPanel").hidden = true));
  $("kwSave").addEventListener("click", saveKeywords);
  $("kwPanel").addEventListener("click", (e) => { const b = e.target.closest("button[data-p]"); if (!b) return; KW[b.dataset.p].splice(Number(b.dataset.n), 1); renderKeywords(); });
  document.querySelectorAll(".kw-add").forEach((f) => f.addEventListener("submit", (e) => {
    e.preventDefault(); const input = f.querySelector("input"); const w = input.value.trim(); const list = KW[f.dataset.p];
    if (w && !list.some((x) => x.toLowerCase() === w.toLowerCase())) list.push(w);
    input.value = ""; renderKeywords(); input.focus();
  }));
  document.querySelectorAll(".stat[data-col], #pipe").forEach((el) => el.addEventListener("click", () => (location.hash = "#board")));
  setupHover($("radarTodayZone"), "tbody tr"); setupHover($("radarAllZone"), "tbody tr");
  setupHover($("rvPendZone"), ".rv-item"); setupHover($("rvQueueZone"), ".rv-item");
  document.addEventListener("keydown", reviewKeys);
  $("applyBtn").addEventListener("click", applyReviews);
  $("vdFilters").addEventListener("click", (e) => { const s = e.target.closest("span[data-f]"); if (!s) return; VD.filter = s.dataset.f; renderVideoList(); });
  $("vdQ").addEventListener("input", (e) => { VD.q = e.target.value; renderVideoList(); });
  $("ingestBtn").addEventListener("click", runIngestNow);
  $("acctBtn").addEventListener("click", openAcct);
  $("acctPreviewBtn").addEventListener("click", acctPreview);
  $("acctStart").addEventListener("click", acctStart);
  $("acctCancel").addEventListener("click", closeAcct);
  $("acctScrim").addEventListener("click", closeAcct);
  $("vdList").addEventListener("click", (e) => { const a = e.target.closest(".vd-item"); if (a && a.dataset.path !== VD.cur) openVideo(a.dataset.path); });
  setupHover($("vdListZone"), ".vd-item");
  load(); loadVideos(); pollAccount();
  // ?shot=1 是截图模式：不连实时更新，否则无头浏览器会一直等这条连接
  if (!/[?&]shot=1/.test(location.search)) { try { const es = new EventSource("/api/events"); es.addEventListener("change", () => { load(); loadVideos(); }); } catch (_) { /* 没有事件流就手动刷新 */ } }
});
