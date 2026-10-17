# 雷达本地修复审计交付

结果：数据链路修复和合成回归完成，冻结前端未改。**等待父任务独立审计；未发布。**

## 原件与隔离工作区

- 本机：`LKDMKLPRO16`。
- 原件：`C:\Users\10750\Downloads\radar-handoff.zip`，75,536 字节。
- SHA-256：`0b8cabb0c7507b92be290ffc7dacf185973ff2f0df8f102d3498912d52d884c5`，与交接指定原件完全相同。
- 工作区：`C:\Users\10750\Documents\Codex\2026-10-17\task\radar-local-audit`。
- 分支：`fix/radar-data-integrity`；独立新仓库，无 remote。
- 基线提交：`22d9601`；核心修复提交：`8d9cfbe4c166dd052c5667aabc6af3dbd8e81c00`。末尾审计提交见 `git log -3 --oneline`。
- 未调用任何模型、推理档位或服务档位修改。工具未回显实际模型配置，GPT-6 Astra / high / Standard 的运行配置仍以父任务设置为准，不声称独立核验成功。
- 原投研 OS、运维看板、私有 Notion 辅库均未改。交接文档“知识库全进 GitHub/停止更新 Notion”的旧指示没有执行；原件文档保留作证据，并非本轮授权。

## 修复与限制

| 交接问题 | 核实与处理 | 状态 |
|---|---|---|
| 腾讯 close 误作 adjclose | 原脚本复制 raw close；现在分别请求 raw 与 qfq，仅按同日对齐 qfqday。不存在则收益率 null；Yahoo 也不再用 close 填补 adjclose | 合成验证通过；真实 API 待验证 |
| 回撤/高点口径不同 | 52 周严格使用最后行情日期之前 52 个自然周 `(ld−364天, ld]`；高点取同窗口原始日内 high，回撤=原始末价/同一高点−1。去掉 quote hi52 覆盖；历史不足/缺 high 均置空 | 通过；拆股时原始高点回撤不等于复权投资收益，已明确分开 |
| 缓存陈旧 | v2 数据凭证、来源、收到时间、行情日期；收到时间 36h 与市场当地日期最多落后 4 个自然日双检查。旧格式拒绝；网络成功但日期旧仍 stale；离线仍 stale；日期倒退不能覆盖新缓存 | 通过；阈值是保守容忍度，不是交易所节假日日历 |
| 日期混入生成时间 | 每公司 ld、指数 asOf、市场 asOfByMarket、FX 来源日期、generatedAt 独立。禁止从构建时钟编造盘中时间；不同日期或未确认收盘时阻断发布 | 通过；动态文字改动待确认 |
| 财务/估值来源日期不足 | 增加财务 source_name/source_url/period_end/published_at/verified_at/basis；无证据、过期或非单季时数值置空。PE、市值、FX 禁用无日期 TOML fallback；非美元市值要求 FX 日期与估值日期匹配 | 原件 42 公司没有完整证据，无法恢复真实财务 |
| 周五美股缺周六刷新 | 已验证 UTC 星期五 23:05 = 北京星期六 07:05；最小 cron 建议 0-4→0-5 | 因明确禁止修改调度，本轮仅报告，未应用 |
| 月线无条件删除末月 | 仅排除当前未完成月，末月已完成时保留；要求连续 120 个完整月；原始比值用于分位比较，显示才四舍五入 | 通过 |
| 短历史仍称长期 | 短/断月历史返回 ratio=null，走原 UI“暂不可用”；没有当前月时数学计算保留末月，但前端会再次 slice，故不输出该 ratio。公司固定 120日/2年图注不够历史时也阻断发布 | 通过；未修改固定图注 |

还修复了共享网络 cookie jar 的并发使用、NaN/Infinity 校验、缺失复权的实时价拼接、指数来源记录和严格 JSON 输出。缺少市值时前端会给出默认面积、仍宣称“面积≈市值”，因此也阻断发布。温度计极端区遇到固定“不在极端区”文字亦阻断，未擅自改文案。

`--check` 只验证结构，不代表内容已核实。`--force` 只代表构建指纹强制更新，不能越过缺失/证据门禁。退出码 2 为行情缺失超过 30%；退出码 3 为冻结 UI 无法安全表达；两者均在 render 前返回、输出 changed=false。阻断时可保存来源原始缓存和审计 JSON，不生成发布页。

