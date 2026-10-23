# V2 回滚操作包

本目录只用于真正需要回滚时准备一个本地提交，不参与 V3 构建或发布。`prepare.py` 不 fetch、不 push、不部署、不停用工作流，不读取任何 token。脚本、固定补丁和说明都在仓库内，干净 checkout 不依赖仓库外的 `work/` 文件。

## 为什么不能只执行 revert

V2 的 `release_operations.fetch_baseline()` 遇到最新成功的 V3 manifest 会报 `invalid_release_manifest`；它只接受 schemaVersion 1/2，而且只查询最近 12 个 production 提交。单纯 `git revert -m 1 <merge>` 恢复源码后，生产运行会在读取基线阶段停止。

本包采用 `git revert --no-commit`，然后把以下兼容修复和新增测试放进**同一个回滚提交**：

- 遇到 schemaVersion=3 只跳过，不把它伪装成 V2；仍严格校验可支持的历史发布。
- 最近 12 条没有健康 V2 时，追加明确记录的生产提交作为候选；精确 Vercel 成功回执、Git production 祖先关系、文件、DATA、history 检查全部保留。
- V2 发布时仅删除旧 `research-snapshot.json`，保留其它文件。根目录残留 snapshot 原本不会使 V2 verifier 失败，删除它是为了保持正确的 V2 发布文件集合。
- 新增六项回归测试，覆盖 V3→V2、损坏 V2、无健康基线、20 次 V3 后的固定 V2、错误祖先和发布树清理。

这份补丁不会应用到当前 V3 的 `release_operations.py`。

## 固定身份与演练证据

2026-10-23 已核对：

