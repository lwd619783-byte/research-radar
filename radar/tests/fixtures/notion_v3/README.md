# radar/tests/fixtures/notion_v3/ — v3 Notion 读取器的离线测试数据

> 属性契约（唯一真相）在 **`radar/data/notion_schema.json`**（不在本目录）；本目录只放测试数据。

这些文件取自 2026-10-21 的「投研雷达｜数据后台」（6 个数据库，15/16/42/42/2/1 行），已转换成 **Notion API `2026-03-11`** 的真实响应形状。
测试全程离线：用 FakeTransport 按 `notion/index.json` 的路由返回这些文件，**不需要 NOTION_TOKEN，也不访问网络**。

> 这批数据已和 2026-10-21 线上 DATA（现行 TOML 构建产物）逐字段对照：除下文「有意差异」外 **0 差异**。

## 1. 文件清单

```
radar/data/notion_schema.json     # 属性契约（唯一真相）：每列类型/级别/枚举映射/正则/长度/规则 + 禁用词、预测词、市场默认时区

radar/tests/fixtures/notion_v3/
├── notion/
│   ├── index.json                # notion_version、as_of、today、6 张表的 database_id/data_source_id/行数、路由表、注意事项
│   ├── ds_<table>.json           # GET  /v1/data_sources/{id}        （schema 检查用）
│   ├── query_<table>.json        # POST /v1/data_sources/{id}/query （第一页）
│   └── query_companies_p2.json   # 公司表第 2 页（p1 25 行 has_more=true，p2 17 行）
├── expected/
│   ├── research_projection.json  # 规范化结果的“投影”，parity 测试的期望值
│   └── v3_view.json              # 研判标签、数据档、周主线回退、今日要点、KPI、基线提示、自动文本模板的期望值
├── cases.json                    # 103 个负面/边界用例（变更操作 + 期望结果 + 断言）
├── quotes/data-2026-10-21.json   # 10/21 线上 DATA（现行 TOML 构建）：parity 对照参考 + PR3 离线渲染用的真实行情
└── README.md
```

`<table>` = `industries / chokepoints / companies / financials / daily / weekly`（读取顺序也按这个顺序）。

`index.json → notes` 里列出了故意保留的难点，读取器必须处理：
- `results` 顺序被打乱 → 输出必须自己排序（排序规则见 `notion_schema.json → tables.*.order`）。
- 公司表分两页，`next_cursor` 原样回传，不解析。
- 源杰科技「快讯」拆成 2 段 rich_text，且 `{{earnings:YJKJ}}` 跨段 → 先拼接所有片段的 `plain_text` 再处理。
- 源杰科技 · FY2026 Q2「注意事项」2 段（含 italic）→ 拼接后按 `\n` 拆成 `conditions`。
- 来源类字段是自动链接（`text.link` + `href`）→ 一律以 `plain_text` 为准。
- property id / option id 只用于诊断；代码按**属性名 / 选项名**读取。

## 2. FakeTransport 约定

```python
class FakeTransport:
    """request(method, path, json_body) -> (status, headers, body_bytes)；可注入 sleep()。"""
    # 路由：index.json["routes"] 中 method + path 完全相等，且 POST 时 body.get("start_cursor") == route["start_cursor"]
    # 找不到路由 → 抛 AssertionError（防止测试偷偷多发请求）
    # 记录：self.requests（每次调用 +1，含重试）、self.sleeps（读取器请求的每次等待秒数，不真的 sleep）
```

- 读取器必须通过**可注入的 transport 和 sleep** 工作（生产用 `urllib`，测试用 FakeTransport）。
- 正常一次完整读取 = **13 个请求**（6 个 GET schema + 7 个 POST query，公司 2 页）。
- POST body 固定为 `{"page_size": 100}`（翻页时加 `"start_cursor"`）；不带 filter / sorts（停用等在代码里排除）。

## 3. 测试 1 — 读取 + 规范化 parity

```
project(build_data(source="notion", transport=FakeTransport(...), fixed_clock=index.as_of))
    == expected/research_projection.json
```

`project()` 只取研究字段，按固定键排序；浮点用 `math.isclose(rel_tol=1e-9, abs_tol=1e-12)` 比较：

```python
FIN_KEYS = ['source_name','source_url','source_urls','period_end','published_at','entered_at','basis','currency',
            'accounting_basis','fiscal_year','fiscal_period','profit_metric','revenue_scope','profit_scope','margin_scope',
            'report_status','profit_comparison','derivation','calculation_note','review_note','disclosure_state',
            'conditions','evidence']
def project(D):
    I = [{k: i[k] for k in ('name','s','total','logic','signal','risk','reps','kb')} for i in D['industries']]
    C = [{k: c[k] for k in ('name','ind','tight','seg','why','track')} for c in D['chokepoints']]
    O = []
    for c in D['companies']:
        o = {k: c[k] for k in ('id','name','code','sym','mkt','cur','role','ind','cp','view','flash','next','url','revg','earng',
                               'gm','period','financialPartial','financialRevenueComparable','financialSignalEligible')}
        o['earnings'] = {k: c['earnings'][k] for k in ('status','source_url','timezone','time_note')}
        f = c['provenance']['financial']
        if f is not None:
            o['financial'] = {k: f[k] for k in FIN_KEYS}
        O.append(o)
    w = D['meta']['weekly']
    return {'industries': sorted(I, key=lambda x: x['name']),
            'chokepoints': sorted(C, key=lambda x: (x['ind'], x['name'])),
            'companies': sorted(O, key=lambda x: x['id']),
            'weekly': {'week': w['sourceWeek'], 'focus': w['focus'], 'lead': w['lead'], 'calHint': w['calHint']}}
```

