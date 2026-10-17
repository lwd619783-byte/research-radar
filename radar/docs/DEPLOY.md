# 投研雷达 · 首次部署（约 15 分钟，只做一次）

> 读者：仓库所有者 LWD。做完这一页，之后行情每个交易日自动刷新 3 次，ChatGPT 每周合并 PR 后自动发布，你不用再操作。
> 说明：构建脚本已在本地实测（抓行情、生成页面、缺数据兜底均通过）；GitHub Actions 与 Vercel 这两步是按官方用法写的，**首次运行时请留意结果**，报错就把 Actions 日志贴给 ChatGPT。

## 0. 把文件放进仓库

压缩包里的 `radar/` 和 `.github/workflows/` 放到仓库**根目录**（与 `投研知识库/` 同级），提交到 `main`。也可以直接把压缩包交给 ChatGPT 让它提交。

## 1. 创建 Vercel Token

1. 登录 vercel.com → 右上角头像 → **Account Settings** → **Tokens**。
2. **Create Token**：名称填 `github-radar`；Scope 选你的个人账户；有效期可选 1 年（到期前 ChatGPT 会提醒你换）或不过期。
3. 复制生成的 token（只显示一次）。

## 2. 把 Token 存进 GitHub

仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**：

| Name | Secret |
|---|---|
| `VERCEL_TOKEN` | 上一步复制的 token |

## 3. 第一次发布

仓库 → **Actions** → 左侧 **radar-deploy** → **Run workflow**（保持勾选「即使行情没变化也重新部署」）→ 绿色按钮。
1–2 分钟后点进这次运行，Summary 里会显示「已部署：https://…vercel.app」。打开确认页面正常。

> 这一步会在你的 Vercel 账户里自动创建项目 **investment-radar**。**不要**在 Vercel 里再「Import Git Repository」导入这个仓库。

## 4. 绑定子域名（腾讯云）

1. Vercel → 项目 **investment-radar** → **Settings** → **Domains** → **Add**，输入完整子域名（如 `xxx.你的域名`）。
   - 子域名之前和 ChatGPT 商量过，**忘了就问 ChatGPT**。
2. Vercel 会显示一条 **CNAME** 记录（记下「Value」那一串）。
3. 腾讯云控制台 → **DNSPod / 云解析 DNS** → 你的域名 → **添加记录**：
   - 主机记录：子域名前缀（如 `xxx`）
   - 记录类型：`CNAME`
   - 记录值：Vercel 显示的 Value
   - 线路：默认；TTL：600
4. 回到 Vercel，几分钟内显示 **Valid Configuration**，HTTPS 证书自动签发。
   - Vercel 服务器在境外，**不需要 ICP 备案**；国内访问速度一般可用，偶有波动。

## 5. （推荐）固定 Vercel 项目

避免 CLI 以后关联到别的项目。再添加两个 GitHub Secret：

| Name | 在哪里找 |
|---|---|
| `VERCEL_PROJECT_ID` | Vercel → 项目 investment-radar → Settings → General → **Project ID** |
| `VERCEL_ORG_ID` | 个人账户：Account Settings → General → **Vercel ID**（团队则为 Team Settings → **Team ID**） |

## 6. 检查访问权限

Vercel → 项目 → **Settings** → **Deployment Protection**，看一眼当前设置：

- 默认的 **Vercel Authentication（Standard Protection）** 保护的是 PR **预览地址**（需登录你的 Vercel 账号才能看），正式子域名对外可访问。页面已设置 `noindex`，搜索引擎不会收录。
- 如果希望正式地址也需要登录 / 口令：先看该页面在你的套餐下有没有对应选项；没有的话，回来找 Notion AI 加一个简单的口令保护（需少量开发）。

## 之后会自动发生什么

| 时间（北京，交易日） | 动作 |
|---|---|
| 07:05 | 美股收盘后刷新 |
| 11:40 | A 股午间刷新 |
| 16:20 | A 股收盘后刷新 |
| ChatGPT 开 PR 时 | 自动校验数据，并在 PR 里评论一个预览地址 |
| PR 合并到 main | 立即重新发布 |

- 周末与节假日行情不变时自动跳过，不产生部署。GitHub 定时任务常晚 5–30 分钟，属正常。
- 定时任务失败时 GitHub 会发邮件给你；线上页面保持上一版，不会挂掉。
- 费用：GitHub Actions 每次约 1–2 分钟，每月约 70–150 分钟，在免费额度内；Vercel Hobby 免费。

## 常用操作

- **立刻刷新**：Actions → radar-deploy → Run workflow。
- **回滚**：Vercel → 项目 → Deployments → 选上一版 → **Instant Rollback / Promote to Production**。
- **暂停自动刷新**：Actions → radar-deploy → 右上角 ··· → **Disable workflow**。
- **离线备用**：任意一次运行页面底部 **Artifacts** → 下载 `investment-radar` → 解压后双击 `index.html`。
