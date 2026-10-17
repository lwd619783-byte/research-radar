# 投研雷达 · 维护手册（HANDOFF）

> 读者：日常维护者（ChatGPT）。仓库所有者：LWD。
> 本文件是投研雷达的唯一维护说明。首次部署步骤见同目录 `DEPLOY.md`。

---

## 1. 背景与已定决策

| 事项 | 决定 |
|---|---|
| 来源 | 2026-10-17 由 Notion AI 搭建：先在 Notion「投研工作看板」建了三张表（行业雷达 / 关键卡点 / 龙头公司），再做成单文件 HTML 仪表盘。现已整体迁到本仓库，Notion 看板只读归档，顶部已标注「已迁移至 GitHub，此处不再更新」。**不要再回 Notion 改数据。** |
| 仓库 | 知识库（`投研知识库/…`）与投研雷达（`radar/`）同一个仓库。 |
| 维护方式 | 维护者在每周分支（如 `weekly/2026-W43`）上增量提交，每周开一个 PR 合并到 `main`。合并即发布。 |
| 行情刷新 | GitHub Actions 定时抓 Yahoo Finance（腾讯财经备用），交易日北京时间 07:05 / 11:40 / 16:20 各一次；行情没变化（节假日、周末）自动跳过部署。 |
| 托管 | Vercel（所有者已有账号），Vercel CLI 从 Actions 部署；项目名 `investment-radar`（来自输出目录名）。**不要在 Vercel 里 Import 这个 Git 仓库**，否则会多出一套自动构建。 |
| 域名 | 所有者在腾讯云的域名下挂一个子域名（CNAME 到 Vercel）。**具体子域名由维护者记录**；所有者忘了时请告诉他。 |
| 前端 | 视觉与交互已定稿，迁移时只做了数据驱动的小改动（见第 8 节）。除非所有者明确要求，不改布局与样式。 |
| 深度开发 | 新模块、重构、数据源大改等，所有者会回到 Notion AI 处理；日常维护不需要。 |

## 2. 架构与数据流

```
radar/data/*.toml ──┐
                    ├─ scripts/build.py ── 校验(schema.py) ── 抓行情(quotes.py) ── 计算指标
radar/site/*  ──────┘                                                       │
                                                                            ▼
                         radar/dist/investment-radar/index.html（CSS/JS/数据全部内联，约 300 KB）
                                                + vercel.json（noindex、禁缓存）+ robots.txt
                                                                            │
                     GitHub Actions ── vercel deploy --prod ──► Vercel ──► 子域名
```

- **你维护的**：`radar/data/*.toml`（观点、评分、财务、快讯、财报日、本周结论）。
- **脚本自动算的**：最新价、涨跌幅（1日/5日/20日/60日/年初至今）、距 52 周高点、52 周高点、市值（折美元）、PE(TTM)、走势图、跑马灯指数、红利温度计比值。**不要把这些写进 TOML。**
- 行情缓存：`radar/.cache/quotes.json`（不进 Git，用 Actions cache 在多次运行之间传递）。某只股票抓取失败时用上次缓存并标注「行情暂未更新」；完全没有数据的显示「暂无行情」；缺失超过 30% 时构建中止、不发布（线上保持上一版）。
- 是否部署：脚本对「页面数据 + 前端文件」算指纹，与缓存里的上次指纹相同就输出 `changed=false`，工作流跳过部署。

## 3. 文件地图

| 路径 | 作用 | 谁改 |
|---|---|---|
| `radar/data/config.toml` | 标题、仓库地址、本周结论、跑马灯指数、比值代码、汇率兜底 | 维护者（每周改 `[weekly]`） |
| `radar/data/industries.toml` | 行业雷达：四维评分、逻辑、信号、风险、代表公司、知识库路径 | 维护者 |
| `radar/data/chokepoints.toml` | 关键卡点：所属行业、紧缺度、为什么卡、跟踪指标 | 维护者 |
| `radar/data/companies.toml` | 细分龙头：代码、定位、看点、快讯、下次财报日、最新一期财务 | 维护者（财报季最频繁） |
| `radar/site/index.html` `style.css` `app.js` | 前端模板 | 一般不改 |
| `radar/scripts/build.py` | 构建入口 | 一般不改 |
| `radar/scripts/schema.py` | 数据校验规则（错误信息为中文） | 加字段时才改 |
| `radar/scripts/quotes.py` | 行情抓取（Yahoo / 腾讯） | 数据源出问题时才改 |
| `.github/workflows/radar-deploy.yml` | 定时刷新 + main 合并后发布 | 一般不改 |
| `.github/workflows/radar-preview.yml` | PR 校验 + 预览地址评论 | 一般不改 |

