# 验收产物保存：离线通过，未取新行情、未执行 Actions

授权：用户批准保存环节并要求只读调查走势偏平，消息 `Sentinel_744543fb8634819183bb77331c218b6b`，回复 `Sentinel_bfc4cd543a448191a43e8c4db4badf5d`，2026-10-19 北京时间 11:45。沿用 gpt-6-astra / high 偏好，接受无法独立核验后端实际受理配置的限制，未更改设置。

私有仓库 `lwd619783-byte/research-radar`，分支 `fix/radar-truthfulness-2026-10-18`。本地及正常 fetch 后均核实起点 `d73747d1d18b0e8845ac68e8bcf1e4abcd5e3641`，工作区干净。没有新建分支、main 或改变默认分支。本轮网络仅用于正常 Git 读取及推送；无市场或财务来源请求、Actions、部署、cron、合并、PR、权限、凭据及账单设置变化。

## 走势偏平调查先行结论

[完整只读调查](CHART-INVESTIGATION.md)和[量化证据](chart-investigation.json)：41 家离线价格来自线性趋势加正弦波，长鑫复用旧公开样例。当前及仓库最早候选基线都用原始收盘价折线，不是蜡烛 K 线。小图函数和详情取区间/坐标/路径代码与 `22d9601eb4879f02ca8278aa27841ce9e604a845` 相同，没有曲线平滑、没有增加采样稀疏化。源杰近60点合成/旧样本方向变化为4/30，LITE为3/30，长鑫54点均29。用户“第一版”的具体页面与 DATA 尚未定位，不冒称根提交就是该版本；也不能排除历史高点口径变化对详情 Y 轴范围的影响。本轮图表、价格算法、样例输入全部未改。

## 同次执行的数据如何保存

1. 保留原 `collect(data,budget,market_sink=None)` 位置参数和四项返回值，新增仅关键字 `snapshot_sink` 与测试注入用的 `snapshot_clock`。本保存路径不使用 `market_sink` 重新组装页面。
2. 所有来源结果收齐后，只读取一次快照时钟，传给唯一一次 `build.assemble(data,mk,mk,fixed_clock)`。之所以在采集后固定，是因为原新鲜度规则不接受 `receivedAt` 晚于检查时钟。请求开始、收讫、结束时间仍保留实际时间，不伪造为固定时间。
3. `release_blockers` 检查该 D；同一固定时钟也用于财务状态计数，消除原先 `date.today()` 的时区/跨日差异。生成该 D 的 canonical JSON SHA256，并把 D 的原对象、时钟、门禁结果传回入口；没有第二次组装、没有重新采集。
4. 新的 `acceptance_bundle.py` 对 D 与 receipt 递归检查后，使用既有 `build.render(D, ...)` 渲染。DATA 全量保留现有公司历史 `s0/sd/sc`、指标、真实已组装指数/FX、issues/blockers、财务状态及来源证明；不保存 market sink、原 HTTP 文档、认证会话或缓存。JSON 与 HTML 内嵌 D 必须完全相等，D 的 digest、日期、snapshot、blockers、生成时间、执行身份必须绑定一致。
5. 归档器不删除字段来掩盖问题：敏感键、凭据形状值、含认证参数/用户口令的 URL、非有限数值等导致失败。cookie/crumb 只允许既有布尔可用性诊断。异常只输出固定错误码，不带拒绝值。现有财务公开来源 URL 和证明字段原样保留；没有读取知识库正文或新增私人研究。
6. 所有检查通过后，将四个白名单文件整体原子放入新目录；现存目录、符号链接、额外文件、篡改、超限或不一致均失败，不截断、不覆盖现有归档。渲染临时目录中的 robots/vercel 辅助文件不进入归档。没有生产缓存、fingerprint 或发布产物路径写入。

HTML 额外套用仅验收归档的固定“未发布”提示、blocker 数量和禁止外连的 CSP。离线样例另有醒目 `OFFLINE TEST DATA — NOT NEW REAL MARKET DATA` 提示。生产 HTML/CSS/JS 未改；生成 HTML 或成功上传只证明诊断归档完成，不是发布批准，非空 blockers 原样保留。

## 文件、限制与 manifest

白名单严格为 `DATA.json`、`index.html`、`receipt.json`、`manifest.json`。四个未压缩文件字节总数（含 manifest）硬上限 **10,000,000 bytes**；receipt 保留原 **512 KiB** 独立上限。写前和上传前都校验。

