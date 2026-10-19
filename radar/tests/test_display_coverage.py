"""Exercise production JS display helpers with Node; no browser/network dependency."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[2]

class DisplayCoverageTests(unittest.TestCase):
    def run_js(self, assertions):
        source=(ROOT/'radar/site/app.js').read_text()
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
            assert.equal(indexAvailability([{}],undefined).label,'指数已提供 1 项 · 覆盖待核');
        """)

    def test_history_labels_report_only_the_plotted_observations(self):
        self.run_js("""
            assert.equal(sparkHistoryLabel({sc:Array(54).fill(1)}),'实际 54 个交易日 · 短历史');
            assert.equal(sparkHistoryLabel({sc:[]}),'实际 0 个交易日 · 短历史');
            assert.equal(sparkHistoryLabel({sc:Array(800).fill(1)}),'实际 60 个交易日');
        """)

if __name__=='__main__':unittest.main()
