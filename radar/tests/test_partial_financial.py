"""Two reviewed partial disclosures; failures stay blocked even with --force."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_integrity import NOW, build
import test_review_regressions as regressions
import integrity

class PartialFinancialTests(unittest.TestCase):
    def rows(self):
        data,mk=regressions.complete_dataset()
        return data,mk,{c['id']:c for c in data['companies']}

    def assert_blocked(self, mutate):
        for force in (False,True):
            with self.subTest(force=force),tempfile.TemporaryDirectory() as td:
                data,mk,rows=self.rows();mutate(data,mk,rows)
                code,report,output=regressions.CompleteMainTests.run_main(self,data,mk,Path(td),force)
                self.assertEqual(code,3)
                self.assertIn('financial_evidence_incomplete',report['blockers'])
                self.assertEqual(output['changed'],'false')
                self.assertFalse((Path(td)/'out').exists())

    def test_approved_partial_disclosures_build_and_display_without_scoring(self):
        for force in (False,True):
            with self.subTest(force=force),tempfile.TemporaryDirectory() as td:
                data,mk,_=self.rows()
                code,report,output=regressions.CompleteMainTests.run_main(self,data,mk,Path(td),force)
                self.assertEqual(code,0);self.assertEqual(report['blockers'],[])
                self.assertTrue((Path(td)/'out/index.html').exists())
                rows={c['id']:c for c in report['data']['companies']}
                for cid in ('KBL','DZSK'):
                    c=rows[cid]
                    self.assertEqual(c['provenance']['financial']['status'],'verified_partial')
                    self.assertTrue(c['financialPartial'])
                    self.assertFalse(c['financialSignalEligible']);self.assertFalse(c['financialRevenueComparable'])
                self.assertEqual(rows['KBL']['revg'],55.441795/100)
                self.assertEqual(rows['KBL']['earng'],209.279805/100)
                self.assertEqual(rows['KBL']['gm'],30.731963/100)
                self.assertEqual(rows['DZSK']['revg'],87.774951/100)
                self.assertEqual(rows['DZSK']['earng'],157.080484/100)
                self.assertIsNone(rows['DZSK']['gm'])

    def test_other_company_missing_source_is_not_waived(self):
        self.assert_blocked(lambda d,m,r:r['YJKJ'].update(financial={}))

    def test_partial_marker_without_sources_or_review_does_not_waive_gate(self):
        for cid in ('KBL','DZSK'):
            for change in ({'source_url':''},{'source_urls':[]},{'conditions_reviewed':False}):
                with self.subTest(cid=cid,change=change):
                    self.assert_blocked(lambda d,m,r:r[cid]['financial'].update(change))
        self.assert_blocked(lambda d,m,r:r['YJKJ']['financial'].update(disclosure_state='arbitrary_missing_metrics'))

    def test_unknown_partial_source_or_company_is_blocked(self):
        self.assert_blocked(lambda d,m,r:r['KBL']['financial'].update(source_url='https://example.test/unknown',source_urls=['https://example.test/unknown']))
        self.assert_blocked(lambda d,m,r:r['KBL'].update(id='UNKNOWN'))
        self.assert_blocked(lambda d,m,r:r['KBL'].update(sym='UNKNOWN.HK'))
        self.assert_blocked(lambda d,m,r:r['YJKJ']['financial'].update(**copy.deepcopy(r['KBL']['financial'])))

    def test_future_and_stale_partial_dates_still_fail_base_gate(self):
        for cid in ('KBL','DZSK'):
            with self.subTest(cid=cid):
                data,mk,rows=self.rows();fin=rows[cid]['financial']
                fin['verified_at']=(NOW.date()+dt.timedelta(days=1)).isoformat()
                self.assertEqual(integrity.financial_status(fin,NOW.date(),rows[cid]),'invalid_dates')
                self.assert_blocked(lambda d,m,r:r[cid]['financial'].update(verified_at=fin['verified_at']))
                dates={'period_end':'2025-12-31','published_at':'2026-01-15','verified_at':'2026-02-01'}
                fin.update(dates)
                self.assertEqual(integrity.financial_status(fin,NOW.date(),rows[cid]),'stale')
                self.assert_blocked(lambda d,m,r:r[cid]['financial'].update(dates))

    def test_fabricated_complete_or_changed_partial_metrics_are_blocked(self):
        self.assert_blocked(lambda d,m,r:r['DZSK'].update(gm=.30))
        self.assert_blocked(lambda d,m,r:r['KBL'].update(earng=9.99))
        self.assert_blocked(lambda d,m,r:r['DZSK']['financial'].update(report_status='final'))
        self.assert_blocked(lambda d,m,r:r['KBL']['financial'].update(basis='single_quarter'))
        self.assert_blocked(lambda d,m,r:r['DZSK']['financial'].update(disclosure_state=''))
        self.assert_blocked(lambda d,m,r:r['KBL'].update(period='2026Q2'))

    def test_missing_or_tampered_public_evidence_still_blocks(self):
        for failure in ('missing','tampered'):
            with self.subTest(failure=failure):
                if failure=='missing':mock=patch.object(integrity.Path,'read_bytes',side_effect=FileNotFoundError())
                else:mock=patch.object(integrity.Path,'read_bytes',return_value=b'tampered public evidence')
                with mock:
                    data,mk,rows=self.rows()
                    self.assertEqual(integrity.financial_status(rows['KBL']['financial'],NOW.date(),rows['KBL']),'partial_evidence_missing_or_tampered')
                    self.assert_blocked(lambda d,m,r:None)

    def test_force_does_not_bypass_other_market_gates(self):
        for mutate,blocker in (
            (lambda d,m:m.update(offline=True),'offline_not_publishable'),
            (lambda d,m:m['daily'][d['companies'][0]['sym']].update(phase='unknown'),'unconfirmed_close_or_intraday_needs_label_approval')):
            with self.subTest(blocker=blocker),tempfile.TemporaryDirectory() as td:
                data,mk,_=self.rows();mutate(data,mk)
                code,report,output=regressions.CompleteMainTests.run_main(self,data,mk,Path(td),True)
                self.assertEqual(code,3);self.assertIn(blocker,report['blockers'])
                self.assertEqual(output['changed'],'false');self.assertFalse((Path(td)/'out').exists())

if __name__=='__main__':unittest.main()
