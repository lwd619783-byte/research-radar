# 私有仓库上传准备回执

检查日期：2026-10-17。状态：本地准备完成；未 push、未创建 PR、未合并、未部署。等待主对话独立审计，不代表审计通过。

## 本阶段授权与远端阻断

用户授权目标为 `https://github.com/lwd619783-byte/research-radar`，仅分支 `fix/radar-data-integrity`。父任务报告已在浏览器验证 owner 和 Private；本地侧仍须独立核验。

- 本机现有 GitHub CLI 执行一次只读 `gh api repos/lwd619783-byte/research-radar`，选择性请求 full_name/private/visibility/owner/permissions/default_branch/size。连接 api.github.com 被 Windows 套接字访问权限拒绝，退出码 1。
- 已连接 GitHub 工具使用与目标 owner 匹配的账户调用 get_repo，返回 HTTP 404 Not Found。404 不能证明仓库不存在，也不能证明公开或私有，可能是连接器未获仓库访问权；原因未核实。
- 未重试上述拒绝、未使用其他访问路径、未升权、未更改代理或网络设置。没有重跑行情来源探测。
- 本机有 gh 和 Git Credential Manager（helper=manager），但网络在身份校验前失败，因此不能确认正常 Git 登录或写权限，也不能断言缺少哪一种凭据。未读取凭据内容、创建令牌或修改登录状态。
- 未配置 remote，未执行 push（包括 dry-run），未查询或修改仓库设置。
- 后续需用户/父任务提供正常允许的 Git 访问环境，并使现有 GitHub 连接器可见这个独立私有仓库；不授权自动修改权限。恢复后先核验 owner/private/写权限及空仓库状态，再决定上传。

## 完整历史与内容检查

原有完整历史只有以下三次提交，作者/提交者均为 `Codex <codex@local.invalid>`，无个人作者邮箱：

1. `22d9601eb4879f02ca8278aa27841ce9e604a845`
2. `8d9cfbe4c166dd052c5667aabc6af3dbd8e81c00`
3. `607080652b35b1d7e3df713689d63f728e15277d`

逐个枚举全部可达历史内容对象：34 个 blob，32 个 UTF-8 文本及 2 张 JPEG。检查常见私钥、GitHub/cloud token、字面量密码/API key、带凭据 URL、个人邮箱、持仓/账户关键词；没有匹配。此为有限规则检查和项目范围核对，不是对所有可能秘密的数学保证。

- 允许范围内的文件为项目代码、测试、原件四份 TOML、项目文档、审计日志/哈希与两张合成页面截图。
- 四份 TOML 保留 15 行业、16 卡点、42 公司；含原件行业/公司研究摘要与未核财务，不是已核实投资信息。未添加真实知识库导出。kb 仅为原件中的笔记路径引用，目标笔记正文不在仓库。
- 没有 .env、凭据文件、用户账户/持仓明细、私人桌面截图、其他项目源码或知识库目录进入历史。
- 两张 JPEG 已重新目视检查：仅雷达页面内容，无桌面、浏览器账户或其他应用；合成行情加交接原文字，不能作真实行情证据。
- 审计回执中保留本项目工作目录、原件位置、机器名、已查 Vercel 团队/项目名称等必要操作证据；不含令牌或账户凭据。
- .git、ignored 的 audit/runtime、audit/visual、行情缓存和 dist 不属于提交树；先前 Library 上传辅助脚本与导出压缩包位于仓库外，不在上传范围。
- 原件 HANDOFF/DEPLOY 中“停止 Notion 更新”等旧指示仅留作历史证据，不执行。完整研究继续留在私有 Notion。

## 阻止未审计 Actions

本阶段获明确授权后，将两个工作流在原目录下改名为 `radar-deploy.yml.disabled` 和 `radar-preview.yml.disabled`，字节不改。当前提交树中没有 `.github/workflows/*.yml` 或 `*.yaml`。因此该分支没有可执行的 push、PR、schedule 或 workflow_dispatch 定义；不依赖仅适用于部分事件的 skip-ci。

GitHub 官方要求工作流后缀为 .yml 或 .yaml：
https://docs.github.com/en/actions/get-started/quickstart

原始历史仍保留旧工作流，仅可用于审计，不可把旧提交作为远端分支头。未更改仓库/组织 Actions 设置、安全配置或持久权限。没有改原 cron 表达式或启用新调度。

**Actions 实际运行核实状态：未推送，无法核实远端运行列表；不能声称服务器已验证零次运行。** 后续成功 push 后仍需检查该分支及提交 SHA 的 Actions runs/checks，并确认未发生部署。首次上传空仓库可能使该分支成为默认分支，因此本准备禁用了全部触发类型。

## 本地验证与变更范围

- `python -m unittest discover -s radar/tests -v`：29 tests，0.800s，OK，退出码 0。新增测试验证无活动工作流，两个禁用文件与基线逐字节相同；原 cron 缺口测试改读禁用文件。
- `git diff --check`：通过。
- `git diff 22d9601 -- radar/site radar/data`：空；冻结前端和四份 TOML 未改。
- 本阶段仅工作流文件改名、禁用说明、相关测试与本回执；核心计算、前端及数据不改。
- audit/REPORT.md 和 DEPLOYMENT-CONDITIONS.md 是此前阶段快照。其中“工作流未改”等陈述对应当时状态；本阶段禁用及远端核验阻断以本回执为准。
- 未调用模型或服务档位修改接口；实际配置以父任务设置为准，不声称工具已独立验证 GPT-6 Astra/high/Standard。

准备提交的完整 SHA 由最终交付列出；不存在已上传分支 URL 或成功上传文件清单。
