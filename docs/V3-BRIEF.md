# 投研雷达 v3 改造任务书（给 Codex）

> **一句话**：研究内容改为**从 Notion 自动读取**；取消人工锁定，改为 **自动生成、标注清楚、自动检查**；首屏改版为「本周主线 + 今日要点 + 更新脉搏」。
>
> 版本 v3.0 · 2026-10-21 · 起草：Notion AI（v1/v2 雷达与设计的原作者）· 实现：Codex（全部代码）· 产品负责人：LWD
> 仓库 `lwd619783-byte/research-radar`（私有）· 线上 Vercel（登录保护）· 时间一律北京时间（Asia/Shanghai），另有注明除外。

**怎么用这份文件**

1. 按 §12 的顺序做 5 个 PR（PR1 → PR5），一次一个，合并后再开下一个。
2. 每个 PR 开工前，把 §12 里对应的「Codex 提示词」整段贴给 Codex。
3. 每个 PR 都要读：§0（规则总览）、§13（不要做）和该 PR 涉及的章节。
4. **以仓库实际为准**：本文件提到的现有文件、函数、字段，是起草人在 10/17–10/21 读仓库（commit `603181e`）时的记录。动手前先画仓库地图；遇到不一致时——**行为按本文件，结构按仓库**——并在 PR 描述的「与任务书的差异」一节列出来。
5. 本文件与 `radar/data/notion_schema.json`（契约）或 fixtures 的期望值冲突时，**以契约和 fixtures 为准**，并在 PR 描述里指出本文件哪一句需要改。

配套文件（随本文件一起放进仓库，见附录 B）：

| 路径 | 内容 |
|---|---|
| `radar/data/notion_schema.json` | **属性契约（唯一真相）**：6 张表每一列的类型、级别、映射、正则、长度、规则；禁用词、预测词、市场默认时区 |
| `radar/tests/fixtures/notion_v3/` | 离线 fixtures：Notion API `2026-03-11` 真实响应形状（10/21 数据）+ 期望结果 + 103 个用例 + README（测试怎么跑） |
| `docs/design/v3/` | 设计稿：`overview-v3.html`（首页目标效果）、`components-v3.html`（组件规格）、`v3-components.css`（新增样式）、`shots/`（截图） |

---

## 0. 一页看懂（12 条）

1. **数据源**：研究内容（行业、卡点、公司、财报、每日要点、每周主线）全部来自 Notion「投研雷达｜数据后台」的 6 个数据库，用只读 token 读取。行情、汇率、温度计仍走现有 `quotes.py` 等，算法不改。
2. **没有人工审核**：研究文字由 AI（用户的 ChatGPT 项目）写进 Notion。程序**不判断观点对错**，只做自动检查：格式、日期、有效期、来源链接、禁用词、与硬数据是否明显冲突。
3. **契约驱动**：读取和校验全部由 `radar/data/notion_schema.json` 驱动；按**属性名 / 选项名**读取（id 只用于诊断）；契约外的新列忽略。
4. **四级失败处理，页面从不变空**：字段有问题 → 置空/截断 + 警告；行有问题 → 隔离该行（有上次成功版本就沿用并标「待更新」，没有就不显示）；表有问题 → 整表沿用上次版本；全部读不到 → 全部沿用上次版本（行情照常更新）。只有「读不到且没有任何上次版本」才 `exit 2`、不发布。
5. **last-good** = 上一次成功发布里的 `research-snapshot.json`（那次实际使用的研究行的简化快照）。
6. **AI 研判有效**的 6 个条件：研判理由非空；来源至少 1 个 http(s) 链接；研判日期 ≤ 今天；有效至 ≥ 今天；有效至 − 研判日期 ≤ 14 天；无禁用词。缺任何一条 → 内容照常显示，标「待更新」并给出原因。
7. **数据档与冲突**：程序用硬数据给「业绩兑现」「卡点强度」算参考档；AI 分与参考档相差 ≥ 2 → 标「数据冲突」。**只提示，不改分**。
8. **每周主线回退链**：本周有效的 AI 行 → 最近 14 天内的行（标待更新）→ 程序按评分自动生成（标自动生成）→ 显示「本周主线待更新」。
9. **今日要点**：A股、美股各一行，日期 = 该市场最近一个已完成交易日（美股用美东日期）；没有有效行 → 程序用指数涨跌自动生成一句（标自动生成）。
10. **禁用词**（24 个，含「买入」「目标价」「已核实」等）与**预测词**（12 个，只管今日要点）：命中就丢弃该字段或该行。最终 HTML 里任何可见文本、提示与属性都不得出现禁用词。
11. **调度**：工作日 08:45 / 12:15 / 18:15 + 周一 06:50（北京时间）。每次：读 Notion → 拉行情 → 构建 → 检查 → 发布。`NOTION_TOKEN` 只出现在 collect 这一步。
12. **界面 v3**：首屏左「本周主线」、右「今日要点」，下面 KPI 和一行「更新脉搏」；不新增颜色；标签只标例外；页脚固定免责声明。按 `docs/design/v3/` 实现，视觉验收见 §10.12。

---

## 1. 背景与政策变更

### 1.1 现状（v2）

- `radar/site/`（`index.html` + `style.css` + `app.js` 单页）由 `radar/scripts/build.py` 把 DATA 渲染进 HTML；GitHub Actions `radar-production.yml` 定时拉行情 → 构建 → 检查 → `publish_release.sh` 发布到 Vercel。
- 研究内容写在 `radar/data/{industries,chokepoints,companies}.toml` 和 `config.toml [weekly]`。
- 10/18 的 truthfulness 修复把研究内容「冻结」：`audit/truthfulness-frozen.json` 锁定 site、data 与 workflow 文件哈希；preflight 做 frozen provenance 检查；页面用「原评分」「原标记」「核验状态见…」「待复核」「核验日期缺失」等措辞；`review`、`verified_at`、`flashStatus` 等字段表达“需要人工核验”。

### 1.2 新决定（产品负责人，10/21）

取消“研究内容锁定”，改为 **自动生成、标注清楚、自动检查**：

- 研究文字由 AI 写进 Notion，不经人工审核；网站**永远不说**“已核实 / 已审核 / 人工确认 / 已验证”。
- 每块 AI 内容都标明：谁写的（AI 研判 / AI 摘要 / 自动生成）、哪天写的、有效到哪天；不满足规则的照常显示，但标「待更新」并说明原因。
- 自动检查只管“能检查的事”：格式、日期、有效期、来源链接、禁用词、与硬数据的明显冲突。

### 1.3 保留什么、删什么

**保留（与研究锁定无关）**：行情/汇率/时点/覆盖率的真实性规则——每个价格带自己的日期与来源、汇率收讫与估算标记、缺失用占位、release blockers、receipt 绑定、fixedClock 新鲜度检查、`verify-release.cjs` 等。相关测试全部保留。

**删除（只为“冻结/人工核验研究内容”服务）**：

- `audit/truthfulness-frozen.json` 对 `radar/site/*`、`radar/data/*.toml`、workflows 的哈希锁（文件若只做这件事就整个删除）；
- preflight 里的 frozen provenance 检查；`test_truthfulness.py` 等测试里「锁哈希」「必须出现 原评分/核验 措辞」一类断言（行情类断言保留，必要时改写）；
- DATA 字段：`industries[].review`、`chokepoints[].review`、`meta.weekly.review`、`meta.weekly.thermoAction`、`companies[].flashStatus`、`earnings.published_at / verified_at`；`provenance.financial.verified_at` 改名 `entered_at`，`provenance.financial.status` 改为 `evidence`；
- 页面措辞：所有「核验 / 核实 / 核对 / 待复核 / 待核 / 原评分 / 原标记 / 人工评分」（唯一例外：页脚免责声明里的“未经人工审核”）。

---

## 2. 目标与非目标

**目标**

- G1 每个交易日自动更新 3 次、周一早上自动切换周次；日常不需要人碰 GitHub 或 Vercel。
- G2 研究内容只在 Notion 维护（由 ChatGPT 写）；仓库里不再改研究文字。
- G3 每块 AI 内容有标注；过期/缺项自动「待更新」；与硬数据冲突自动提示。
- G4 Notion 出任何问题，页面都不会变空或报错：最坏情况是“沿用上次版本 + 黄点提示”。
- G5 首屏一眼看到：本周主线、今日要点、更新是否正常。
- G6 全部可离线测试（fixtures + FakeTransport），同输入同输出（逐字节相同）。

**非目标（这次不做）**

- 不做账号、付费墙、订阅；不写回 Notion；网站不调用任何大模型（程序只用固定模板）。
- 不改行情源、估值、温度计、比值算法；不引入前端框架或打包工具（保持单页 + `build.py` 渲染）。
- 不显示港股每日要点（读取但不显示）；不做多语言。

---

## 3. 架构

### 3.1 新增 / 修改的模块（`radar/scripts/`）

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `notion_source.py`（新） | HTTP：请求、节流、重试、分页、体积上限、错误归类；返回每张表的 schema、原始 pages、请求统计 | 不解析业务字段 |
| `notion_normalize.py`（新） | 按契约把 page 变成「简化行」→ 字段 / 行 / 表三级校验 → DATA 行；产出 warnings、quarantined | 不发网络请求 |
| `research_snapshot.py`（新） | 读写 `research-snapshot.json`；按 page id 用 last-good 替代坏行；整表回退 | — |
| `research_view.py`（新） | 研判标签、数据档/冲突、每周主线回退链、今日要点选择、自动模板、KPI 辅助数 | 不读网络、不读文件 |
| `build.py`（改） | 增加 `--source notion\|toml`（PR2 默认 toml；PR4 默认 notion；PR5 删除 toml） | 不改行情逻辑 |
| `production_release.py`、`release_operations.py`、`daily_changes.py`、`verify-release.cjs`（改，PR4） | 快照进 bundle、`release.json` v3、读取 last-good、今日变化 | — |
| `tools/export_notion_fixtures.py`（新，放 `radar/tools/` 或仓库现有工具目录） | 用只读 token 重新导出 fixtures（人手动跑） | 不在 CI 里跑 |

依赖：**只用 Python 标准库**（`urllib.request`、`json`、`hashlib`、`unicodedata`、`re`、`zoneinfo`、`datetime`、`decimal`）。不新增第三方包。

### 3.2 数据流

```
               Notion 6 库（只读 token）
                        │
notion_source ── schema + 原始 pages ──▶ notion_normalize ──▶ 简化行 → DATA 行 + warnings / quarantined
                                                 │
上次发布的 research-snapshot.json ──▶ research_snapshot（坏行 / 坏表 → last-good）
                                                 │
                    research_view（研判标签、数据档、主线、今日要点、模板）
                                                 │
quotes.py 等（行情 / 汇率 / 温度计，不变；公司清单改为来自 Notion）
                                                 ▼
                  build.render → DATA → index.html（同时写 research-snapshot.json）
                                                 ▼
          production_release（bundle、release.json v3、verify）→ publish_release.sh
```

### 3.3 一次构建的顺序

1. 读契约并自检（JSON 合法、6 张表与必需字段齐全）。契约坏 → `exit 2`（这是代码问题，不是数据问题）。
2. 读 last-good（可以没有）。
3. 读 Notion（§4）→ 规范化（§5）→ 合并 last-good（§8.3）。
4. 把公司清单（Notion 的公司，最多 80 家）交给行情步骤。
5. 行情 → 研判/视图计算（§6）→ render → 自检（禁用词扫描、DATA 结构）→ 写文件。

### 3.4 配置（`radar/data/config.toml`；PR2 加 `[notion]` `[daily]`，PR4 加 `[schedule]`）

```toml
[notion]
contract = "notion_schema.json"     # 相对 radar/data
api_base = "https://api.notion.com"
version = "2026-03-11"
timeout_seconds = 20                # 单个请求
phase_budget_seconds = 180          # 整个 Notion 阶段
max_body_bytes = 8388608            # 8 MB，边读边计数
max_pages_per_table = 50            # 每页 100 行
min_interval_seconds = 0.34         # 节流，约 3 次/秒
quality_threshold = 0.20            # 坏行占比 > 20% 且表 ≥ 5 行 → 整表 last-good
quality_min_rows = 5

[daily]
markets = ["A股", "美股"]            # 显示顺序；港股读取但不显示
chips."A股" = ["000001.SS", "399006.SZ", "HSTECH.HK"]
chips."美股" = ["^IXIC", "^GSPC", "^SOX"]
short = { "000001.SS" = "上证", "399006.SZ" = "创业板", "HSTECH.HK" = "恒生科技", "^IXIC" = "纳指", "^GSPC" = "标普500", "^SOX" = "费城半导体" }

[schedule]
cron_utc = ["45 0 * * 1-5", "15 4 * * 1-5", "15 10 * * 1-5", "50 22 * * 0"]
late_after_minutes = 90
```

- 自动模板里的指数名用 `indices[].name`（config 里的全名，如「创业板指」「标普500」「费城半导体」）；今日要点下方的指数小字用 `short`。
- 旧的 `[weekly]`（手写主线）在 PR5 删除。
- `cron_utc` 必须与 workflow 里的 `schedule` 完全一致（加一个测试比对两处）。

---

## 4. Notion 访问

### 4.1 Token 与权限

- 用户在 Notion 开发者门户建一个 **internal connection**（旧称 internal integration；能力只勾 *Read content*），把它添加到页面「投研雷达｜数据后台」（6 个库继承权限）。token 存为 GitHub Secret **`NOTION_TOKEN`**（步骤见附录 A）。
- token 只出现在 workflow collect 步骤（以及手动 dry-run job）的 `env` 里；其他步骤拿不到。
- token **绝不**出现在：日志、异常信息、DATA、snapshot、artifact、step summary。`Authorization` 头不得被打印；所有异常统一转成 `NotionError(code, table, http_status, notion_code)`，只带这些字段。用例 X01 会在日志和产物里搜 token 字符串。
- 没有 token（未设置或为空）→ 0 个请求，6 张表全部 last-good，code `notion_token_missing`，exit 0（T01）。

### 4.2 请求序列

按表顺序 `industries → chokepoints → companies → financials → daily → weekly` **串行**读取，每张表：

1. `GET /v1/data_sources/{data_source_id}` → schema 检查（§4.6）。失败 → 该表 last-good，跳过 query。
2. `POST /v1/data_sources/{data_source_id}/query`，body 固定 `{"page_size": 100}`；有 `next_cursor` 时加 `"start_cursor"`（原样回传，不解析）。**不带 filter / sorts**（停用等在代码里排除，排序在代码里做）。

请求头：`Authorization: Bearer <token>`、`Notion-Version: 2026-03-11`、`Content-Type: application/json`、`Accept: application/json`、`User-Agent: research-radar/3`。
基线 = **13 个请求**（6 GET + 7 POST，公司表 2 页）。ID 见附录 C 与契约 `tables.*.data_source_id`。

