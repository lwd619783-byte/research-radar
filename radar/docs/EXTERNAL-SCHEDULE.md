# 外部时钟触发

外部服务只向 GitHub `radar-production.yml` 发送 `workflow_dispatch`，不接触 Notion、网页内容或 Vercel。PAT 仅授权本仓库 Actions 读写与 Metadata 读取。cron-job.org API key 只用于配置该账号的任务，不放进 GitHub。

`python -B radar/tools/external_schedule_jobs.py` 输出四份不含凭据、`enabled=false` 的配置：北京时间工作日 08:45、12:15、18:15，以及周一 06:50。配置格式依据 [cron-job.org REST API](https://docs.cron-job.org/rest-api.html)；触发接口依据 [GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。模板不会发请求。

安装时从本机加密存储读取 PAT，**仅在进程内**补入 GitHub 请求的 Authorization 头，再通过外部服务 API 保存。密钥不得写进模板、仓库、命令行、PR 或日志；读回任务详情时只输出标题、ID、启用状态、时区、时段和脱敏校验结论。未知创建结果先按唯一标题查找，不重复创建。

启用前必须完成 PR5 的准入与去重测试、真实演练、合并及生产确认。提前创建的任务保持禁用；不得用生产 workflow 试发来验证 PAT。默认任务在 2026-12-21 北京时间零点到期，续期前核对 PAT 与运营授权。

生产 workflow 先取得 Vercel 已验证的基线，再检查触发时段。外部时段只接受已知四种 slot，由 GitHub 的运行创建时间定位日期，最多容许 180 分钟延迟；外部提交的自定义日期不能提前或回填时段。内置 cron 使用事件中的具体表达式，晚到也不会误判为另一个时段。

同一生产 concurrency 串行执行。若同一源码 SHA 已有该时段之后的成功发布，跳过重复采集、构建、发布和失败提示更新。不同源码、未到该时段的旧版本、失败提示状态不能占用本次时段。push 和显式手动恢复不受本门禁的时段去重影响；生产失败需新建一次运行，不使用 Re-run。

现有 concurrency 配置仍只有一个 pending 位置；后来的触发可能替换尚未开始的 pending 运行，`cancel-in-progress=false` 不提供完整排队交付保证。本门禁只处理实际开始执行的运行。外部任务启用验收必须包含该风险的处理方案，不能把门内去重当作门前队列可靠性证明。

cron 的 HTTP 成功只证明 GitHub 接受了触发请求，不证明发布成功。运营记录仍需追踪对应 GitHub run、verifier 和 Vercel 结果，失败在 24 小时内处理。停用外部任务不会关闭 GitHub 内置 cron；故障时先禁用本项目四个外部任务，保留其他任务不动。
