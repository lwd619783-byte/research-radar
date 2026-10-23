# 交易所日历与行情新鲜度

2026-10-23 核对；静态数据为 `radar/data/market_calendar.json`，覆盖 2026-01-01 至 2027-12-31。运行时只依赖 Python 标准库，不安装 pandas 或 exchange_calendars。

## 放行口径

生产 Notion 构建和真实 `production_collect → acceptance_probe → assemble` 强制启用交易所日历。历史 V2/Common snapshot 接口保留原行为，既有 fixtures 和期望值不变。`assemble_notion` 也显式启用；调用方不能靠缺少参数关闭真实生产路径。

- 按证券具体交易所、当地时区、正式收盘时刻和半日市计算“最近应完成交易日”；不使用统一的四个自然日容忍度。德股 Xetra 和法国 Euronext Paris 分开。
- `completed_bars` 原有 provider session / timestamp 证据仍须通过。日历仅检查日期，不能把未知或盘中 bar 升格为收盘。
- 完成日必须精确匹配。缺少一个应完成交易日也会拦截；禁止用未来交易日或休市日伪造行情。
- 抓取收据仍须在 36 小时内，缓存身份、离线、来源、币种、最终性约束继续生效。合法长假不等于允许数据源中断。
- 实时行情可单独保留有效当天 `intraday` / `unknown`，不改变指标完成日，也不把 phase 改成 `closed`。未知 phase 的指数继续为 partial。
- FX 保留原来的真实日线、准确估值日期与明确估算上限，不能拿某股票交易所假日替代全球 FX 日期。

只有已取得真实完成行情、且完成日等于应完成日，才给假期沿用标签。标签描述日线指标，当前市场可能已重新开盘；盘中价格仍显示自己的 phase。

## 来源及确认程度

