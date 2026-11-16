"""Generate the Notion maintenance guide from the checked-in property contract."""
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / 'radar/data/notion_schema.json'
GUIDE = ROOT / 'docs/NOTION-CONTRACT.md'

LEVELS = {
    'row': '行内必填', 'judgment': '研判必填', 'evidence': '证据必填',
    'optional': '可空', 'ignore': '仅供 Notion 内查看',
}
TYPES = {
    'title': '标题', 'rich_text': '文本', 'number': '数字', 'select': '单选',
    'relation': '关联', 'date': '日期', 'url': '链接', 'formula': '公式', 'checkbox': '复选框',
}
TABLE_MEANINGS = {
    'industries': '维护各行业的四项评分、逻辑、信号和风险。',
    'chokepoints': '维护行业下的具体瓶颈、紧缺度和跟踪指标。',
    'companies': '维护公司代码、所属行业、快讯和财报日历。',
    'financials': '按公司、财年、期间和口径维护财报及出处。',
    'daily': '按市场维护最近一个已完成交易日的复盘要点。',
    'weekly': '按 ISO 周维护本周主线与研判。',
}
COMMON_FIELDS = {
    '名称': ('用于显示及关联的名称。', 'AI 网络设备'),
    '行业': ('该记录所属的行业。', '关联到「AI 网络设备」'),
    '研判理由': ('支持这条研判的具体依据。', '本期出货量高于上期'),
    '来源': ('支持研判的原文链接，可填多条。', 'https://example.com/report'),
    '研判日期': ('实际形成研判的日期。', '2026-11-09'),
    '有效至': ('研判需要重新核对的最晚日期。', '2026-11-20'),
    '研判状态': ('在 Notion 查看本行的研判状态。', '待更新'),
    '知识库': ('相关研究笔记的页面链接。', 'https://example.com/notes'),
    '停用': ('从本次读取结果排除该记录。', '勾选'),
}
FIELDS = {
    'industries': {
        '景气度': ('行业需求、增长和活跃程度的评分。', '4'),
        '业绩兑现': ('业绩兑现程度的评分。', '3'),
        '卡点强度': ('行业关键瓶颈约束程度的评分。', '5'),
        '估值位置': ('行业估值位置的评分。', '3'),
        '总分': ('景气度、业绩兑现、卡点强度、估值位置的合计。', '15'),
        '一句话逻辑': ('概括目前最主要的行业逻辑。', '高速光互连订单增长'),
        '最新信号': ('逐条记录近期可核对的变化。', '订单增加；交付周期延长'),
        '主要风险': ('记录当前值得跟踪的风险。', '扩产进度存在不确定性'),
        '代表公司': ('列出有代表性的公司名称。', '甲公司、乙公司'),
    },
    'chokepoints': {
        '名称': ('卡点的显示名称。', '光芯片供给'),
        '紧缺度': ('当前供需紧张程度。', '偏紧'),
        '细分': ('瓶颈所在的具体环节或产品。', '高速光芯片'),
        '为什么卡': ('说明供给受限的具体原因。', '现有产能集中'),
        '跟踪指标': ('下一步核对的指标或事件。', '交付周期、财报 {{earnings:NVDA}}'),
        '排序': ('控制同一行业内卡点显示顺序，数字小的在前。', '10'),
    },
    'companies': {
        '名称': ('公司的显示名称。', '英伟达'),
        '代号': ('仓库用于关联和识别公司的固定代号。', 'NVDA'),
        'Yahoo代码': ('用于行情采集的 Yahoo Finance 代码。',
                       'A股 300308.SZ、美股 NVDA、港股 0522.HK、台股 2383.TW、韩股 000660.KS、日股 8035.T、欧股 SU.PA'),
        '显示代码': ('页面上给读者看的证券代码。', 'NVDA'),
        '市场': ('公司证券所属的交易市场。', '美股'),
        '币种': ('行情报价的币种。', 'USD'),
        '定位': ('公司在对应研究环节中的定位。', '全球龙头'),
        '卡点': ('与该公司直接相关的行业卡点。', '关联到「光芯片供给」'),
        '看点': ('目前需要跟踪的公司要点。', '高速产品交付进度'),
        '快讯': ('最近一条已发生的公司事件。', '公司公布本期营收'),
        '快讯日期': ('快讯所述事件的日期。', '2026-11-12'),
        '快讯来源': ('快讯的原始发布链接。', 'https://example.com/news'),
        '下次财报日': ('下一次财报发布的当地日期。', '2026-11-18'),
        '财报日状态': ('标明下次财报日是否由公司正式确认。', '官方确认'),
        '财报日来源': ('支持财报日期的原始公告或 IR 日历。', 'https://example.com/ir/calendar'),
        '财报日时区': ('发行人用于财报安排的当地时区。', 'America/Los_Angeles'),
        '财报日备注': ('记录盘前、盘后等已知安排。', '当地时间盘后'),
    },
    'financials': {
        '记录': ('便于在 Notion 查找记录的标题。', '甲公司 FY2026 Q3 单季'),
        '公司': ('该财报记录所归属的公司。', '关联到「甲公司」'),
        '财年': ('公司报告使用的财年。', 'FY2026'),
        '期间': ('财报覆盖的财季、半年或全年。', 'Q3'),
        '口径': ('用于区分本季数、半年数、累计数或全年数。', '单季'),
        '显示期间': ('页面上给读者看的报告期。', '2026 财年第三季度'),
        '期末日': ('本报告期的最后一天。', '2026-09-30'),
        '发布日': ('报告首次对外发布的日期。', '2026-10-30'),
        '录入日': ('这条记录录入 Notion 的日期。', '2026-10-31'),
        '营收同比%': ('报告期营收较去年同期的变动。', '15.2'),
        '净利同比%': ('报告期净利较去年同期的变动。', '-8.5'),
        '毛利率%': ('报告期毛利占营收的比例。', '45.6'),
        '报告状态': ('披露材料所处的阶段。', '正式报告'),
        '利润可比性': ('说明本期净利与去年同期能否直接比较。', '可比'),
        '推导方式': ('说明数值来自直接披露或累计差额。', '直接披露'),
        '币种': ('财报披露使用的币种。', 'USD'),
        '利润指标': ('净利等利润数值使用的指标名称。', '归属于母公司股东的净利润'),
        '会计准则': ('报告所用的会计准则。', 'IFRS'),
        '营收口径': ('营收指标涵盖的报表范围。', '合并营业收入'),
        '利润口径': ('利润数值的归属范围或调整口径。', '归母净利润'),
        '毛利口径': ('毛利率的报表范围或计算口径。', '合并毛利率'),
        '来源名称': ('主要证据的文件名称或发布方。', '第三季度报告'),
        '来源链接': ('主要披露原文的链接。', 'https://example.com/ir/q3.pdf'),
        '其他来源': ('补充原文或口径核对用的链接。', 'https://example.com/ir/filing'),
        '计算说明': ('记录推导过程或公式。', '前三季累计减上半年累计'),
        '录入说明': ('记录本行录入时的说明。', '数值来自合并损益表'),
        '披露状态': ('补充说明材料实际披露了哪些项目。', '仅披露营收'),
        '注意事项': ('逐行写明使用数据时需要留意的条件。', '合并范围变动（下一行可另写一条）'),
    },
    'daily': {
        '标题': ('便于在 Notion 查找复盘的标题。', '2026-11-12 A股复盘'),
        '日期': ('这条复盘对应的交易日。', '2026-11-12'),
        '市场': ('复盘针对的市场。', 'A股'),
        '一句话': ('用一句话概括该日已发生的市场事实。', '上证指数收盘上涨，通信板块成交活跃'),
        '涉及行业': ('这条要点涉及的行业。', '关联到「AI 网络设备」'),
        '复盘链接': ('对应复盘全文的链接。', 'https://example.com/daily'),
    },
    'weekly': {
        '周次': ('这条主线所对应的 ISO 周次。', '2026-W46'),
        '主线行业': ('该周研判聚焦的行业。', '关联到「AI 网络设备」'),
        '导语': ('概括本周主线及其事实依据。', '高速产品交付加快，本周重点看订单兑现'),
        '日历提示': ('提示本周已知、值得核对的事件。', '周三核对财报披露'),
    },
}


