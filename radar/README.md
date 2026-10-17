# 投研雷达 · Alpha Radar

一屏看清：最值得追踪的行业 → 关键卡点 → 细分龙头 → 近期走势与财务。单文件静态页面，部署在 Vercel。

```
radar/
├─ data/            ← 唯一需要日常维护的地方（TOML）
│  ├─ config.toml       站点配置、本周结论、跑马灯指数
│  ├─ industries.toml   行业雷达（四维评分）
│  ├─ chokepoints.toml  关键卡点
│  └─ companies.toml    细分龙头（财务、快讯、财报日）
├─ site/            ← 前端模板（index.html / style.css / app.js），一般不改
├─ scripts/         ← build.py（入口）、schema.py（校验）、quotes.py（行情）
└─ docs/
   ├─ HANDOFF.md        维护手册（给维护者 / ChatGPT）
   └─ DEPLOY.md         首次部署步骤（给仓库所有者）
```

常用命令（仓库根目录，Python ≥ 3.11，无需安装依赖）：

```bash
python radar/scripts/build.py --check     # 只校验数据（改完 TOML 先跑）
python radar/scripts/build.py             # 抓行情并生成 radar/dist/investment-radar/index.html
python radar/scripts/build.py --offline   # 不联网，用上次缓存的行情
```

自动化：`.github/workflows/radar-deploy.yml` 在交易日北京时间 07:05 / 11:40 / 16:20 刷新行情并发布；`radar-preview.yml` 为 PR 生成预览地址。

本页仅用于研究跟踪，不构成投资建议。
