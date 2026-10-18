# 同轮独立审计 P2 修复：旧 FX 回退及日线终结性

基于 `622b5f98062b635dc2ad9137cd26915b3f256c21`，正常 fetch 的 FETCH_HEAD 相同；继续 `fix/radar-truthfulness-2026-10-18`，无用户修改被覆盖。本补丁不修改前端文件、财务数据、布局、权限或 Actions。

## 结论及修复

审计指出的问题成立。旧版 `quotes.fx()` 从 `regularMarketPrice` 生成 `schemaVersion=2/value/asOf/receivedAt/src`；即使 asOf 恰好与股票日期相同且缓存不足36小时，也不能证明历史日收盘。此前 `dated_fx()` 的无 rates 兼容分支错误地允许该路径，本轮已移除。仅含 rates 而无终结性证据的首轮新缓存也保守拒绝；不会自动补造证明。

非 USD 仅采用 Yahoo 日线中带有以下证据的历史数据：明确1d间隔、交易所时区、原始bar时间戳、供应商 currentTradingPeriod.regular 的开始与结束时刻、实际接收时间。每个已接受的 bar 都满足以下之一：

1. 它在已经开始的供应商当前时段之前，且属于更早的交易所日期；或
2. 它的时间戳位于供应商当前时段内，并且**抓取时已到该时段结束**。

当前时段未结束、未来/错误时段、结束后的额外实时点、时间戳与日期不符、缺来源/间隔/时区/证明均不能被当成历史收盘。读取缓存时再次用该缓存的原接收时刻验证，等待时间不会把早先抓取的盘中值变成收盘值。USD本币恒等换算不受影响；非USD缺合格FX时市值与FX来源留空，既有最小缺失标签继续表达。

## 实测与保持不变的结果

`fx-finality-capture.json` 记录本次6个正常公开GET的起止时间、200响应、内容哈希、解析质量与交易日覆盖。没有重抓42家公司，没有把HTTP 200当质量通过。6种FX均通过终结性检查，每种保留23条最终日线，最新2026-10-16。供应商该交易时段 start=1792105200、end=1792191540，Europe/London；本次接收时间晚于结束时刻，数据中的额外实时点不采用。

6种FX的10/16日值与原快照逐项相同，非FX的daily/quote/index/ratio完全相同。新版回放仍为42/42同日报价/FX市值。原42条快照使用的是rates序列，并非旧版无rates兼容分支；其问题是未持久保存终结性依据，而不是证明所有值错误。新抓取增加独立证据，未反写旧回执。

财务仍是40条件采用 = 37三指标完整 + COHR/CXMT两项扭亏 + SU仅收入；普通增长信号36，KBL/DZSK仍缺。CXMT仍54条。三项指数、Tencent元数据、两项PE、Yahoo月度单点问题未冒充解决。

## 可移植公共证据

`fixtures/` 只含公开市场数据：

- `market-original.json.gz`：原119请求阶段留下的完整归一化市场数据，解压SHA256仍为 `7104fc3546ed56aa9878e98c8c0632da0b776948fd4f12b6ac9af488555006d2`，保留历史截图与验收的原输入。
- `market-finality.json.gz`：仅替换6个FX记录，加入本次实际终结证据；解压SHA256为 `8bfc4755070254fff382230457c68293865cd17aecbbe8647ebf9ac9dc429365`。
- `fx-public-responses.json`：为复核最终性保留的最小公开响应字段（时间、价格、交易时段），不保存Cookie、crumb、请求头或账户数据。
- `legacy-fx-cache.json`：从基线SHA `414eb80626d3200dfebe4a010507c5fe74d7ca31` 提取并执行**未修改的实际旧 fx() 实现**，输入上述真实公开CNY响应而得到的旧格式缓存。它是可复现的旧生产者重建，不是假称仍存有当年的原始生产缓存文件。测试内的匹配收盘股票响应为明确合成数据，不进入页面/财务TOML。

压缩/解压哈希、时间及旧生产者身份见 `fx-finality-capture.json`。保留完整日线与月线是为了重放既有图表及指标，已剔除HTTP传输、身份及私人研究内容。回放从仓库fixtures读取，不再依赖服务器原有/tmp输入。/tmp仅用于新生成的本地页面。

## 重放与测试

从仓库根目录执行（不联网、不触发Actions）：

```bash
python -B -m unittest discover -s radar/tests -v
python -B radar/scripts/acceptance_probe.py --preflight
python -B audit/truthfulness-2026-10-18/prepare_desktop_review.py
python -B audit/truthfulness-2026-10-18/verify_release_gate.py
```

回放使用 `fx-finality-capture.json` 中固定的 `replayAt`，不会把今天时间写到旧证据上使它“新鲜”。prepare脚本需本地Git包含基线414eb80…对象，用该对象重建before；after使用当前代码和同一持久快照。若浅克隆未含基线，先正常fetch该提交，不能用其他版本冒充before。

真实桌面截图（需系统Chromium与已安装Playwright）：

```bash
python -m http.server 8765 --bind 127.0.0.1 --directory /tmp/radar-desktop-review
# 在另一终端运行；完成后关闭本地HTTP服务
python -B audit/truthfulness-2026-10-18/desktop_acceptance.py
```

截图输出到 `screenshots-finality/`，回执 `desktop-finality-receipt.json`；原 `screenshots/` 与 `desktop-receipt.json` 不覆盖。像素哈希受浏览器/字体影响，回执保存实际本机结果，DOM与数据断言另行校验。

96项测试已实际重跑，日志见 `fx-finality-tests.txt`；新增6项覆盖旧生产者缓存、抓取失败→merge→assemble真实调用链、缺失/篡改终结证据、股票收盘但FX日线仍更新、盘中缓存等待后仍不可用、持久快照哈希与42项覆盖。旧测试的合法FX样例改为带真实字段结构的合成终结证据，没有放松断言。

`--force` 仍因财务缺口退出3、changed=false、不生成页面；空缓存offline仍退出2；回执 `fx-finality-release-gate.json`。这是实现端本轮测试，独立审计尚未重跑，不宣称获得独立测试通过。

本补丁未合并、部署、启用或dispatch Actions。终结性依赖免费供应商交易时段元数据的准确性；缺失/冲突时保守空缺，而不假设已收盘。