manifest 绑定执行完整 SHA、run ID、attempt、固定时钟、选定日期、blockers、数据分类、未授权发布状态、7天保留期、各载荷文件大小/SHA256及含自身的总大小。manifest 不可能包含自己的哈希；完成日志在 manifest 外记录全部四个文件各自大小/SHA256，便于独立核验。线下示例 run ID `0` 明确代表离线测试，不冒充 Actions run。

仅调整现有手动 workflow 的归档目的部分：[单列差异](workflow.diff)。增加上传前的 `--verify-bundle`；上传改为四条精确文件路径，并要求 probe 与 archive verify 均成功。保留7天、官方 action SHA、压缩设置；触发、分支/SHA/attempt/费用授权门禁、runner、超时、取数步骤与 240 次请求上限均逐项比较未变。两个发布工作流仍禁用。未 dispatch 或启用任何工作流。

冻结清单只更新 `.github/workflows/radar-interface-acceptance.yml`：

- 旧：`4acc5639340665b4ed4d2e4d8035677c1d8c2df1c82a7fe6ad82079937c4e34b`
- 新：`168635dd28f16fbbc1c5e4c174aaaf991a3b3aa3c4b21d90f605871f8d11a572`

其他9个冻结文件保持原哈希，包括前端三文件、四个 TOML 和禁用工作流。[冻结记录](frozen-update.json)。`build.py`、`quotes.py`、`snapshot.py`、`integrity.py`、财务证据和发布门禁全部未改。

## 实际离线验证与复现

完整 suite **140 项全部通过**（原127项＋13项保存测试），[完整日志](offline-tests.log)、[起止时间/退出码](offline-test-receipt.json)。10个冻结哈希匹配，schema 0错误/17既有警告，`git diff --check` 通过。

新增测试覆盖完整 DATA/内嵌 D 一致、重新渲染字节一致、证据保留、固定时钟、同对象门禁、只采集一次和组装一次、无 socket、非空 blockers、敏感键和值、NaN、manifest 身份/目的篡改、额外文件/符号链接/已有目录、总量含 manifest、真实超过10MB、receipt 超限与失败不留部分目录。入口集成测试使用实际 main/collect/assemble/save，只把全部来源适配器替换为明确的合成失败，保存了131项诊断并保留 blocker；请求计数0，不是实测市场连通。

首轮12项专项测试有1个边界测试断言失败：测试降低字节阈值时 manifest 自身的阈值数字也缩短，导致“旧总量减1”仍可容纳，不能据此判定实现越界。随后测试改为只容纳三个载荷、排除 manifest 空间，严格证明 manifest 也计入上限；真实10MB超限测试保持独立。失败日志留在 `initial-targeted-tests.log`。139项中间结果后，又增加 manifest 目的/额外字段校验，最终重跑140项通过，没有把中间结果当最终结果。

离线完整保存示例由 `offline_archive_demo.py` 复用上一阶段标明合成/旧样本的 D，在临时目录实际写入四文件、读取校验并重新渲染，随后删除临时包；仅保留[四文件哈希与大小回执](offline-demo-receipt.json)，避免把新完整 DATA 归档长期写入 Git。真实未来运行的归档由 GitHub artifact 的7天保留期管理，本轮没有上传真实产物。

```bash
python -B -m unittest discover -s radar/tests -v
python -B audit/bundle-preservation-2026-10-19/offline_archive_demo.py
# 将未来正常取得的完整包放在本地，在 manifest 对应执行 SHA 的代码下验证：
python -B radar/scripts/acceptance_probe.py --verify-bundle /path/to/archive
```

上述命令不请求行情、不 dispatch、不部署。离线示例每次会记录实际本地执行 SHA，run ID 0 与测试分类保持明确。

## 下一步条件

本轮只证明保存链路可用，**尚无新一次真实完整 DATA、HTML 或页面验收结果**。父任务独立审计本提交、冻结差异及离线证据后，仍须用户另行批准一次有界正常真实取数/手动验收执行（含当时可用网络、费用和执行SHA门禁核验）。该次执行必须一次保存四文件及完整哈希日志；随后正常取得包、核对 run/attempt/SHA/时钟/日期/哈希，再以实际 D 做桌面页面验收。明确拒绝的访问路径继续停止；不得以缺包为由擅自再取数或再 dispatch。发布仍需独立验收批准。