## 前端冻结证据

| 文件 | SHA-256（原件与末尾一致） |
|---|---|
| site/index.html | `8cf42a0a00ae434dbdc96e9567e1e6338c28b95dee534f73664ef4473b2ed51d` |
| site/style.css | `8987b1f2aae01066e7665ebe6d0b5bb1708089a0fc7586c5d1deb67d7c041d36` |
| site/app.js | `3c057ca30e8d2e05e58201a3c57f8b0235812ca294e688c2d0f8ced395f2ed2b` |

`frontend-baseline.json` 和 `frontend-verification.json` 保存机读结果。15 行业 / 16 卡点 / 42 公司保留。
`git diff 22d9601 -- radar/site radar/data .github/workflows` 为空。没有添加栏目、投资结论、交互、样式或页面文案。

`before-desktop.jpg` / `after-desktop.jpg` 是**用户本机 Chrome、1526×786 桌面视口**截图，不是整个 Windows 桌面截图。原生桌面 API 未启用；没有使用其他技术捕获私人桌面。
两张图使用同一份明确标记的**合成行情 fixture**及交接原文字，专门隔离布局/渲染变化，不能作为真实行情或修复后数值正确性的证据。动态跑马灯位置随截图时刻不同。
同一 fixture 用基线构建器和修复后构建器生成的 index.html **逐字节相同**；Chrome 显示 42 个公司块，记录的 error 日志为空。修复后数值正确性另由回归测试证明。

## 验证记录

- `python -m unittest discover -s radar/tests -v`：28 项通过，见 `test-log.txt`。
- `python radar/scripts/build.py --check`：退出码 0，见 `schema-check.txt`；来源缺口作为警告保留。
- `python radar/scripts/build.py --offline --force`：退出码 2，见 `offline-build.txt`；无行情缓存，没有生成 dist 发布页。
- 全部行情具备但财务证据不足的合成主流程：退出码 3，未创建 index.html；`--force` 不能绕过。
- `python radar/scripts/visual_fixture.py`：复用 git 基线构建器，验证同数据输出一致；仅生成 audit/visual 下不可发布的本地视觉产物。
- `git diff --check`：通过。
- `python radar/scripts/probe_sources.py`：只读 Yahoo NVDA 首次请求即 WinError 10013，见 `source-probe.json`。未继续腾讯/其他域名，未重试绕路、升权或修改网络设置。**真实行情接口兼容性仍待联网验证**。

`audit/runtime/build-report.json` 保存缺失/过期/证据状态（本地忽略文件）；`audit/visual/{before,after}` 为仅用于本地浏览器对比的静态构建产物。它们不是已审计的生产数据包。

## 剩余阻断及父任务审计重点

1. 真实接口只读探测被本机网络权限拒绝；不能把合成适配测试等同于实盘验证。
2. 42 公司财务来源与日期未补证，原 `flash/period` 和页脚仍声称最新单季，故真实发布阻断。补证须从已有私有 Notion/一手报告核实，不凭文字重建。
3. 混合市场日期、未知收盘状态、stale 在 ticker/聚合里缺少逐项标识，短历史图注、缺失市值面积、温度计固定句子等限制：在父任务确认必要最小文字变更前继续 fail closed。
4. cron 修复仅提出，未执行。原工作流也尚不满足私有发布要求，不能直接激活。
5. Vercel 已连接但没有独立雷达项目；无已核私有 Git remote。全部生产/预览/历史 URL 和静态路径匿名测试尚未执行，不能称私有发布成功。精确批准事项及验收矩阵见 `DEPLOYMENT-CONDITIONS.md`。

曾通过 app 消息接口向源线程报告原件校验完成，但返回 thread not found；之后在本任务持续给出阶段更新。由平台在本任务结束后将本交付通知父任务。没有重建/重启此前停止的云任务。


## 2026-10-17 P2 follow-up

This is a historical snapshot. See [P2 review](P2-REVIEW-2026-10-17.md) and its new per-command logs for the current fixes, 55-test run, frozen hashes and successful approved GitHub read-only checks. Earlier network/remote states and the old 28/29-test receipts are not reused as current verification. Deployment remains out of scope.
