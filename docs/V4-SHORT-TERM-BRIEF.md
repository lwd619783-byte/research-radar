# 投研雷达 V4 · 短线复盘（Short-Term Radar）目标模式一体化总任务书（给 Codex）

> **一句话定位**：在保留现版「投研雷达 V3」全部产业研究与行情真实性门禁的前提下，新增独立切换视图 **「短线复盘」**。前端视觉、7 层动态交互光效与文案规范已由设计侧定稿交付，本任务书为 **Codex 目标模式（Goal Mode）一站式执行规范**：涵盖页面融合、双平面后端数据源、容错门禁及连续 4 个里程碑的全栈实现与自检标准。
>
> 目标仓库：`lwd619783-byte/research-radar` · 默认源码分支：`fix/radar-truthfulness-2026-10-18`
> 配套交付包位置：`docs/design/v4-short/`、`radar/data/short_term_schema.json`、`radar/tests/fixtures/short_term_v4/`

---

## 0. 一页看懂（10 条核心铁律）

1. **职责边界**：前端样式（`docs/design/v4-short/short-term-v4.css`）、渲染与动效引擎（`docs/design/v4-short/short-term-v4-ui.js`）以及视觉基准页（`docs/design/v4-short/short-term-v4-preview.html`）**已定稿**。Codex 负责将它们精确挂载到现有构建体系，并完整实现后端采集、脱敏校验、容错合并、离线测试与本地调度；**不得推翻或简化既定 UI 布局、配色与 7 层动态光效**。
2. **双视图不拉长首页**：原版 5 大板块（总览 / 行业雷达 / 卡点地图 / 龙头公司 / 财报日历）收拢在 `#longTermView`；新增同级 `#shortTermView[hidden]`。顶部 `.nav` 末尾新增「短线复盘」；首屏 `#today` 卡片底部新增 `#todayShortTeaser` 跳转条。
3. **每日一版 20:30 晚间定稿**：兼顾 15:00 收盘硬数据与 18:00–20:00 抖音/小红书财经大V晚间复盘评论区发酵，本地管线于每个交易日 **北京时间 20:30** 统一跑完采集并产出一版定稿。
4. **双平面架构（关键）**：`ego-browser` 登录态与免封禁本地行情网关（`mootdx`/腾讯/串行东财）仅存在于**本机运行环境**，**禁止把任何账号 Cookie、Ego 会话或爬虫塞进 GitHub Actions 云端**。本地采集脚本产出标准化的滚动 10 日快照 `radar/data/short_term_history.json`；云端只负责安全合并、校验、扫描与构建发布。
5. **个股红黑榜硬门槛**：全市场榜必须 **剔除上市不足 30 自然日新股、剔除 `ST / *ST / 退市整理` 标的，且日成交额 `>= 10 亿元`**，取涨幅 Top 5 与跌幅 Top 5 **双版面常驻**；同步对比 `DATA.companies` 中 `market == "A股"` 的核心池涨跌 Top 5。
6. **板块同屏可切换**：同时采集并输出申万/东财 **行业板块 Top 5** 与 **概念题材 Top 5**，标注是否命中雷达高景气卡点（`★ 雷达主线`）。
7. **Ego 五平台抓取与双层脱敏**：覆盖 `东方财富股吧`、`雪球`、`同花顺论股堂` + `抖音 / 小红书`（采用 **固定大V白名单 + `#A股复盘` 热榜** 双轨抓取大V内容下的散户评论）。落盘前必须过滤水帖/引流帖、**剥离所有 `@个人网名` 改为匿名角色标签**，并对口语中的禁用词执行映射替换。
8. **昨日锚点对账 + 3~5★ 催化日历**：自动读取前一交易日 3 条观察锚点与今日实盘对比给出 `pass / partial / fail`；同时整合未来重要宏观/产业催化大事（3~5★ 评级），计算 `T-N天` 倒计时并标注「会前预期潜伏 / 临近防兑现 / 宏观定调锚」。
9. **绝对隔离故障（主站优先）**：短线模块任何采集失败、快照缺失、字段超限，仅在短线视图降级沿用上次快照并标 `isStale: true`，**绝对不允许阻断原有 V3 产业雷达 6 张 Notion 表与主站行情的发布**。
10. **零放宽现有安全门禁**：`output_scan.py`（24 个 `banned_words`、8 个 `UI_WORDS`、`disclaimers == 1`、XSS 转义、无 `.mock-note`、无 Token 泄露）与 `verify-release.cjs` 一律不得放宽或绕过。