| 对象 | 身份 |
|---|---|
| V2 源码（PR4 合并前第一 parent） | `988c6d289d9347ffb253abca0582fa19771f932f` |
| 健康 V2 production 提交 | `a24e805552d8e1ce606d214a14bc08db93af50d6` |
| 健康 V2 Vercel 部署 | `dpl_DKuTY3wLLjVzcePaPU6AiQwNM8U9` |
| 其成功生产运行 | [39794082213](https://github.com/lwd619783-byte/research-radar/actions/runs/39794082213) |
| 固定补丁 SHA256 | `4b31a751f5363215a958e6410986649fe9d31f24ecfb1ab0edcc50e1e358f608` |

V2 → 本地合并 PR4 → 纯 revert 的 tree 完全相同（`e5db4450097aa2b2e816d3a977a0a928c6e7cc62`）。原 V2、纯 revert 和兼容回滚使用上述成功运行的原 DATA/receipt、原时钟 `2026-10-22T22:17:48.295596+08:00` 进行离线构建，7 个发布文件逐字节相同，schemaVersion=2，`verify-release.cjs --check-only` 通过。六项新增 V2 回归测试在旧代码全部失败，在补丁后通过；连同相关原测试共 26 项通过。

这些是历史时点离线证据，不是新的行情、生产许可或真实部署。Vercel、GitHub 状态和实际上线 SHA 必须在操作时重新读取。

## 上线与回滚手册（可复制到 PR4 描述）

上线仅合并 PR4。先确认 offline、visual、live_notion 都通过，完成旧失败调查、误报阈值决定及本手册核对；在周一 2026-10-26 14:00–16:30 北京时间窗口，对最终 PR4 SHA 跑 W44 真实演练。演练 ready 后 30 分钟内恢复 `v3-ready-to-ship` 并执行：

```text
gh pr merge 4 --merge --match-head-commit <FINAL_PR4_SHA>
```

不使用 squash/rebase，不使用 `--admin`，合并信息不能含 `[skip ci]`，不单独合并 PR3。记录实际 merge SHA 及两个 parent。该合并触发的一次 push 运行就是上线运行，不再额外触发首次生产发布。若 PR3 未被 GitHub 自动标记 merged，说明其提交已随 PR4 合入后关闭，不另行合并。

失败先看 `publication.blockers`；内容问题修改 Notion 原行，代码问题开修复 PR。修好后必须新建运行：

```text
gh workflow run radar-production.yml --ref fix/radar-truthfulness-2026-10-18
```

不点击 Re-run：生产 admission 只接受 attempt=1。到 16:30 仍未修好，执行下面的方法①。

### 回滚①：准备一个带兼容修复的 V2 回滚提交

使用有完整 Git 历史及 `origin/production` 的干净独立 checkout，确认 origin 是 `lwd619783-byte/research-radar`。下面的 `<MERGE_SHA>` 和 `<FINAL_PR4_SHA>` 必须是实际记录值，不是本地演练 SHA。

```text
python radar/tools/v2_rollback/prepare.py --repo . --merge <MERGE_SHA> --expected-v2-head 988c6d289d9347ffb253abca0582fa19771f932f --expected-pr4-head <FINAL_PR4_SHA> --rollback-baseline-sha a24e805552d8e1ce606d214a14bc08db93af50d6
```

脚本先检查完整 SHA、仓库身份、干净状态、HEAD、两个 merge parent、健康 V2 manifest 及 production 祖先关系，并校验补丁哈希。回滚会删除本包，所以脚本提前把**经过哈希检查的补丁**暂存到仓库外，随后执行 revert、apply、26 项相关测试和本地 commit。相对原 V2，只允许 `release_operations.py` 和新增测试两份文件不同。任何异常都不会 push；发生冲突或测试失败时保留未提交状态供检查，不自动 reset 或覆盖。

查看脚本输出的回滚提交、工作树及差异，按任务授权用普通非 force 精确 refspec 推送到源码生产分支：

```text
git push origin HEAD:refs/heads/fix/radar-truthfulness-2026-10-18
```

这次 push 触发 V2 重新发布，跟踪该次运行和对应 Vercel 回执。脚本生成的提交不带 `[skip ci]`。重新上线 V3 时，revert **完整的兼容回滚提交**，再按相应检查和真实演练门禁操作。

若源码 HEAD 已有后续提交，脚本会拒绝：在新 checkout 中保留后续工作，适配并重新演练，不强行覆盖。固定候选使两周后超过 12 次 production 输出仍可找到健康 V2，但不代表可以跳过后续源码冲突。

源码回滚也恢复 V2 的旧 cron：UTC `15 23 * * 1-5`、`15 4 * * 1-5`、`35 8 * * 1-5`，对应北京时间次日 07:15、当日 12:15、16:35；不再是 V3 的四个时段。恢复 V3 时一并恢复其计划。

### 回滚②：回到已知健康 Vercel 部署

选择健康 V2 `dpl_DKuTY3wLLjVzcePaPU6AiQwNM8U9`；不要把失败提示版 `dpl_9GkcizfnHgJyR3WMfgP5q695Ec9C` 当作健康候选。执行 Vercel 回滚时同时：

```text
gh workflow disable radar-production.yml
```

否则下一次计划运行会重新发布 V3。恢复时再 `gh workflow enable radar-production.yml`，并重新核对当前代码和发布门禁。本包不会自动执行 Vercel 操作或 disable/enable。

### 上线检查清单

- 匿名访问首页、版本和数据入口仍被登录保护挡住。
- manifest `schemaVersion=3`，附带 research snapshot，绑定实际 merge/push/deployment SHA。
- W44 为 AI 研判，42 家行情齐全，pulse 正常；缺失、待核与过期状态保持真实。
- 页脚提醒按真实数据核对；无法核实的内容继续保留标记，不为达到“只剩一条”而隐藏警告。
- 同一天 18:15 定时运行也成功后，才记为正式上线。

与原任务书的差异：**纯 revert 不足以通过 V2 基线读取，所以方法①附加最小兼容补丁和新增测试**；不降低发布门禁、登录保护或数据真实性要求。

## 操作包自身测试

```text
python -B -m unittest discover -s radar/tests -p test_v2_rollback_package.py -v
```

它检查仓库/SHA/parent 绑定、拒绝脏目录、补丁哈希、包被 revert 删除后的继续执行、失败不 commit、不 push/fetch 等边界。真正执行回滚准备时还会运行补丁内六项测试及原 V2 相关测试。
