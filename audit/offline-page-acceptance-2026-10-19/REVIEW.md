# 离线页面验收：组件行为已测，四项展示问题待批准修复

**这是测试数据页面，不是 run 39190870708 的真实页面，也不是正式预览。** [打开可下载 HTML](preview.html)；[测试数据来源](data-provenance.json)；[浏览器检查回执](desktop-receipt.json)。所有 13 张截图均由实际 Chromium 渲染生成并逐张目视检查，底部固定黄色条显著写明“测试数据（合成行情＋旧样本）· 非本次 Actions 真实页面 · 未发布”。没有图像生成、修图或伪造浏览器截图。

本阶段按用户批准 Sentinel_6b081d0ebf8c8191a74c17fc68028545（回复 Sentinel_6b7e884db1608191ac354894ea593b97，2026-10-19 北京时间 11:11）执行。起点 HEAD `f4bc66728925b55bf61edda926b3f0db857a099f`、分支 `fix/radar-truthfulness-2026-10-18`，工作区干净；生产执行代码仍是 `dce7a0cd4a457f566e56809cb3644bb75476ecfa`。Astra / high / Standard 为接受的配置偏好，没有后台实际受理回执，未改变设置。

## 为什么不能生成本次真实运行页面

父任务已独立核验用户原 ZIP（12910 bytes，SHA-256 `6a640acb65dc94d0d1ebfb4b7ffbd10640f857f584a02d172282bf717d7254f7`）及 receipt（164090 bytes，SHA-256 `2b4475eeac7c3e1a2888915a53019d0196c7b41007383b6a4d436bcae521a144`），run 39190870708 / attempt 1 / dce7a0cd 完全匹配。本执行端接受父任务提供的核验结论，没有重试被拒 artifact 路径。

父任务直接读到 selectedDate 2026-10-16、complete 42/42、七市场同日、missing/stale 0、blockers []、集成市值 17/42、PE 16/42、ratioAvailable false、财务 40 verified / 2 partial。本轮只借这些事实设置**缺失模式**，不从诊断记录制造完整价格。

本地检查结果：

- `radar/.cache`、`radar/dist` 均不存在，没有此次运行的完整行情缓存或页面。
- `audit/runtime/build-report.json` 是 10/18 的旧文件，asOf=null，不适合作为当前页面数据。
- 已有真实公开 `market-finality.json.gz` 是 10/18 采集，报价记录没有新 contract 的 marketState；不可冒作 10/19 的本次运行。
- 原 receipt 不保存完整选后 bar 数组、价格/估值数值、完整组装指数/FX 或完整 DATA。再次取得相同 ZIP 也不能补齐这些缺口。

**最小下一步**：若用户已有同次运行保存的完整脱敏 DATA/缓存，可正常提供并核来源、时间、SHA 后离线渲染；若从未留存，则需另行批准一次有界正常取数，保存可追溯的完整组装 DATA，再做真实页面验收。本轮没有执行该取数或请求新的 Actions。

## 样例构造与验收方式

`make_preview.py` 使用当前未变组装逻辑，固定测试时钟为 2026-10-19 02:38 UTC。多数日线、所有估值数值、指数数值、FX 数值及时间戳是**合成**的；长鑫复用旧公开样本，先附加合成盘中 bar，再由当前选择逻辑裁至 10/16。样例选后为 54 根，仅是该旧样本的组件测试结果；不宣称原 run 的选后数量为 54 或 55。财务和页面原有文本取未变仓库输入，没有新投资结论，也未读取私有知识库内容。

样例保留用户给出的 17 家市值缺失模式，LITE PE 缺失，另 25 家市值/PE 均为空；ratio 设为异日后由组装逻辑清空。三个指数缺失、其余五个为合成值；5/8 是本测试明确设定，不冒充原 receipt 直接存有组装列表。

预览仅在生成 HTML 上添加测试标题、固定水印和禁止网络连接的 CSP。生产 HTML/CSS/JS、布局、模块、TOML、财务证据和门禁未改。预览 DATA 显式含 fixture/reviewPreview/offline 及禁止发布阻断。

首次 file:// 导航被既有浏览器策略拒绝（ERR_BLOCKED_BY_ADMINISTRATOR），该路径随即停止。只读核对现有策略后确认 HTTP URL 明确在允许列表中，采用仓库此前使用的正常 loopback HTTP 方式：仅绑定 127.0.0.1 的临时服务，只提供这个测试 HTML，不提供目录浏览或任意文件读取。未改浏览器策略、安全设置、权限或凭据；浏览器路由拒绝其余所有地址，CSP connect-src none。测试结束服务已关闭；没有外网发布或行情请求。

## 实际检查结果