---

## 1. 页面如何融入现有「投研雷达 V3」

### 1.1 HTML 壳与 DOM 挂载约定（`radar/site/index.html`）
保持现版单文件内联构建机制（`build.py` 注入 CSS/JS/DATA）与无外部依赖原则不变：

1. **顶部导航 `.nav`**：在 `<a href="#calendar" data-sec="calendar">财报日历</a>` 之后新增：
   ```html
   <a href="#short" id="navShort" data-sec="short" class="is-new">短线复盘</a>
   ```
2. **双视图容器包裹 `<main class="wrap">`**（**页脚 `<footer class="foot">` 与唯一 `#disclaimer` 保持放在视图容器外部，确保全页始终仅出现 1 次 `#disclaimer` 以通过 `output_scan.py`**）：
   ```html
   <main class="wrap">
     <div id="longTermView">
       <!-- 原有的 #overview / #radar / #choke / #leaders / #calendar 五个 section -->
     </div>
     <div id="shortTermView" class="sr-view" hidden></div>
     <footer class="foot" id="foot"><!--__SSR_FOOT__--></footer>
   </main>
   ```
3. **首屏 `#today` 卡片联动入口**：在 `radar/site/app.js` 渲染 `#today`（今日要点）底部时追加 `<div id="todayShortTeaser"></div>`，交由 `short-term-v4-ui.js` 渲染「短线复盘 · MM/DD · 情绪分 · 领涨行业 → 进入短线复盘」。

### 1.2 CSS、JS 与 7 层动态光效保留要求
1. 将 `docs/design/v4-short/short-term-v4.css` 完整追加至 `radar/site/style.css` 末尾（不删减动画关键帧、聚光灯遮罩与 `prefers-reduced-motion` 无障碍降级）。
2. 将 `docs/design/v4-short/short-term-v4-ui.js` 逻辑并入 `radar/site/app.js`（或作为内联模块紧跟 `app.js` 注入 `index.html`），保证完整保留其实现的 **7 大动态特效**：
   - 顶栏 2px 阅读进度细线（`.sr-read-progress`）
   - `IntersectionObserver` 错峰滚动渐显（`.sr-reveal`）
   - 入场数字滚动跳字（`countUp` / `data-count`）与散户情绪半圆仪表弹簧指针 + 呼吸光环（`.sr-gauge-needle` / `.sr-gauge-halo`）
   - 鼠标跟随双层径向聚光灯与语义色边缘高光（`.sr-glow` + `--glow-c`）及 `★★★★★` 催化卡顶部流光扫描灯带（`@keyframes srScan`）
   - 物理滑动滑块胶囊组（`.sr-seg .thumb`）与视图柔滑过渡（`.sr-fade-swap`）
   - 红黑榜行级竖向光条、Sparkline 渐变面积发光（`#sr-g-up` / `#sr-g-down`）与光标悬浮毛玻璃提示框（`.sr-tip`）
   - 纵向时间轴滚动激光充能进度线（`--tl-fill` / `.is-lit`）与左侧粘性目录 ScrollSpy 自动高亮闪烁定位（`.sr-flash`）
3. 在 `app.js` 初始化末尾挂载：
   ```js
   const shortCtl = window.AlphaRadarShortTerm.initShortTermModule({
     shortData: D.shortTerm || null,
     mountEl: document.getElementById('shortTermView'),
     longViewEl: document.getElementById('longTermView'),
     todayTeaserEl: document.getElementById('todayShortTeaser'),
     onViewChange(view) { /* 同步更新顶部 .nav 激活态与 .nav-ind 滑块位置 */ }
   });
   ```
4. **搜索与旧 DATA 兼容**：点击 `.nav` 中原 5 个锚点或按 `⌘K` 搜索跳转到某公司/行业时，自动切回 `long` 视图再平滑滚动；当 `DATA.shortTerm` 缺失时，`#longTermView` 与 `#today` 不受影响，手动切入 `#shortTermView` 时显示温和降级提示。

---

## 2. 后端需要哪些数据 & 通过什么方式取数

整体采用 **「本机 20:30 采集汇总 → 标准化滚动 JSON（+ Notion 轻量台账）→ 云端构建发布」** 的混合架构，严格符合 `radar/data/short_term_schema.json` 契约：

### 2.1 数据清单与精确获取路径