### 4.3 节流、超时、重试

- 节流：相邻两个请求间隔 ≥ `min_interval_seconds`。节流通过单独注入的 `pace()` 实现（测试里为空操作），**不计入** `transport.sleeps`。
- 单个请求超时 20 秒；整个 Notion 阶段预算 180 秒，用完 → 还没读的表记 `notion_timeout` 并 last-good。
- 每个请求最多重试 3 次（最多 4 次尝试）；等待通过注入的 `sleep()`，测试里记录在 `transport.sleeps`。

| 情况 | 重试 | 等待 | 用尽后 | code | 用例 |
|---|---|---|---|---|---|
| 401 | 不重试，**立即停止所有请求** | — | 6 张表全部 last-good（已读到的表也不用，避免新旧混用） | `notion_unauthorized` | T02 T12 X01 |
| 403 | 同 401 | — | 同 401 | `notion_forbidden` | — |
| 404 | 不重试 | — | 该表 last-good，其他表继续 | `notion_not_found` | T03 |
| 429 | 最多 3 次 | `min(Retry-After, 60)` 秒；没有该头 → 1 / 2 / 4 | 该表 last-good | `notion_rate_limited` | T04 T13 |
| 5xx | 最多 3 次 | 1 / 2 / 4 | 该表 last-good | `notion_server_error` | T05 |
| 超时 / 连接错误 | 最多 3 次 | 1 / 2 / 4 | 该表 last-good | `notion_timeout` | T06 |
| 200 但不是 JSON 或结构不对 | 不重试 | — | 该表 last-good | `notion_bad_json` | T07 |
| 响应体 > 8 MB | 不重试（边读边计数，超了立即断开） | — | 该表 last-good | `notion_body_too_large` | T09 |
| `next_cursor` 重复出现 | — | — | 该表 last-good | `notion_cursor_loop` | T08 |
| 分页超过 50 页 | — | — | 该表 last-good | `notion_too_many_pages` | — |
| 其他 4xx（400、409 等） | 不重试 | — | 该表 last-good | `notion_http_error` | — |

### 4.4 结果过滤

- `results[]` 里 `object != "page"` → 跳过，不报警（T10）。
- `in_trash == true` → 排除，不报警（T11）。2026-03-11 起字段名是 `in_trash`，不是 `archived`。
- `停用` 勾选 → 排除，不报警。级联：行业停用 → 其卡点、公司、财报都排除（R13）；卡点停用 → 相关公司 `cp` 置空（R14）；公司停用 → 其财报排除（F12）。
- 被排除的行不进 snapshot，也不计入坏行比例。

### 4.5 简化行（simplified row）

每个 page → `{id, created_time, last_edited_time, props}`；`props` 只含契约里 level ≠ ignore 的列：

| Notion 类型 | 简化值 |
|---|---|
| title / rich_text | 所有片段的 `plain_text` 直接拼接后 `strip()`；不读 annotations、href；mention 片段同样只取 `plain_text`（X03） |
| number | 数字或 `null` |
| select | 选项**名称**或 `null` |
| checkbox | `true` / `false` |
| date | `start` 的前 10 位 `YYYY-MM-DD` 或 `null`（忽略 end、time_zone） |
| url | 字符串或 `null`（scheme 在规范化时检查） |
| relation | page id 列表（保持 API 顺序）；属性带 `has_more: true` 时视为“超过上限” |
| formula 等 ignore 列 | 不读 |

简化行是 last-good 的存储单位：坏行替代、整表回退，都是“拿旧的简化行，按今天的时钟重新走一遍规范化”。

### 4.6 Schema 检查

`GET data_source` 后，按**属性名**逐列核对契约里 level ≠ ignore 的列：缺失或类型变化 → 整表 last-good，code `notion_schema_changed`，`detail = {prop, change: "missing" | "type_changed", expected, actual}`（S01 S02 S07）。契约外的新列忽略（S04）；ignore 列被删除不报警（S06）；select 新增选项不报警（S03），只有被某行使用时，该行按 `invalid_enum` 隔离（S05）。

---

## 5. 属性契约摘要（细节以 `notion_schema.json` 为准）

### 5.1 级别

| level | 不合格时 |
|---|---|
| `row` | 该行隔离（quarantine） |
| `judgment` | 照常显示，研判标签降为「待更新」并给出 reasons |
| `evidence` | 决定财报证据等级（有原文 / 部分 / 缺来源） |
| `optional` | 格式不对 → 置空 + warning |
| `ignore` | 程序不读（Notion 公式只给人看，如「总分」「研判状态」） |

### 5.2 六张表

| 表 | key（唯一） | 排序 | row 级必填 | 备注 |
|---|---|---|---|---|
| 行业 `industries` | 名称 | 总分↓ → 景气度↓ → 名称 | 名称、四项分（1–5 的整数） | 总分由程序重算 = 四项之和；`kb` = Notion 页面 URL |
| 卡点 `chokepoints` | 名称 | 所属行业顺序 → 排序↑（空 = 9999）→ 名称 | 名称、行业（恰好 1 个）、紧缺度 | 紧缺度映射为 DATA 现有值 `🔴极紧 / 🟠偏紧 / 🟢缓解中` |
| 公司 `companies` | 代号 | 所属行业顺序 → 代号；最多 80 家 | 名称、代号、Yahoo代码、显示代码、市场、币种、定位、行业 | 代号永不修改、不自动转大写；Yahoo 代码按市场正则 |
| 财报记录 `financials` | (公司, 财年, 期间, 口径) | — | 公司、财年、期间、口径、显示期间、期末日、发布日、报告状态、币种 | 百分比列 ÷100 后进 DATA |
| 每日要点 `daily` | (日期, 市场) | — | 日期、市场、一句话 | 只显示 A股、美股 |
| 每周主线 `weekly` | 周次 | — | 周次（`YYYY-Www`）、主线行业（恰好 1 个）、导语 | — |

### 5.3 行级规则

- 隔离原因（row codes）：`missing_required` `number_out_of_range` `number_not_integer` `invalid_enum` `regex_mismatch` `relation_missing` `relation_multiple` `duplicate_key` `period_after_publish` `publish_in_future`。
- relation 指向的行不可用（不存在、被隔离且没有替代）→ 本行按 `relation_missing` 隔离；指向**停用**行 → 按 §4.4 级联排除或置空，不报警。
- 重复 key：一般 → `created_time` 较晚的那行隔离（相同则 page id 较大的隔离），code `duplicate_key`。**两个例外**：
  - 财报重复 → 保留 `录入日` 较晚的一行（相同或为空 → `last_edited_time` 较新者；再相同 → page id 较小者），另一行丢弃，warning `financial_duplicate`（F04）；
  - 每日要点重复 → 保留 `last_edited_time` 较新的一行，warning `daily_duplicate`（D05）。
- 坏行比例：某表隔离行数 ÷ 该表有效 page 数（不含排除）> 20%，且该表 ≥ 5 行 → 整表 last-good，code `table_quality_low`（Q01：4/15 触发；Q02：3/15 = 20% 不触发）。
- 替代范围：`industries / chokepoints / companies / financials` 的坏行可用 last-good 中**同 page id** 的旧版本替代；`daily / weekly` 的坏行直接跳过，由回退链处理（W05）。

### 5.4 字段规则要点

- **文本**：拼接 → strip → 禁用词检查 → 长度。超过 `soft_len` → `text_long`（info 级，不截断）；超过 `hard_len` → 截断到 `hard_len − 1` 个单位再加 “…”，warning `text_truncated`。长度单位 = Python `len()`（Unicode 码位）；每个 `{{earnings:代号}}` 按 10 计；截断点落在 token 里 → 整个 token 去掉（P19）。
- **列表**：「最新信号」按「；」拆、最多 4 条；「代表公司」按「、」拆、最多 12 个；超出截掉 + `list_truncated`。DATA 里仍是用原分隔符连接的字符串。
- **URL**：从文本里用正则 `https?://[^\s<>"'）)]+` 提取，去重保序；`url` 类型列要求 `https`，否则置空 + `url_invalid`。研判「来源」接受 http 与 https。
- **百分比**：`营收同比% 174.6` → `revg = 1.746`；越界、可疑、疑似小数的规则见契约（`pct_out_of_range` / `pct_suspicious` / `pct_maybe_fraction`）。
- **日期**：快讯日期晚于今天 → 当作今天 + `flash_date_future`；下次财报日早于今天 → 保留 + `earnings_date_past`。
- **时区**：财报日时区为空 → `""`（页面用市场默认时区）；非法 IANA → 市场默认时区 + `timezone_invalid`。
- **token**：`{{earnings:代号}}` 指向不存在或已停用的公司 → `token_unknown_company`；DATA 保留原始 token，页面渲染为「日期待定」（C04）。
- **公司上限**：超过 80 家 → 按「所属行业顺序 → 代号」保留前 80，warning `company_cap_exceeded`，`detail.dropped` 列出被丢的代号（P13）。
- **禁用词**：先 `unicodedata.normalize("NFKC")`，再删除所有空白（`\s` 与全角空格 U+3000），然后做子串匹配（R17）。命中 → 该字段置空 + `banned_words`；研判表同时在 reasons 里加 `banned_words`；每日/每周行整行作废。

---

## 6. 标注规则

### 6.1 页面上只有这几种标签

| 标签 | class | 含义 | 出现在哪 |
|---|---|---|---|
| AI 研判 | `.st.ai` | AI 写的判断，6 个条件全部满足 | 主线来源行、行业评分卡标题、行业/卡点详情顶部 |
| AI 摘要 | `.st.ai` | 每日要点里 AI 写的一句话 | 今日要点卡标题 |
| 自动生成 | `.st.auto` | 程序按数据用模板生成的文字或分类 | 兜底一句话、自动主线、温度计说明 |
| 待更新 | `.st.stale` | AI 内容缺项、过期或被隔离；内容照常显示 | 例外的行或卡 |
| 数据冲突 | `.st.conflict` | AI 分与数据档相差 ≥ 2 | 行业评分行、行业详情分项 |
| 有原文 / 部分 / 缺来源 | `.st.src` / `.st.src.part` / `.st.src.none` | 财报证据等级 | 公司抽屉里总是显示；表格里只显示「部分」「缺来源」 |

- **标题多数原则**：一张卡或一个列表，在标题处显示“多数行”的标签一次；与多数不同的行才在行内显示自己的标签；「数据冲突」总是逐行显示。没有任何一行来自 AI 时，标题不显示 AI 标签。
- 每个标签可聚焦（`tabindex="0"`），`data-tip` 给出原因（中文文案见附录 E）。

### 6.2 研判（judgment）——行业、卡点、每周主线

```python
reasons = []
if not 研判理由:                        reasons.append("missing_reason")     # 含因禁用词被置空
if not urls(来源):                       reasons.append("missing_source")
if 研判日期 is None or 有效至 is None:    reasons.append("missing_dates")
else:
    if 研判日期 > today:                 reasons.append("future_judgment_date")
    if 有效至 < today:                   reasons.append("expired")            # 有效至 == today 仍有效
    if (有效至 - 研判日期).days > 14:      reasons.append("validity_too_long")
if 本行任一 AI 文本命中禁用词:            reasons.append("banned_words")
if 本行是 last-good 替代行:               reasons.append("row_quarantined")
label = "ai" if not reasons else "stale"
```

- `today` = 本次构建 fixedClock 换算到北京时间的日期。
- 每周主线：行的周次 ≠ 当前 ISO 周时，在 reasons **最前面**加 `not_current_week`。
- `stale` 不影响内容：分数、文字照常显示（R05）。
- 整表回退时，各行标签照常按今天计算，不强制待更新（Q01）；只有单行替代才加 `row_quarantined`（S05）。
- DATA：`judgment = {label, reasons, date, validUntil, reason, sources}`；`sources` 是 URL 数组；行业另有 `anchors`、`conflicts`。

### 6.3 数据档（anchors）与冲突——只给行业

- **业绩兑现**：样本 = 该行业中 `financialRevenueComparable == true` 且 `revg` 非空的公司（与页面「单季营收同比 · 中位数」同一口径，§7.3）。样本 ≥ 3 家时，取营收同比中位数（%，`ROUND_HALF_UP` 保留 1 位），按这个数分档：≥ 50 → 5；≥ 25 → 4；≥ 10 → 3；≥ −10 → 2；否则 1。不足 3 家 → 不出档。
- **卡点强度**：该行业卡点里最紧的一级：极紧 → 5，偏紧 → 4，缓解中 → 2；没有卡点 → 不出档。
- `anchors = {"业绩兑现": {anchor, n, medianRevenueYoYPct}, "卡点强度": {anchor, n, maxTightness}}`；不出档的项不写。
- 冲突：`|AI 分 − anchor| ≥ 2` → `conflicts.append({field, ai, anchor})`。标签仍按 §6.2 计算，**不改分**（R12）。
- 基线：AI网络与光互连 5（9 家，+85.5%）、AI核心半导体 5（9 家，+55.2%）、PCB与覆铜板 5（10 家，+60.9%）、电力与数据中心 3（11 家，+18.1%）；无冲突。
- 提示文案：`业绩兑现：AI 2 · 数据档 5（营收同比中位数 +85.5%，9 家）`；`卡点强度：AI 3 · 数据档 5（最紧卡点为「极紧」）`。

### 6.4 每周主线（`meta.weekly`）

当前周 `W` = 今天（北京时间）的 ISO 周；`weekStart` = 周一，`weekEnd` = 周日。先丢掉作废行（row 级不合格；**任一 AI 文本命中禁用词也整行作废**，W04）和周次晚于 `W` 的行（提前写的下周行，等到那周再用，不报警）。

| 步骤 | 条件 | mode | judgment.label | 内容 |
|---|---|---|---|---|
| 1 | 有周次 = `W` 且研判有效（label ai）的行 | `ai` | ai | 该行 |
| 2 | 否则：取研判日期 ≤ 今天、且距今 ≤ 14 天的行中研判日期最新的一行（同日 → 周次大者 → page id 小者） | `stale` | stale（reasons 见 §6.2） | 该行 |
| 3 | 否则：至少 1 个行业 label = ai | `auto` | auto（reasons `["no_weekly_row"]`） | focus = 排序最前的 AI 有效行业；lead、calHint 用模板 |
| 4 | 否则 | `none` | stale（reasons `["no_weekly_row"]`） | focus / lead / calHint 为 `""`；页面显示「本周主线待更新」 |