## 4. 字段说明（单位务必看清）

### 4.1 `config.toml`

| 字段 | 说明 |
|---|---|
| `[site] title` | 页面标题，默认「投研雷达」。 |
| `[site] repo_url` | `https://github.com/用户名/仓库名`。填了才显示「知识库笔记」「打开 GitHub 仓库」按钮。私有仓库链接只有有权限的人能打开。 |
| `[site] kb_branch` | 知识库链接指向的分支，默认 `main`。 |
| `[weekly] week` | 如 `2026-W43`，仅记录用。 |
| `[weekly] focus` | 首屏「本周最值得追踪」的行业，必须与 `industries.toml` 的 `name` 完全一致；留空则取总分最高者。 |
| `[weekly] lead` | 首屏导语（1–2 句）。只在 focus 行业作为首屏时显示；留空自动拼「该行业 logic + 最紧卡点」。 |
| `[weekly] calendar_hint` | 财报日历「今天」格子下的一句提示，如「三季报季：先看预告与快报，再看正式报告」。 |
| `[weekly] thermo_action` | 红利定投温度计的操作建议，如「按原计划定投，不加不减」。 |
| `[[index]]` | 跑马灯指数：`symbol`（Yahoo 代码）、`name`、`tencent`（腾讯备用代码，可省略）。 |
| `[ratio]` | 创业板指 ÷ 中证红利 月线的数据代码，一般不改。 |
| `[fx_fallback]` | 汇率抓取失败时的兜底：1 美元兑当地货币；`EURUSD` 是 1 欧元兑美元。只影响市值折算。 |

### 4.2 `industries.toml` → `[[industry]]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | 字符串 | 行业名，唯一。被卡点、公司、`weekly.focus` 引用，**改名要同步改所有引用**。 |
| `scores` | `{ boom, delivery, choke, valuation }` | 各 1–5 **整数**。总分 = 四项之和（满分 20）。 |
| `logic` | 字符串 | 一句话逻辑（结尾不加句号）。 |
| `signal` | 字符串 | 最新信号，用「；」分隔多条。 |
| `risk` | 字符串 | 主要风险。 |
| `reps` | 字符串 | 代表公司，用「、」分隔（也用于搜索）。 |
| `kb` | 字符串 | 知识库笔记的**仓库相对路径**，如 `投研知识库/行业研究/AI网络与光互连｜交换、光模块、CPO与高速连接.md`。路径不存在时 `--check` 会提醒。目前这些路径按 Notion 导出时的文件名填写，迁移后若目录或文件名不同，请批量改成实际路径。 |

评分口径（AI 初评，所有者可校准）：

- `boom` 景气度：需求增速与资本开支强度，5 = 最强。
- `delivery` 业绩兑现：龙头最近财报是否已兑现高增长，5 = 大幅兑现。
- `choke` 卡点强度：供给瓶颈是否清晰并带来定价权，5 = 极紧。
- `valuation` 估值位置：相对历史与增速的性价比，**5 = 回调最充分 / 最便宜**。
- 级别（页面自动计算）：总分 ≥ 17 重点追踪；14–16 持续观察；≤ 13 低频跟踪。
- 只有在 `chokepoints.toml` 里有卡点的行业，才会出现在卡点地图和龙头热力图里（目前 4 个：AI网络与光互连、AI核心半导体、PCB与覆铜板、电力与数据中心）。前端预留了 6 种行业配色，新增第 5、6 个有卡点的行业会自动分配颜色。

### 4.3 `chokepoints.toml` → `[[chokepoint]]`

| 字段 | 说明 |
|---|---|
| `name` | 卡点名，唯一。被公司引用。 |
| `industry` | 所属行业，必须与某个行业 `name` 完全一致。 |
| `tightness` | 只能是 `极紧` / `偏紧` / `缓解中`。同一行业内按紧缺度、再按文件顺序展示。 |
| `segment` | 细分领域。 |
| `why` | 为什么卡（转述的信息注明「转述」）。 |
| `track` | 跟踪指标；写成 `10/31` 这种 月/日 格式的日期会被高亮。 |

### 4.4 `companies.toml` → `[[company]]`