| 模块 / 字段 | 所需数据明细 | 首选数据源与获取方式 | 降级与约束 |
| :--- | :--- | :--- | :--- |
| **1. 市场宽度与极值 KPI** | 上涨/平盘/下跌家数、三市总成交额及较前日差值、涨停/跌停家数、炸板率、昨日涨停今日溢价率 | **A股硬数据层**：`mootdx`（通达信行情接口）+ 腾讯财经批量报价；涨停/炸板/溢价率取同花顺问财/涨停复盘接口或本机已有 `a_share_review` 包 | 单源异常标 `X` / `—`，不编造 `0` 填充 |
| **2. 板块红黑榜 Top 5** | 行业板块涨跌幅 Top 5 & Bottom 5；概念题材 Top 5 & Bottom 5（含成交额、主力净流向、5日走势微图、驱动归因、命中雷达卡点标记） | 东方财富板块指数与资金流端点（**必须串行请求且间隔 ≥ 1.5s**）+ 同花顺行业/概念热点原因；雷达主线映射通过比对 `DATA.industries` 与 `DATA.chokepoints` 关键词/成分股匹配 | 归因缺失时写「行业/题材短线资金波动」 |
| **3. 个股红黑榜双版面** | ① **全市场活跃股 Top 5（涨/跌各5）**：全市场日线剔除上市 `< 30` 天新股、`ST/*ST/退市`、限定日成交额 `>= 10 亿元`；② **雷达核心池 Top 5**：从 `DATA.companies`（`market == 'A股'`）排序截取 | `mootdx` 全市场收盘行情 + 腾讯行情补充上市日期/换手率/成交额；5日 `spark` 取近 5 个交易日收盘价数组 | 上市日期缺省时保守排除 `N`/`C` 前缀次新股 |
| **4. 昨日锚点对账** | 读取 `short_term_history.json` 中前 1 个交易日的 `anchors`（或 Notion 台账覆盖值），对照今日实际成交额、涨跌家数、板块强弱、连板高度生成 `pass / partial / fail` 与实盘结果句 | 本地脚本 `reconcile_previous_day()` 自动比对数值锚点（若当日 Notion 台账存在人工填入的对账结论，以 Notion 为准） | 无前一日数据时展示「首个记录日，暂无前日对比」 |
| **5. 日内时间轴演进** | `09:25` 竞价定调、`10:30` 早盘主升、`13:30` 午后承接、`15:00` 收盘结算、`17:30` 龙虎榜、`20:15` Ego 舆情 | 拉取上证/创业板及当日 Top1 领涨行业/概念的 **5 分钟 / 15 分钟 K 线**（`mootdx` / 腾讯分时），由固定规则模板提取各时段涨跌幅与领涨领跌切换事实，**禁止调用大模型编造盘中细节** | 分时接口失败时退化为仅展示 `15:00`、`17:30`、`20:15` 三节点 |
| **6. 周期梯队与共振矩阵** | ① 短线周期 5 阶段定位、最高连板与 2/3/4+ 连板晋级率；② 基本面×短线 2×2 共振四象限 | ① 由连板股池统计封板率/晋级率映射周期阶段；② 交叉比对「今日行业/概念涨跌幅」与 `DATA.industries` 20分制评分（`>= 16分且大涨`→主线共振；`< 16或未入池且大涨`→纯情绪脉冲；`>= 16且回调`→主线分歧；`缺卡点且大跌`→双杀回避） | 四象限无符合项时保留空态文案「今日暂无此类标的」 |
| **7. 17:30 龙虎榜与排雷** | 当日重点异动股买/卖前五席位净额（识别机构席位、沪深股通 vs 东财拉萨营业部）；未来 5 日大额解禁、减持、严重异动提示 | 东方财富龙虎榜详情接口（串行限流）+ 东方财富限售解禁日历 + 巨潮公告关键词（减持 / 异常波动） | 无上榜股或接口限流时省略或标「今日数据暂缺」 |
| **8. 20:15 Ego 5 平台舆情** | 东财股吧、雪球、同花顺论股堂 + 抖音/小红书（`kol_whitelist.toml` 固定大V白名单 + `#A股复盘` 热榜）散户评论、多空占比、声量增幅与圈层温差 | 本机 **Ego Browser 只读采集器**（复用用户已登录会话标签页，只读不发帖不点赞）；经本地规则/摘要提炼情绪标签与反向指标诊断 | **强制过滤引流/水帖；强制剥离 `@网名` 匿名化；强制执行 24 词替换脱敏；单平台超时则降级标记部分覆盖** |
| **9. 3~5★ 宏观与产业催化日历** | 未来 45 天重大国际/国内宏观决议、产业大会、数据发布日（日期窗口、`T-N天`、3~5 星评级、映射板块、预期/兑现博弈提示） | **三源融合**：① `jin10` 金十财经日历（筛选中美重要度 `>= 3星`）；② 东财/同花顺投资日历（筛选产业大会）；③ **Notion《催化事件日历》**（人工维护特注事件如听证会、股东大会，同 ID 以 Notion 为准） | 根据距开始日期天数与映射板块近5日累计涨幅，自动标注「会前潜伏 / 临近防兑现 / 宏观观望」 |

