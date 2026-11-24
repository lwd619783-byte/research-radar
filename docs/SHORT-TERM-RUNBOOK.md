# 短线复盘本机运维

交易日北京时间 20:30，由登录桌面的 Windows 用户运行一次 `radar/tools/collect_short_term.py`。结果写入 `radar/data/short_term_history.json`，保留最近 10 个有效交易日和未来 45 天的催化事件。发布由维护者评审和既有生产工作流接手。本机定时任务只采集、检查和写快照。

## 配置本机

在准备长期运行的源码 checkout 根目录执行以下命令。使用同一个 Windows 用户完成配置、登录和任务注册。建议选用 Python 3.12，Windows 上安装 `tzdata` 以供 `zoneinfo` 读取交易所时区。

```powershell
python --version
python -m pip install mootdx tzdata
python -c "from mootdx.quotes import Quotes; from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Shanghai'))"
python radar/tools/collect_short_term.py --help
```

| 项目 | 准备内容 |
| --- | --- |
| 行情与公告 | `mootdx` 使用本机通达信标准行情网关。运行账户还需能读取腾讯财经、东方财富、同花顺和巨潮公网端点。东财请求在同一进程内串行，前一次请求结束后至少等待 1.5 秒。 |
| V3 核心池 | 默认读取仓库 `production` 上的 `release.json` 和 `public/index.html`，按清单中的 DATA 哈希配对。可用 `--radar-data` 指向已经发布的 V3 DATA JSON 或单文件 HTML。文件须有 `meta.today`、行业、卡点和公司，日期不晚于目标日。上下文缺失时核心池和行业映射降级。 |
| Ego 命令与登录 | 在任务运行账户的 PATH 中提供 `ego-browser`，也可将 `SHORT_TERM_EGO_BROWSER` 指向本机可执行文件。先在 Ego 默认用户资料中登录需要的站点。使用与任务相同的用户，在普通终端运行 `Get-Command ego-browser` 检查命令位置。 |
| Ego 账号范围 | 默认配置为 `radar/data/kol_whitelist.toml`。在工作区外复制一份，用用户环境变量 `SHORT_TERM_KOL_WHITELIST_FILE` 指向它。按 `[platforms.dy]`、`[platforms.xhs]` 的 `kol` 数组填入抖音、小红书官方域名下的作者主页 HTTPS 地址；`tags` 默认含 `A股复盘`。`em/xq/ths` 的 `seeds` 为各社区的只读入口。白名单为空时，短视频或笔记仍可取标签热榜，覆盖记录反映实际来源。 |
| 金十日历 | 可设置 `SHORT_TERM_JIN10_CALENDAR_FILE`，指向本机授权导出的 `list_calendar` JSON（`status=200`、`data` 数组，行内有 `title/pub_time/star`）。或提供用户环境变量 `JIN10_MCP_TOKEN` 并在同一 Python 环境安装 `mcp`、`httpx`。文件优先。缺少配置时保留其他可用日历，并记金十缺项。 |
| 可选人工台账 | 用户环境中的 `NOTION_TOKEN` 使用只读连接；`SHORT_TERM_LEDGER_DATA_SOURCE_ID` 与 `SHORT_TERM_CATALYST_DATA_SOURCE_ID` 分别指向已共享给该连接的短线台账、催化日历 **data source ID**。两表可独立配置。未设置的表跳过，读取超时或无权访问时沿用本机记录。 |

本机采集使用的账号授权、Cookie 和 Token 留在该账户对应的浏览器或私密配置内。任务参数、任务 XML 和 Git 快照中只放程序路径、可公开的行情和匿名汇总。更改用户环境变量后，在同一用户的新登录会话中确认任务能读取新配置。

### 台账列

按 `radar/data/short_term_schema.json` 中的列名和类型建表。《短线复盘台账》以 `交易日期` 为标题，必填 `定调结论`、`散户情绪分`（0–100）、`短线周期阶段`，可填 `明日锚点_1` 至 `明日锚点_3` 与 `停用`。五个周期名称与契约保持一致。《催化事件日历》按 `事件ID` 覆盖，事件起始日须在快照日及后续 45 天内。手填事件使用已有 ID 时，覆盖该 ID 的公开事件。