def code(value):
    return f'`{value}`'


def codes(values):
    return '、'.join(map(code, values))


def format_field(table, field, spec, tables):
    rules = []
    kind = spec['type']
    if spec.get('enum'):
        rules.append('选项 ' + '、'.join(code(key) if key == value else f'{code(key)} → {code(value)}'
                                     for key, value in spec['enum'].items()))
    if spec.get('target'):
        rules.append(f'关联「{tables[spec["target"]]["label"]}」')
    if spec.get('limit'):
        rules.append(f'最多 {spec["limit"]} 条关联')
    if kind == 'date':
        rules.append('日期用 `YYYY-MM-DD`')
    if spec.get('regex'):
        rules.append(f'格式 {code(spec["regex"])}')
    if spec.get('regex_by_market'):
        rules.append('按市场使用 ' + '、'.join(f'{market} {code(pattern)}' for market, pattern in spec['regex_by_market'].items()))
    if spec.get('unique'):
        rules.append('值须唯一')
    if spec.get('integer'):
        rules.append('整数')
    if 'min' in spec and 'max' in spec:
        rules.append(f'{spec["min"]} 至 {spec["max"]}')
    elif 'min' in spec:
        rules.append(f'最小值 {spec["min"]}')
    elif 'max' in spec:
        rules.append(f'最大值 {spec["max"]}')
    if spec.get('percent'):
        rules.append('填百分数，例如 15.2 表示 15.2%')
    if 'default' in spec:
        rules.append(f'留空时使用 {code(spec["default"])}')
    if spec.get('soft_len'):
        rules.append(f'建议最多 {spec["soft_len"]} 字')
    if spec.get('hard_len'):
        rules.append(f'超过 {spec["hard_len"]} 字会截断')
    if spec.get('split'):
        split = spec['split']
        rules.append('每行一项' if split == '\n' else f'用「{split}」分隔')
    if spec.get('max_items'):
        rules.append(f'最多保留 {spec["max_items"]} 项')
    if spec.get('item_hard_len'):
        rules.append(f'每项按契约控制在 {spec["item_hard_len"]} 字内，当前程序仅按条数截断')
    if spec.get('scheme'):
        rules.append(f'使用 {code(spec["scheme"] + "://")} 链接')
    if spec.get('urls'):
        count = spec['urls']['min']
        rules.append(f'至少 {count} 条 HTTP(S) 链接' if count else '可填 HTTP(S) 链接')
    if spec.get('tokens'):
        rules.append('可用 `{{earnings:代号}}`')
    if spec.get('iana_tz'):
        rules.append('IANA 时区名')
    if spec.get('banned'):
        rules.append('检查禁用词')
    if spec.get('banned_prediction'):
        rules.append('检查预测词')
    if spec.get('result'):
        rules.append(f'公式返回 {code(spec["result"])}')
    if (table, field) == ('companies', '下次财报日'):
        rules.append('留空显示待定。早于发行人当地当天时保留日期并提示 `earnings_date_past`')
    elif spec.get('rule'):
        rules.append(spec['rule'])
    if spec.get('note') and not spec.get('tokens') and not spec.get('item_hard_len'):
        rules.append(spec['note'])
    return '；'.join(rules) or '—'