### 2.2 混合存储架构与 Notion 可选表设计
1. **仓库滚动快照（`radar/data/short_term_history.json`）**：存最近 **10 个交易日** 的完整 `days[]` 明细与 `catalysts[]`（每次采集自动裁剪超出 10 个交易日的旧条目）。
2. **Notion 轻量人工校准表（可选，对应 `short_term_schema.json`）**：
   - 《短线复盘台账》：8 列（`交易日期`, `定调结论`, `散户情绪分`, `短线周期阶段`, `明日锚点_1~3`, `停用`）。
   - 《催化事件日历》：人工维护 3~5★ 宏观/产业大会及博弈提示。
   - 若 Notion 未建表或配置为空，`build.py` 与采集器静默跳过 Notion 覆写，完全使用 `short_term_history.json`。

### 2.3 安全与合规硬门禁（极其重要！）
**本机采集写入 JSON 之前** 以及 **云端 `build.py` 合并 `DATA.shortTerm` 时**，必须双保险运行 `sanitize_short_term_text()`：
- 正则剥离 `@[^\s，。！？、）)]+` 替换为 `匿名用户`；
- 按 `radar/data/short_term_schema.json` 的 `banned_word_mask_map` 替换全部 24 个 `banned_words` 与 8 个 `UI_WORDS`，保证 100% 不触发 `output_scan.py` `exit 2` 阻断发布！

---

## 3. 目标模式全栈实施里程碑（连续闭环推进）

Codex 在目标模式下，按以下 **Milestone 1 → Milestone 4** 顺序连续开发与自检；**每个里程碑完成后必须跑通对应门禁再进入下一里程碑**（禁止跳步、禁止直接推送或 merge 生产分支 `fix/radar-truthfulness-2026-10-18`）：

### Milestone 1：数据契约、云端容错合并与脱敏门禁
- **工作内容**：
  1. 将 `radar/data/short_term_schema.json` 与标准离线样本 `radar/tests/fixtures/short_term_v4/sample_short_term_history.json` 纳入仓库。
  2. 新增 `radar/scripts/short_term_merge.py`（仅用 Python 标准库）：
     - 读取可选的 `radar/data/short_term_history.json`（缺失或 JSON 损坏时返回 `None` + warning，绝不阻断主站）。
     - 执行契约校验、`<= 10` 日滚动裁剪、`sanitize_short_term_text()` 二次脱敏清洗（清除 24 个禁用词、8 个旧 UI 词及 `@个人网名`）。
     - 预留可选 Notion 台账/催化表只读叠加接口（未配置或 404/超时均静默降级）。
  3. 更新 `radar/scripts/build.py`，注入 `DATA["shortTerm"]`（无短线快照时保持缺省且不影响原有 V3 产物）。
  4. 新增离线单元测试 `radar/tests/test_short_term_merge.py`（覆盖正常合并、注入禁用词/UI词/@网名清洗、缺失/损坏降级、超 10 日裁剪、`output_scan.scan_output()` 验证）。
- **门禁自检**：原有全部测试 + `test_short_term_merge.py` 全绿；注入 fixture 构建后运行 `python radar/scripts/output_scan.py` 返回 `ok: true`。

### Milestone 2：前端双视图与定稿 7 层动效 UI 挂载
- **工作内容**：
  1. 将定稿样式 `docs/design/v4-short/short-term-v4.css` 追加进 `radar/site/style.css` 末尾。
  2. 改造 `radar/site/index.html`：新增 `#navShort`、包裹 `#longTermView`、同级挂载 `#shortTermView[hidden]`，保证 `<footer class="foot">` 与唯一 `#disclaimer` 在视图容器外。
  3. 将定稿模块 `docs/design/v4-short/short-term-v4-ui.js` 集成至 `radar/site/app.js`，在 `#today` 底部挂载 `#todayShortTeaser`，联动 `.nav-ind` 滑块、`⌘K` 搜索回切 `#longTermView` 及缺省降级提示，**完整保留全部 7 层动画与鼠标光效**。
  4. 扩充 Playwright 自动化测试：覆盖「总览 ⇄ 短线复盘切换」「10日胶囊切换」「行业⇄概念切换」「Ego 5平台过滤」「1440 / 1180 / 390 三档无横向溢出」「深浅色与红绿切换」并生成截图产物。