| 字段 | 说明 |
|---|---|
| `id` | 唯一短代号（英文字母/数字/`-`/`_`），如 `ZJXC`。网址锚点和内部索引用，**定了就别改**。 |
| `name` | 显示名。海外公司可写「博通 Broadcom」，页面短名取第一个空格前的部分。 |
| `symbol` | **Yahoo Finance 代码**，用于抓行情：A 股 `300308.SZ` / `688498.SS` / `920xxx.BJ`；港股 `0522.HK`（Yahoo 用 4 位数字）；美股 `NVDA`；台股 `2383.TW`（上柜 `.TWO`）；韩股 `000660.KS`；日股 `3110.T`；欧股 `ENR.DE`、`SU.PA`、`ASML.AS`。 |
| `code` | 页面上显示的代码，如 `SZ300308`、`HK0522`、`NVDA`。 |
| `market` | `A股` / `港股` / `美股` / `台股` / `韩股` / `日股` / `欧股`。 |
| `role` | 定位，目前用 `全球龙头` / `国内龙头` / `国产替代`。 |
| `industry` `chokepoint` | 必须与卡点及其所属行业一致，否则校验报错。 |
| `view` | 一句话看点。 |
| `flash` | 业绩快讯：最近一次预告 / 快报 / 财报要点；以「；⏳ 三季报10/31」这类格式提示下一个事件。 |
| `next_earnings` | 下次财报日 `YYYY-MM-DD`；未知留空 `""`。已过去的日期 `--check` 会提醒你更新。财报日历只显示今天及以后的日期。 |
| `kb` | 公司研究笔记的仓库相对路径（可留空）。 |
| `fin.period` | 财报期，如 `26Q2单季`、`26Q3`、`26H1`、`FQ3(至8/2)`。A 股写「单季」表示由累计数倒算单季。 |
| `fin.revenue_yoy` | 营收同比，**百分数**：+174.6% 写 `174.6`，−35% 写 `-35`。 |
| `fin.profit_yoy` | 净利（A 股为归母净利）同比，百分数；亏损转盈等无意义时省略该键。 |
| `fin.gross_margin` | 毛利率，百分数（`46.4` = 46.4%）。银行等无毛利率的省略。 |
| `fallback_pe` | Yahoo 拿不到 PE 时的兜底，可省略。亏损公司不写。 |
| `fallback_mcap_usd_bn` | Yahoo 拿不到市值时的兜底，**十亿美元**（`19.1` = 191 亿美元），用于热力图面积。 |

页面自动生成的信号（不用写）：

- 业绩（看净利同比，缺失时看营收）：高增 ≥ 50%；增长 ≥ 10%；平稳 > −10%；其余为下滑。
- 股价：走强 = 近 20 日 ≥ +5%；深度回调 = 距 52 周高点 ≤ −40%；回调 = 近 20 日 ≤ −10%；其余为震荡（按此顺序判断）。
- 收益率用复权价计算；价格、52 周高点与走势图用原始收盘价。市值按当日汇率折美元。

## 5. 每周维护清单

1. 从 `main` 建分支 `weekly/YYYY-Www`，本周的知识库和雷达改动都提交到这里（可多次增量提交）。
2. **财报**：本周发了财报 / 预告 / 快报的公司 → 更新 `fin`、`flash`，把 `next_earnings` 改成下一次（未知留空）。
3. **行业**：有新信号就更新 `signal` / `risk`；景气、兑现、卡点、估值有实质变化时再改 `scores`，并在 PR 描述里写一句理由。
4. **卡点**：紧缺度变化（如扩产落地 → `缓解中`）更新 `tightness` 与 `track`。
5. **本周结论**：更新 `config.toml [weekly]` 的 `week`、`focus`、`lead`、`calendar_hint`、`thermo_action`。`lead` 里的数字类表述（如「龙头近期大幅回调」）要与页面实际行情相符——可先看线上页面再写。
6. 运行 `python radar/scripts/build.py --check`（无法本地运行时，开 PR 后看 `radar-preview` 的校验结果）。
7. 开 PR → 等预览评论里的地址，打开检查首屏、卡点地图、财报日历 → 合并到 `main`，几分钟后正式地址更新。

建议在 PR 描述里列出：改了哪些公司财务、哪些分数变化及理由、本周结论。

## 6. 常见变更怎么做

