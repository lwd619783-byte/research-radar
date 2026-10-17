# 私有部署条件（仅审计；没有发布）

检查日期：2026-10-17。通过已连接 Vercel 只读 API 查询。

## 已核目标

- 团队：LKDMKL / `lkdmkl`，ID `team_9Yr7DlwRIfTtq6lvfc30z6Ni`。
- 默认作用域按 radar 搜索：0 个结果。
- 团队完整项目列表：`this-time-that-time-v141-migration-test`、`investment-research-dashboard`、`ops-collaboration-dashboard-trial`。
- 没有已核实的独立雷达项目；未读取或更改这三个项目的内容、部署或配置。
- 本地新 Git 仓库没有 remote。未 push、创建 PR、合并 PR、上传研究或部署产物。

## 保护要求

当前官方文档指出 Standard Protection 不保护生产域名；All Deployments 覆盖生产、预览及生成的 URL，并可结合 Vercel Authentication。
文档说明 All Deployments 在全部套餐提供，但本任务没有独立项目，尚不能验证当前账户的实际配置能力。

- https://vercel.com/docs/deployment-protection
- https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication

`noindex`、robots.txt、私有 Git 仓库、隐藏链接均不是站点访问控制。生成器现在输出 `Cache-Control: private, no-store`，这也不替代身份验证。
不要使用可在浏览器源码中读取的口令，也不要把真实研究先上传再加保护。

## 父任务需要核定/批准的具体下一步

1. 指定或批准新建**独立私有雷达 Git 仓库**，核对 owner、仓库名、private 状态和准确 remote URL；之后才可批准 push 审计通过的提交。
2. 指定或批准在上述团队创建**独立雷达 Vercel 项目**。不得复用已有投研或运维看板。
3. 在上传任何真实研究前，由用户/获批操作者确认该项目启用 **Vercel Authentication + All Deployments**，访问者名单仅含用户明确授权的人。任何付费、凭据生成、权限扩大都要单独批准；本任务未执行。
4. 首次仅用不含研究的测试标记验证保护；经批准的真实研究上传必须排在匿名测试通过之后。
5. 审计现有工作流再单独批准启用：原件会上传 artifact、在 PR 发预览评论、使用 `vercel@latest`，且缺少项目 ID 时会自动创建/关联项目。本轮按约束**未修改工作流，也未运行调度**；不应原样启用。
6. 来源联网验证需在已获授权、正常可联网的执行上下文重跑。当前普通本机进程的第一次 Yahoo 请求得到 WinError 10013。本任务未升权、改防火墙、代理、网络设置或绕路。

## 匿名验收矩阵（全部待执行）

没有目标域名，不能执行矩阵，也不能称“私有发布成功”。验收需使用无 Cookie、Authorization、分享 token、保护绕过 header 的新会话。

| URL 类别 | 必须覆盖 | 检查 |
|---|---|---|
| 生产 | 自定义域名、项目 production alias、生成部署 URL | `/`、`/index.html`、实际构建的全部静态路径 |
| 预览 | 分支 alias、每个待使用 preview URL | 同上 |
| 历史 | 项目部署清单枚举的旧 production / preview URL 和别名 | 同上；没有历史时保存完整清单空结果 |
| 静态与旁路 | 内联 DATA 所在 HTML、任何外置 JSON/JS/CSS、下载与 artifact 链接 | 未认证不得返回真实研究内容；记录状态码、Location、响应摘要 |

应记录枚举来源、检查时间、每个 URL/路径、最终状态和重定向链。401/403 或经核验的登录挑战可作保护证据；网络错误、404、只看到登录页但原静态路径仍返回数据，均不足以证明私有。另用用户授权会话验证可访问性，不能以认证会话测试冒充匿名测试。

## 调度修正提案（未应用）

原 `5 23 * * 0-4` 对应北京时间周一至周五 07:05，漏掉周五美股收盘后的周六刷新。
最小增量建议：改成 `5 23 * * 0-5` 并同步注释为“北京时间周一至周六 07:05”。这样保留既有时点，只补星期五 UTC 23:05 = 星期六北京 07:05。须父任务另行确认，不能在本轮启用或更改调度。


## 2026-10-17 P2 follow-up

This is a historical snapshot. See [P2 review](P2-REVIEW-2026-10-17.md) and its new per-command logs for the current fixes, 55-test run, frozen hashes and successful approved GitHub read-only checks. Earlier network/remote states and the old 28/29-test receipts are not reused as current verification. Deployment remains out of scope.