- **门禁自检**：`output_scan.py`（含 `site_dir` 扫描）分别对「含 `sample_short_term_history.json`」与「不含 `shortTerm` 的旧 DATA」测试均返回 `ok: true`；Playwright 测试全绿。

### Milestone 3：本机 A 股硬数据、龙虎榜、催化日历与昨日对账采集器
- **工作内容**：
  1. 新增本地采集包 `radar/tools/short_term_collector/` 与 CLI 入口 `radar/tools/collect_short_term.py`（支持 `--dry-run`、`--offline-fixture`、`--date YYYY-MM-DD`）：
     - 市场宽度/极值、行业与概念 Top 5（东财请求严格串行间隔 `>= 1.5s`）、个股红黑榜硬过滤（剔除 `< 30` 日新股、`ST/*ST/退市`、成交 `< 10亿`）与雷达池对照、5日 Sparkline。
     - 5/15 分钟线客观提取日内时间轴节点（禁用大模型编造）。
     - 17:30 龙虎榜机构/北向/拉萨席位统计 + 未来 5 日解禁/减持排雷。
     - 3~5★ 催化兑现日历（聚合 `jin10` + 东财投资日历 + 预留 Notion 表覆写，计算 `T-N天` 与预期/兑现阶段）。
     - 昨日锚点自动对比（`pass/partial/fail`）、10 日滚动裁剪、强制脱敏清洗、原子写入 `radar/data/short_term_history.json`。
  2. 编写完全离线单元测试（FakeHttp/MockFetcher，CI 运行零外网请求），验证过滤、限流间隔、对账计算、10 日裁剪、24 词脱敏。
- **门禁自检**：离线单测全绿；本机 `--dry-run` / 离线样本生成 JSON 后，通过 `short_term_schema.json`、`build.py` 与 `output_scan.py`。

### Milestone 4：本机 Ego 五平台采集器、可选 Notion 同步与 20:30 调度收口
- **工作内容**：
  1. 新增 `radar/data/kol_whitelist.toml`（配置抖音、小红书固定大V白名单及 `#A股复盘` 搜索标签）。
  2. 新增 `radar/tools/short_term_collector/ego_sentiment.py`（支持 `--skip-ego` 降级参数）：通过本机 `ego-browser` 只读巡检东财/雪球/同花顺 + 抖音/小红书双轨评论区，执行水帖/引流过滤、强制匿名化与 24 词+8 词脱敏替换，计算多空比、圈层温差与 0–100 情绪分。
  3. 编写本机运维手册 `docs/SHORT-TERM-RUNBOOK.md`：说明 Windows 20:30 定时任务设置、Ego 未登录/验证码交接流程、`--skip-ego` 降级路径及推送触发云端发布流程。
  4. 新增 5 平台 HTML/JSON 离线解析与极限脏数据（含禁用词/`@网名`/引流微信号）测试，并全量跑通 `Milestone 1~4` 端到端回归。
- **门禁自检**：全仓所有离线测试、`output_scan.py`、`verify-release.cjs`（可用检查项）全绿；在最终交付报告中列出新增/修改文件、实测命令逐项结果、截图路径及需要用户在本机补充的抖音/小红书大V白名单或可选 Notion 表 ID。

---

## 4. 明确禁止项（Codex 不得越界）

1. **严禁** 修改现版主站产业研究（`industries / chokepoints / companies / financials / daily / weekly`）的评分算法、估值、汇率或比值计算逻辑。
2. **严禁** 将 `ego-browser` 登录状态、Cookie 或无头爬虫脚本配置进 `.github/workflows/*.yml` 云端 CI 运行。
3. **严禁** 在页面正文、图表、提示或 `DATA.shortTerm` 中保留未脱敏的 `@个人昵称` 或任何 `banned_words` / `UI_WORDS`。
4. **严禁** 让短线模块异常导致主站（V3 产业雷达）构建 `exit 2` 中断发布。
5. **严禁** 未经用户评审擅自 merge 或直接 push 生产分支，严禁在代码中调用外部大模型 API 或泄露任何 Token。