def markdown_row(values):
    return '| ' + ' | '.join(value.replace('|', r'\|') for value in values) + ' |'


def render_guide(schema):
    lines = [
        '<!-- 由 radar/tools/generate_notion_contract.py 从 radar/data/notion_schema.json 生成。 -->',
        '# Notion 数据维护手册', '',
        f'契约版本 {code(schema["contract_version"])}。Notion API 版本 {code(schema["notion_version"])}。',
        f'表中的 `today` 以构建时钟换算到 {code(schema["timezone"])} 后的日期为准。', '',
        '## 属性和必填规则', '',
        '保留表中的属性名称与类型。只有标为「仅供 Notion 内查看」的属性可以从数据库结构中省略。',
        '「可空」指单元格可留空。关系字段通过 Notion 选择对应行，链接字段填写完整链接。', '',
    ]
    for level, explanation in schema['levels'].items():
        lines.append(f'- **{LEVELS[level]}** {explanation}')
    lines.extend(['', '读取器按属性名核对数据库结构。缺少非忽略列或属性类型改变时，整表回退到上次成功快照，'
                  '并记录 `notion_schema_changed`。没有可用快照时停止构建。额外添加的属性会被忽略。',
                  '新增单选选项只在被填入行后校验。行内必填列使用未定义选项时隔离该行，可空列会清空并记录 `invalid_enum`。', '',
                  '行业、卡点、公司、每周主线的重复键保留创建较早的行，创建时间相同则保留页面 ID 较小的行。',
                  '财报重复键优先保留录入日较晚的行，其次按最后编辑时间较晚、页面 ID 较小排序。',
                  '每日要点重复键按最后编辑时间较晚、页面 ID 较小排序。',
                  '逐行校验失败时，行业、卡点、公司和财报可沿用上次成功快照中的同一页面。每日和每周的无效行直接跳过。', ''])
    tables = schema['tables']
    for table_name, table in tables.items():
        lines.extend([f'## {table["label"]}', '', TABLE_MEANINGS[table_name], '', f'行键为 {code(table["key"])}。'])
        if table.get('order'):
            lines.append(f'显示顺序为 {table["order"]}。')
        if table.get('cap'):
            lines.append(f'最多显示 {table["cap"]} 家公司。')
        lines.extend(['', '| 属性 | 类型 | 必填 | 用途 | 填写格式 | 示例 |',
                      '| --- | --- | --- | --- | --- | --- |'])
        for field, spec in table['properties'].items():
            meaning, example = (FIELDS[table_name].get(field) or COMMON_FIELDS[field])
            kind = spec['type']
            lines.append(markdown_row([field, f'{TYPES[kind]} {code(kind)}', LEVELS[spec['level']], meaning,
                                       format_field(table_name, field, spec, tables), code(example)]))
        lines.append('')
    lines.extend(['## 研判和来源', '',
                  '行业、卡点和每周主线需满足以下条件才会标为 AI 研判。', ''])
    lines.extend(f'- {rule}' for rule in schema['judgment_rule']['ai_when_all'])
    lines.extend(['', '每周主线还需对应当前 ISO 周。每日要点需对应各市场最近一个已完成交易日。',
                  '在研判「来源」里优先填写可直接访问的公开原文链接。若已有公开 HTTPS 原文，'
                  '系统可解析被 Notion 显示为独立 `Untitled` 占位符的有效页面或数据库提及，作为补充链接。'
                  '单独填写这种占位符仍会显示来源缺失。',
                  '财报记录的「其他来源」用于补充。「来源链接」为空时，该记录仍属缺来源。', '',
                  '## 文本规则', '',
                  '- 文本直接拼接各片段的纯文本，再去掉首尾空白。长度按 Unicode 码位计。',
                  '- 来源文本提取 HTTP(S) 链接，去重并保留顺序，公开链接优先显示。',
                  '- 超过建议长度时提示 `text_long`。超过上限时截断，末尾补 `…`，并提示 `text_truncated`。',
                  '- 每个 `{{earnings:代号}}` 按 10 个字计，截断落在占位符内时整段移除。'
                  '代号不存在或停用时提示 `token_unknown_company`，页面显示「日期待定」。', '',
                  '### 禁用词', '', codes(schema['banned_words']), '',
                  '标记「检查禁用词」的字段会先做 Unicode NFKC 规范化并去掉空白，再查找子串。'
                  '命中时清空字段并记录 `banned_words`。研判增加待更新原因，每日和每周的对应行跳过。', '',
                  '### 预测词', '', f'适用字段为 **{schema["prediction_words"]["applies_to"]}**。'
                  '匹配方式与禁用词相同。', '', codes(schema['prediction_words']['words']), '',
                  '命中时跳过整行并提示 `prediction_words`，该市场改用自动生成句。', '',
                  '## 财报日默认时区', '', '| 市场 | 默认时区 |', '| --- | --- |'])
    lines.extend(markdown_row([market, code(timezone)]) for market, timezone in schema['market_timezones'].items())
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check the guide without writing files')
    args = parser.parse_args()
    expected = render_guide(json.loads(SCHEMA.read_text(encoding='utf-8')))
    if args.check:
        if not GUIDE.exists() or GUIDE.read_text(encoding='utf-8') != expected:
            parser.exit(1, 'docs/NOTION-CONTRACT.md is out of date. Run python -B radar/tools/generate_notion_contract.py\n')
    else:
        GUIDE.write_text(expected, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
