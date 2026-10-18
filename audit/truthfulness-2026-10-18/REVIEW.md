# 2026-10-18 数据真实性修复：待独立审计，未发布

后续同轮审计修复及持久化回放证据见 [FX-FINALITY-AUDIT-FIX.md](FX-FINALITY-AUDIT-FIX.md)。下文保留首阶段历史事实；“仅在/tmp”的限制已由该补丁解决。

## 身份、执行配置与边界

用户批准 `gpt-6-astra / high / Standard`。本执行端没有提供实际模型、推理级别、服务层的受理回执，因此实际配置仍**无法核实**，没有把授权偏好当成已生效配置。私有仓库身份经 GitHub API 确认：`lwd619783-byte/research-radar`，`private=true`，默认分支 `fix/radar-data-integrity`。2026-10-18 02:06:14 UTC fetch 后确认起点为 `414eb80626d3200dfebe4a010507c5fe74d7ca31`，从此建立 `fix/radar-truthfulness-2026-10-18`，保留原分支。初始工作区干净。未找到 AGENTS.md；已读 HANDOFF.md 与 `audit/INTERFACE-ACCEPTANCE-2026-10-17.md`。

首阶段正常提交并推送 `814eea7b0a6a1de54859c072855f397f4075b26f`。后续提交及远端回执见 `push-receipts.txt` 和交审答复；本文件不循环嵌入自身提交 SHA。

未改默认分支、未建 main、未强推、未合并、未部署、未触发或启用 Actions、未改权限或安全设置、未升级依赖、未建立长期凭据。投研 OS、运维看板、行业论点与公司观点保持原样。`style.css`、`index.html`、行业/卡点/配置 TOML 和 workflows 保持原字节；companies.toml 仅修改 fin 字段。新 manifest 单独保存为 `audit/truthfulness-frozen.json`，历史审计 manifest 未覆盖。

## 网络与实际样本

访问情况不是依据环境设置推断。初始 GitHub API 200；普通 urllib Yahoo 429；Frankfurter 403 后停止该路径。仓库原有正常 Yahoo 客户端取得 200，未更换 Yahoo 主机、代理或凭据。详细初查见 CHECKPOINT.md。

本轮行情实测时间为 **02:17:26.854657–02:20:41.553297 UTC**，119 次请求、131 个诊断项，见 `local-market-receipt.json`。它在财务候选写入前执行，因此其中财务门禁为 0/42；不是最终集成数据结果。所有连接、解析、质量、发布门禁分栏保存，200 不等于有效。

| 实测项 | 解析 | 质量通过 | 结论 |
|---|---:|---:|---|
| Yahoo 公司日线 | 42/42 | 41/42 | CXMT 短历史；真实 54 条，不能宣称完整两年/52周 |
| Yahoo 公司报价 | 42/42 | 40/42 | LITE、000660.KS PE 缺失，非有效 PE |
| Yahoo 指数 | 8/8 | 5/8 | 399006.SZ、000922.SS、HSTECH.HK 各仅1条；明确 `yahoo_index_insufficient_daily_bars` |
| Tencent 公司备源 | 24/24 | 0/24 | 币种、时区与收盘阶段未知，不能借用 Yahoo 元数据 |
| Tencent 指数 | 5/5 | 5/5 | 发布门禁仍0/5，未知收盘元数据不能代替可信收盘 |
| Yahoo FX | 6/6 | 6/6 | 23或24条历史值，真实 10/16 同日值可用 |
| Yahoo 比值月线 | 2/2 | 0/2 | 月度单点不构成充分历史 |
| Tencent 比值月线 | 2/2 | 2/2 | 实际完整历史通过检查 |

财务候选来自父任务公开来源包（40项，71个去重URL），原包及条件未删减，见 `financial-candidates-received.json`、`financial-supplement-received.json`。初次69份文档完成读取解析；CXMT辅助招股书超过本地12/32MiB大小限制，正常96MiB有界读取成功（53,555,300字节，非权限拒绝）；CNINFO查询URL GET 500，正常公开只读 POST 200，获取中际旭创公告时间元数据。没有把接入回执直接当成内容核验。下载回执、PDF哈希、补充回执和逐项数值复核分别保存。

## 财务采用结果与口径

40/42 财务来源和适用条件已复核；37项具有营收同比、利润同比和毛利率全部三项；36项满足普通季度增长信号条件。**KBL（1888.HK）和 DZSK（301200.SZ）仍缺可核实来源**，不采用原有数字；前者标明半年累计，后者标明初步结果。不得将这两项填成0或称全量验收通过。