人工校正昨日锚点时，可在**今日**台账上增设三组可选列，`对账状态_1` 至 `对账状态_3` 的类型为 select，可选 `pass / partial / fail`；`对账实盘_1` 至 `对账实盘_3` 的类型为 rich_text，每项最多 180 字。按 ANCHOR 原编号成对填写。昨日题目变更后，旧题目的自动结论失效。没有昨日题目、可追溯的原始观察项或实际观测时，该槽位保留缺项。

## 先用离线样本检查

样本输入走真实采集整形、脱敏、10 日合并、建页与扫描路径。临时输出与运行中的真实历史分开，`--dry-run` 将清洗后的 JSON 写入标准输出。使用下列命令时，当前目录为仓库根目录。

```powershell
$reviewDir = Join-Path ([IO.Path]::GetTempPath()) ('radar-short-review-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $reviewDir | Out-Null
python -B -m unittest discover -s radar/tests
python -B radar/tools/collect_short_term.py --offline-fixture --dry-run --skip-ego | Out-Null
python -B radar/tools/collect_short_term.py --offline-fixture --output "$reviewDir/history.json"
python -B radar/tools/build_short_term_preview.py --history "$reviewDir/history.json" --out "$reviewDir/pages"
python -B radar/scripts/output_scan.py "$reviewDir/pages/short/index.html"
python -B radar/scripts/output_scan.py "$reviewDir/pages/legacy/index.html"
```

`--offline-fixture` 可选填原始采集 JSON 路径，默认使用 `radar/tests/fixtures/short_term_v4/raw_session.json`。`sample_short_term_history.json` 是已归一化的 UI 契约样本，作为 `build_short_term_preview.py --history` 输入。三档 Playwright 验收可运行 `python -B radar/tools/short_term_visual_acceptance.py --out "$reviewDir/screenshots"`，使用本机 Playwright 和 Chromium 环境。

## 20:30 计划任务

先确认电脑在该时段能运行、用户已登录、Ego 可连接。脚本把当前 checkout、当前解释器的绝对路径和当前用户 SID 写入任务定义。脚本在 XML 中指定 `20:30:00+08:00`，使用交互登录令牌与普通用户权限。任务每天触发，采集器按 XSHG 日历跳过休市日。

```powershell
$installer = '.\radar\tools\register_short_term_task.ps1'
& $installer -WhatIf
[xml]$taskDefinition = & $installer -EmitXml
$taskDefinition.Task.Triggers.CalendarTrigger.StartBoundary
```

确认路径与账户后，由维护者运行 `& $installer` 注册 `ResearchRadar-ShortTerm-2030`。如 Python 不在用户 PATH 首位，可加 `-PythonPath 'D:\path\to\python.exe'`。如需绑定 V3 文件，可加 `-RadarData 'D:\path\to\DATA.json'`。只需要硬数据的任务可加 `-SkipEgo`。安装器以 `-Replace` 显式更新同名定义。用下面两条命令查看任务状态。

```powershell
Get-ScheduledTask -TaskName 'ResearchRadar-ShortTerm-2030'
Get-ScheduledTaskInfo -TaskName 'ResearchRadar-ShortTerm-2030'
```

运行摘要位于 `%LOCALAPPDATA%\ResearchRadar\short-term\YYYY-MM.log`，仅记录北京时间、目标日期、状态和退出码。`finished_or_closed` 对应正常完成或休市跳过；对照快照中的 `days[0].date`、`generatedAt` 和 `meta.coverageWarnings` 确认真正取得的数据。`before_target` 表示错过触发后恢复时，当日尚未到 20:30。任务启动策略为 `StartWhenAvailable`，允许错过时间后在可用时运行。同一天 20:30 后恢复会尝试当日定稿；跨日恢复按当日日期判断。任务运行满 3 小时会停止；未完成的临时文件不会替换经过验证的旧历史。

`IgnoreNew` 让已有任务运行时跳过第二次计划触发。CLI 写快照前还会取得当前目标文件对应的 OS 文件锁，跨进程重入会报告 `collector_already_running`。锁文件可常驻，锁随持有进程结束释放。写入通过同目录临时文件、回读校验和原子替换完成。

## 当晚运行与覆盖判读

```powershell
python -B radar/tools/collect_short_term.py
python -B radar/tools/collect_short_term.py --skip-ego --dry-run
```

