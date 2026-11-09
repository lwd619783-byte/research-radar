# 2383.TW 独立官方收盘证明

产品负责人于2026-10-27明确授权的窄范围补充。仅为2383.TW新增一种独立收盘证明，原Yahoo行情及收益算法、其他股票/汇率的provider证明、旧测试和发布门槛不变。

## 来源与接入

只在真实有界采集流程中、2383.TW原Yahoo日线为unknown且日期等于官方日历要求的已完成交易日时尝试。仅请求`https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY`，参数固定为stockNo=2383、response=json及所需日期。默认TLS验证、禁止重定向、HTTP拒绝停止、原超时与240次总请求预算保持；新增一次请求仅可沿用原有一次429重试。

## 必须同时成立

1. TWSE返回HTTP200、stat=OK、正确年月和2383台光電标题、完整且无重复字段/日期的月日表；所需民国日期行唯一、没有未评审的公司行动注记。日期必须是台湾当地当天且为XTAI官方日历要求的真实交易日，仅支持13:30正常收盘；原provider跨日证明规则保持。
2. 标的仅2383.TW，经过批准的映射为XTAI/TWD；Yahoo响应标的、币种和Asia/Taipei时区一致。TWSE日表没有独立currency字段，不声称从其响应中读出了币种。
3. Yahoo原始收盘价、最新复权价与TWSE收盘价用Decimal精确相等，当日最高价也与TWSE相等；不引入价格或时间容差。
4. 原记录仍保留schema、priceBasis、returnBasis、bars、phase、barTimestamps、finality及receivedAt。仅支持元数据齐全、收盘后日线timestamp晚于provider end但不晚于真实HTTP receipt的窄情形。两来源receipt都必须在实际收盘后、不在未来且不超过原36小时时效。
5. 证明绑定本次GITHUB_SHA/RUN_ID/ATTEMPT=1、两份响应摘要及原Yahoo规范记录摘要。原HTTP文本和headers只留在进程内，不扩展已有安全附件出口；摘要不是数字签名，来源可信性来自本次受控HTTPS采集，不能通过外部JSON或verified布尔导入证明。

任何条件缺失或失败均保留原unknown及阻断；不使用历史官方缓存、手填价格或移动receipt来替代。

## 选择与发布

股票记录级判定保留原provider规则，并在严格验证独立证明后允许该日派生选择结果为closed；原sourcePhase=unknown仍留在provenance。原fx_bar_final与equity_bar_final不改，无独立证明的+15秒记录仍拒绝。10/23、10/26已核实的休市伪bar过滤不变。

收益和历史曲线继续使用同一Yahoo原序列；不把TWSE原始价拼接进复权序列，不宣称官方已认证整段复权历史。报价先后顺序判定不改，独立证明不足以升级另一个新报价时保留经证明的日收盘。

安全proof摘要只在实际使用时添加到DATA的daily provenance、receipt及release manifest；Python bundle/发布复核和Node均检查摘要、执行身份、日期、价格及三者一致性。不存在proof的旧产物不增加字段，文件白名单、附件体积和秘密扫描规则不变。

## 验收边界

旧测试/fixtures/cases/schema不改。新增测试包括充分独立证明成功、无证明仍拒绝、错误标的/日期/币种/价格/最高价/复权价、盘前/过期/未来receipt、跨运行/篡改/布尔冒充、严格HTTPS路由与重定向/拒绝、原输入/收益不变、休市过滤及Python/Node绑定。

最终SHA必须完成全量CI和完整只读真实演练；不能用离线合成数据代替。PR5保持Draft，原五交易日、延迟样本、新鲜真实ready及后续发布验收门槛保留；本功能不授权提前合并、生产dispatch、关闭登录保护或移除缺失/待核标记。