- 保留单季/累计、财年和期间、GAAP/non-GAAP、财务币种、收入/利润/毛利范围、全部来源、披露日、原核验日、采用条件和推导说明。
- 累计差分使用两年相同口径的累计报告相减；金盘科技为前三季度减半年，其余相应项目为半年减一季。复核记录保存原金额、来源和计算结果。
- COHR、CXMT扭亏不生成普通利润同比；SU只有收入，利润同比和毛利率保留空值。LITE GAAP利润包含一次性债务项目，不作为普通增长信号。
- ASMPT持续经营收入/毛利与含终止经营归母净利分开表述；MOD保留分拆前集团口径；DFDQ、ZGXD的营业总收入同比与营业收入毛利分母区别保留。
- COHR/ASML采用发行人披露毛利率，展示金额舍入计算差异在复核记录中说明。TSM财务币种TWD与美股报价USD分离。
- 候选原 `verified_at=2026-10-17` 保留，没有自动改为今天；本轮读取/复核时间另记 `checkedAt`。中际旭创披露日期采用公开元数据8/22，正文8/24差异留痕。其他披露日期保留来源包信息，不声称所有日期都由本轮接口重新验证。

逐项证据见 `financial-content-review.json`；中国公司差分复算见 `cn-quarter-recalculation.json`，其中 HDGF 自动抽取未成功的原记录保留，人工金额定位结果另记在内容复核文件，不能把抽取失败误报为缺源或成功自动抽取。

## 日期、短历史与最小标签

FX 从真实历史序列选择报价日同日汇率，不移动日期标签、不用未来/邻近汇率填补；EUR倒数方向经过验证。全局汇率摘要与逐公司市值均指向同一实际日期。财务币种不参与报价币种替代。

用本轮快照集成最新财务后：42家公司行情日期均为 **2026-10-16**；日线缺失0、过期0；42/42市值可计算，42/42使用同日报价/FX（USD按1）。`integrated-data-review.json` 是同一实测快照的回放，不是第二次联网，快照 SHA256 为 `7104fc3546ed56aa9878e98c8c0632da0b776948fd4f12b6ac9af488555006d2`。

CXMT实际54条（2026-07-27至10-16，跨度81天），显示短历史、实际区间及区间不足，60日/年初至今/52周指标不足时为空，不制造120日、两年或52周完整历史。使用“实际历史”而非未独立验证的上市日断言。

前端只修改必要状态/真实性文字、缺失占位及信号适用判断；标明财务期间、币种、会计口径、扭亏/一次性/仅收入、PE缺失和业绩快讯待核实。既有布局、样式、模块与投资观点不变。

## 本轮测试、桌面证据及发布阻断

- 新鲜基线75测试通过：`baseline-tests.txt`；首阶段88测试通过：`core-tests.txt`；财务集成90测试通过：`financial-final-tests.txt`。这些均在本轮运行，不引用旧Actions运行39047568864作为本轮通过依据。
- 最终本地 preflight（完整90测试、9文件hash与schema）、JS语法和diff检查见 `final-preflight.txt`。本地调用不触发Actions。
- `verify_release_gate.py` 用真实快照回放 `build.main --force`：退出3、`changed=false`、不生成页面，原因 `financial_evidence_incomplete`。空缓存 `--offline --force`：退出2、同样不生成页面。见 `release-gate-receipt.json`。
- 真实系统Chromium经Playwright以1440×1000浏览本地HTTP页面，11张PNG原始截图，哈希/尺寸与DOM断言见 `desktop-receipt.json`。before/after使用相同本轮真实行情快照，before仅供代码行为比较，不是历史线上截图。after包含本地验收未发布标签和强制不可发布标志。
- 原 file:// 导航收到 `ERR_BLOCKED_BY_ADMINISTRATOR`，已停止该协议路径且未改浏览器政策；独立正常localhost HTTP预览成功。无脚本错误、无横向溢出，5个主体section、4个顶部卡片、42家公司、CSS长度一致；人工查看CXMT/LITE/SU/ASMPT截图，财务悬浮说明也在视口内。

重点截图：[CXMT短历史](screenshots/after-cxmt.png)、[LITE一次性与PE缺失](screenshots/after-lite.png)、[SU仅收入](screenshots/after-su.png)、[ASMPT口径](screenshots/after-asmpt.png)、[完整桌面](screenshots/after-desktop.png)；目录含对应before截图。

## 剩余风险与交审

仍缺KBL与DZSK公开财务候选；未补造。三项Yahoo指数语义失败、Tencent元数据未知、两项PE缺失、Yahoo月线单点均保留诊断，不伪装有效。历史FX虽日期匹配，仍依赖免费接口的历史数据准确性。已采用40项需父任务独立复核财务原报告、计算口径、来源日期和差异说明，当前不是发布批准。

公共原文与完整临时行情快照仅位于 `/tmp`，未提交到仓库；审计目录保存公开来源URL、金额、HTTP/解析回执、内容哈希及必要截图。重跑公开源脚本会产生新的访问记录；回放/截图脚本依赖本轮 `/tmp` 快照，当前工作区可复现，其他机器须先重新采集并保留新时间/哈希，不可冒充本轮证据。提交前范围与敏感内容检查见 `scope-review.json`。