第一条会写真实快照；第二条检查当晚硬数据，输出清洗后的候选结果。同日可以重跑，按交易日期替换当日一项。历史补跑不会用今天的 Ego 评论填入旧日期。历史补跑显式指定 `--date YYYY-MM-DD` 和单独的 `--output` 路径，并在需要时传该日之前发布的 `--radar-data`。当前行情端点可能无法证明历史收盘，目标日早于已有历史头也会被拒绝。只有真实日期证据才用于回放。

- **排名与市场宽度。** 全市场榜要求三所覆盖完整，成交额达到 10 亿元、可证明上市已满 30 个自然日，并剔除 ST、退市和新股标识。相同证券的冲突记录移出候选。缺上市日期证据或覆盖不全时，保留有当日行情的 A 股核心池。行业、概念和个股两侧各最多五项。
- **周期与矩阵。** 晋级率逐只比对昨日连板股的今日高度。周期依晋级率、最高板数与炸板率映射五阶段。矩阵用 V3 已有 20 分制行业评分，16 分为高分线，2% 为显著涨跌幅；无符合项的象限留空。
- **时间轴与公告。** 09:25、10:30、13:30 的模板只显示实际取得的同日时点。分时失败时保留 15:00 收盘、17:30 龙虎榜与 20:15 舆情栏目，并标明缺项。龙虎榜按单日原因归集席位。大额解禁筛选未来 5 个自然日内参考解禁市值至少 1 亿元的记录，同时检查巨潮减持与异常波动公告。
- **催化与对账。** 3–5 星事件限未来 45 天。产业事件距开始日不超过 3 天且映射板块近五个交易日累计上涨至少 5% 时标注“临近防兑现”。首个交易日、缺上个交易日或不可量化锚点保留缺项。
- **Ego。** 股吧、雪球、同花顺从社区入口取当日收盘后讨论，抖音、小红书按固定作者和热榜两条路径取评论。三个社区的评论窗口是当日 15:00–20:15，抖音和小红书是当日 18:00–20:15，时间均取北京时间。单平台未登录、出现验证码或超时，可保留其余平台样本。用户自行在 Ego 中处理验证并重新运行；接管期间保留用户控制。需要先取得硬数据时用 `--skip-ego`，缺少样本时散户分值显示“—”。先按平台计算“偏多比例 + 一半中性比例”，再按有样本的平台等权得到 0–100 分。圈层温差取两组平台平均偏多比例之差。声量变化仅在上一交易日采样方法、来源范围相同且两次均未截断时显示。

| 退出码 | 现场判断与处理 |
| --- | --- |
| `0` | 已得到可用当日结果，或目标日休市。查看日期、源覆盖、台账和舆情样本数。 |
| `1` | 采集前提或写入检查失败。检查运行时点、路径、行情来源和锁状态。若报 `existing_history_corrupt_or_newer`，先保留现有文件及其副本，找到最后一份能通过扫描的历史，再在独立路径重跑和比对。 |
| `2` | 当日硬数据缺失或结果沿用。查看保留的交易日、`meta.isStale` 和上次真实生成时间，待源恢复后重跑。首次运行无任何可用收盘记录会以 `1` 结束。 |

## 快照如何进入生产

1. 维护者检查真实快照中的 `generatedAt`、最近交易日、来源、部分覆盖、匿名化样本和日历。禁止把 `reviewOnly` 样本用作生产历史。在新的评审分支中只纳入通过检查的真实 `radar/data/short_term_history.json`，向 `fix/radar-truthfulness-2026-10-18` 提交 PR。定时任务不操作 Git 或远端。
2. 评审并由维护者合并后，源码分支 `radar/**` 的变更符合 `radar-production.yml` 的 push 路径。该工作流另有原有的定时触发和人工调度。当次源码 SHA、分支、首次 attempt、运行准入及既有 V3 门禁共同决定发布结果。
3. 在 **Radar refresh and publish** 检查 `preflight → collect → prepare → publish → result`。`prepare` 对同一 run 的绑定与数据门禁执行检查，并在候选发布目录运行 `node verify-release.cjs --check-only`；`publish` 才会更新静态产物分支 `production`。维护者最后比对 `release-result.json`、Vercel 状态和正式站的 `/version.json`。若需要人工恢复，沿用 V3 运维手册的新 dispatch 流程。

现有触发条件和失败恢复依据仓库的[生产工作流](../.github/workflows/radar-production.yml)和[V3 生产运维说明](PRODUCTION.md)。
