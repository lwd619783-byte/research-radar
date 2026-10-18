"""Apply only the two explicitly approved and recalculated partial disclosures."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
proof=json.loads((HERE/'public-evidence.json').read_text())
urls={r['id']:r['url'] for r in proof['reports']}
common=dict(verified_at='2026-10-18',fiscal_year='FY2026',profit_metric='net_income_attributable_to_parent',
 revenue_scope='合并营业收入',profit_scope='合并归母净利润',conditions_reviewed=True,profit_comparison='comparable',
 review_note='2026-10-18 正常读取指定官方原文、复核金额与单位并计算；公共摘录、来源哈希及计算见 audit/partial-financial-2026-10-18/public-evidence.json。仅限本期已批准部分披露。')
rows={
 'KBL':dict(common,period='2026H1累计',**proof['values']['KBL'],source_name='Kingboard Laminates 2026 Interim Results / Interim Report',
 source_url=urls['KBL-results'],source_urls=[urls['KBL-results'],urls['KBL-interim']],period_end='2026-06-30',published_at='2026-08-24',
 basis='half_year',currency='HKD',accounting_basis='HKFRS',fiscal_period='H1',margin_scope='半年合并毛利 / 半年营业收入',report_status='final',derivation='reported',
 calculation_note='单位千港元；收入14903809/9588032-1；归母2886561/933317-1；毛利率(14903809-10323576)/14903809。均为H1累计。',
 disclosure_state='reviewed_h1_cumulative',conditions=['2026H1半年累计，不是单季；排除完整评分和普通增长排名。','收入及归母净利同比；毛利率=(收入−销售成本)/收入，原表单位千港元。','首次业绩公告2026-08-24；完整中报2026-09-18来源金额相符；中期数字未经审计。']),
 'DZSK':dict(common,period='2026Q3初步推算',**proof['values']['DZSK'],source_name='大族数控2026年前三季度业绩快报、2026半年度报告及2025第三季度报告',
 source_url=urls['DZSK-9M-preliminary'],source_urls=[urls['DZSK-9M-preliminary'],urls['DZSK-H1'],urls['DZSK-2025Q3']],
 period_end='2026-09-30',published_at='2026-10-15',basis='single_quarter',currency='CNY',accounting_basis='PRC_ASBE',fiscal_period='Q3',
 margin_scope='未披露Q3营业成本，毛利率不可计算',report_status='preliminary',derivation='cumulative_difference',
 calculation_note='9M快报万元先乘10000：收入784094.79×10000-4984920813.21=2856027086.79元；归母154412.46×10000-956862424.74=587262175.26元。分别对2025Q3单季1520984069.00元、228435144.32元计算同比；毛利null。',
 disclosure_state='reviewed_q3_preliminary',conditions=['2026Q3初步推算（9M快报−H1），不是正式季报；快报未经审计，最终值可能调整。','9M快报以万元披露，先统一为元再减H1；同比基数使用2025Q3报告的单季值。','未披露本期营业成本，毛利必须留空；不搬入H1毛利、不填零。','仅展示这两项初步同比；排除完整评分和普通增长排名。'])}
def value(v):
 if isinstance(v,bool):return str(v).lower()
 return json.dumps(v,ensure_ascii=False)
file=ROOT/'radar/data/companies.toml';lines=file.read_text().splitlines();cid=None
for i,line in enumerate(lines):
 if line.startswith('id = '):cid=json.loads(line.split('=',1)[1].strip())
 if line.startswith('fin = ') and cid in rows:
  lines[i]='fin = { '+', '.join(k+' = '+value(v) for k,v in rows[cid].items() if v is not None)+' }'
file.write_text('\n'.join(lines)+'\n')
print('Updated only KBL.fin and DZSK.fin; DZSK gross_margin omitted/null.')