- 模板 lead：`本周综合分最高：「{行业}」（{总分}/20）；最紧卡点「{卡点}」。`；卡点 = 该行业最紧的卡点（极紧 > 偏紧 > 缓解中，同级按 排序 → 名称）；没有卡点就只写前半句并以「。」结尾。
- calHint：步骤 1、2 用行里的「日历提示」；为空或步骤 3 → 模板 `本周 {n} 家公司预计发布财报`（n = 下次财报日在 `weekStart..weekEnd` 的公司数，含预估）；n = 0 → `""`。
- DATA：`meta.weekly = {week, weekStart, weekEnd, sourceWeek, mode, focus, lead, calHint, judgment}`；`sourceWeek` = 所用行的周次（步骤 3、4 为 `""`）。
- 基线：`mode = stale`，`sourceWeek = 2026-W42`，`reasons = ["not_current_week", "expired"]`（这就是线上当前的真实状态，W02）；W01 → ai；W03 → auto；W06（时钟 11/02）→ none，`week = 2026-W45`；W07（有效期 20 天）→ stale `["validity_too_long"]`。

### 6.5 今日要点（`meta.daily`）

- 每个市场 `m ∈ [daily] markets` 的目标日期 = 该市场**最近一个已完成交易日**：生产用行情侧已有的按市场完成日（现有 `meta.snapshot.sourceAsOfByMarket` / `asOfByMarket`，以仓库实际为准）；测试用 `cases.json → trading_days`。美股用美东日期（北京时间 10/21 18:15 时，美股是 10/20）。
- 候选行：市场 = m 且日期 = 目标日期。日期晚于目标 → 忽略 + `daily_future_date`（D09）；早于目标 → 静默忽略（D02）。
- 行作废：一句话为空；命中禁用词（`banned_words`，D04）；命中预测词（`prediction_words`，D03）。截断不作废（D06）。
- 有效行 → `source = "ai"`；`reviewUrl` 必须 https，否则 `""` + `url_invalid`（D08）；涉及行业最多 3 个（`relation_truncated`，D10），停用的去掉。
- 没有有效行 → `source = "auto"`，`line` = 模板句，`reviewUrl = ""`，`industries = []`（D01）。
- `chips`：按 `[daily] chips[m]` 顺序，只放 `asOf` 等于该行日期的指数 `{symbol, label(short), chg}`；日期不同的（例如香港休市）不放。
- 模板（用 chips 里的指数，名称用 `indices[].name`；先把 `chg×100` 按 `ROUND_HALF_UP` 保留 2 位，再按这个值判断涨/跌/平；同值取 chips 顺序靠前者）：

| 情况 | 句子 |
|---|---|
| 全部上涨 | `主要指数集体上涨，{最大}涨 x.xx% 领涨` |
| 全部下跌 | `主要指数集体下跌，{最小}跌 x.xx% 领跌` |
| 有涨有跌 | `主要指数涨跌互现，{最大} +x.xx%，{最小} −x.xx%` |
| 有涨有平、无跌 | `主要指数未见下跌，{最大}涨 x.xx% 领涨` |
| 有跌有平、无涨 | `主要指数未见上涨，{最小}跌 x.xx% 领跌` |
| 全部持平 | `主要指数基本持平` |
| 没有可用指数 | `""`（页面显示「今日要点待更新」） |

  基线模板结果（行无效时才会用到）：A股 `主要指数集体下跌，创业板指跌 1.62% 领跌`；美股 `主要指数涨跌互现，标普500 +0.28%，费城半导体 −0.29%`。
- DATA：`meta.daily = {"A股": {date, source, line, reviewUrl, industries, chips}, "美股": {...}}`；港股不写（D07）。

### 6.6 页面怎么用这些标签（摘要，完整见 §10）

- 主线来源行：`[AI 研判] 10/19 研判 · 有效至 10/26 · 依据 3 条 · 查看理由`；stale → `[待更新] 10/12 研判 · 已于 10/19 过期 · 显示上次结论 · 查看理由`；缺项 → `[待更新] 缺来源链接 · 内容照常显示`；auto → `[自动生成] 本周还没有主线研判，按行业评分自动选出`；none → 标题「本周主线待更新」，不显示来源行。
- 行业评分卡标题：多数为 ai → `[AI 研判] 10/19 · 每周一更新`；行内只出现例外（「待更新」「数据冲突」）。
- 今日要点卡标题：两行都是 ai → `[AI 摘要]`；某行是 auto → 该行显示 `[自动生成]` 与「复盘未更新」。


---

## 7. 财报与公司字段

### 7.1 证据等级（`provenance.financial.evidence`）

按顺序判断，先命中先算：

| evidence | 条件 | 页面标签 | 参与统计与信号 |
|---|---|---|---|
| `missing` | 来源链接 为空或不是 https（`http://` 另记 `url_invalid`，F01 F14） | 「缺来源」`.st.src.none`，数字灰显 | 不参与任何统计 |
| `source` | 口径 = 单季，且 报告状态 ∈ {正式报告, 仅营收} | 抽屉里显示「有原文」`.st.src`；表格里不标 | 见 §7.3 |
| `partial` | 其余：口径为半年 / 累计 / 全年，或报告状态为业绩快报 / 业绩预告 / 初步结果 | 「部分」`.st.src.part` | 只展示，不参与 |

### 7.2 每家公司显示哪一条财报

1. **候选** = 该公司所有可用财报行：本行与所属公司都未停用（F12）；通过行级校验，或已用 last-good 同 page id 版本替代（F02 F03 F13）；重复 key 已按 §5.3 去重（F04）。
2. **池** = 候选中 evidence ≠ `missing` 的行；池为空 → 用全部候选。
3. **排序取第一条**：期末日（新 → 旧）→ 口径（单季 > 半年 > 累计 > 全年）→ 报告状态（正式报告 > 业绩快报 > 初步结果 > 业绩预告 > 仅营收）→ 发布日（新 → 旧）→ page id（小 → 大）。
   - 期末日排第一是有意的：新录入的 Q3 正式报告取代 Q2（F09）；Q3 业绩预告也会取代 Q2，但显示「部分」、不参与信号（F10）。页面总是显示最新一期，同时把证据等级标清楚。
4. 没有候选 → `revg / earng / gm = null`，`period = ""`，`provenance.financial = null`，三个布尔都是 `false`；页面财务列显示「—」，抽屉写「暂无财报记录」。

### 7.3 映射与可比口径

| DATA | 规则 |
|---|---|
| `revg` / `earng` / `gm` | 营收同比% / 净利同比% / 毛利率% ÷ 100；空 → `null`（越界、可疑、疑似小数见契约） |
| `period` | 显示期间，原样（如 `2026Q2单季（H1−Q1）`） |
| `financialPartial` | `evidence == "partial"` |
| `financialRevenueComparable` | `evidence == "source"` 且 报告状态 = 正式报告 且 `today − 期末日 ≤ 200` 天（F15：204 天 → false；F16：正好 200 天 → true） |
| `financialSignalEligible` | `financialRevenueComparable` 且 利润可比性 = 可比 |
| `provenance.financial` | fixtures README 里的 `FIN_KEYS`（含 `entered_at`、`evidence`）+ `rowSource`（`notion` / `last_good`）；`source_urls` = [来源链接] + 其他来源里的 URL（去重保序） |

- **一个口径**：页面「单季营收同比 · 中位数」和业绩数据档（§6.3）只用 `financialRevenueComparable == true` 的公司；业绩信号（高增 / 增长 / 平稳 / 下滑）和「业绩高增龙头」KPI 只用 `financialSignalEligible == true` 的公司，算法沿用现有代码（先取净利同比，没有再取营收同比；≥ 50% 高增、≥ 10% 增长、> −10% 平稳、其余下滑）。现有页面已经在用这三个布尔，逻辑不改，只是它们改由上表计算。
- **不参与信号的公司**：信号位置显示「不适用」（旧文案「待核/不适用」），提示写原因：部分 / 缺来源 / 利润不可比 / 期末日超过 200 天。
- **净利同比显示**（不可比时显示文字，不显示数字）：可比 → 数字；扭亏 → 「扭亏」（F08，提示「上年同期为亏损，同比不适用」）；一次性 → 「一次性」（提示「含一次性项目，利润不可比，不参与信号」）；未披露 → 数字灰显（提示「利润可比性未披露，不参与信号」），没有数字则「—」。
- **部分**：数字灰显 +「部分」+ 期间，如「部分 · 2026Q3预告」；提示 `{显示期间} · {报告状态} · 只展示，不参与信号`。
- **缺来源**：数字灰显 +「缺来源」；提示「没有来源链接，不参与任何统计」。

### 7.4 下次财报日（`next`、`earnings`）

- `next` = 下次财报日；空 → `null`，页面「日期待定」（P07）。早于今天 → 保留 + `earnings_date_past`（P08）：不进「两周内财报」和日历的未来日期，公司抽屉显示原日期并标「待更新」。
- `earnings.status = "confirmed"` 当且仅当：`next` 非空、财报日状态 = 官方确认、财报日来源是 https。官方确认但没有 https 来源 → `unverified` + `earnings_confirmed_without_source`（P06）。财报日状态为空 → `unverified`。
- 页面编码（与设计稿 ⑥ 一致）：confirmed → 实心胶囊「10/31 · 官方确认」，并链接来源 ↗；unverified → 空心胶囊「10/31 · 预估」；`null` → 虚线「日期待定」。图例 `.cf-legend` 每屏只出现一次。
- 时区：日期按**公司所在地时区**显示，不换算成北京时间。`earnings.timezone` 为空 → 用契约 `market_timezones` 里的市场默认时区；时区中文名见附录 E（如 `Asia/Seoul` → 韩国时间）。`time_note` 放进胶囊提示：`SK海力士 · 官方确认 · 韩国时间 09:00 前发布`。
- DATA 删除 `earnings.published_at` 与 `earnings.verified_at`。

### 7.5 快讯

- `flash` = 快讯（token 与长度规则见 §5.4）；`flashDate` = 快讯日期（晚于今天 → 记为今天 + `flash_date_future`，P15）；`flashFresh` = `flashDate` 非空且 `today − flashDate ≤ 30` 天（空 → `false`）；`flashSource` = 快讯来源（https，否则 `""`）。
- 页面：`flashFresh` → 正常显示；否则灰显并在前面加日期「9/15」，不在首页突出（P12）；有 `flashSource` → 末尾加 ↗。
- DATA 删除 `flashStatus`。

### 7.6 公司清单与行情

- 公司清单 = 规范化并合并 last-good 之后的公司（≤ 80 家，P13），顺序 = 所属行业顺序 → 代号。行情步骤按 `sym`（Yahoo代码）拉取，`code`、`mkt`、`cur` 来自 Notion；`marketTimezone`、`priceAsOf` 等仍由现有行情逻辑产生。
- 新加的公司第一次拉不到历史 → 价格类字段为空，页面显示「—」，不阻塞发布。
- 停用或删除的公司从 DATA 消失；它们的财报一并排除。

---

## 8. 管线、调度与发布

### 8.1 生产 workflow（`radar-production.yml`）改动

| 步骤（名称以仓库为准） | v3 改动 |
|---|---|
| baseline | 取上一次成功发布的文件时，多取一个 `research-snapshot.json`。上次 `release.json.schemaVersion < 3`（v2 发布没有快照）→ 视为没有 last-good |
| preflight | 删除 frozen provenance 检查（PR1）；其余检查保留 |
| collect | 先读 Notion，再拉行情。**只有这一步的 `env` 有 `NOTION_TOKEN`**。读取结果写成 `work/notion-fetch.json`（不含 token）→ 规范化 + 合并 last-good → 公司清单交给行情 |
| build / prepare | 产出 DATA v3（附录 D）；bundle 增加 `research-snapshot.json`；`release.json` 升到 `schemaVersion: 3`，新增 `researchSnapshotSHA256` 和 `notion` 摘要（`source`、`requests`、`counts`、`fallbackTables`、`warningCount`、`quarantinedCount`） |
| verify | `verify-release.cjs` 新增：快照 sha256 与 `release.json` 一致；免责声明全文恰好出现 1 次；可见文本与属性无禁用词；DATA 含 `meta.notion`、`meta.schedule` |
| publish | 不变（`publish_release.sh`） |

- `work/notion-fetch.json` = `{fetchedAt, requests, sleeps, tables: {<table>: {ok, code, detail, schema: {属性名: 类型}, rows: [简化行]}}}`。后面的步骤只读这个文件，**不再访问 Notion**；构建可以离线重放。
- 如果 workflow 还没有并发保护，加 `concurrency: {group: radar-production, cancel-in-progress: false}`。

### 8.2 调度

| cron（UTC） | 北京时间 | 为什么是这个点 |
|---|---|---|
| `45 0 * * 1-5` | 周一至周五 08:45 | 美股收盘、ChatGPT 约 08:15 写完美股复盘之后 |
| `15 4 * * 1-5` | 周一至周五 12:15 | A股、港股午间 |
| `15 10 * * 1-5` | 周一至周五 18:15 | A股收盘、约 17:50 写完 A股复盘之后 |
| `50 22 * * 0` | 每周一 06:50 | 切换到新的 ISO 周；本周主线进入新周状态 |

- GitHub 的定时任务在整点前后负载最高，可能延迟甚至被丢弃，所以全部避开 `:00`（[GitHub 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)）。
- **定时任务只在默认分支上触发**（同上文档）。现在生产 job 的 `if` 要求分支 = `fix/radar-truthfulness-2026-10-18`（`production_release.py` 的 `SOURCE_BRANCH` 也是它）。如果默认分支不是这个分支，schedule 触发的 run 会被 `if` 跳过——**定时更新实际不会发生**。PR4 必须：
  1. 运行 `gh api repos/lwd619783-byte/research-radar --jq .default_branch` 和 `gh run list --workflow radar-production.yml --event schedule --limit 20`；
  2. 把结果写进 PR 描述，并给用户二选一：**A** 用户在 GitHub「Settings → General → Default branch」把默认分支改成生产分支；**B** 把生产分支改成默认分支（改 `SOURCE_BRANCH`、workflow 的 `if` 和相关测试）；
  3. **不要自己改仓库设置。**
- 保留现有守卫：仓库名、分支、事件类型、`GITHUB_RUN_ATTEMPT == 1`。
- `meta.schedule = {cronUtc, nextRunAt, lateAfterMinutes}`：`nextRunAt` = fixedClock 之后的第一个 cron 时刻（北京时间 ISO 字符串）。页面据此显示「下次 10/22 08:45」并判断是否迟到（§10.3）。
- `[schedule] cron_utc` 与 workflow 里的 `schedule` 必须完全一致（测试比对）。

### 8.3 last-good 合并

