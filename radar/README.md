# 投研雷达 · Alpha Radar

投研雷达把行业研判、产业卡点、公司行情和财报放在同一页。GitHub Actions 构建静态站点，Vercel 在登录保护下提供访问。

## 维护内容和配置

- 行业、卡点、公司、财报记录、每日要点和每周主线在 Notion「投研雷达｜数据后台」维护。字段、格式和示例见 [Notion 数据契约](../docs/NOTION-CONTRACT.md)。
- `data/config.toml` 管理站点、指数、比值、调度及 Notion 读取配置，`data/notion_schema.json` 定义六表契约，`data/market_calendar.json` 定义各交易所会期。
- `scripts/` 包含采集、归一化、构建和发布校验，`site/` 是静态前端，`tests/` 是离线回归测试。

## 离线检查

在仓库根目录运行。生产 CI 使用 Python 3.12，部分回归测试需要 Node.js。

```bash
python -B radar/scripts/build.py --check
python -B radar/scripts/acceptance_probe.py --preflight
python -B radar/tools/build_visual_fixtures.py --out work/radar-visual-pages
```

`--check` 校验配置和契约，`--preflight` 还运行离线回归。视觉夹具通过 FakeTransport 生成，产物仅用于本地审阅。PR 的视觉 CI 生成 Chromium 截图和检查报告，真实 Notion 只读演练另用独立入口。入口和产物说明见 [生产运维手册](../docs/PRODUCTION.md)。

## 生产更新

北京时间工作日 08:45、12:15、18:15 和周一 06:50 触发生产流程。GitHub 内置计划与外部时钟共用时段准入和去重规则。计划、排队、发布和回滚的操作步骤见 [生产运维手册](../docs/PRODUCTION.md) 与 [外部时钟触发](docs/EXTERNAL-SCHEDULE.md)。

本页仅用于研究跟踪，不构成投资建议。