要点：百分比列 ÷100（`营收同比% 174.6 → revg 1.746`）；`cp` 无卡点时为 `''`；`next` 为空时为 `None`；
`earnings.status` 仍是内部值 `confirmed | unverified`（页面显示「官方确认 / 预估」）；`kb` 是 Notion 页面 URL。

### 与现行 TOML 构建对照（PR2 期间必须一起跑）

`--source toml` 产出的 DATA 做同样的投影，再套用下面的**有意差异**后，应与 `--source notion` 完全相同：

| # | 字段 | TOML（现行） | Notion（v3） |
|---|---|---|---|
| 1 | `industries[].kb` | 仓库 md 路径 | Notion 页面 URL |
| 2 | `provenance.financial.verified_at` | 有 | 改名 `entered_at` |
| 3 | `provenance.financial.status` | `verified / verified_partial` | 改为 `evidence: source / partial / missing` |
| 4 | `industries / chokepoints / meta.weekly .review` | 有 | 删除，改为 `judgment {...}` |
| 5 | `meta.weekly.thermoAction` | 有 | 删除 |
| 6 | `earnings.published_at / verified_at` | 有 | 删除 |
| 7 | `companies[].flashStatus` | 有 | 删除，改为 `flashDate / flashFresh / flashSource` |
| 8 | `meta.weekly.week` | 行的周次 | 当前 ISO 周；行的周次放到 `sourceWeek` |

## 4. 测试 2 — v3 视图（expected/v3_view.json）

基线（未修改的 fixtures，今天 = 2026-10-21，ISO 周 2026-W43）应得到：

- 15 个行业、16 个卡点全部 `judgment.label = "ai"`（研判日期 10-17，有效至 10-24）。
- 数据档（anchors）：AI网络与光互连 业绩兑现 5（n=9，中位数 +85.5%）、AI核心半导体 5（n=9，+55.2%）、PCB与覆铜板 5（n=10，+60.9%）、电力与数据中心 3（n=11，+18.1%；施耐德「仅营收」不计入，口径同 financialRevenueComparable）；四个行业卡点强度档均为 5（极紧）；**无冲突**。
- 每周主线：`mode = "stale"`，`sourceWeek = "2026-W42"`，`reasons = ["not_current_week", "expired"]`（这就是线上当前真实状态）。
- 今日要点：A股 2026-10-21、美股 2026-10-20 都来自 Notion（`source = "ai"`）。
- 公司证据：有原文 40、部分 2（KBL 半年累计，DZSK 初步结果）；KPI：重点行业 3、极紧卡点 7/16、公司 42、财报日官方确认 1、待定 4。
- 提示：只有 7 条 info 级 `text_long`（6 条公司快讯 + Modine 显示期间）。
- `autoTemplates`：当行无效时自动生成句的期望文本（每日两条、每周导语与日历提示）。

## 5. 测试 3 — cases.json

每个用例：先把 fixtures 复制到临时目录 → 按 `mutations` 依次修改 → 用 FakeTransport 跑完整读取 + 规范化 + 构建 → 检查 `expect`。

**基线 last-good**：默认先用未修改的 fixtures 跑一次，得到 `research-snapshot.json` 作为 last-good；`given.baseline = "none"` 表示没有 last-good。
**时钟与行情**：默认用顶层 `as_of / trading_days / index_changes`；`clock` 操作可覆盖时钟。

### 变更操作（mutation helper）

