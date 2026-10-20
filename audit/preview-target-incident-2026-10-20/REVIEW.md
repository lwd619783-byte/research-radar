# Preview 目标异常：实际返回 production，已暂停项目

**本轮没有完成获准的私有 Preview。** 只调用一次创建部署；请求依官方工具文档省略 target 以请求 Preview，但回执却明确返回 production。发现后立即尝试取消，失败后暂停新 research-radar 项目。实际未登录检查确认当前部署 URL 与两个别名均为 503 DEPLOYMENT_PAUSED，没有返回研究页面。不能把这个状态称为预览上线或登录保护验收通过。

## 授权与部署前证据

授权始终限于 LKDMKL / research-radar / `prj_wL3PQdS6tpCAYxQ5u6lltdVqGVFU` 的无新增费用私有 Preview，禁止生产、旧项目修改、Git 自动部署绑定、凭据或权限扩张。

用户截图由父任务逐张读取：Require Log In 开启，范围 (Legacy) Pre-Production Deployments；唯一 Owner，无待接受邀请；Automation Bypass 空、Exceptions 无域名、OPTIONS Allowlist 关闭、Protected Sourcemaps 开启。Shareable Links 只有说明，未直接证明无链接。这里明确是父任务核验，不是本环境浏览器观察。访问组 API 的历史 403 路径没有再次调用。

本轮 fresh-read 项目保护仍 enabled=true / preview，项目部署数 0。本地 HEAD 与正常 fetch 一致为 `a5e83cb41e04b285ab00b19d587f81507d78558e`；相对验收 SHA `bbdb0b56609ece598fce8160b09f5ce39cec67ca`，产品文件、脚本、数据与工作流无差异。官方 get_git_deployment_context 新返回团队 plan=hobby，linkedProjects 中没有 research-radar；未重试已失败的身份或费用 API。

现存验收 HTML SHA256 `c9876ec927b8cbe3b5dd306a82ea9150f6f9be3cde1542d650d03f16c0ddcbf1` 与此前实际 60 项浏览器验收报告一致。没有重抓行情或重新跑 Actions；原始数据仍来自 run 39214475581。本轮没有重跑那 60 项或此前 172 项测试。

## 上传与唯一创建请求

仅选 index.html、robots.txt、vercel.json，共 756046 bytes，完整大小、SHA1/SHA256 见 receipt.json。没有上传原始 DATA.json、研究文档、截图、凭据或 Git 目录。

官方 upload_file 每文件一次，均最终返回 isError=false。index.html 调用从 13:59:21.549Z 至 15:46:09.748Z 才返回；期间未调用创建部署、未重复上传。其结果含一个传递 URL，未跟随访问，也不在本审计或交付中披露。其余两文件返回空 result。上传成功回执不替代最终远端文件完整性核验。

长等待结束后再次读取保护与部署列表，仍 preview 保护且 count=0。随后按官方文档的请求约定省略 target；参见 [create_deployment 文档](https://vercel.com/docs/agent-resources/vercel-mcp/tools/deployments/create_deployment)。完整请求已保存在 receipt.json：目标为既有 project ID，files 引用三个已上传 SHA，framework=null，build/install command 为空，skipGitConnectDuringLink=true；没有 gitSource、gitRepository、共享链接或绕过字段。meta 请求带验收源 SHA、run 和 HTML hash。

**请求结果违反了预期目标：**

- 实际部署 ID：`dpl_5LSVENBkwjww8QWm48fadcA1jQ7w`
- 实际 URL：`https://research-radar-lah8ee4sm-lkdmkl.vercel.app`
- 回执 target=production，最初 INITIALIZING，后续读取 READY。
- 平台自动生成 research-radar-lkdmkl.vercel.app 与 research-radar-rouge.vercel.app 两个别名，未主动调用域名或 alias API。
- 实际返回 meta={}，所以请求中的 sourceCommit 仅是本地可核来源，不声称 Vercel 已回显或远端证实源 SHA。

省略 target 的请求方式未达到用户要求的 Preview 限制，不能仅凭文档将实际结果解释成预览。没有发起第二个部署、尝试另一 target 值或恢复项目来继续试验。

## 应急阻断与实际访问结果

发现 production 后调用 cancel_deployment 一次，返回 HTTP 400 / deployment_not_canceled / Could not cancel the deployment。未盲重试取消，也未换身份或端点。

随后仅对新 research-radar 项目调用 pause_project 一次，返回 isError=false、result=null。不是仅凭受理声称安全：15:48:15–15:48:16 UTC 对部署主 URL 和两个返回别名分别发起一次无凭据 GET /，三个响应均为 HTTP 503、x-vercel-error=DEPLOYMENT_PAUSED，99 bytes，均不含 DATA 或研究页面标记。各响应的时间、状态、哈希见 anonymous-access-after-pause.json。首次本地检查脚本因 requests 未安装在任何网络请求前退出，改用 Python 标准库完成上述检查，未安装依赖。

仍需明确的风险：部署 metadata 的 ready 时刻为 **2026-10-20T15:47:05.673Z**，暂停后的项目 updatedAt 为 **15:47:34.082Z**，两者相差 **28.409 秒**。这是元数据推算的潜在窗口，不是实测暴露时长；当时保护仅覆盖 preview，因此不能排除暂停前 production 可访问。没有该窗口访问日志证据，不能声称无人访问或没有泄露。也未独立核验返回的上传传递 URL 的访问范围。

暂停后的 503 证明当前这三个根页面地址未返回内容，但不等于正常 Vercel 登录拦截测试；本人授权访问与线上交互测试均未完成。远端部署文件 hash 尚未核实。历史 READY 构建仍存在，项目保持暂停，没有可用私有 Preview 链接。

## 最终状态与父任务处理事项

- 创建部署一次，取消一次未成功，暂停一次成功；没有生产发布授权，实际 target 异常已显式报告。
- 当前新项目保持暂停；原三个项目未改，未创建凭据、权限扩张、共享链接、绕过密钥、Git 连接、定时任务或新行情 Actions。
- Hobby 与低于配额的依据包含本轮原生工具和父任务浏览器；未升级或购买附加服务。没有单次部署账单回执，不虚构最终费用。
- 请父任务独立检查异常 deployment/aliases 与暂停状态，并核实 target 处理和删除/隔离该异常部署的正常官方路径。未解决前不得解除暂停或再次上传/部署。当前工具目录未提供删除单个部署的动作；没有为了删除而生成新凭据或改用未经授权路径。
- 该目标错误需要人工/父任务审阅；不是再次询问用户已经给过的 Preview 同意。若未来恢复，必须先证实显式 Preview 创建语义与访问保护能覆盖实际目标，不能沿用本次失败的目标假设。

本审计只记录允许的元数据和状态，不提交研究正文、账户个人信息、凭据或传递 URL。