```python
snap = load_last_good()        # 上次发布的 research-snapshot.json；不存在 / 损坏 / 版本不对 → None
fetch = load("work/notion-fetch.json")

# 1) 表级
if fetch.stopped_all:          # notion_token_missing / notion_unauthorized / notion_forbidden
    want_last_good = set(TABLES)          # 已读到的表也不用，避免新旧混用
else:
    want_last_good = {t for t in TABLES if not fetch.tables[t].ok}   # 传输错误、schema 变化
for t in TABLES:               # industries → chokepoints → companies → financials → daily → weekly
    if t in want_last_good:
        if snap is None: abort("no_last_good")            # exit 2，不写任何文件（T12）
        rows[t], source[t] = snap.rows(t), "last_good"
        fallbackTables.append({table: t, code, detail, lastGoodFetchedAt: snap.fetchedAt(t)})
    else:
        rows[t], source[t] = fetch.rows(t), "notion"

# 2) 行级：按表顺序规范化（relation 只指向前面的表，一遍即可）
for t in TABLES:
    good, bad = normalize(rows[t], today, resolved)       # bad = 行级不合格
    if source[t] == "notion" and too_many_bad(bad, t):    # > 20% 且 ≥ 5 行（§5.3）
        改为整表 last-good（table_quality_low），重新规范化旧行；snap 为空 → abort("no_last_good")
    for row in bad:
        old = snap.row(t, row.id) if snap and t in SUBSTITUTABLE else None
        if old and normalize_one(old, today, resolved).ok:
            用旧版本：rowSource = "last_good"；研判 reasons 追加 "row_quarantined"；usedLastGood = true
        else:
            丢弃本行：usedLastGood = false
        quarantined.append({table, pageId, key, code, field, usedLastGood})
```

- `SUBSTITUTABLE = {industries, chokepoints, companies, financials}`；daily / weekly 坏行直接跳过（W05）。
- 旧行永远“按今天的时钟重新规范化”（§4.5）：过期照样变「待更新」，引用的行没了照样被隔离。
- 整表回退的行：`rowSource = "last_good"`，但研判标签照常计算，不加 `row_quarantined`（Q01）。
- `meta.notion.source`：6 张表都来自 Notion（允许有行级替代）→ `notion`；1–5 张表回退 → `partial`；6 张全回退 → `last_good`；TOML 构建 → `toml`。
- `counts[t] = {fetched, used, excluded, quarantined, substituted}`。

### 8.4 `research-snapshot.json`

```json
{
  "schemaVersion": 1,
  "contractVersion": "3.0",
  "notionVersion": "2026-03-11",
  "builtAt": "2026-10-21T18:15:00+08:00",
  "tables": {
    "industries": {
      "source": "notion",
      "fetchedAt": "2026-10-21T18:15:00+08:00",
      "schemaHash": "sha256:…",
      "rows": [{"id": "…", "created_time": "…", "last_edited_time": "…", "props": {"名称": "AI网络与光互连", "景气度": 5}}]
    }
  }
}
```

- 内容 = 本次构建**实际用到的**简化行：新读到且合格的行 + 替代用的旧行 + 回退表的旧行；被排除的行不存。
- `fetchedAt`：新读的表 = 本次 fixedClock；回退表 = 保留旧值。`builtAt` = 本次 fixedClock。不用墙钟。
- `schemaHash` = `{属性名: 类型}`（只含契约内、level ≠ ignore 的列）的规范 JSON 的 sha256，只做诊断。
- 规范 JSON：`json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"`，UTF-8；行按 `id` 排序（X02：Notion 返回顺序不同，输出逐字节相同）。
- 不存 Notion 用户 id / 邮箱（`created_by`、`last_edited_by` 不读），不存 token 和请求头。

### 8.5 退出码与原子写入

| exit | 含义 | 何时 |
|---|---|---|
| 0 | 发布 | 正常；有警告；行 / 表 last-good；6 张表全部 last-good（行情照常更新） |
| 2 | 不发布，线上保持上一次部署 | `no_last_good`；契约文件不合法；构建产物命中禁用词（`banned_words_in_output`）；现有行情类 release blockers（以仓库为准）。如果现有 blockers 没有覆盖“大面积缺行情”，新增：有行情的公司 < 70% → exit 2（`quotes_coverage_low`） |
| 1 | 程序错误 | 未捕获的异常（异常信息里不得出现 token，§4.1） |

- 构建先写到临时目录，全部检查通过后再一次性移动到输出目录；exit 2 时 `files.written == []`（T12）。
- 单个公司缺行情：沿用现有处理（以仓库为准），页面脉搏黄点「{n} 家行情暂缺，显示上次值」（§10.3）。

### 8.6 Step summary（中文，写到 `$GITHUB_STEP_SUMMARY`）

正常：

```
### 投研雷达 · 10/21 周三 18:15 更新 ✅
- 研究数据：Notion（13 次请求，0 次重试）· 行业 15 · 卡点 16 · 公司 42 · 财报 42 · 每日要点 2 · 每周主线 1
- 沿用上次版本：无 · 隔离：0 行 · 提醒：7 条（均为「文字偏长」）
- 本周主线：2026-W43 · AI 研判 · AI网络与光互连
- 今日要点：A股 AI 摘要 · 美股 AI 摘要
- 行情：42/42 家 · 汇率 ✅ · 温度计 ✅ · 下次 10/22 08:45
```

有问题时，在下面追加一张表，最多 20 行，文案用附录 E：

```
| 表 | 行 | 问题 | 处理 |
|---|---|---|---|
| 行业 | 消费 | 景气度超出 1–5 | 显示上次版本 |
| 每周主线 | — | 每周主线库 404：未共享给 connection 或已移动 | 整表沿用 10/20 18:15 的版本 |
```

### 8.7 安全

- DATA 嵌入 HTML 时转义 `<`、`>`、`&`、U+2028、U+2029（防 `</script>` 注入）；现有 `build.py` 已做的保持。
- 前端渲染 Notion 文本只用 `textContent` 或现有 `esc()`；链接只接受 `^https?://`，其他丢弃；外链一律 `target="_blank" rel="noopener noreferrer"`。
- `{{earnings:代号}}` 在转义之后再替换成受控片段（胶囊）。
- token 规则见 §4.1；X01 在日志、DATA、snapshot、artifact、step summary 里搜 token 字符串。

### 8.8 手动 dry-run：读真实 Notion，但不发布

