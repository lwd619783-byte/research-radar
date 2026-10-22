"""Exercise production JS display helpers with Node; no browser/network dependency."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[2]

class DisplayCoverageTests(unittest.TestCase):
    def run_js(self, assertions):
        source=(ROOT/'radar/site/app.js').read_text(encoding='utf-8')
        fin=next(line for line in source.splitlines() if line.startswith('const fin='))
        ranking=next(line for line in source.splitlines() if line.startswith('const rankValue='))
        helpers=source.split('/* ---------- display coverage ---------- */',1)[1].split('/* ---------- data ---------- */',1)[0]
        script="const assert=require('node:assert/strict');\n"+fin+'\n'+ranking+'\n'+helpers+'\n'+assertions
        result=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_numeric_zero_remains_an_observation_but_null_is_missing(self):
        self.run_js("""
            const rows=[{v:0},{v:null},{v:2},{v:NaN},{v:Infinity}];
            assert.equal(coverageCount(rows,c=>c.v),2);
            assert.equal(coverageText(rows,c=>c.v),'2/5');
        """)

    def test_empty_and_all_missing_never_claim_full_coverage(self):
        self.run_js("""
            assert.equal(coverageText([],c=>c.v),'0/0');
            assert.equal(coverageText([{v:null},{v:undefined}],c=>c.v),'0/2');
        """)

    def test_partial_rank_values_and_metric_denominators(self):
        self.run_js("""
            const rows=[{financialPartial:true,revg:3,financialRevenueComparable:false},
                        {financialPartial:false,revg:0,financialRevenueComparable:true},
                        {financialPartial:false,revg:null,financialRevenueComparable:true}];
            assert.equal(coverageText(rows,c=>rankValue(c,'revg')),'1/3');
            assert.equal(coverageText(rows,c=>c.financialRevenueComparable?c.revg:null),'1/3');
            assert.equal(rankValue(rows[0],'revg'),null);
            assert.equal(rankValue(rows[1],'revg'),0);
        """)

    def test_index_missing_names_and_coverage_not_silently_complete(self):
        self.run_js("""
            const issues=[{kind:'index',symbol:'A'},{kind:'index',symbol:'B'},
                          {kind:'index',symbol:'A'},{kind:'valuation',symbol:'C'}];
            assert.deepEqual(indexAvailability([{},{}],issues),{missing:['A','B'],label:'指数有效 2/4'});
            assert.equal(indexAvailability([],issues).label,'指数有效 0/2');
            assert.equal(indexAvailability([{}],[]).label,'指数有效 1/1');
            assert.equal(indexAvailability([{}],undefined).label,'指数已提供 1 项 · 覆盖未提供');
        """)

    def test_history_labels_report_only_the_plotted_observations(self):
        self.run_js("""
            assert.equal(sparkHistoryLabel({sc:Array(54).fill(1)}),'实际 54 个交易日 · 短历史');
            assert.equal(sparkHistoryLabel({sc:[]}),'实际 0 个交易日 · 短历史');
            assert.equal(sparkHistoryLabel({sc:Array(800).fill(1)}),'实际 60 个交易日');
        """)

    def test_missing_numeric_values_stay_last_in_both_sort_directions(self):
        self.run_js("""
            const rows=[{v:null},{v:0},{v:-2},{v:7},{v:NaN},{v:''},{v:Infinity},{v:false}];
            const col={v:c=>c.v};
            for(const direction of [-1,1]){
                const sorted=rows.slice().sort((a,b)=>compareRows(a,b,col,direction));
                assert.deepEqual(sorted.slice(0,3).map(c=>c.v),direction===1?[-2,0,7]:[7,0,-2]);
                assert.ok(sorted.slice(3).every(c=>!fin(c.v)));
            }
            assert.equal(coverageText(rows,c=>c.v),'3/8');
        """)

    def test_empty_dates_and_partial_financial_values_sort_last(self):
        self.run_js("""
            const dates=[{v:''},{v:'2026-10-20'},{v:undefined},{v:'2026-10-19'}];
            for(const direction of [-1,1]){
                const sorted=dates.slice().sort((a,b)=>compareRows(a,b,{s:1,v:c=>c.v},direction));
                assert.ok(sorted.slice(0,2).every(c=>c.v));assert.ok(sorted.slice(2).every(c=>!c.v));
                const rows=[{revg:3,financialPartial:true},{revg:0},{revg:-1}];
                assert.equal(rows.sort((a,b)=>compareRows(a,b,{v:c=>rankValue(c,'revg')},direction)).at(-1).financialPartial,true);
            }
        """)

    def test_pe_missing_is_distinct_from_evidenced_loss_and_unknown_cause(self):
        self.run_js("""
            const c={pe:null,provenance:{valuation:{peStatus:'missing'}}};
            assert.equal(peStatusText(c),'暂未取得');
            c.provenance.valuation={peStatus:'not_meaningful',epsTrailingTwelveMonths:-92.96};
            assert.equal(peStatusText(c),'亏损 · 不适用');
            c.provenance.valuation.epsTrailingTwelveMonths=null;
            assert.equal(peStatusText(c),'不适用');
            assert.equal(peStatusText({pe:10}),'');
            assert.equal(peStatusText({pe:null,provenance:{valuation:{peStatus:'invalid'}}}),'来源数值无效');
        """)

    def test_history_reason_uses_observed_count_without_inventing_listing_cause(self):
        self.run_js("""
            const c={sym:'688825.SS',ld:'2026-10-19',r60:null,ytd:null,dd52:null,r20:0,
                history:{count:55,firstDate:'2026-07-27',days:84}};
            for(const k of ['r60','ytd','dd52'])assert.equal(metricGap(c,k),'上市时间不足 · 可用 55 个交易日');
            assert.equal(metricGap(c,'r20'),'');
            assert.equal(metricGap({...c,sym:'OTHER'},'r60'),'历史数据不足 · 可用 55 个交易日');
            assert.equal(metricGap({...c,history:{count:1000,days:1500,firstDate:'2020-01-01'}},'r60'),'暂未取得');
            assert.equal(metricGap({financialPartial:true,revg:1},'revg'),'部分披露 · 不参排');
        """)

    def test_filter_combinations_empty_result_and_effective_sample_denominator(self):
        self.run_js("""
            const rows=[{ind:'A',mkt:'A股',v:0},{ind:'A',mkt:'美股',v:null},{ind:'B',mkt:'韩股',v:2}];
            assert.equal(filterCompanies(rows,'all','all').length,3);
            assert.equal(coverageText(filterCompanies(rows,'A','all'),c=>c.v),'1/2');
            assert.deepEqual(filterCompanies(rows,'A','港股'),[]);
            assert.deepEqual(filterCompanies(rows,'B','其他'),[rows[2]]);
            assert.equal(rows.length,3);
        """)

    def test_summary_counts_are_derived_and_keep_partial_na_missing_separate(self):
        self.run_js(r"""
            const rows=[{status:'complete'},{status:'partial'},{status:'missing'},{status:'not_applicable'},{status:'access_blocked'}];
            assert.deepEqual(dataStateCounts(rows),{complete:1,partial:1,missing:1,not_applicable:1,access_blocked:1});
            assert.match(dataStateLabel(rows),/1\/5 项完整/);assert.match(dataStateLabel(rows),/1 项不适用/);
            assert.equal(dataStateLabel([]),'数据覆盖未提供');
            assert.equal(nativeCapText({mcapLocal:123456789,cur:'KRW'}),'1.23 亿 KRW');
            assert.equal(nativeCapText({mcapLocal:null}),'原币市值暂未取得');
        """)

if __name__=='__main__':unittest.main()
