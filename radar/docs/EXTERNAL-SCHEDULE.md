# 外部时钟触发

外部服务只向 GitHub `radar-production.yml` 发送 `workflow_dispatch`，不接触 Notion、网页内容或 Vercel。PAT 仅授权本仓库 Actions 读写与 Metadata 读取。cron-job.org API key 只用于配置该账号的任务，不放进 GitHub。

`python -B radar/tools/external_schedule_jobs.py` 输出四份不含凭据、`enabled=false` 的配置：北京时间工作日 08:45、12:15、18:15，以及周一 06:50。配置格式依据 [cron-job.org REST API](https://docs.cron-job.org/rest-api.html)；触发接口依据 [GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。模板不会发请求。

安装时从本机加密存储读取 PAT，**仅在进程内**补入 GitHub 请求的 Authorization 头，再通过外部服务 API 保存。密钥不得写进模板、仓库、命令行、PR 或日志；读回任务详情时只输出标题、ID、启用状态、时区、时段和脱敏校验结论。未知创建结果先按唯一标题查找，不重复创建。

初次启用前核对准入与去重测试、真实只读演练和生产合并后的发布与核验结果。提前创建的任务保持禁用，PAT 在正式启用前通过只读配置和权限检查核对。模板设置的到期时刻为 2026-12-21 北京时间零点，续期前核对 PAT 与运营授权。

生产 workflow 先取得 Vercel 已验证的基线，再检查触发时段。外部时段只接受已知四种 slot，由 GitHub 的运行创建时间定位日期，最多容许 180 分钟延迟；外部提交的自定义日期不能提前或回填时段。内置 cron 使用事件中的具体表达式，晚到也不会误判为另一个时段。

同一生产 concurrency 串行执行。若同一源码 SHA 已有该时段之后的成功发布，跳过重复采集、构建、发布和失败提示更新。不同源码、未到该时段的旧版本、失败提示状态不能占用本次时段。push 和显式手动恢复不受本门禁的时段去重影响；生产失败需新建一次运行，不使用 Re-run。

生产组配置为 `queue: max`、`cancel-in-progress: false`。同一组一次运行一个任务，最多另有 100 个 pending。队列满时额外运行会被取消。GitHub 按进入并发组的等待时间排队，实际执行顺序可能与 dispatch 时间不同。检查调度时分别记录未入队、被取消、已开始后被时段去重跳过和真实成功发布。 [GitHub Actions 并发文档](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) · [2026-05-07 功能公告](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/)

cron 的 HTTP 成功只证明 GitHub 接受了触发请求，不证明发布成功。运营记录仍需追踪对应 GitHub run、verifier 和 Vercel 结果，失败在 24 小时内处理。停用外部任务不会关闭 GitHub 内置 cron；故障时先禁用本项目四个外部任务，保留其他任务不动。