在 `radar-interface-acceptance.yml` 增加 `workflow_dispatch` 输入 `live_notion`（boolean，默认 false）。为 true 时运行一个单独的 job：只在读取那一步注入 `NOTION_TOKEN` → 构建 → `verify-release.cjs` → 上传 artifact `live-notion-dry-run`（`meta.notion`、`meta.weekly`、`meta.daily`、`research-snapshot.json`、step summary；保留 7 天），**不发布**。用途：PR4 合并前，用户设好 token 后先手动跑一次，确认真实数据能通过。
- 触发方式：GitHub 要求 workflow 文件在**默认分支**上才会出现「Run workflow」按钮（[GitHub 文档](https://docs.github.com/en/actions/using-workflows/manually-running-a-workflow)）；运行时在 Branch 下拉框选 `v3/pr4-production`，再勾选 `live_notion`。如果默认分支上没有 `radar-interface-acceptance.yml` 或它没有 `workflow_dispatch`，先解决 §8.2 的默认分支问题，或在 PR 描述里给出其他可行的触发办法。

---

## 9. 测试

全部离线可跑（FakeTransport + fixtures），用仓库现有的测试命令与目录（以仓库为准）。fixtures 的读法、mutation 操作、断言语法见 `radar/tests/fixtures/notion_v3/README.md`。

### 9.1 新增测试

| 测试 | 内容 | PR |
|---|---|---|
| 契约完整性 | 契约 JSON 合法；6 张表、每列 type / level 齐全；`data_source_id` 与附录 C 一致；禁用词 24 个、预测词 12 个；`cases.json` 用到的 code 都在 `codes` 里，且代码里都有中文文案（附录 E；这一条 PR2 再加） | PR1 |
| Notion parity | FakeTransport + fixtures → `project(DATA) == expected/research_projection.json`（0 差异） | PR2 |
| TOML parity | `--source toml` 的投影套用 8 项有意差异后 == Notion 投影；PR5 随 TOML 一起删除 | PR2 |
| v3 视图 | 研判标签、数据档、冲突、主线、今日要点、KPI 辅助数 == `expected/v3_view.json` | PR2 |
| 103 个用例 | 每个用例：复制 fixtures → 应用 `mutations` → 完整构建 → 比对 `outcome / exit / codes / assert`（含 `transport.requests`、`transport.sleeps`） | PR2 |
| 确定性 | 同一输入跑两次，DATA、HTML、snapshot 逐字节相同；打乱 Notion 返回顺序仍相同（X02） | PR2 |
| 产物扫描 | §9.2 | PR3 |
| 调度 | `[schedule] cron_utc` == workflow `schedule`；`nextRunAt`：周三 18:15 → 周四 08:45；周五 18:15 → 周一 06:50；周日 12:00 → 周一 06:50 | PR4 |
| 发布 | bundle 含快照；`release.json` v3 字段齐全；`researchSnapshotSHA256` 正确；baseline 读到 v2 发布 → 无 last-good；X01 token 扫描覆盖 artifact | PR4 |

### 9.2 产物扫描（构建后自动跑；`verify-release.cjs` 也做同样检查）

1. **禁用词**：契约 24 个词，按 §5.4 的归一化方式，扫描 HTML 可见文本、属性 `data-tip` / `title` / `aria-label` / `placeholder` / `alt`、DATA 的所有字符串值。命中 → exit 2（`banned_words_in_output`）。
2. **界面措辞**：`radar/site/` 下所有文件与渲染后 DOM 中**不属于 Notion 内容**的文字，不得出现「核验 / 核实 / 核对 / 待复核 / 待核 / 原评分 / 原标记 / 人工评分」。前端把渲染 Notion 文本的容器标 `data-src="notion"`，扫描时跳过这些节点（Notion 里的「录入说明」等可能含“核对”之类的字，那是内容，不是界面）。
3. 免责声明全文恰好出现 1 次（§10.7）。
4. 不得出现 `.mock-note`。
5. `docs/design/v3/components-v3.html` 是规格页，里面故意列出了禁用词——**不要**把 `docs/` 纳入扫描，也不要部署它。

### 9.3 Playwright 视觉与交互（复用 `radar-interface-acceptance.yml` 现有环境）

- 视口 1440×900、1180×900、390×844 × 深色 / 浅色，共 6 组；每组截首屏与整页，作为 artifact 上传。
- 硬性断言：
  - 任何视口都没有横向滚动（`scrollWidth == clientWidth`）；
  - 1440×900：`#heroTitle`、`#today`、`#kpis`、`#pulse` 都完整落在首屏内，`#today` 与 `.hero-main` 同一行，`#topCard` 顶边 < 900（露出一截）；
  - 1180×900：`#today` 在 `.hero-main` 下方，`#pulse` 完整在首屏；
  - 390×844：`#heroTitle`、`#heroProv` 完整在首屏；
  - 1440×900 首屏内可见的 `.st` ≤ 3 个；
  - 控制台无 error。
- 位置参考（设计稿用基线数据实测，允许 ±24px）：1440×900 `#heroTitle` 225–276、`#today` 200–442、`#kpis` 464–516、`#pulse` 532–552、`#topCard` 顶 578；1180×900 `#today` 391–535、`#kpis` 557–609、`#pulse` 625–645；390×844 `#heroTitle` 211–244、`#heroProv` 256–276、`#today` 顶 387。
- 状态页：用用例 W03（自动主线）、W06（无主线）、D01（今日要点自动生成）、T01（全部沿用上次版本）、R12（数据冲突）各构建一页，断言关键文字存在（如 W06 的标题「本周主线待更新」、T01 的脉搏黄点「研究数据未更新」），并截图。
- 键盘：所有 `.st` 可 Tab 聚焦并显示提示；「查看理由」抽屉可用 Esc 关闭，关闭后焦点回到触发按钮。

### 9.4 旧测试怎么处理

- 行情、汇率、时点、覆盖率、release blockers、receipt、fixedClock 相关测试**一律保留**；只因措辞变化而失败的断言，改成新措辞。
- 只为“锁哈希 / 必须出现 原评分、核验 措辞”存在的测试：删除，并在 PR 描述里逐个列出。
- 不允许为了让测试通过而放宽行情类断言。

---

## 10. 界面 v3 规格

目标效果看 `docs/design/v3/overview-v3.html`（首页）与 `components-v3.html`（组件），截图在 `docs/design/v3/shots/`。设计稿是 10/21 的真实快照，「数据冲突」「待更新」两行是**示例**（设计稿顶部已注明）。

### 10.1 品味规则（违反任何一条都算不通过）

1. 不新增颜色、渐变、阴影、字体、图标库、emoji。只用现有 CSS 变量，加上 `v3-components.css`（追加到 `radar/site/style.css` 末尾，**删掉第 8 节 `.mock-note`**）。
2. 一屏只有一条状态线（更新脉搏）。不再有「当前上线快照」「每日变化摘要」这类状态卡。
3. 标签只标例外；1440×900 首屏最多 3 个 `.st`。
4. 数字一律 `.num`（等宽）；格式见 §10.8。
5. 动画只保留现有的 reveal 与 KPI 数字滚动；`prefers-reduced-motion` 时全部关闭。最终数字先渲染在 HTML 里，关掉 JS 也正确。
6. 间距用 8px 网格；任何宽度都不出现横向滚动。
7. 超长文字用「…」截断，悬停 / 聚焦看全文；外链末尾加 ↗。
8. 措辞：不出现禁用词；不出现「核验 / 核实 / 核对 / 待复核 / 待核 / 原评分 / 原标记 / 人工评分」（免责声明里的“未经人工审核”除外）。

### 10.2 旧 → 新对照

| 位置 | v2 线上 | v3 |
|---|---|---|
| hero 眉标 `#heroDate` | 研究观点 · 行情截至 各市场最新可得 · 2026-10-20—… | `2026-W43 · 10/19–10/25` |
| hero 标题 `#heroTitle` | 研究关注：AI网络与光互连 | 本周主线：AI网络与光互连（`mode = none` → 本周主线待更新） |
| `#researchStatus` | 观点周期 2026-W42 · 已过期 · 待复核 · 核验日期缺失 · … | 删除，改为来源行 `.prov#heroProv`（§10.3） |
| `#dataStatus` | 数据：437/477 项完整 · … · 数据说明 | 删除；覆盖率留在页脚「数据状态与缺项」 |
| `#releaseStatus` | 当前上线快照 · 正在核对线上版本 · 本次发布记录 ↗ · 所有更新与失败 ↗ · 刷新查看新版 | 删除，改为 `.pulse#pulse`；「发布记录 ↗」「更新历史 ↗」移到页脚「数据说明」；新版本提示进脉搏 |
| `#dailyChanges` | 每日变化摘要 · 财报更新 / 日历变更 / 缺项恢复 / 覆盖下降 | 删除，改为脉搏里的「今日变化」 |
| KPI 1 | 原评分重点行业 · 总分 ≥ 17 · 核验状态见行业详情 | 重点追踪行业 · 总分 ≥ 17 |
| KPI 2 | 原标记极紧卡点 · 共 16 个 · 核验状态见卡点 | 极紧卡点 · 共 16 个 |
| KPI 4 | 深度回调龙头 · 距52周高点 ≤ −40% · 含近期反弹 | 深度回调龙头 · 距52周高点 ≤ −40% |
| KPI 5 | 两周内财报日期 · 官方确认 1 家 · 日期待核 29 家 | 两周内财报 · 官方确认 1 · 预估 29 |
| 主线卡 `#topCard` | review-note「待核 · 核验日期缺失」 | 删除；主线卡只放内容 |
| 评分卡 `#rankCard` | 行业人工评分 · 原评分 · 核验状态见行业详情 | 行业评分 · `[AI 研判]` 10/19 · 每周一更新 |
| 行业详情 | 原研究信号 · 核验状态见上方 | 最新信号 |
| 温度计 | 红利定投温度计；按原计划定投，不加不减 | 成长/红利温度计；`[自动生成]` 只描述位置，不含操作建议 |
| 两周内财报 | 官方确认 1 家 · 日期待核 29 家 · 各日期按所列来源时区…；名单写「中际旭创（日期待核）」 | 图例：官方确认 / 预估 / 日期按公司所在地时区；名单不加括号，用胶囊样式区分 |
| 日历 `#calSub` | …日期按来源时区；点击公司查看核验依据 | 今天 10/21 周三 · 官方确认 1 · 预估 37 · 待定 4 · 日期按公司所在地时区 |
| 公司抽屉 · 财务 | 披露日 / 核验日 · 核验备注 | 发布日 / 录入日 · 录入说明 |
| 公司抽屉 · 财报日 | 披露… · 核验… / 时区待核 / 待核 | 10/31 · 官方确认 ↗ / 10/31 · 预估 / 日期待定；时区用中文名 |
| 各处 | 日期待核 | `next == null` → 日期待定；否则按状态显示 官方确认 / 预估 |
| 页脚 | 单季中位数只含已核实正式单季…业绩快讯待核实…核验日期 | 设计稿页脚原文（数据口径 / 信号规则 / 说明）+ 固定免责声明 |

**通用替换规则**（上表之外，`radar/site/` 和生成页面文字的 Python 代码里还有约 60 处旧措辞，例如「行情待核实」「时间待核」「核验依据 ↗」「线上版本已核对」「保留已核实数据」）。Codex 先 `rg -n "核验|核实|待核|复核|核对|原评分|原标记|人工评分|人工观点|定投"` 列全，再按下表逐条改，并把清单贴进 PR 描述：

| 旧 | 新 |
|---|---|
| 研究内容的「待核 / 待复核 / 待重新核验」 | 待更新 |
| 行情、汇率、时点类的「待核 / 待核实」（如 行情待核实、时间待核、来源待核、口径待核、覆盖待核、同步时刻仍待核、构建提交号待核） | 暂缺 / 未提供 / 未注明（按语义选，如「行情暂缺」「时间未提供」「口径未注明」） |
| 核验依据 ↗ / 原文链接缺失 · 待核 | 来源 ↗ / 缺来源 |
| 核验日 / 上次核验 / 核验备注 | 录入日 / 删除 / 录入说明 |
| 线上版本核对类（正在核对线上版本、线上版本已核对、Vercel 上线核对、暂无法核对新版本…） | 删除；新版本提示只剩脉搏里的「有新数据 · 刷新」，检查失败时不提示 |
| 已核实 / 已核对（任何位置） | 删除（「已核实」是禁用词） |
| 人工观点与评分 / 人工评分 | AI 研判 |
| 业绩信号「待核/不适用」 | 不适用 |
| 已过 n 天 · 待复核 / 已过期日期保留在财报日历，待复核。 | 已过 n 天 · 待更新 / 已过的日期保留在日历里，待更新。 |

这些只改界面措辞；行情类的“缺值用占位、不填 0”等真实性规则本身不变。Notion 内容（如财报「录入说明」里写的“核对”）不在此列。

### 10.3 首屏

```
.hero-head
  .hero-split
    .hero-main
      .eyebrow #heroDate      2026-W43 · 10/19–10/25
      h1#heroTitle            本周主线：<span class="grad">AI网络与光互连</span>
      .prov#heroProv          [AI 研判] 10/19 研判 · 有效至 10/26 · 依据 3 条 · 查看理由
      p.lead#heroLead         导语（≤ 90 字）
    aside.today#today         今日要点
  .kpis#kpis                  5 个 KPI
  .pulse#pulse role=status    更新脉搏（一行）
.bento                        主线拆解 / 行业评分 / 温度计 / 两周内财报 …
```

**来源行 `#heroProv`**

| meta.weekly | 来源行 |
|---|---|
| `mode = ai` | `[AI 研判] 10/19 研判 · 有效至 10/26 · 依据 3 条 · 查看理由` |
| `mode = stale` | `[待更新]` + 首要原因 + `· 显示上次结论 · 查看理由`。首要原因按 `expired` > `not_current_week` > 其余（按 reasons 顺序）选；提示里列出全部原因。基线：`[待更新] 10/17 研判 · 有效至 10/19，已过期 · 显示上次结论 · 查看理由` |
| `mode = auto` | `[自动生成] 本周还没有主线研判 · 按行业评分自动选出` |
| `mode = none` | 不显示来源行；标题「本周主线待更新」；导语「行业研判均待更新，下方数据照常显示。」 |

窄屏（≤ 760）隐藏来源行里的 `.opt` 部分（「依据 3 条」等），保留标签与「查看理由」。

**今日要点 `#today`**

- 标题「今日要点」；两行都是 `ai` → 标题旁一个 `[AI 摘要]`（提示：AI 根据当日收盘复盘写的一句话，只陈述已发生的事实，不做预测。）；小字「每个交易日收盘后更新」。
- 每个市场一行，顺序按 `[daily] markets`：`A股 10/21 周三 · 收盘` + `看复盘 ↗`（`reviewUrl` 非空才显示）→ 一句话 → 指数小字（`short` 名 + 涨跌幅）。美股用美东日期（10/20 周二）。
- `source = auto` → 该行显示模板句 + `[自动生成]` +「复盘未更新」，不显示「看复盘」。
- `line == ""` → 该行显示灰字「今日要点待更新」。
- 涉及行业（`industries`）本期不显示，DATA 保留。

**KPI `#kpis`**

| # | 数值 | 标签 | 小字 |
|---|---|---|---|
| 1 | 总分 ≥ 17 的行业数 | 重点追踪行业 | 总分 ≥ 17；其中有待更新的 → 追加「· k 个待更新」 |
| 2 | 极紧卡点数 | 极紧卡点 | 共 N 个 |
| 3 | 业绩信号为「高增」的公司数（§7.3，现有算法） | 业绩高增龙头 | 同比 ≥ 50% · 共 N 家 |
| 4 | 距 52 周高点 ≤ −40% 的公司数 | 深度回调龙头 | 距52周高点 ≤ −40% |
| 5 | 两周内有财报日的公司数 | 两周内财报 | 官方确认 a · 预估 b |

**更新脉搏 `#pulse`**（一行，`role="status"`，点 `#2ee59d` 绿 / 黄 / 红沿用设计稿 `.pulse.ok/.warn/.bad`）

| 状态 | 条件 | 文案 |
|---|---|---|
| ok | 无下列问题 | `● 行情更新于 10/21 18:15 · 下次 10/22 08:45 · 今日变化：财报 2 · 财报日确认 1 · 评分 0 · 数据说明` |
| warn | 构建时有下列任一问题（按优先级，最多显示 2 条，不再显示「下次」和「今日变化」） | `● 行情更新于 10/21 18:15 · {问题1} · {问题2} · 数据说明` |
| bad | 浏览器端：现在 > `nextRunAt` + `lateAfterMinutes` | `● 本次更新未完成，显示 10/21 12:15 的数据 · 下次 10/22 08:45 · 数据说明` |

- warn 的问题文案（优先级从高到低）：6 张表都沿用 → `研究数据未更新，沿用 {最早 lastGoodFetchedAt} 的版本`；1–5 张表沿用 → `{n} 张研究表沿用上次版本`；有隔离行 → `{n} 行研究数据有误，已沿用上次版本或暂不显示`；有公司缺行情 → `{n} 家行情暂缺，显示上次值`。字段级提醒（`text_long`、`url_invalid` 等）不进脉搏，只在页脚「数据说明」里列出。
- bad 里的「下次」由浏览器按 `meta.schedule.cronUtc` 计算（只需支持 `分 时 * * 星期` 这种写法）。
- 有新版本：沿用现有的线上版本核对逻辑（旧 `#refreshSnapshot` 用的那套，以仓库为准）；发现更新 → 脉搏末尾追加 `· 有新数据 · 刷新`（按钮）。
- 「数据说明」链接到页脚 `#dataNotes`。
- **今日变化**（只在 ok 状态显示）：北京时间当天 00:00 以来的变化。每次发布存 `changesToday`：上一次发布是同一天 → 继承它的 `changesToday` 再并上本次与上一次的差异；不是同一天 → 只算本次差异。按 key 去重计数：财报 = 显示的财报期变了的公司数；财报日确认 = `earnings.status` 变成 `confirmed` 的公司数；评分 = 四项分任一变化的行业数。三项总是都显示（0 也显示）；没有上一次发布 → `今日变化：首次更新`。在 `daily_changes.py` 里扩展，保留现有字段，新增 `scores`。

### 10.4 首屏以下

- **主线拆解 `#topCard`**：结构不变，删除 review-note。`mode = none` 时显示评分第一的行业，卡片标题旁加 `[待更新]`。
- **行业评分 `#rankCard`**：标题「行业评分」，右侧按多数原则显示一次标签与日期（`[AI 研判] 10/19 · 每周一更新`；日期取 ai 行里最常见的研判日期）。行内只出现例外：`[待更新]`（`.rk.is-stale`，条形降饱和）和 `[数据冲突]`（逐行显示）。行提示：`AI网络与光互连｜景气度 5 · 业绩兑现 5 · 卡点强度 5 · 估值位置 4`。
- **行业详情**：顶部一条来源行（同 hero 的写法）；四项分里，业绩兑现、卡点强度旁边用灰色小字写 `数据档 5`（有档才写）；冲突时加 `[数据冲突]`，提示 `业绩兑现：AI 2 · 数据档 5（营收同比中位数 +85.5%，9 家）`。「最新信号」最多 4 条。知识库链接 ↗。
- **卡点**：紧缺度徽标不变；只有 stale 才加 `[待更新]`；`{{earnings:代号}}` 渲染成财报日胶囊（未知代号 → 「日期待定」）。
- **公司表**：列不变；财务格按 §7.3；快讯按 §7.5；证据标签只标「部分」「缺来源」。
- **公司抽屉**：财务块 = `{显示期间} · {报告状态} · [有原文|部分|缺来源]`，来源列表（`source_urls`，每个显示域名 + ↗），发布日 / 录入日，计算说明，录入说明，注意事项（列表）。财报日块按 §7.4。
- **温度计**：标题「成长/红利温度计」；原「操作建议」位置改为 `[自动生成] 只描述位置，不含操作建议`；比值、分位、区间算法与文字不变。
- **两周内财报 / 日历**：按 §7.4；图例每屏一次。
- **页脚 `#foot`**：「数据口径 / 信号规则 / 说明」三栏用设计稿原文；保留「指数、汇率与比值来源」「数据状态与缺项」；新增「数据说明」`#dataNotes`：
  - `研究数据：来自 Notion · 读取于 10/21 18:15 · 13 次请求`（`partial` / `last_good` 时写明哪些表沿用、沿用的是几点的版本）；
  - 隔离的行：表 · 行 · 原因 · 处理（附录 E 文案）；
  - 提醒：最多 50 条（表 · 行 · 字段 · 原因）；
  - `发布记录 ↗`（本次 run）· `更新历史 ↗`（workflow 页面）；
  - 最后是免责声明（§10.7）。

### 10.5 「查看理由」抽屉

- 复用现有 `#drawer`。内容：标题 `{对象} · 研判理由`；标签 + 原因列表（中文）；研判日期 / 有效至；研判理由全文（`textContent`，保留换行）；来源列表（域名 + ↗）；行业另附四项分、数据档与冲突说明。
- 打开时焦点进入抽屉并锁在里面；Esc 关闭；关闭后焦点回到「查看理由」。

### 10.6 标签出现在哪

| 位置 | 可以出现的标签 |
|---|---|
| hero 来源行 | AI 研判 / 待更新 / 自动生成 |
| 今日要点 | AI 摘要（标题）/ 自动生成（行内） |
| 行业评分卡 | 标题：AI 研判或待更新（多数）；行内：待更新、数据冲突 |
| 行业详情、卡点 | 来源行：AI 研判 / 待更新；分项：数据冲突 |
| 温度计 | 自动生成 |
| 公司表 | 部分 / 缺来源 |
| 公司抽屉 | 有原文 / 部分 / 缺来源 |
| 页脚说明 | 三种标签各一个，作图例 |

### 10.7 免责声明（固定文字，全站只出现一次，放在页脚 `#disclaimer`）

> 研究内容由 AI 依据公开资料撰写，程序自动检查格式、日期与来源，未经人工审核；行情由定时任务更新。仅供研究参考，不构成投资建议。

删除其他地方的旧免责声明或“不构成投资建议”字样。

### 10.8 文案与数字

- 负号一律 `−`（U+2212），正数带 `+`；涨跌幅 2 位小数，财务同比 1 位；价格沿用现有位数；千分位分隔。
- 日期 `10/21 周三`，时间 `18:15`（北京时间，除财报日按公司所在地时区）；跨年才写年份。
- 写「AI 研判」（中间有空格）；不用“我们”；中文标点。
- 长度：一句话 ≤ 40 字（硬上限 50）、导语 ≤ 90 字、看点 ≤ 30 字、快讯 ≤ 60 字（硬上限 80）；以契约为准。

### 10.9 响应式

沿用设计稿 CSS 第 9 节：> 1180 首屏左右两栏；≤ 1180 今日要点移到主线下方；≤ 760 单栏，来源行隐藏 `.opt`，脉搏字号 11.5px。

### 10.10 旧 DATA 兼容（读到 v2 DATA 或缺字段时不报错）

| 缺什么 | 页面怎么做 |
|---|---|
| 行业 / 卡点没有 `judgment` | 当作 `stale`，原因「旧版数据，无研判信息」 |
| `meta.weekly.mode` | 当作 `stale`，来源行「[待更新] 旧版数据，无研判信息」 |
| `meta.daily` | 今日要点两行都显示「今日要点待更新」 |
| `meta.notion` | 脉搏不显示研究数据问题；「数据说明」写「研究数据：仓库文件」 |
| `meta.schedule` | 脉搏不显示「下次」，不做迟到判断 |
| 公司没有 `flashDate` | 快讯照常显示，不加日期 |

用途：回滚到 `--source toml` 时页面仍可用。PR3 → PR4 之间不要让生产停留在“v3 界面 + 旧数据”（见 §12 的合并顺序）。

### 10.11 无障碍

- 标签与「查看理由」可 Tab 聚焦；提示在 hover 与 focus 时都出现；提示内容同时写进 `aria-label`。
- 脉搏 `role="status"`；状态不只靠颜色区分（文字里有「未完成」「沿用」等）。
- 对比度不低于现有正文；图例与胶囊在浅色主题下同样可辨。

### 10.12 视觉验收清单（对照 `shots/`）

1. 1440 深色首屏与 `ov_desk_dark_top.png` 结构一致：左主线、右今日要点、KPI 一行、脉搏一行、主线卡露出顶边。
2. 浅色主题、1180、390 分别对照 `ov_desk_light_*`、`ov_tab_dark_*`、`ov_mobile_*`。
3. 组件对照 `sheet_*.png`：标签形状、来源行、脉搏三态、今日要点、胶囊三态、评分例外行。
4. 全页没有「核验 / 待核 / 原评分」等旧措辞；免责声明 1 次。
5. 截图作为 PR3 的 artifact，PR 描述里贴 1440 深色首屏。

---

## 11. 合规与收费前提（不是开发任务）

> 这一节写给产品负责人。v3 **不做**任何收费功能；Codex 不需要实现本节，只需保证不写出与本节冲突的东西（荐股措辞、付费墙、对外开放访问）。以下是起草人整理的公开资料要点，**不构成法律意见**；开始收费前，请找熟悉证券和互联网业务的律师确认。

### 11.1 定位：产业研究工具，不是投资建议

- 在中国境内，以有偿方式向投资者提供证券投资分析、预测或建议，属于证券投资咨询业务，需要证监会许可（[湖北证监局：非法荐股典型案例](https://www.csrc.gov.cn/hubei/c105452/c7584358/content.shtml)）。以获利为目的销售或提供“荐股软件”，同样属于这类业务（[证监会相关规定](https://www.csrc.gov.cn/csrc/c100028/c1002385/content.shtml)）。2026 年 4 月，网信办还专项整治过“AI 选股软件”一类账号（[网信办通报](https://www.cac.gov.cn/2026-04/16/c_1778078583431637.htm)）。
- 产品越像“告诉你该看哪只、该怎么做”，越接近需要牌照的业务。两条路：
  - **A. 与持牌投顾机构合作**：最稳，适合直接面向散户收费；
  - **B. 只做产业研究工具**：只提供行业层面的数据、产业链与卡点、财报日程和知识库，不对个股下结论，不给操作建议。
- v3 已经为 B 路线打好基础：禁用词与预测词自动拦截（§5.4、§6.5）；温度计删除操作建议（§10.4）；全站固定免责声明（§10.7）；每块 AI 内容都标明出处与有效期（§6）。
- 收费前再看一遍措辞：「重点追踪」「龙头」「信号」单独看是数据描述，但和收费放在一起，可能被理解为荐股。是否改名，等律师看过页面再定；改名只动界面文案，不动数据。

### 11.2 收费方式与网站许可

- 自建网站向用户收费提供信息，属于经营性互联网信息服务，要办理增值电信业务经营许可（俗称 ICP 经营许可证）（[《互联网信息服务管理办法》第七条](http://xzfg.moj.gov.cn/front/law/detail?LawID=550&Query=%E7%BD%91)）。
- ICP 备案与许可要通过境内的接入服务商办理；托管在 Vercel 这类境外平台上的站点办不了，境内访问也不稳定。“升级 Vercel Pro + 办 ICP”两件事不能同时成立。
- 最省事的起步方式：先用知识星球这类平台收费和管理会员，雷达保持登录访问；规模确定后再决定是否迁到境内托管、自建付费网站。

### 11.3 行情数据授权

- 沪深交易所产生的行情、指数等证券信息归交易所所有，未经许可不得复制、传输或用于开发金融信息产品（[上证信息：授权声明](https://www.sseinfo.com/aboutus/authstatement/)）；深交所数据由深证信息授权。
- 雷达现在用的 Yahoo、腾讯等是非官方接口，不提供商业授权。收费前要换成有正式授权的行情源（v3 不改行情源，§2）。

### 11.4 托管

- Vercel 免费版（Hobby）只限个人、非商业用途；商用要升级 Pro（[Vercel 合理使用准则](https://vercel.com/docs/limits/fair-use-guidelines)）。
- 升级 Vercel 解决不了 11.2 的许可问题。

### 11.5 与 Notion 知识库捆绑

- 付费用户打不开你的私人 Notion 工作区。可选做法：Notion 公开分享链接（拿到链接的人都能看，不适合付费内容）；或者以后把知识库内容同步到雷达网站，登录后阅读（另立项目，不在 v3 范围）。
- 无论哪种，知识库里同样不出现个股买卖建议；ChatGPT 写进 Notion 的研判同样受 11.1 约束。

### 11.6 收费前检查单

| 事项 | v3 状态 | 收费前要做 |
|---|---|---|
| 内容定位 | 已按路线 B 打基础 | 选定 A 或 B；律师审页面与措辞 |
| 投资咨询资质 | 自用，不涉及 | A：与持牌机构签约；B：律师确认边界 |
| 网站许可 | 不涉及 | 用平台收费，或境内托管并办证 |
| 行情授权 | 非官方接口 | 换授权数据源 |
| 托管 | Vercel Hobby | 商用升级 Pro，或迁到境内 |
| 免责声明 | 已固定（§10.7） | 律师确认措辞 |
| 用户协议、隐私政策 | 无 | 起草（收费平台一般自带一部分） |

---

## 12. 实施计划：5 个 PR

### 12.1 总表与共同规则

| PR | 名称 | 分支（建议） | 基于 | 主要内容 | 上线影响 |
|---|---|---|---|---|---|
| PR1 | 政策落地 + 测试基线 | `v3/pr1-policy` | `v3-inputs`（附录 B） | 仓库地图；删除研究冻结锁、preflight frozen 检查、锁哈希与措辞测试；契约完整性测试 | 无（产物逐字节相同） |
| PR2 | Notion 数据层 | `v3/pr2-notion-data` | 生产分支（已含 PR1） | 4 个新模块；`--source`（默认 toml）；`[notion]` `[daily]`；FakeTransport；parity、v3 视图、103 个用例、确定性；导出工具 | 无（默认仍读 TOML） |
| PR3 | 界面 v3 | `v3/pr3-ui` | 生产分支（已含 PR2） | §10 全部；产物扫描；Playwright；截图 | **评审通过后先不合并** |
| PR4 | 生产切换 | `v3/pr4-production` | PR3 的分支 | `[schedule]`；默认 notion；workflow（§8.1）；cron（§8.2）；`changesToday`；dry-run job；默认分支报告 | 与 PR3 一起合并后生效（§12.7） |
| PR5 | 清理 + 文档 | `v3/pr5-cleanup` | 生产分支（已含 PR4） | 删除 TOML 研究数据、`--source toml`、`[weekly]`、TOML parity；README、`docs/PRODUCTION.md`、`docs/NOTION-CONTRACT.md` | 无可见变化 |

**所有 PR 共同规则**

- PR 的目标分支 = 生产分支（现为 `fix/radar-truthfulness-2026-10-18`，以 PR1 仓库地图为准；PR4 的默认分支选择可能改变它）。
- 一次只做一个 PR；上一个合并后再开下一个（例外：PR4 基于未合并的 PR3 分支）。
- Codex 不自己合并、不直接推送生产分支、不改仓库或 Vercel 设置；CI 全绿才算完成；新增测试必须离线可跑。
- 每个 PR 描述都包含：**改了什么** · **怎么验证的**（命令 + 结果）· **删除或改写的测试**（逐个列出，各一句理由）· **与任务书的差异**（每处差异一行：任务书写的 / 仓库实际 / 怎么处理）· **需要产品负责人做的事**（没有写“无”）。
- fixtures 期望值、契约与本文件之间有矛盾 → 停下，在 PR 里提问，不要自行取舍。

### 12.2 PR1 · 政策落地 + 测试基线

目的：把“取消研究锁定”落到代码上，并先立好测试基线；页面和数据一字不变。

**Codex 提示词（整段复制）**

```text
你在仓库 lwd619783-byte/research-radar 工作。任务书是 docs/V3-BRIEF.md（下称“任务书”）。本次只做 PR1「政策落地 + 测试基线」，不要做其他 PR 的内容。

先读：任务书 §0、§1、§9.4、§12.1、§12.2、§13，附录 B、C；radar/data/notion_schema.json；radar/tests/fixtures/notion_v3/README.md。

分支：从 v3-inputs 新建 v3/pr1-policy；PR 的目标分支 = 生产分支（第 1 步确认）。

要做：
1. 画仓库地图（只读，写进 PR 描述）：目录结构；构建入口与测试命令；每个 workflow 的触发方式与守卫（if 条件）；生产分支（production_release.py 的 SOURCE_BRANCH）；运行 `gh api repos/lwd619783-byte/research-radar --jq .default_branch` 和 `gh run list --workflow radar-production.yml --event schedule --limit 20` 并贴结果（命令不可用就写明，请产品负责人在 GitHub 网页查看）；任务书提到、但仓库里不存在或不一致的文件、函数、字段。
2. 删除研究内容冻结：audit/truthfulness-frozen.json 对 radar/site/*、radar/data/*.toml、workflows 的哈希锁（文件只做这件事就整个删除）；preflight 的 frozen provenance 检查；只为“锁哈希 / 必须出现 原评分、核验 等措辞”而存在的测试或断言。
3. 保留并保持通过：行情、汇率、时点、覆盖率、release blockers、receipt、fixedClock、verify-release.cjs 相关的全部逻辑与测试，不得放宽。
4. 新增契约完整性测试（任务书 §9.1 第 1 行；“代码里都有中文文案”那一条 PR2 再加）。
5. 不改页面、DATA、行情逻辑，也不改 workflow 的调度与守卫。

验收：
- 全部测试通过；
- 用仓库现有的离线构建方式（同一 fixedClock、同一份行情数据），改动前后各构建一次：index.html 与 DATA 逐字节相同（写明命令与比对结果）；
- PR 描述按任务书 §12.1 的格式，另含仓库地图、默认分支与定时运行记录。
不要合并 PR，不要改仓库设置。
```

### 12.3 PR2 · Notion 数据层

目的：能从 Notion（测试里是 fixtures）产出 v3 DATA，并用 103 个用例证明各种异常都按规则处理；生产仍读 TOML。

**Codex 提示词（整段复制）**

```text
你在仓库 lwd619783-byte/research-radar 工作。任务书是 docs/V3-BRIEF.md。本次只做 PR2「Notion 数据层」。

先读：任务书 §0、§3–§7、§8.3–§8.5、§9.1、§12.1、§12.3、§13，附录 C、D、E；radar/data/notion_schema.json；radar/tests/fixtures/notion_v3/README.md（测试怎么跑、mutation 与断言语法都在里面）。

分支：从最新的生产分支新建 v3/pr2-notion-data。

要做：
1. radar/scripts/ 新增 notion_source.py、notion_normalize.py、research_snapshot.py、research_view.py（职责见 §3.1），只用 Python 标准库；网络、等待、节流都通过可注入的 transport、sleep、pace 实现。
2. build.py 增加 --source notion|toml，默认值读 config（本 PR 默认 toml）。
3. config.toml 增加 [notion]、[daily]（§3.4）。
4. 测试（§9.1 中标 PR2 的行）：Notion parity、TOML parity（8 项有意差异见 fixtures README）、v3 视图、103 个用例逐个跑、确定性；外加附录 E：每个 code 都有中文文案。
5. radar/tools/export_notion_fixtures.py（或仓库现有工具目录）：用只读 token 手动重新导出 fixtures；CI 不跑。

规则：
- 不改 radar/site/、生产 workflow、行情逻辑；默认 --source toml 的构建产物与本 PR 之前逐字节相同。
- 测试不访问网络、不需要 NOTION_TOKEN。
- 不改 fixtures 期望值（expected/*.json、cases.json）和契约。认为它们有错 → 停下，在 PR 里写明用例号、期望、实际和理由，等回复。

验收：
- 全部测试通过；103 个用例逐个通过（PR 描述贴汇总：各 outcome 数量、总耗时）；
- 用 FakeTransport + fixtures 构建一次 --source notion，贴 meta.notion 与 meta.weekly（基线应为 mode = stale、sourceWeek = 2026-W42、reasons = ["not_current_week", "expired"]）；
- PR 描述按任务书 §12.1 的格式。
不要合并 PR。
```

### 12.4 PR3 · 界面 v3

目的：页面改成设计稿的样子，并能同时显示 v3 与旧版 DATA。评审时请对照截图看效果；**评审通过后先不合并**，和 PR4 一起上线（否则线上会出现“新界面 + 旧数据”，满屏「待更新」）。

**Codex 提示词（整段复制）**

```text
你在仓库 lwd619783-byte/research-radar 工作。任务书是 docs/V3-BRIEF.md。本次只做 PR3「界面 v3」。

先读：任务书 §0、§6.1、§6.6、§7.3–§7.5（显示部分）、§8.7、§9.2、§9.3、§10 全部、§12.1、§12.4、§13。打开 docs/design/v3/overview-v3.html（首页目标效果）和 components-v3.html（组件规格），对照 docs/design/v3/shots/ 截图。

分支：从最新的生产分支新建 v3/pr3-ui。

要做：
1. 把 docs/design/v3/v3-components.css 追加进 radar/site/style.css，去掉 .mock-note 相关规则；沿用现有 CSS 变量，不新增颜色。
2. 按 §10 改 radar/site/（index.html、app.js 等，以仓库为准）：首屏（本周主线、今日要点、KPI、更新脉搏）、首屏以下各卡片、「查看理由」抽屉、标签规则、页脚数据说明、免责声明；§10.2 的旧 → 新对照与通用替换规则全部落实。
3. 渲染 Notion 文本的容器加 data-src="notion"；文本只用 textContent 或现有 esc()；链接只接受 ^https?://；外链 target="_blank" rel="noopener noreferrer"（§8.7）。
4. 旧 DATA 兼容（§10.10）：读到 v2 DATA 不报错。
5. 测试：§9.2 产物扫描、§9.3 Playwright（复用 radar-interface-acceptance.yml 的环境）。离线页面用 fixtures + radar/tests/fixtures/notion_v3/quotes/data-2026-10-21.json，fixedClock = 2026-10-21T18:15:00+08:00；状态页用 W03、W06、D01、T01、R12。

规则：
- 不改行情、温度计、比值算法；不引入框架或打包工具；不部署、不扫描 docs/。
- 本 PR 评审通过后先不合并，和 PR4 一起合并（任务书 §12.7）。

验收：
- §9.2、§9.3 全部通过；6 组视口截图 + 5 个状态页截图作为 artifact；
- 旧措辞检查（§10.2 的 rg 命令）结果为 0；
- PR 描述贴 1440×900 深色首屏截图，逐条对照 §10.12 写明与 shots/ 的差异；其余按 §12.1 的格式。
不要合并 PR。
```

### 12.5 PR4 · 生产切换

目的：生产改为读 Notion，按新时间表自动运行；合并前用户先用 dry-run 读一次真实 Notion。

**Codex 提示词（整段复制）**

```text
你在仓库 lwd619783-byte/research-radar 工作。任务书是 docs/V3-BRIEF.md。本次只做 PR4「生产切换」。

先读：任务书 §0、§3.3、§3.4、§4.1、§8 全部、§9.1（标 PR4 的行）、§10.3（今日变化）、§12.1、§12.5、§12.7、§12.8、§13，附录 A、D。

分支：从 v3/pr3-ui 新建 v3/pr4-production（PR3 还没合并）；PR 的目标分支 = 生产分支。PR3 合并后如有冲突，把本分支 rebase 到最新的生产分支。

要做：
1. config.toml 增加 [schedule]；build.py 默认 --source notion（保留 --source toml，用于回滚）。
2. radar-production.yml 按 §8.1 改：baseline 多取 research-snapshot.json（v2 发布视为没有 last-good）；collect 先读 Notion 写 work/notion-fetch.json，再拉行情（只有这一步的 env 有 NOTION_TOKEN）；bundle 加快照；release.json v3；verify-release.cjs 新检查；concurrency。
3. cron 按 §8.2；加测试比对 [schedule] cron_utc 与 workflow 的 schedule；产出 meta.schedule（含 nextRunAt）。
4. daily_changes.py：changesToday（§10.3 的增量定义），保留现有字段，新增 scores。
5. radar-interface-acceptance.yml 增加 live_notion dry-run（§8.8）。
6. 默认分支：运行 §8.2 的两条只读命令，把结果和 A/B 两个选项写进 PR 描述；不改仓库设置，等产品负责人回复后再按选择补改（选 B 时在本 PR 内改 SOURCE_BRANCH、workflow 的 if 和相关测试）。

规则：
- NOTION_TOKEN 不得出现在日志、异常、DATA、snapshot、artifact、step summary（X01）。
- 保留现有守卫：仓库名、分支、事件类型、GITHUB_RUN_ATTEMPT == 1。
- 不直接推送生产分支。

验收：
- §9.1 中标 PR4 的测试全部通过；
- 离线演练一次完整生产流程（collect 用 FakeTransport + fixtures，其余步骤与生产相同），贴 step summary（§8.6 格式）和 release.json；
- PR 描述按 §12.1 的格式，另含默认分支结论，以及「合并前用户要做的事」清单（照抄 §12.8 中 PR4 那几行，按实际情况补充；写清 dry-run 怎么触发，见 §8.8）。
不要合并 PR。
```

### 12.6 PR5 · 清理 + 文档

前提：PR4 上线满 1 周，且至少 15 次定时运行成功。目的：删掉回滚用的 TOML 旧路径，补齐运维文档。

**Codex 提示词（整段复制）**

```text
你在仓库 lwd619783-byte/research-radar 工作。任务书是 docs/V3-BRIEF.md。本次只做 PR5「清理 + 文档」。

前提检查：运行 gh run list --workflow radar-production.yml --limit 30 并贴结果；PR4 上线不满 1 周或成功的定时运行少于 15 次 → 停下告诉我。

先读：任务书 §0、§10.10、§12.1、§12.6、§13。

分支：从最新的生产分支新建 v3/pr5-cleanup。

要做：
1. 删除 TOML 研究数据源：radar/data/ 里只为研究内容服务的 TOML（industries、chokepoints、companies 中的研究字段；先确认没有其他代码在用）、--source toml、config.toml 的 [weekly]、TOML parity 测试。
2. 保留 §10.10 的旧 DATA 兼容（回滚到旧发布时页面仍要能显示）。
3. 文档：更新 README；新增 docs/PRODUCTION.md（运维手册：调度表、每次运行做什么、脉搏绿/黄/红的含义、step summary 怎么看、怎么手动重跑、怎么回滚到上一次部署、怎么更换 NOTION_TOKEN、Notion 出错时看哪里）；新增 docs/NOTION-CONTRACT.md（给维护 Notion 的人看：每张表每列的含义、是否必填、格式与例子；由脚本从 notion_schema.json 生成，测试保证两者一致）。

验收：全部测试通过；用 FakeTransport + fixtures 构建，产物与本 PR 之前逐字节相同（不同就逐项说明）；PR 描述按任务书 §12.1 的格式。
不要合并 PR。
```

### 12.7 上线步骤（PR3 + PR4）

1. PR3 评审通过（看截图）→ 先不合并。
2. PR4 评审通过，且 §12.8 中「PR4 合并前」的事项都已完成（默认分支已选定、dry-run 通过）。
3. 在工作日北京时间 **14:00–17:00**（两次定时运行之间）：先合并 PR3，再合并 PR4。PR4 有冲突时，让 Codex 先 rebase 再合并。
4. 合并后立即手动运行一次生产 workflow（GitHub → Actions → radar-production → Run workflow，以仓库实际的触发方式为准），确认 step summary 是 ✅，线上首屏正常。
5. 看当天 18:15 那次定时运行有没有发生。没有发生，多半是默认分支问题（§8.2）。
6. 出问题时回滚：
   - **最快**：Vercel 控制台 → 项目 → Deployments → 上一次生产部署 → Instant Rollback（页面立刻恢复）。注意：回滚后，后续部署可能不会自动指向正式域名，修好后要在 Vercel 撤销回滚（以 Vercel 界面为准）；
   - **代码层**：在 GitHub 上 revert PR4（必要时连同 PR3）的合并提交，再手动运行一次生产 workflow。`--source toml` 在 PR5 之前一直保留，页面靠 §10.10 兼容显示。

### 12.8 产品负责人要做的事

| 什么时候 | 做什么 | 参考 |
|---|---|---|
| PR1 之前 | 把 zip 里的文件上传到新分支 `v3-inputs` | 附录 B |
| PR1 之后 | 如果 Codex 拿不到默认分支或定时运行记录：在 GitHub 网页看「Settings → General → Default branch」和「Actions → radar-production」（按 Event 筛选 schedule），把结果告诉 Codex | §8.2 |
| PR3 评审 | 打开 PR 里的截图，与 `docs/design/v3/shots/` 对照；满意就 Approve，**先不合并** | §10.12 |
| PR4 合并前 ① | 在 Notion 建 internal connection（只勾 Read content），添加到页面「投研雷达｜数据后台」；在自己电脑上跑 curl 自测 | 附录 A |
| PR4 合并前 ② | GitHub → Settings → Secrets and variables → Actions → New repository secret：`NOTION_TOKEN` | §4.1 |
| PR4 合并前 ③ | 回答 Codex 的默认分支问题（A 或 B）；选 A 就在 GitHub 上改默认分支 | §8.2 |
| PR4 合并前 ④ | 让 ChatGPT 按《维护规则》做第一次完整刷新：当周每周主线 + 15 个行业 + 16 个卡点的研判（理由、来源、研判日期、有效至） | Notion「维护规则｜ChatGPT」 |
| PR4 合并前 ⑤ | Actions → radar-interface-acceptance → Run workflow：Branch 选 `v3/pr4-production`，勾选 `live_notion`；打开 artifact `live-notion-dry-run`，确认 `meta.weekly.mode = ai`、没有沿用上次版本的表 | §8.8 |
| 合并 | 工作日 14:00–17:00 依次合并 PR3、PR4，然后手动运行一次生产 | §12.7 |
| 上线 1 周后 | 确认成功的定时运行 ≥ 15 次 → 让 Codex 开 PR5 | §12.6 |

日常不需要再碰 GitHub 或 Vercel：内容由 ChatGPT 写进 Notion，雷达每个交易日自动读取 3 次；脉搏变黄时打开页脚「数据说明」看原因。

---

## 13. 不要做

1. 不改行情、汇率、温度计、比值、估值的算法与数据源（`quotes.py` 等）。
2. 网站和管线不调用任何大模型；所有自动生成的文字只用固定模板（§6.4、§6.5）。
3. 不写回 Notion：token 只读，不调用任何写接口。
4. 不新增第三方依赖、前端框架、打包工具；不新增颜色。
5. 页面不出现禁用词、买卖或仓位建议、预测性文字；不出现「已核实 / 已审核 / 人工确认 / 已验证」和旧的核验类措辞（唯一例外：免责声明里的“未经人工审核”）。
6. 不泄露 token：不打印，不写进文件、异常、DATA、snapshot、artifact、step summary，不传给 collect 以外的步骤。
7. 不改仓库设置（默认分支、分支保护、Secrets）和 Vercel 项目设置；需要改时写进 PR 描述，由产品负责人操作。
8. 不直接推送生产分支，不自己合并 PR，不跳过或关闭 CI。
9. 不删除或放宽行情真实性测试；不为了让测试通过而改阈值或断言。
10. 不改 fixtures 期望值和契约；认为它们有错 → 停下来问。
11. 不部署、不扫描 `docs/`；`.mock-note` 不进生产。
12. 查询 Notion 不带 filter / sorts（全量读取后在代码里排除与排序，§4.2）；不按属性 id 读取（id 只用于诊断）。
13. 不显示港股每日要点；不做账号、付费墙、订阅。
14. 一个 PR 只做该 PR 的范围；发现范围外的问题，写进 PR 描述的「后续建议」，不顺手改。

---

## 附录 A · Notion token：创建与自测（在你自己的电脑上做）

1. 打开 Notion 开发者门户 [app.notion.com/developers/connections](https://app.notion.com/developers/connections)（需要工作区所有者身份）→ 新建 connection，类型选 **Internal**，名称写「投研雷达只读」，工作区选你的工作区。
2. 能力（Capabilities）**只勾 Read content**；不勾 Update content、Insert content；用户信息选 No user information。
3. 在 Configuration 标签页复制 API token。**不要把 token 发到任何聊天里**（包括 ChatGPT、Codex、Notion AI）。
4. 打开页面「投研雷达｜数据后台」→ 右上角 ••• → Connections → + Add connection → 选「投研雷达只读」→ 确认它能访问该页面及全部子页面（6 个库都在这个页面下）。
5. 在自己电脑的终端里自测：

```bash
read -rs NOTION_TOKEN && export NOTION_TOKEN   # 粘贴 token 后回车（不会显示在屏幕上）
curl -sS https://api.notion.com/v1/data_sources/12b00256-3ec7-4755-ad78-d14932b7f42f \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2026-03-11" | head -c 200; echo
```

| 看到 | 含义 | 怎么办 |
|---|---|---|
| `{"object":"data_source","id":"12b00256-…` | 成功 | 进入第 6 步 |
| `"status":401`（`unauthorized`） | token 不对 | 重新复制 token（前后不要带空格或引号） |
| `"status":404`（`object_not_found`） | connection 没加到页面上 | 重做第 4 步 |
| `"status":403`（`restricted_resource`） | 能力不够 | 确认勾了 Read content |

6. GitHub → 仓库 → Settings → Secrets and variables → Actions → New repository secret：Name 填 `NOTION_TOKEN`，Secret 粘贴 token → Add secret。
7. 以后要换 token：在 Configuration 标签页重新生成 → 更新这个 GitHub Secret → 手动运行一次生产 workflow。

---

## 附录 B · 配套文件放进仓库

zip 解压后的目录结构就是它们在仓库里的位置：

| zip 里的路径 | 用途 |
|---|---|
| `docs/V3-BRIEF.md` | 本任务书 |
| `docs/design/v3/overview-v3.html` | 首页目标效果（静态设计稿，10/21 基线数据） |
| `docs/design/v3/components-v3.html` | 组件规格（故意列出了禁用词：不部署、不扫描） |
| `docs/design/v3/v3-components.css` | 新增样式（PR3 追加进 `radar/site/style.css`） |
| `docs/design/v3/shots/*.png` | 截图：`ov_*` = 首页（桌面深 / 浅、平板、手机深 / 浅 × 首屏 / 整页），`sheet_*` = 组件页 |
| `radar/data/notion_schema.json` | 属性契约 |
| `radar/tests/fixtures/notion_v3/` | fixtures、期望值、103 个用例、README、`quotes/data-2026-10-21.json` |
| `先看我.md` | 给产品负责人看的上传说明，**不放进仓库** |

这些都是新增文件，不会覆盖仓库里现有的文件；如果上传时提示同名文件已存在，先停下来问 Codex。

**方式一：GitHub 网页上传（不用装任何东西）**

1. 打开仓库主页 → 左上角分支下拉框 → 先切到生产分支 `fix/radar-truthfulness-2026-10-18`。
2. 在同一个下拉框里输入 `v3-inputs` → 点「Create branch v3-inputs from fix/radar-truthfulness-2026-10-18」。
3. 确认当前分支是 `v3-inputs` → 「Add file」→「Upload files」。
4. 把解压出来的 `docs` 和 `radar` **两个文件夹**一起拖进上传区（网页会保留文件夹结构）。
5. 提交说明写「v3 任务书、设计稿与 fixtures」→ 选「Commit directly to the v3-inputs branch」→「Commit changes」。
6. 检查：在 `v3-inputs` 分支能看到 `docs/V3-BRIEF.md` 和 `radar/tests/fixtures/notion_v3/README.md`。
7. 把 §12.2 的 PR1 提示词交给 Codex（提示词里已写明从 `v3-inputs` 开始）。

**方式二：本地仓库 / Codex CLI**

```bash
git fetch origin
git switch -c v3-inputs origin/fix/radar-truthfulness-2026-10-18
unzip radar-v3-brief.zip -d /tmp/v3 && cp -R /tmp/v3/docs /tmp/v3/radar .
git add docs radar && git commit -m "v3 任务书、设计稿与 fixtures" && git push -u origin v3-inputs
```

---

## 附录 C · Notion 数据库 ID

顶层页面「投研雷达｜数据后台」：`653140659aa74497abcc6d5041a4d3f8`。请求一律用 **data source id**（API `2026-03-11`）；database id 只用于诊断。

| 代码表名 | Notion 库 | database id | data source id |
|---|---|---|---|
| `industries` | 行业 🧭 | `e0f96809-3f5b-4d41-9029-c8ceb4d2c467` | `12b00256-3ec7-4755-ad78-d14932b7f42f` |
| `chokepoints` | 卡点 🔩 | `545d8e99-b83d-4483-bd5d-c5ee449e5e29` | `fcb39e45-1e23-41de-bef9-9f91fef8cfb6` |
| `companies` | 公司 🏢 | `f5e1e4e5-84c0-4801-b4f8-c1a1892f561d` | `51ff5113-6a00-495b-9ae9-8f66a5999f63` |
| `financials` | 财报记录 📑 | `f2e6f09d-be6f-4206-99b1-2fad27220d3e` | `adfa9345-7f74-42c0-88c8-cc706b7970cf` |
| `daily` | 每日要点 🗓️ | `94a84484-238d-4159-8438-7e999a4ff302` | `8c8f38ad-be8d-4fce-bbdf-7701492f9e8e` |
| `weekly` | 每周主线 📌 | `7391dcc4-49ad-4085-b1c5-2691d19481f4` | `81122088-02df-4abf-a79a-d8574cf7cbef` |

契约里的 `tables.*.data_source_id` 必须与上表一致（契约完整性测试检查）。

---

## 附录 D · DATA v3 结构

只列新增和改动的部分；其余字段（行情、汇率、温度计、`meta.snapshot` 等）保持现状，以仓库为准。

```jsonc
{
  "meta": {
    "weekly": {
      "week": "2026-W43", "weekStart": "2026-10-19", "weekEnd": "2026-10-25",
      "sourceWeek": "2026-W42",                    // 所用行的周次；auto / none 为 ""
      "mode": "ai | stale | auto | none",
      "focus": "AI网络与光互连", "lead": "…", "calHint": "…",
      "judgment": {"label": "ai | stale | auto", "reasons": ["not_current_week", "expired"],
                   "date": "2026-10-17", "validUntil": "2026-10-19", "reason": "研判理由全文", "sources": ["https://…"]}
    },
    "daily": {                                      // 只有 A股、美股；港股不写
      "A股": {"date": "2026-10-21", "source": "ai | auto", "line": "…", "reviewUrl": "https://… 或 \"\"",
              "industries": ["AI核心半导体"], "chips": [{"symbol": "000001.SS", "label": "上证", "chg": -0.00598}]},
      "美股": {"date": "2026-10-20", "…": "同上"}
    },
    "notion": {
      "source": "notion | partial | last_good | toml",
      "fetchedAt": "2026-10-21T18:15:00+08:00",
      "snapshotSHA256": "64 位小写十六进制（research-snapshot.json 的 sha256，无前缀）",
      "requests": {"total": 13, "GET": 6, "POST": 7, "retries": 0},
      "counts": {"industries": {"fetched": 15, "used": 15, "excluded": 0, "quarantined": 0, "substituted": 0}, "…": "6 张表"},
      "fallbackTables": [{"table": "weekly", "code": "notion_not_found", "detail": {}, "lastGoodFetchedAt": "…"}],
      "quarantined": [{"table": "industries", "pageId": "…", "key": "消费", "code": "number_out_of_range", "field": "景气度", "usedLastGood": true}],
      "warnings": [{"code": "text_long", "table": "companies", "key": "CXMT", "field": "快讯", "detail": {}}]
    },
    "schedule": {"cronUtc": ["45 0 * * 1-5", "15 4 * * 1-5", "15 10 * * 1-5", "50 22 * * 0"],
                 "nextRunAt": "2026-10-22T08:45:00+08:00", "lateAfterMinutes": 90}
  },
  "industries": [{
    "name": "…", "s": [5, 5, 5, 4], "total": 19, "logic": "…", "signal": ["≤ 4 条"], "risk": "…", "reps": "…",
    "kb": "Notion 页面 URL", "rowSource": "notion | last_good",
    "judgment": {"label": "ai | stale", "reasons": [], "date": "…", "validUntil": "…", "reason": "…", "sources": ["https://…"],
                 "anchors": {"业绩兑现": {"anchor": 5, "n": 9, "medianRevenueYoYPct": 85.5},
                             "卡点强度": {"anchor": 5, "n": 4, "maxTightness": "极紧"}},
                 "conflicts": [{"field": "业绩兑现", "ai": 2, "anchor": 5}]}
  }],
  "chokepoints": [{"name": "…", "ind": "…", "tight": "极紧 | 偏紧 | 缓解中", "seg": "…", "why": "…", "track": "…",
                   "rowSource": "notion | last_good",
                   "judgment": {"label": "…", "reasons": [], "date": "…", "validUntil": "…", "reason": "…", "sources": []}}],
  "companies": [{
    "…": "现有字段（id、name、code、sym、mkt、cur、role、ind、cp、view、flash、next、url、revg、earng、gm、period、三个布尔、行情字段）",
    "flashDate": "2026-10-17", "flashFresh": true, "flashSource": "https://… 或 \"\"",
    "rowSource": "notion | last_good",
    "earnings": {"status": "confirmed | unverified", "source_url": "…", "timezone": "Asia/Seoul", "time_note": "09:00 前发布"},
    "provenance": {"financial": {"…": "fixtures README 的 FIN_KEYS（含 entered_at、evidence）", "rowSource": "notion | last_good"}}
  }],
  "changes": {"today": {"date": "2026-10-21", "reports": ["公司代号"], "confirmed": ["公司代号"], "scores": ["行业名"]}}
}
```

- `provenance.financial` 没有财报记录时为 `null`（§7.2）。
- `changes` 的位置沿用现有 `daily_changes.py` 输出（以仓库为准），只新增 `today`；页面显示的数 = 各列表长度。
- **删除的字段**：`industries[].review`、`chokepoints[].review`、`meta.weekly.review`、`meta.weekly.thermoAction`、`companies[].flashStatus`、`earnings.published_at`、`earnings.verified_at`。**改名**：`provenance.financial.verified_at` → `entered_at`；`provenance.financial.status` → `evidence`（`source | partial | missing`）。
- `release.json` v3：现有字段保留；`schemaVersion: 3`；新增 `researchSnapshotSHA256`（同 `meta.notion.snapshotSHA256`）和 `notion: {source, requests, counts, fallbackTables, warningCount, quarantinedCount}`。

---

## 附录 E · code 的中文文案

用于 step summary、页脚「数据说明」、标签提示和日志。`{}` 是占位符；表名用中文（industries 行业、chokepoints 卡点、companies 公司、financials 财报记录、daily 每日要点、weekly 每周主线）。日志里只写这些文案和 code，**不写请求头和 token**。

**读取（transport）**

| code | 文案 | 处理 |
|---|---|---|
| `notion_token_missing` | 未设置 NOTION_TOKEN | 研究数据全部沿用上次版本 |
| `notion_unauthorized` | NOTION_TOKEN 无效或无权限（401） | 同上 |
| `notion_forbidden` | NOTION_TOKEN 权限不足（403） | 同上 |
| `notion_not_found` | {表}库 404：未共享给 connection 或已移动 | 整表沿用 {时间} 的版本 |
| `notion_rate_limited` | Notion 限流（429），重试 3 次仍失败 | 同上 |
| `notion_server_error` | Notion 服务器错误（{状态码}），重试 3 次仍失败 | 同上 |
| `notion_timeout` | 读取超时或连接失败 | 同上 |
| `notion_bad_json` | Notion 返回的内容无法解析 | 同上 |
| `notion_cursor_loop` | 分页游标重复，已停止读取 | 同上 |
| `notion_too_many_pages` | 超过 50 页，已停止读取 | 同上 |
| `notion_body_too_large` | 单次响应超过 8 MB，已停止读取 | 同上 |
| `notion_http_error` | Notion 请求失败（{状态码}） | 同上 |
| `no_last_good` | 读不到研究数据，也没有上次成功的版本 | 本次不发布，线上保持上一次部署 |

**表级**

| code | 文案 | 处理 |
|---|---|---|
| `notion_schema_changed` | Notion 列名被改：{列名}（`missing`）／Notion 列类型被改：{列名}（{原类型} → {新类型}） | 整表沿用 {时间} 的版本 |
| `table_quality_low` | 有误的行太多（{坏行}/{总行}） | 整表沿用 {时间} 的版本 |

**行级**（处理：有上次版本 → 显示上次版本；没有 → 暂不显示；每日要点 / 每周主线 → 跳过该行）

| code | 文案 |
|---|---|
| `missing_required` | 缺必填项：{列名} |
| `number_out_of_range` | {列名}超出 {最小}–{最大} |
| `number_not_integer` | {列名}应为整数 |
| `invalid_enum` | {列名}的选项「{值}」不在约定范围内 |
| `regex_mismatch` | {列名}格式不对：{值} |
| `relation_missing` | {列名}没有关联，或关联的行已停用 |
| `relation_multiple` | {列名}只能关联 1 行 |
| `duplicate_key` | 与另一行重复：{key}（保留较早创建的一行） |
| `period_after_publish` | 期末日晚于发布日 |
| `publish_in_future` | 发布日晚于今天 |

**字段级**（只提醒，按规则置空、截断或降级，不影响整行）

| code | 文案 |
|---|---|
| `text_long` | 文字偏长：{n} 字（建议 ≤ {上限}） |
| `text_truncated` | 文字超长，已截到 {上限} 字 |
| `list_truncated` | 条目过多，只保留前 {上限} 条 |
| `relation_truncated` | 关联过多，只保留前 {上限} 个 |
| `banned_words` | 含禁用词「{词}」，该内容不显示 |
| `prediction_words` | 含预测性用词「{词}」，改用自动生成句 |
| `token_unknown_company` | 财报日标记里的代号 {代号} 不存在或已停用，显示为「日期待定」 |
| `cp_industry_mismatch` | 所属卡点不属于该公司的行业，不挂卡点 |
| `earnings_confirmed_without_source` | 标了官方确认但没有 https 来源，按预估显示 |
| `earnings_date_past` | 下次财报日已过，待更新 |
| `timezone_invalid` | 时区无效：{值}，改用市场默认时区 |
| `url_invalid` | 链接不是 https，已忽略 |
| `pct_out_of_range` | {列名}超出合理范围，已置空 |
| `pct_suspicious` | {列名}数值异常大，照常显示 |
| `pct_maybe_fraction` | {列名}可能写成了小数（{值}），照原值显示 |
| `flash_date_future` | 快讯日期晚于今天，按今天处理 |
| `financial_duplicate` | 同一期有多条财报记录，保留录入日较晚的一条 |
| `daily_duplicate` | 同一市场同一天有多条，用最近编辑的一条 |
| `daily_future_date` | 日期晚于该市场最近交易日，已忽略 |
| `company_cap_exceeded` | 公司超过 80 家，多出的不显示 |

**研判原因**（标签「待更新」的提示；多个原因用「；」连接）

| code | 文案 |
|---|---|
| `missing_reason` | 缺研判理由 |
| `missing_source` | 缺来源链接 |
| `missing_dates` | 缺研判日期或有效至 |
| `future_judgment_date` | 研判日期晚于今天 |
| `expired` | 研判已过期（有效至 {日期}） |
| `validity_too_long` | 有效期超过 14 天 |
| `banned_words` | 含禁用词，相关文字不显示 |
| `row_quarantined` | 本行数据有误，显示上次成功读取的版本 |
| `not_current_week` | 不是本周的研判，显示上次结论 |
| `no_weekly_row` | 本周还没有主线研判 |
| `legacy_data`（仅前端，§10.10） | 旧版数据，无研判信息 |

**构建产物**（都是 exit 2：本次不发布，线上保持上一次部署）

| code | 文案 |
|---|---|
| `banned_words_in_output` | 页面里出现禁用词「{词}」（{位置}） |
| `quotes_coverage_low` | 有行情的公司只有 {n}/{总数}（低于 70%） |
| `contract_invalid` | 契约文件不合法：{原因} |

**时区中文名**（财报日胶囊与提示）

| IANA | 显示 |
|---|---|
| `Asia/Shanghai` | 北京时间 |
| `America/New_York` | 美东时间 |
| `Asia/Hong_Kong` | 香港时间 |
| `Asia/Taipei` | 台北时间 |
| `Asia/Seoul` | 韩国时间 |
| `Asia/Tokyo` | 东京时间 |
| `Europe/Paris`、`Europe/Amsterdam`、`Europe/Berlin` | 欧洲中部时间 |
| 其他 | 原样显示 IANA 名称 |

---

## 附录 F · 术语

| 术语 | 意思 |
|---|---|
| last-good | 上一次成功发布时实际用到的研究数据（`research-snapshot.json`） |
| 简化行 | 把一个 Notion page 压成 `{id, created_time, last_edited_time, props}`，只留契约里要读的列（§4.5） |
| 研判 | AI 对行业、卡点、每周主线写的判断，带理由、来源、研判日期、有效至 |
| 数据档 | 程序用硬数据算出的参考档位（业绩兑现、卡点强度），只用来提示，不改分 |
| 数据冲突 | AI 分与数据档相差 ≥ 2 |
| 隔离 | 某一行不合格，不用这一行（有上次版本就用上次版本） |
| 排除 | 停用、已删除或上级停用的行，静默不显示，不报警 |
| fixedClock | 构建用的固定时钟；同一输入 + 同一时钟 → 同一输出 |
| ISO 周 | 周一开始的周次，如 `2026-W43` = 10/19–10/25 |
| 契约 | `radar/data/notion_schema.json`，规定每张表每一列怎么读、怎么校验 |
| FakeTransport | 测试里代替网络的假 Notion，按 fixtures 回放响应，并记录请求与等待 |
| 脉搏 | 首屏 KPI 下面那一行更新状态（绿 / 黄 / 红） |

---

## 参考资料

- Notion API：[Retrieve a data source](https://developers.notion.com/reference/retrieve-a-data-source) · [Query a data source](https://developers.notion.com/reference/query-a-data-source) · [Request limits](https://developers.notion.com/reference/request-limits) · [Changes by version（2026-03-11：`archived` → `in_trash`）](https://developers.notion.com/reference/changes-by-version) · [Internal connections](https://developers.notion.com/guides/get-started/internal-connections) · [Capabilities](https://developers.notion.com/reference/capabilities)
- GitHub Actions：[Events that trigger workflows（schedule 只在默认分支触发、整点高峰可能延迟）](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) · [Manually running a workflow](https://docs.github.com/en/actions/using-workflows/manually-running-a-workflow)
- 合规（§11）：[湖北证监局：非法荐股典型案例](https://www.csrc.gov.cn/hubei/c105452/c7584358/content.shtml) · [证监会：荐股软件相关规定](https://www.csrc.gov.cn/csrc/c100028/c1002385/content.shtml) · [网信办通报](https://www.cac.gov.cn/2026-04/16/c_1778078583431637.htm) · [《互联网信息服务管理办法》](http://xzfg.moj.gov.cn/front/law/detail?LawID=550&Query=%E7%BD%91) · [上证信息：授权声明](https://www.sseinfo.com/aboutus/authstatement/) · [Vercel 合理使用准则](https://vercel.com/docs/limits/fair-use-guidelines)