| 交易所 | 2026 | 2027 | 来源 |
|---|---|---|---|
| XSHG / XSHE | official | provisional | [上交所休市安排](https://www.sse.com.cn/disclosure/dealinstruc/closed/)、[深交所日历](https://investor.szse.cn/English/services/trading/calendar/index.html) |
| XHKG | official | official | [HKEX 日历](https://www.hkex.com.hk/News/HKEX-Calendar?sc_lang=en)、[交易及收市竞价时间](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market) |
| XTKS | official | official | [JPX 年度日历](https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html)、[15:30 收市](https://www.jpx.co.jp/equities/trading/domestic/01.html) |
| XKRX | official | official | [KRX 休市及交易规则](https://global.krx.co.kr/contents/GLB/06/0602/0602020204/GLB0602020204T1.jsp)、[2026 月历要项](https://www.kasi.re.kr/kor/post/newsMaterial/32031)、[KASA 2027 月历要项](https://www.kasa.go.kr/prog/plcyBrf/brief/kor/sub01_01_04/view.do?plcyBrfNo=431) |
| XTAI | official | provisional | [TWSE 年度安排](https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=html)、固定版本 XTAI 规则估计 |
| XETR | official | official | [德交所现金市场日历及时间](https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours) |
| XPAR | official | rule_based | [Euronext 年度日历](https://www.euronext.com/en/trading/trading-hours-holidays)、固定版本 XPAR 规则展开 |
| XNYS | official | official | [NYSE 2026–2028 日历及半日市](https://www.nyse.com/trade/hours-calendars) |
| XNAS | official | rule_based | [Nasdaq 2026 日历](https://www.nasdaqtrader.com/Trader.aspx?id=Calendar)、固定版本 XNAS→XNYS 规则展开 |

`rule_based` 来自实际运行 `exchange_calendars==4.13.2` 导出的静态日期；不是官方年度公告。包 SHA256 为 `fc5a2ad0d61b5c3a6539a3061cd4cbb55c59f4a903455cec7926e4b798919996`，包版本和摘要也保存在 JSON。对应源文件：[XPAR](https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/exchange_calendar_xpar.py)、[XNAS 别名](https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/calendar_utils.py)、[XTAI](https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/exchange_calendar_xtai.py)。2026 官方日期优先核对；不引用 Oslo 专属表证明 Paris 日期。

KRX 官方规则包含政府公休日、劳动节及年末最后工作日，配合 KASA 正式月历推导。2027 韩国春节为 2 月 7 日，假期为 2 月 6–9 日；不能直接复制中国农历春节安排。

## 尚未官宣的 2027 安排

用户明确允许春节按惯例估计并保留待核提示。A 股估计窗口为 02/05–02/12（[香港天文台 2027 公农历](https://www.hko.gov.hk/en/gts/time/calendar/pdf/files/2027e.pdf)的除夕与初一、除夕起 8 天的近年惯例），其他估计日期逐条存于 `provisionalHolidays`。这些都不是正式交易所公告，不保证调休长度。台湾使用上述固定版本规则估计，春节额外结算休市日仍待交易所正式表。

`provisional` 是显式估计，不能显示成 official：即使日期精确匹配而放行，必须展示 `休市·沿用 MM/DD 收盘（待官方确认）` 及对应警告。超出所列假日窗口的旧行情仍会拦截。完全未知的交易所、过期覆盖范围不放行。

2026-12-20 前复核 A 股和台湾正式公告，用来源明确的日期替换估计并调整确认程度。此期限是维护要求，不是把估计自动转换成官方的触发器。新增突发休市也须更新表，不自动猜测。日历有效范围到期前 60 天自动提醒；2027 尚待确认安排在进入该年或进入其前 60 天时提示。2028 不会自动继续推算。

## 输出接口

公司及指数新增 `marketCalendar`：`exchange`、`timezone`、`expectedCompletedDate`、`quoteDate`、`status`、`confidence`、`validThrough`、`label`、`warnings`、`sources`。

`status` 为 `holiday_carry / current / stale / unconfirmed`；`confidence` 为 `official / rule_based / provisional / unconfirmed / unavailable`。`warnings` 是 `string[]`。公司标签依照已完成指标日，不能覆盖 `pricePhase`。`meta.marketCalendar` 给出有效截止日期、60 天提醒阈值、汇总警告及各交易所判定。

## 固定时钟验证与任务日期差异

运行 `python -B -m unittest discover -s radar/tests -p test_market_calendar.py -v`。

- 2026-12-28 北京 08:45、12:15、18:15，Xetra 最近应完成日都是 12/23，五天前真实收盘可沿用。
- 2027-01-04 北京 06:50、08:45、12:15，日本、韩国、Xetra 仍以 12/30 为最近完成日；**18:15 日本和韩国已完成 1/4 交易，必须使用 1/4**，这两项不显示休市标签，12/30 会被拦截。Xetra 仍未完成 1/4，继续沿用 12/30。按事实处理，不为满足“全部休市”文字假设伪造收盘或延长假期。
- 2027-02-09 的四槽覆盖 22 家 A 股、台光电、SK 海力士。A/台使用明确标记的估计，韩股使用正式规则。
- 2027-03-26、03-29 的三槽覆盖 Xetra、Paris、ASMPT、KBL。
- 额外测试：少一个真实交易日、旧收据、非休市中断、假日伪造 bar、盘中/未知 phase、半日市/夏令时、未知交易所、2028 过期、提醒边界；真实默认 collector 强制开启策略。比值的当日共同观察仍可盘中展示，继续 partial 和“未证明同时观察”，不能升格为收盘。

以上为离线合成市场证据测试，不代表将来真实数据已取到或已发布。

## financialPartial 实情

`financialPartial` 在 V3 `render_v3.py` 高增统计中仍被使用，`test_render_v3.py` 及 `test_partial_financial.py` 也验证它；用户要求“先确认无用才清理”的条件尚未成立。因此本轮保留 `PARTIAL_DISCLOSURES` 与相关哈希锁、字段和原测试期望，不以清理名义解除真实性约束。
