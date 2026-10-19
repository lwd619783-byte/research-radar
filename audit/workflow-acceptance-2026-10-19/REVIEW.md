# 手动接口验收分支修复：费用未核实，未触发

## 本轮身份与配置

用户于2026-10-19批准本阶段，偏好 Astra / high / Standard，且接受后台实际模型和强度无法独立核验的限制。本执行端仅能确认所选环境启动成功、仓库/工作区/命令结果；没有后台模型、推理强度或速度受理回执。未变更任何模型或速度设置，不能将授权偏好写成实际生效证明。

正常fetch及远端查询确认工作分支 `fix/radar-truthfulness-2026-10-18` 起点为已验收的 `7a1015f789162ed4d2ff51f60323d3aeb2013b84`，工作区干净。仓库API确认 `lwd619783-byte/research-radar` 为私有、个人所有，默认分支仍是 `fix/radar-data-integrity`，其HEAD仍为 `414eb80626d3200dfebe4a010507c5fe74d7ca31`。未发现适用AGENTS.md，已重新读取HANDOFF、工作流说明及历史接口验收报告；旧main/部署指引不覆盖用户当前限制。

## 已修复内容

仅修改手动 `radar-interface-acceptance.yml`、必要测试、范围哈希和说明文件：

- 手动任务分支限制从旧 `fix/radar-data-integrity` 改为当前已批准的工作分支。
- job条件同时要求workflow_dispatch、正确分支、attempt=1、`zero_cost_verified=true`、输入reviewed SHA匹配GITHUB_SHA；缺条件时不分配该job的runner。
- runner内在checkout之前验证事件、分支、首次运行、费用布尔值、40位小写完整SHA及大小写敏感精确匹配。GitHub表达式中的相等比较不能替代这层精确校验。
- checkout仍引用 `${{ github.sha }}`，仍不持久化凭据；新增checkout后实际 `git rev-parse HEAD` 同时匹配reviewed SHA与GITHUB_SHA，失败不进入preflight或数据请求。
- 保留单个标准 `ubuntu-24.04` job、20分钟总超时、16分钟probe step、240次只读GET总上限、原限流/拒绝处理、原脱敏receipt、7天产物保留、contents:read、固定官方action SHA及不取消既有任务的concurrency。
- 冻结manifest原9项值完全保留，新增手动工作流本身的哈希，变为10项。所有生产脚本、数据真实性门禁、KBL/DZSK部分披露证据与含义、前端文件、财务TOML及两份禁用发布工作流均保持字节相同。

## 费用核验及明确阻断

本轮以现有正常权限读取GitHub：仓库API和账户身份API成功，账户API没有返回计划名称（null，不解释为Free）。读取 `/users/{owner}/settings/billing/actions` 返回 **HTTP 403 / Resource not accessible by integration**，见 `billing-check.json`。收到明确权限拒绝后停止该账单路径；没有换凭据、扩大scope、读取浏览器凭据、修改预算或调用其他账单路径绕过拒绝。当前没有暴露可用的已授权账单浏览器会话。

因此，当前计划、剩余Actions分钟、共享产物存储余量、有效超额费用阻断均**未核实**。本轮 `zeroCostVerified=false`，从未提交true、从未dispatch。10/17的Free计划、额度和$0预算记录只作历史资料，不能沿用为10/19的费用证明；本仓库只有一次旧运行也不能证明整个账户的剩余额度。

官方说明区分标准runner的计划内额度、共享artifact/Packages存储和超额收费，不能由“标准ubuntu”推导私有仓库无条件免费：[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。个人仓库不能套用组织预算API来替代当前个人账单核验：[Billing usage](https://docs.github.com/en/rest/billing/usage)、[Budgets](https://docs.github.com/en/rest/billing/budgets)。这些公开规则不是当前账户的费用回执。

**继续所需的最小缺口**：通过已有正常授权渠道取得当前账户的计划、剩余标准Linux分钟/共享产物存储，以及本次适用的零超额费用硬限制（例如当前Actions $0预算且启用usage blocking）的可核验证据。额度须足以容纳一次最长20分钟任务及计费取整、一个不超过512KiB的receipt及上传封装、7天保留，不能依赖过期额度或仅有告警而无硬限制。本阶段不请求新凭据或权限扩张。

## 实际测试与运行状态

- `tests.txt`：本轮完整 **107项测试通过**（原104项＋3项工作流测试）。实际执行workflow中的Bash guard，覆盖正确值通过以及旧分支、错误事件、attempt=2、未核/false费用、缩写/空/不同/大写SHA、shell替换字面值均拒绝；checkout HEAD不符也拒绝。
- `preflight.txt`：本轮本地preflight再次通过107项测试、10项哈希、schema 0错误；diff检查通过。没有把旧75/90/104测试或旧Actions运行当作本轮重跑。
- `pre-dispatch-state.json`：本轮开始时远端只有历史运行 [39047568864](https://github.com/lwd619783-byte/research-radar/actions/runs/39047568864)，2026-10-17，旧分支、旧SHA、attempt 1。它不是本轮运行URL。
- 本轮运行ID/URL：**无**；dispatch次数0；本轮真实行情接口请求0；没有新的来源连通、市场日期、返回内容、数据质量或集成构建门禁结果可供宣称。
- 费用条件解决后，仅可对届时重新核实的精确reviewed SHA触发一次。不能因分支继续推进而沿用旧SHA；响应不明确时先只读核对运行列表，不能直接重发。已触发后须跟踪至终态并保存日志/receipt；失败也不得自行第二次运行。

## 范围与交付

范围/敏感内容检查见 `scope-review.json`。代码提交与正常push回执见 `push-receipts.txt`；最终HEAD以交审答复及最终远端核验为准。未创建PR、合并、部署Vercel、改默认分支、启用定时任务、启动其他云任务或启用两份发布workflow。代码成功推送不等于上线或真实接口验收通过。

本轮按用户授权停在触发前：修复和本地验证完成，真实Actions验收仅受上述费用核验缺口阻断，交父任务审计及补证。