| op | 字段 | 作用 |
|---|---|---|
| `set` | `table, row, prop, value` | 改一个属性。`row` 用表的 key：行业/卡点 = 名称，公司 = 代号，财报 = 记录（标题），每日 = 标题，每周 = 周次。`value` 简写：`null`；数字；字符串（title/rich_text/url → 单段 text；date → `YYYY-MM-DD`；select → 选项名）；布尔（checkbox）；字符串数组（relation → 目标表的 key，helper 解析成 page id） |
| `set_raw` | `table, row, prop, raw` | 直接写入 Notion 原始属性值（测 mention 等） |
| `add_row` | `table, id, copy_of?, created_time, last_edited_time, set` | 新建 page（可从某行复制后再改） |
| `add_many` | `table, count, id_start, pattern, created_time, last_edited_time` | 批量新建；`pattern` 里 `{n:02d}` 等用 Python `str.format(n=…)` 展开，n 从 1 开始 |
| `remove_row` | `table, row` | 删除该行 |
| `page_attr` | `table, row, attr, value` | 改 page 顶层字段（如 `in_trash`） |
| `schema_rename` / `schema_type` / `schema_add_prop` / `schema_remove_prop` / `schema_add_option` | `table, prop, …` | 同时修改 `ds_<table>.json` 与所有 page 的属性 |
| `http` | `match {kind: schema\|query\|any, table?, start_cursor?}, responses[], then: normal\|repeat_last` | 对匹配的请求依次返回给定响应（`status/headers/body` 或 `body_text`、`body_bytes: n`、`timeout: true`），用完后恢复正常或一直重复最后一个 |
| `inject_result` | `table, object` | 在 query 结果里混入非 page 对象 |
| `cursor_loop` | `table` | 第 2 页返回 `has_more: true` 且 `next_cursor` 等于第 1 页的 cursor |
| `shuffle` | `seed` | 用另一种顺序打乱所有 results |
| `env` | `unset[] / set{}` | 改环境变量 |
| `clock` | `as_of` | 覆盖 fixedClock |

新 page id 用 `00000000-0000-4000-8000-000000000xxx`；新行的 `created_time` 晚于原有行（原有行均为 `2026-10-21T02:40:00.000Z`）。

### 期望（expect）

- `outcome`：`ok | warning | exclude | quarantine_row | table_last_good | all_last_good | abort`（含义见 `cases.json → outcomes`）。
- `exit`：进程退出码（abort = 2）。
- `codes`：必须全部出现在 `meta.notion.warnings[].code ∪ quarantined[].code ∪ fallbackTables[].code`（abort 时看错误输出）；除 info 级 `text_long` 外**不得出现其他 code**，除非 `other_codes = "ignore"`。
- `ui`：人工可读的页面效果（Playwright 视觉测试可抽查）。
- `assert`：机器断言，`{path, <op>: value}`。

**path 语法**：`a.b.c`；`[k=v]` 过滤列表（字符串比较），过滤后只剩 1 个元素时自动取出；`[0] / [-1]` 取下标；`[*].k` 投影。
**根**：`industries / chokepoints / companies / meta.*` → 构建出的 DATA；`transport.requests / transport.sleeps`；`logs`（stdout+stderr 文本）；`snapshot`（research-snapshot.json 文本，`snapshot.sha256` 为其 SHA-256）；`data`（DATA JSON 文本）；`files.written`（本次写出的发布文件列表）。
**op**：`eq / ne / contains / not_contains / absent / len / approx / eq_baseline`（与基线运行结果相等）。

### 用例分组

| 组 | 编号 | 覆盖 |
|---|---|---|
| transport | T01–T13 | token 缺失、401/403、404、429 + Retry-After、5xx、超时、非 JSON、游标循环、>8 MB、非 page 结果、in_trash、无 last-good 时 abort |
| schema | S01–S07 | 列改名/改类型/删除（整表 last-good）、新增选项/新列（忽略）、新选项被使用（隔离该行） |
| industries / judgment | R01–R17 | 分数越界/非整数/为空、重名、研判各缺项、过期/未来/超 14 天、截断、禁用词（含全角空格拆分）、数据冲突、停用级联、信号条数 |
| chokepoints | C01–C06 | relation 缺失/多个、紧缺度为空、未知 token、排序为空、禁用词 |
| companies | P01–P19 | 重复/小写代号、Yahoo 代码、市场为空、卡点跨行业、官方确认无来源、财报日为空/已过、时区、未知 token、快讯截断（含 token 边界）、快讯新旧、80 家上限、未来快讯日期、URL、禁用词、名称为空 |
| financials | F01–F17 | 缺来源、期末日晚于发布日、未来发布日、重复录入、小数/越界百分比、扭亏、新 Q3 正式报告/预告、无公司、公司停用、报告状态为空、http 来源、200 天边界、可疑大数 |
| daily | D01–D10 | 未写/日期不对/预测词/禁用词/重复/截断/港股/复盘链接/美股日期/涉及行业上限 |
| weekly | W01–W07 | 本周有效 → ai；基线 stale；自动生成；禁用词/无主线 → 回退；全部过期 → none；有效期过长 |
| quarantine | Q01–Q03 | 整表阈值（>20%，表 ≥5 行）、边界 20%、新坏行无 last-good |
| security | X01–X04 | token 不出现在日志/产物、顺序无关的确定性输出、mention 片段、基线请求数 |

## 6. 以后 Notion 结构变了怎么办

1. 先改 `notion_schema.json`（契约），再改代码；
2. 用只读 token 重新导出 fixtures（脚本由 Codex 写在 `tools/export_notion_fixtures.py`，导出后打乱 results 顺序，保留 index.json 的结构）；
3. 重新生成 `expected/*`，人工看 diff 后提交。
