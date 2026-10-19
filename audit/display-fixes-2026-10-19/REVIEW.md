# 四项最小展示修正：离线验收通过，待父任务独立审计

本阶段依据批准 `Sentinel_9e90145bc8048191a565cc67f995db5a`、回复 `Sentinel_af86b7b6553881919ec1ddae6774bf3d`（2026-10-19 北京时间 11:29）执行。私有仓库 `lwd619783-byte/research-radar`，工作分支 `fix/radar-truthfulness-2026-10-18`，起点 `2de3aca8d5f9088fb8d7e3f57d65e0aa092f729f`，起点工作区干净且 fetch 后匹配。默认分支仍为 `fix/radar-data-integrity`，没有新建 main。Astra / high / Standard 是已接受的配置偏好；环境没有提供可独立核实的后台实际受理回执，本报告不冒称已验证。

**截图是真实 Chromium 渲染，但页面行情是明确标记的测试数据，不是本次 Actions 的真实 DATA，也未发布。** 复用上一阶段完全相同的合成行情＋旧长鑫样本，DATA SHA-256 `16a2f5da19e4b679df367889b3eb45c87d5d4b9412dafc28a6b6e91fa1373023`。前后页面只替换内联 app.js，未重新取数或改变样例财务；出处与边界仍见[上一阶段说明](../offline-page-acceptance-2026-10-19/REVIEW.md)。

[修正前页面](before.html) · [修正后页面](after.html) · [精确生产差异](app.diff) · [浏览器回执及截图哈希](browser-receipt.json) · [完整离线测试日志](offline-tests.log)

## 修正范围与截图

| 问题 | 本次结果 | 修正前 / 修正后 |
| --- | --- | --- |
| F1 有效覆盖分母 | 列表每项数字表头、筛选提示和现有行业聚合指标显示有效数/当前公司数。全表市值 17/42、PE 16/42；A 股两项均 0/22；PCB 营收中位数 10/12；半导体距高点均值 8/9。数字聚合公式和 partial 排除规则不变 | [PCB 前](screenshots/before-04-pcb.png) / [后](screenshots/after-04-pcb.png)；[半导体前](screenshots/before-04-semiconductor.png) / [后](screenshots/after-04-semiconductor.png) |
| F2 缺失指数 | 复用现有 issues 指标诊断，固定标签显示有效 5/8，现有跑马灯显式列出 399006.SZ、000922.SS、HSTECH.HK。没有 issues 元数据则显示“覆盖待核”，不声称完整覆盖 | [总览前](screenshots/before-01-overview-indices.png) / [后](screenshots/after-01-overview-indices.png) |
| F3 比值缺失 | 仅陈述“当前快照无可用比值数据”，不承诺自动恢复；保持不渲染旧比值、温度计或固定判断 | [前](screenshots/before-02-ratio.png) / [后](screenshots/after-02-ratio.png) |
| F4 短历史 | 表头改为“走势（最多60日）”，每行标出实际绘制交易日数。本样例长鑫为“实际 54 个交易日 · 短历史”；长历史只说实际绘制的 60 日，不冒充全部历史 | [长鑫前](screenshots/before-03b-cxmt-actual-history.png) / [后](screenshots/after-03b-cxmt-actual-history.png) |

只改生产 `radar/site/app.js`，新增离线测试和审计材料，并更新冻结清单中唯一获准的 app.js 哈希。模板、CSS、模块、数据源、TOML、财务证据、partial 规则、计算公式和发布门禁均未改。既有表格仍在原容器内滚动，新增标签随原有布局自然排版，没有新模块或样式表。没有新增投资结论或读取私有知识库正文；测试页面保留此前已有雷达内容，按原私有仓库边界交付。

## 本轮实际验证

- 2026-10-19 03:37:20–03:37:47 UTC，完整 `python -B -m unittest discover -s radar/tests -v`：**127 项通过，exit 0**（原 122 项＋5 项新测试），耗时 26.418 秒。[时间回执](offline-test-receipt.json)。不是引用旧测试。
- 新测试通过当前已安装 Node 执行真实生产 JS helper，覆盖 0/null/NaN/Infinity、全缺失、空集合、partial 排除、缺失指数去重及元数据未知、54/0/超过60个点的历史标签。不新增或升级依赖。
- 真实 Chromium / Playwright，1440×1000，**114 项断言通过**，15 张截图；JS 错误 0，外部请求尝试 0。断言核对五个市场筛选、空交集、十项指标各自分母、五项排序双向空值置后、三个财务指标排除 partial、四个行业聚合有效数及前后数值不变、指数与 ratio 缺失、0与null区别。`node --check`、`git diff --check` 通过。
- 全缺失变体：列表指标有效 0/42，聚合显示“—”和有效 0/9，指数 0/8 并列出缺项。空筛选显示 0/0；真实数值 0 显示 0.0% 且排序在 null 之前。[全缺失](screenshots/after-06-all-missing.png)、[空筛选](screenshots/after-05-empty-filter.png)、[0/null](screenshots/after-06-zero-vs-null.png)。边界数据只在测试脚本内生成，不修改生产数据。
- 已目视检查关键总览、两个行业、ratio、长鑫前后及三个边界截图，标签没有产生页面横向溢出。模块结构和页面视口溢出检查前后一致；截图保留固定黄色“测试数据、非本次 Actions 真实页面、未发布”水印，没有图像生成或修图。
- 10 个当前冻结哈希全部匹配；仅 app.js 的基线获准更新，其他 9 个文件逐字节未变。[旧新哈希与授权记录](frozen-update.json)。原历史 frontend-baseline.json 不改。

复核命令（无市场请求、无 Actions、无部署）：

```bash
python -B audit/display-fixes-2026-10-19/make_comparison.py
python -B audit/display-fixes-2026-10-19/check_display.py
python -B -m unittest discover -s radar/tests -v
```

浏览器仅在既有政策允许的 loopback HTTP 下访问内存中四个精确路径，不提供目录或任意文件；其他 URL 被测试路由拒绝，页面 CSP 禁止连接。服务随测试结束关闭。本阶段没有重试之前被拒的 file://、artifact 或 billing 路径，没有更改安全设置。网络实测只使用正常 Git fetch / ls-remote / push，实际回执随提交归档；未请求行情、公共来源或 Actions API。

## 仍待验收的事项

本轮结论仅为四项展示修正通过离线组件验收。run 39190870708 的完整组装 DATA / 缓存仍不在当前环境；此前 receipt 不包含足够的价格、完整历史、估值和组装字段，不能据它重造真实页面。样例长鑫的 54 根不能当作该 run 选后的真实数量，样例 5/8 指数也不能冒充 receipt 的直接组装列表。

后续若已有同次运行完整脱敏 DATA，可核实来源、时间、SHA 后离线渲染；否则需另行批准一次有界正常取数并保存可追溯 DATA。真实页面验收和私有发布验收仍独立待办。本轮没有新增市场请求、dispatch、定时 Actions、PR、合并、部署、权限、凭据或默认分支修改。代码与审计证据正常推送当前工作分支，交父任务独立审计，不直接发布。
