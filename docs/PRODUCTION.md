# 投研雷达 V3 生产运维

生产源码与默认分支为 `fix/radar-truthfulness-2026-10-18`。`production` 由发布工作流生成静态文件。Vercel 使用 `lkdmkl/research-radar` 项目，Vercel Authentication 的 All Deployments 保护覆盖正式站点和版本端点。[正式站点](https://research-radar-lkdmkl.vercel.app/) · [生产工作流](../.github/workflows/radar-production.yml)

## 调度与运行

| 北京时间 | GitHub cron（UTC） | 外部 slot |
| --- | --- | --- |
| 周一 06:50 | `50 22 * * 0` | `monday-0650` |
| 工作日 08:45 | `45 0 * * 1-5` | `weekday-0845` |
| 工作日 12:15 | `15 4 * * 1-5` | `weekday-1215` |
| 工作日 18:15 | `15 10 * * 1-5` | `weekday-1815` |

内置 cron 和外部时钟共用 `radar-production` 并发组。排队、外部触发识别和 180 分钟外部准入窗口见 [外部时钟触发](../radar/docs/EXTERNAL-SCHEDULE.md)。生产源码的相关 push 及手动 dispatch 也会触发工作流。

1. `baseline` 核对执行 SHA，读取经过 Vercel 成功回执及发布文件校验的基线。定时运行先判定所属时段，同源码 SHA 在该时段已有成功发布时跳过。
2. `preflight` 执行全量离线回归和契约检查。`collect` 只读 Notion 六表，将请求结果脱敏后交给构建，再按交易所日历采集和选择行情。
3. `prepare` 校验同一次执行的 receipt、数据时钟、文件哈希和发布门槛，并运行 `node verify-release.cjs --check-only`。
4. `publish` 检查生产源码头和当前基线，以普通快进提交发布到 `production`。`result` 等待 Vercel 对该输出 SHA 的结果。发布失败时，符合恢复条件才发布保留原 DATA 和原数据时钟的失败提示。回退守卫会拒绝已不再是当前版本的旧基线。

## 如何看运行结果

- GitHub Actions 的 run Summary 中，「投研雷达」区块列出 Notion 六表用量、回退和隔离、警告、周主线、每日要点、公司行情、汇率、温度计及下次计划。沿用日线时每家公司另列一行，包含名称、市场和原始收盘日期。采集失败时看同一 run 的 `collect` 步骤及附件中的 `diagnostic.json`。
- 核对 `release-result.json` 的最终状态及该 run 的 `prepare`、`publish`、`result` 步骤。`skipped` 表示时段已被同版本的成功发布覆盖。`failed` 即使发布了失败提示，原行情仍保留。诊断附件 `radar-production-<run-id>` 保留七天。
- 验收真实发布时，核对 `release.json` 的源 SHA、run ID 和数据哈希，确认正式域名绑定同一个 READY 部署。登录后读取 `/version.json`，确认 `state=current` 及输出 SHA 相符。另用匿名请求确认登录保护仍生效。
- PR 的离线和视觉 CI 与生产分开。真实 Notion 演练用 `radar-interface-acceptance.yml` 对允许的分支以 `live_notion=true` 触发，核对 run 的候选 SHA 和 workflow 身份。演练用 attempt 1，验收报告须显示 `publicationAuthorized=false`。

## 页面脉搏

| 颜色 | 含义 |
| --- | --- |
| 绿 | 当前页没有触发脉搏警告，显示行情更新时间、下次计划及今日变化。 |
| 黄 | 页面仍可用，脉搏报告 Notion 研究表沿用、问题行处理或行情缺项。 |
| 红 | 本次更新失败，或下次计划时刻已超过 `lateAfterMinutes` 且仍无新版本。页面继续标示所显示版本的数据时钟。 |

迟到阈值取自 `radar/data/config.toml` 的 `schedule.late_after_minutes`。它控制页面提醒。外部准入有自己的时间窗。公司日线沿用另看公司标签、行情汇总和页脚「数据状态与缺项」。

## 公司日线沿用

本次日线请求失败、应有的行情行缺失或收盘价为空时，可从上一次经 Vercel 验证并绑定当前发布头的版本沿用同一家公司的日线。沿用日期必须是该交易所当前应有的完成日，或最多早一个交易日。连续沿用仍以原始收盘日 `carriedSince` 计算。新公司没有基线记录、基线无法核验或日期更旧时，原发布门槛继续生效。

公司数上限为 `floor(10% × requiredCompanies)`，分母来自本次 Notion 构建。超限以 `carried_daily_exceeds_limit` 阻断。休市日出现收盘、时区或币种矛盾、未来日期、无效收盘证明和结构不合法的日线继续被拦截。指数、汇率和比值沿用各自原有发布门槛。

公司标签「沿用 MM/DD 收盘 · 本次未取得」保留原始日期，包含沿用公司的行情汇总显示「部分沿用」。在 GitHub run 的 Step Summary 查看公司、市场、原收盘日。DATA 中 `carried` 和 `meta.carriedDaily` 记录来源提交、运行、原因和数量，覆盖状态标为部分覆盖。无法证明当次报价晚于该完成日线时，展示沿用的收盘价。

「数据源提前报收盘 · 按日历沿用 MM/DD 收盘」表示采集时按交易所日历排除了过早标为收盘的当日记录，选用本次观测中已完成的日线。「收盘价来自行情快照」表示系统用通过同日收盘校验的 Yahoo 行情快照补足当期缺失的收盘字段。

会话边界、提前收市及台股独立收盘证明见 [交易日历](../radar/docs/MARKET-CALENDAR.md) 与 [TWSE 收盘证明](TWSE-CLOSE-PROOF.md)。

## 手动更新和排查

问题已修复且需要立即更新时，在 GitHub Actions 的 **Radar refresh and publish** 中点击 **Run workflow**，选生产源码分支，使用 `trigger=manual` 和 `schedule_slot=none`。命令行可发起同样的新运行。

```bash
gh workflow run radar-production.yml --ref fix/radar-truthfulness-2026-10-18 -f trigger=manual -f schedule_slot=none
```

生产执行只接收 attempt 1。失败修复后创建新的 dispatch，避免使用 **Re-run jobs**。合并产生的 push 会触发生产，先检查该 run 的实际结果。

Notion 出错时，先读 Step Summary 的表级或行级原因及 `diagnostic.json` 的阶段和错误码。401 检查连接 token，403 检查读权限，404 检查连接是否共享到对应数据源，429 或超时检查请求记录。列名或类型不符时查 [Notion 数据契约](NOTION-CONTRACT.md)。页面「数据说明」列出已发布版本使用的表级沿用、隔离和提醒。修复原表或连接后再做只读演练或新运行。

内置 cron 晚到时先核对对应外部时段是否已经发布。休市时按交易所日历检查最近的完成交易日。行情缺失时在诊断附件查看预期日期、末三行日线和收盘证明。出现失败提示时核对保留版本的 DATA 哈希和数据时钟，再按实际失败阶段处理。

### 更换 Notion token

由有权限的维护者在 Notion 的内部连接中生成替换 token。保留只读权限，确认连接覆盖「投研雷达｜数据后台」下六个数据源。到 GitHub 仓库 **Settings → Secrets and variables → Actions** 更新仓库 secret `NOTION_TOKEN`。通过真实只读演练确认读取后，再按需发起新生产运行。token 仅交给采集步骤，避免把值写入代码、命令参数、报告、日志或产物。 [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

### 更换外部定时器的 PAT

创建仅限本仓库的细粒度 PAT，给 Actions 读写和 Metadata 读取权限。使用本机加密存储保存新值，按四个现有任务 ID 替换 GitHub dispatch 的 Authorization 头，保留时段与时区。脱敏读回任务配置，并对账下一次真实触发、归槽和发布结果，再撤销旧 PAT。 [外部时钟触发](../radar/docs/EXTERNAL-SCHEDULE.md)

## 回到健康部署

手动回滚由获授权的项目维护者操作。先记录当前输出 SHA、最近一次健康发布的 run 和 READY 部署 ID，并检查队列。在事故处置需要暂停自动更新时，暂停本项目生产工作流及对应四个外部触发。随后在 Vercel 项目对合资格的健康生产部署执行 **Instant Rollback**，核对域名、登录保护和认证后的 `/version.json`。Vercel 会暂停自动绑定生产域名。恢复时用 **Undo Rollback** 或 promote 经验证的部署，并核对自动更新和触发器恢复。 [Vercel Instant Rollback](https://vercel.com/docs/instant-rollback)

需要恢复 V2 源码时，使用仓库保留的 [固定 V2 回滚包](../radar/tools/v2_rollback/README.md)。它以原 PR #4 合并及两个 parent 为输入，并固定健康 V2 输出 `a24e805552d8e1ce606d214a14bc08db93af50d6`。原 V2 的 TOML 研究输入留在其历史 Git 树中。工具只在匹配的干净 checkout 生成经离线测试的本地回滚提交。当前 V3 已包含后续提交，须先在独立 checkout 适配和演练并保留后续工作，再由维护者审查实际部署或源码回滚。