- **新增行业**：在 `industries.toml` 加一段 `[[industry]]`。没有卡点的行业只出现在行业热度榜。
- **新增卡点**：在 `chokepoints.toml` 加一段；`industry` 必须已存在。没有公司的卡点会被提醒。
- **新增公司**：在 `companies.toml` 加一段，先在 Yahoo Finance 网站确认 `symbol` 能打开；`id` 选一个新短代号。合并后下一次刷新自动出现行情。建议每个卡点 1–3 家，总数控制在 60 家以内（页面体积与抓取时间）。
- **删除公司**：直接删整段。
- **行业 / 卡点改名**：搜索旧名，在三个 TOML（和 `weekly.focus`）里全部替换。
- **调整刷新时间**：改 `radar-deploy.yml` 的 cron（UTC = 北京时间 − 8 小时，注意跨日时星期也要往前挪一天）。

## 7. 本地运行与校验

```bash
python radar/scripts/build.py --check      # 只校验，不联网；有错误时退出码 1
python radar/scripts/build.py              # 抓行情 + 生成；然后用浏览器打开 radar/dist/investment-radar/index.html
python radar/scripts/build.py --offline    # 用缓存，不联网
python radar/scripts/build.py --force      # 强制 changed=true
```

- 只需要 Python ≥ 3.11 标准库，无第三方依赖。
- 校验**错误**（阻断）：TOML 语法、缺必填字段、重复的 name / id / symbol、分数不是 1–5 整数、紧缺度不在枚举内、行业 / 卡点引用不一致、市场不在枚举内、A 股 / 港股代码格式不对、日期格式不对、财务字段名拼错或毛利率写成小数。
- 校验**提醒**（不阻断）：知识库路径不存在、`next_earnings` 已过去、卡点下没有公司。
- 退出码 2 = 行情缺失超过 30%，本次不发布。

## 8. 迁移时对前端做的改动（相对 Notion 版）

- 「行情截至」标签由脚本生成：A 股盘中显示「10/20 10:05 盘中」，午休「10/20 午间」，收盘后「10/20 收盘」。
- 「今天」按访问者浏览器的北京时间计算（财报倒计时不会因节假日不部署而过期）。
- 首屏行业取 `weekly.focus`，导语取 `weekly.lead`；温度计建议取 `weekly.thermo_action`；日历提示取 `weekly.calendar_hint`。
- 去掉所有「在 Notion 打开」按钮；行业与公司的主按钮改为「知识库笔记」（有 `kb` 且配置了 `repo_url` 时才显示）；页脚改为「打开 GitHub 仓库」。
- 行情缺失 / 过期的展示兜底；表格列名「收盘」改为「最新价」；页面加 `noindex`。

## 9. 排错

| 现象 | 处理 |
|---|---|
| Actions 里「校验数据」失败 | 打开该运行的 Summary 或日志，按中文错误提示改 TOML。 |
| 某只股票一直「行情暂未更新」 | 多半是 `symbol` 写错或 Yahoo 改了代码。去 finance.yahoo.com 搜索确认；A 股 / 港股会自动尝试腾讯备用源。 |
| 大面积抓取失败、退出码 2 | Yahoo 临时限流（HTTP 429）或接口变动。等下一次定时任务；持续 1 天以上再查 `quotes.py`。线上会保留上一版，不会挂掉。 |
| 市值 / PE 全部变成兜底值 | Yahoo 的 crumb 接口失效（`quotes.yahoo_quotes`）。不影响主要功能；必要时更新 `fallback_*`。 |
| 定时任务晚了几十分钟 / 偶尔漏跑 | GitHub 定时任务的正常现象，下一次会补上。需要立刻刷新时：Actions → radar-deploy → Run workflow。 |
| 部署步骤报 token 错误 | `VERCEL_TOKEN` 过期或被删：所有者重新创建并更新 GitHub Secret（见 DEPLOY.md）。 |
| 部署成功但域名没更新 | 在 Vercel 项目 Domains 里确认子域名挂在 `investment-radar` 项目、状态为 Valid；浏览器强刷。 |
| 部署成功但出现了第二个 Vercel 项目 | 未配置 `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` 时 CLI 按目录名关联项目，作用域变化可能新建项目。按 DEPLOY.md 第 5 步补上两个 ID。 |
| 定时任务全部停了 | 公开仓库 60 天无提交会自动停用定时任务；Actions 页面点 Enable 即可。 |

## 10. 不要做的事

- 不要把价格、涨跌幅、市值、PE 手工写进 TOML。
- 不要提交 `radar/dist/` 和 `radar/.cache/`（已在 `.gitignore`）。
- 不要在 Vercel 导入这个 Git 仓库，也不要改 Vercel 项目的 Build 设置（我们上传的是已构建好的静态文件）。
- 不要把 `VERCEL_TOKEN` 写进任何文件或 PR。
- 不要回 Notion「投研工作看板」更新数据（已归档）。
