# 单次真实快照复验 — 2026-10-19

运行：[39190870708](https://github.com/lwd619783-byte/research-radar/actions/runs/39190870708)。执行 SHA `dce7a0cd4a457f566e56809cb3644bb75476ecfa`，分支 `fix/radar-truthfulness-2026-10-18`，workflow_dispatch，attempt 1。本阶段仅追加审计证据；审计提交的 HEAD 将晚于实际执行 SHA。

## 授权、费用与去重

父任务转述用户明确批准本次单次复验，消息 Sentinel_7b0cfe66e4bc8191b58c6d463a5b6544（回复 Sentinel_627f48bf7dd08191a8197e2a1293699f），2026-10-19 北京时间 10:35。Astra / high / Standard 是接受的偏好，后台实际配置仍无独立受理回执；未修改设置。

费用证据为用户当天北京时间 09:12–09:15 提供、父任务和独立审计已逐像素核实的截图：GitHub Free，Actions 2/2000 分钟，存储显示 0/0.5 GB（非精确字节），账单 $0，Account scope Actions $0 预算且 Usage blocked 100%。之后只知 run 39184829414 的一个 92 秒 job；即保守按其完整 20 分钟上限计入，已知余量仍为 1978 分钟，足以覆盖本次最多 20 分钟任务。单个 <=512 KiB receipt、7 天保留及既有 $0 超额阻断延续。没有虚构新的账单读数或最终计费结果，没有重试被拒的账单 API、修改预算/付款/权限或上传截图。最小证据摘要见 `cost-and-authorization.json`。

开始及 dispatch 紧前均核实本地/远端为精确目标 SHA、工作区干净、10 个 frozen hashes 匹配。只读运行列表仅有 39047568864 与 39184829414，均 completed，无目标 SHA 重复执行。先以排他创建方式保存 `single-dispatch.json`，然后仅发出一次 POST，UTC 02:37:49 成功返回；只读确认新的唯一运行 39190870708。无第二次 dispatch 或 rerun。

独立审计是 121 项通过加 1 项缺历史 22d9601 Git 对象的环境错误；历史工作流另逐字节核验，10 项冻结哈希和 schema 0 错误/17 警告独立通过。它不能被写成“独立 122 全绿”。上一阶段云端本地 122 项通过也不代替本次 runner 的实际结果。

## 实际运行及可访问证据

运行 completed / success。标准 `ubuntu-24.04` job 117863154906，UTC 02:37:52–02:39:27，实际经过 95 秒（不是最终计费分钟读数）。cost/SHA guard、精确 checkout、checkout 后 HEAD guard、离线预检、真实探测及上传阶段均成功；步骤原始时间见 `run-terminal.json`。

本次 runner 实跑 **122 项测试通过、10 项 frozen hashes 匹配、schema 17 警告/0 错误**。真实探测 UTC 02:38:16–02:39:24，**119 次请求**。日志明确输出 **publicationBlocked=false**。精确执行版本的 stdout 定义是 `bool(gates['blockers'])`，因此可推断本次 aggregate blockers 为 **[]**；这里没有声称已从原 receipt 读取该数组。没有改动执行代码或门禁。

原始运行日志通过正常获准的 run-logs API 下载成功。保存四个必要 step 日志原始字节，未保存 checkout/凭据相关日志；各文件及完整临时日志 ZIP 的 SHA-256 见 `log-download.json`。`runner-summary.json` 是明确标注的 stdout 摘要，不是替代 receipt。

| 原始接口诊断 | 计划行数 | 连通 | 解析 | 数据质量通过 | 行级 publicationGate |
| --- | ---: | ---: | ---: | ---: | ---: |
| company-tencent-backup | 24 | 24 | 24 | 0 | 0 |
| company-yahoo-daily | 42 | 42 | 42 | 41 | 17 |
| company-yahoo-quote | 42 | 42 | 42 | 16 | 16 |
| fx | 6 | 6 | 6 | 6 | 6 |
| index-tencent | 5 | 5 | 5 | 5 | 0 |
| index-yahoo | 8 | 8 | 8 | 5 | 4 |
| ratio-tencent | 2 | 2 | 2 | 2 | 2 |
| ratio-yahoo | 2 | 2 | 2 | 0 | 0 |

这些是 **131 个原始接口诊断行**，批量报价共享请求，所以不是 131 次请求。行级 daily gate 17/42 描述原始最新日线的状态；集成快照可以从已完成历史 bar 选取共同日，两者不可混用。报价 quality 16/42 还包括 PE、市值、状态及日期等多个条件，**不等于集成市值覆盖 16 家，也不是集成 PE 覆盖数**。FX 6/6 只证明源级检查通过，不能替代选定快照的逐项同日核验。

## 原产物与核验缺口

artifact 元数据第一次读取遇 HTTP 503；仅对同一只读 metadata 请求重试一次后成功。这不是被禁止的 artifact 下载路径重试。run-logs 正常读取一次成功。**本轮 ZIP/receipt 下载尝试次数为 0**，此前明确 Forbidden 的路径继续停止，没有换地址/工具/凭据绕过。

[现有产物 12159459634](https://github.com/lwd619783-byte/research-radar/actions/runs/39190870708/artifacts/12159459634)：`radar-interface-acceptance-39190870708`，ZIP 元数据为 **12,910 bytes**，到期 **2026-10-26 02:39:24 UTC**。

- ZIP SHA-256（元数据与 upload 日志一致）：`6a640acb65dc94d0d1ebfb4b7ffbd10640f857f584a02d172282bf717d7254f7`
- receipt.json（probe stdout）：**164,090 bytes**；SHA-256 `2b4475eeac7c3e1a2888915a53019d0196c7b41007383b6a4d436bcae521a144`

本执行端没有取得本次原始 ZIP/receipt，未作独立字节哈希验证。元数据/日志哈希相符只证明上传出处的一致性。不能复用旧 run 39184829414 的 artifact 或哈希。

父任务可按用户安排取得现有原文件，核上述哈希、run ID、attempt 1 与执行 SHA，再逐项核验：

| 待核项目 | 当前能证明什么 | 仍缺什么 |
| --- | --- | --- |
| snapshot 选定日、42 家覆盖 | aggregate flag 为 false；执行逻辑和回归测试已通过 | 原 receipt 的 `publication.snapshot`、asOf/asOfByMarket、missing/stale 计数 |
| 韩日盘中日线裁剪 | 原接口质量/行级 gate 总数已知 | 韩日原行日期/phase、共同选择日期及完整覆盖证据；不能拿合成样例替代 |
| 异日/unknown 报价清空 | 报价质量通过 16/42；新 close 状态检查已执行 | 各公司 quote 日期/marketState/检查项，publication 的 marketCapAvailable/peAvailable 及与快照对应关系 |
| 估值、指数、FX 同日 | 源级 FX 6/6、Yahoo 指数质量 5/8 | 精确选定日、逐项源日期及集成可用性；未直接读到日期时不猜为 10/16 |
| 缺 PE、短历史、单点指数、Tencent unknown | Yahoo 日线 1 行质量未通过、报价 26 行未通过、指数 3 行未通过；Tencent 日线 24 行未通过，Tencent 指数 5 行 gate 未过，Yahoo ratio 2 行未过 | 每个具体 symbol、检查项及失败原因须读本次 receipt；不能直接沿用上一 run 的名单 |
| 财务 partial | 未变的输入已独立核为 40 verified、2 partial；本次 frozen/preflight 通过 | receipt 的实际 financialVerified/financialPartial 汇总复核；partial 不得解释成完整单季评分 |

现有 receipt 仅保留经脱敏的行检查/来源详情及集成摘要，不是完整原始市场响应或所有选后公司字段；逐项评估应区分 receipt 直接证据与依照精确执行代码作出的推断，不能将推断写成另一次真实重放。

## 结论与后续边界

这次已经完成唯一获准真实运行，且 aggregate flag 从旧运行的 true 变为本次 false。**这不等于所有数据质量通过或获得部署授权。** 原 ZIP/receipt 字节验证、选定日和估值覆盖核验、每一实际缺项及父任务独立审计尚未完成；本次证据不能据此宣称可部署。

本阶段只提交审计记录，生产代码、诊断规则、前端、财务证据、工作流和 10 个冻结文件均保持执行 SHA 字节不变。无部署、cron、PR、合并、权限/预算修改、再次 dispatch 或 rerun。费用证据仍是已核验截图及已知使用边界，未伪造本次最终账单。
