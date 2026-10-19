# 收盘后单次真实验收运行：已完成执行，原件审计待补

本阶段只发出一次 dispatch。运行 [39214475581](https://github.com/lwd619783-byte/research-radar/actions/runs/39214475581)，`workflow_dispatch`，attempt 1，已于 2026-10-19 完成，结论 success。执行 SHA 与父任务独立审计 SHA 均为 **b629883c76f578be4dac2740e5bfc5e8bfa4cb35**，分支 `fix/radar-truthfulness-2026-10-18`。

运行前远端 SHA 精确匹配；私有仓库身份 `lwd619783-byte/research-radar` 已经正常只读 API 确认。运行前仅有 4 次已完成运行，无运行中任务，也无本 SHA 的既有运行；运行后共 5 次，新增集合恰为本次 ID。没有重发、rerun 或额外 Actions。默认分支仍是 `fix/radar-data-integrity`，未改默认分支、发布工作流、权限、定时任务或付费设置。

## 实际执行证据

[Job 117935032406](https://github.com/lwd619783-byte/research-radar/actions/runs/39214475581/job/117935032406)，标准 `ubuntu-24.04`，07:12:18–07:14:24 UTC（北京时间 15:12:18–15:14:24），126 秒。元数据确认以下步骤 success：

- reviewed SHA / execution SHA / attempt 1 校验及精确 checkout 校验。
- 离线 regression / schema / frozen-hash preflight：07:12:23–07:13:10 UTC。**本次日志不可取得，不能声称已读取本次 runner 输出的测试数量。** 本 SHA 上轮本地 166 项通过属于之前本地证据。
- 真实接口探测步骤：**07:13:10–07:14:21 UTC，即北京时间 15:13:10–15:14:21，71 秒**。这是步骤执行区间，不是单条行情的来源观察时点或 receivedAt。
- 四文件 allowlist / 哈希 / 10 MB 校验及 artifact 上传均 success。说明 runner 完成这些校验；不能代替本地取得原件后的独立复核。

工作流与代码限制已经复核：20 分钟 job timeout、240 GET 上限、840 秒内部 deadline、四文件总计 10,000,000 bytes 上限、receipt 524,288 bytes 上限、7 天保留、contents:read。仍保留两个 `.yml.disabled` 发布工作流。当天原有零付费预算与额度证据按用户批准沿用，并核对新增运行；没有重试账单 API，也不声称有新的账单读数或实际最终费用。

## 归档身份与正常下载交付

- [Artifact 12168898178](https://github.com/lwd619783-byte/research-radar/actions/runs/39214475581/artifacts/12168898178)
- 名称：`radar-interface-acceptance-39214475581`
- GitHub 元数据大小：**442,011 bytes**（归档大小，不能当四文件未压缩总大小）。
- GitHub 元数据 digest：`sha256:9965b4718b29cc4da212e37c4afa259c5f8723bc984b5f64b76f50eb950e2f30`
- 创建：2026-10-19 07:14:22 UTC；过期：**2026-10-26 07:14:21 UTC / 北京时间 15:14:21**。
- 预期原件为 `DATA.json`、`index.html`、`receipt.json`、`manifest.json`。runner 校验步骤成功，但**本地尚未取得这四文件，未声称已计算各自 SHA256**。元数据 digest 也未用本地 ZIP 字节独立重算。

请由有权限的用户在上述 GitHub Actions 运行页面正常下载该 artifact 的**原始 ZIP 并原样上传**。不要用页面另存、复制 JSON、重新打包或旧 artifact 代替。拿到原件后再核 ZIP digest、文件 allowlist、四文件字节数与 SHA256、manifest 和 receipt/DATA/HTML 的同一快照绑定。

## 明确访问阻断及停止路径

正常只读 job-log 请求尝试一次。GitHub 重定向至 actions-results 存储服务后返回 **Forbidden**，日志取得字节数为 0。该路径已停止；没有重试日志、切换其他日志入口或改变访问设置。带签名的重定向 URL 未保存进审计文件。

本阶段 **artifact 下载尝试为 0**：此前已明确被拒，用户禁止重试，所以没有再次调用下载接口或换渠道绕过。artifact 和 run/job 的普通元数据接口正常成功。上述阻断不是已观察到的自动审批拒绝，不作此误称。

## 尚不能宣布完成的验收

| 项目 | 本次可证实状态 |
|---|---|
| 实际 GET 次数、HTTP 状态分布、源拒绝记录 | 待原始 receipt；已知硬上限 240，不能把计划 119 写成实测 |
| 42 标的价格 / 原币与美元市值 / PE 的逐项有效性、N/A 与缺失 | 待原始 DATA/receipt |
| A 股是否确有 10/19 已完成收盘新数据 | **待核**；步骤在 15:13 后执行不是数据日期证据 |
| 8 指数、6 FX、比值的来源观察时间、取得时间与阶段 | 待原始 DATA/receipt |
| 477 项覆盖矩阵、complete/partial/missing/N/A/access_blocked | 477 是配置预期项数；本次实际内容与计数待原件核对 |
| 四文件 SHA256 和未压缩合计字节数 | runner 检验成功，本地独立数值审计待原件 |
| 真实生成页面的桌面视觉验收 | **待验**，原因是本次 index.html 未取得；未用旧截图或离线重放替代，也未声称浏览器不可用 |
| 数据完整性、发布/部署验收 | **未通过独立验收；没有授权或进行部署** |

此前 8/8 指数及比值可计算只是离线混合时点重放证据，不能移植为本次全量实时接通结论。模型/推理偏好沿用已批准 gpt-6-astra/high，后端实际配置仍无独立回执。

本次执行已经终态，不需要也不允许为这些资料缺口再次 dispatch。后续只需取得本次原始归档并继续独立审计。