桌面 Chromium，1440×1000，实际点击排序、市场/行业筛选、详情、热力图和行业面板；36 项行为断言通过，页面脚本错误 0，外部请求尝试 0。完整检查项、排序顺序、空值数量、聚合期望值/页面值及截图哈希均见 `desktop-receipt.json`，控制台摘要见 `browser-check-output.txt`。没有重跑或借用旧的 122 项测试来声称本轮 UI 全面通过。

| 检查 | 实际结果 | 截图 |
| --- | --- | --- |
| 日期 | 首屏及跑马灯显示 10/16 收盘，生成日期 10/19 单列；未称实时。页面没有额外解释“跨市场共同快照”的选择策略 | [总览](screenshots/01-overview-test-data.png) |
| 25 家市值、PE 缺失 | 所有对应表格单元格显示“—”，不是 0；A 股筛选的 22 家保持为空 | [A股筛选](screenshots/04-a-share-filter.png)、[缺估值详情](screenshots/05-missing-valuation-drawer.png) |
| LITE PE | 市值可用、PE(TTM) 缺失显示“—” | [LITE](screenshots/06-lite-missing-pe.png) |
| 排序 | 市值 17 个有效/25 个空，PE 16 个有效/26 个空；升降序均数值正确且空值置后。营收、净利、毛利率排序同样检查 | [排序](screenshots/03-table-sort-and-missing-values.png) |
| 筛选 | 5 个市场选项及 4 个有龙头的行业均与样例 DATA 的实际公司集合一致 | [A股筛选](screenshots/04-a-share-filter.png) |
| ratio 缺失 | 不渲染旧比值、图表、分位、定投动作或“不在极端区”固定判断；但恢复承诺文案有问题 | [ratio 缺失](screenshots/02-ratio-unavailable.png) |
| 短历史 | 详情标出实际 54 日、区间不足、52周数据不足，r60/ytd 等为“—”；列表固定标题仍有问题 | [短历史详情](screenshots/07-short-history.png)、[列表标题](screenshots/10-short-history-table-label.png) |
| partial | KBL 半年累计、DZSK 初步推算均显示“部分披露·不评分”；三类财务排序中为缺项，营收热力图为中性色 | [KBL](screenshots/08-kbl-partial.png)、[DZSK](screenshots/09-dzsk-partial.png)、[热力图](screenshots/12-map-placeholders-and-partial.png) |
| 聚合计算 | 半导体距高点均值实际仅取有效 8/9 家；PCB 单季营收中位数仅取 10/12 家、排除两家 partial。页面数字与独立计算一致，但分母未显式展示 | [半导体](screenshots/11-aggregate-semiconductor.png)、[PCB](screenshots/11-aggregate-pcb.png) |
| 市值总和、PE 行业均值 | 当前页面没有这两个聚合组件，不能虚称已验证其计算。实际存在的收益均值/营收中位数已验证；热力图缺市值采用占位面积且有提示 | [热力图](screenshots/12-map-placeholders-and-partial.png) |

## 四项未解决展示问题

**验收并非全部通过。** 以下问题已在实际渲染中确认并及时报告。本轮没有获得生产逻辑或布局修改授权，因此只留证，不修复：

1. **F1：有效覆盖分母缺失。** 表格排序/筛选没有市值 17/42、PE 16/42 或当前筛选后的有效/总数；行业面板只写总公司数。半导体标“基于9家”，距高点均值却实际是8家；PCB标“基于12家”，单季收入中位数实际仅10家。数值计算正确，表达不完整。
2. **F2：缺失指数静默省略。** 跑马灯显示五个已有指数，没有 5/8 或三项缺失提示。不能由“能显示五个”推断全部指数有效。
3. **F3：ratio 缺失文案过度承诺。** “下次刷新会自动恢复”无法由日期对齐或来源状态保证。应另行批准改为只陈述缺失事实的提示。
4. **F4：列表短历史标题。** 表头仍统一为“60日走势”，54 根样例的长鑫行没有个别不足标识。详情正确不消除列表阅读时的歧义。

这些是现有生产文件的验收发现，不是建议新增业务模块。后续若获准，可仅补真实性文案/覆盖提示并重新验证；本轮没有执行修改。

## 复核与交付边界

```bash
python -B audit/offline-page-acceptance-2026-10-19/make_preview.py
python -B audit/offline-page-acceptance-2026-10-19/check_desktop.py
```

两个脚本不会取行情、触发 Actions 或部署。第二个仅在允许的 loopback HTTP 下渲染，并在结束时关闭服务。像素哈希会受浏览器/字体版本影响；DOM行为及数据断言独立记录。

10 个冻结哈希及生产文件与起点逐字节比较见 `scope-check.json`。这里只新增离线预览、合成测试数据、脚本、报告和真实浏览器截图。没有修改生产布局、财务证据、发布门槛、工作流、默认分支或权限；没有 PR、合并、cron、Actions 或外网部署。交父任务独立审计四项问题及真实数据预览缺口。
