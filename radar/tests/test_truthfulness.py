"""Regression cases from the actual 2026-10-17 acceptance gaps. All synthetic."""
import copy
import datetime as dt
import json
import unittest
from unittest.mock import patch
from test_integrity import NOW, bars, build, financial_evidence, quotes, record
from test_review_regressions import complete_dataset
from integrity import dated_fx, financial_status, pe_status
import acceptance_probe as probe

class FxTests(unittest.TestCase):
    def test_historical_day_selected_despite_tomorrow_metadata(self):
        class H:
            def yahoo(self, path):
                return {'chart': {'result': [{'meta': {'exchangeTimezoneName':'UTC', 'regularMarketPrice':99,
                    'regularMarketTime':1792195200}, 'timestamp':[1792108800,1792195200],
                    'indicators': {'quote':[{'close':[7.,8.]}]}}]}}
        fx=quotes.fx(H(),'CNY');fx['receivedAt']=NOW.isoformat()
        self.assertEqual(fx['asOf'],'2026-10-17')
        self.assertEqual(dated_fx(fx,'CNY','2026-10-16',NOW)['value'],7.)
        self.assertIsNone(dated_fx(fx,'CNY','2026-10-15',NOW))
        self.assertNotEqual(fx['value'],99)

    def test_eur_inversion_and_no_nearest_or_future_fill(self):
        f=record(asOf='2026-10-17',currency='EUR',rates=[['2026-10-16',.5,2.],['2026-10-17',.4,2.5]])
        self.assertEqual(dated_fx(f,'EUR','2026-10-16',NOW)['value'],.5)
        self.assertIsNone(dated_fx(f,'EUR','2026-10-15',NOW))
        self.assertIsNone(dated_fx(f,'CNY','2026-10-16',NOW))
        f['rates'][0][1]=2.
        self.assertIsNone(dated_fx(f,'EUR','2026-10-16',NOW))

    def test_mcap_uses_historical_fx_and_currency_is_not_financial_currency(self):
        data,mk=complete_dataset();c=data['companies'][0];cur=c['cur']
        c['financial']['currency']='EUR'
        mk['fx'][cur]=record(asOf='2026-10-17',value=99,currency=cur,
                            rates=[['2026-10-16',7.,7.],['2026-10-17',99.,99.]])
        row=build.assemble(data,mk,mk,NOW)[0]['companies'][0]
        self.assertEqual(row['mcapUSD'],round(1e10/7/1e8,1))
        self.assertEqual(row['cur'],cur)
        self.assertEqual(row['provenance']['financial']['currency'],'EUR')
        self.assertEqual(row['provenance']['valuation']['fx']['asOf'],'2026-10-16')
        mk['quote'][c['sym']]['currency']='EUR'
        self.assertIsNone(build.assemble(data,mk,mk,NOW)[0]['companies'][0]['mcapUSD'])

    def test_no_historical_date_stays_missing(self):
        data,mk=complete_dataset();c=data['companies'][0]
        mk['fx'][c['cur']]=record(value=7.,asOf='2026-10-17')
        self.assertIsNone(build.assemble(data,mk,mk,NOW)[0]['companies'][0]['mcapUSD'])

class FinancialTests(unittest.TestCase):
    def test_link_alone_is_not_verified(self):
        f=financial_evidence();f.pop('profit_scope')
        self.assertEqual(financial_status(f,NOW.date()),'missing_scope')
        f=financial_evidence();f.update(conditions=['scope'],conditions_reviewed=False)
        self.assertEqual(financial_status(f,NOW.date()),'conditions_unreviewed')

    def test_cumulative_difference_needs_multiple_sources_and_calculation(self):
        f=financial_evidence();f['derivation']='cumulative_difference'
        self.assertEqual(financial_status(f,NOW.date()),'missing_derivation_evidence')
        f.update(source_urls=['https://example.test/report','https://example.test/q1'],calculation_note='Both years H1-Q1')
        self.assertEqual(financial_status(f,NOW.date()),'verified')

    def test_h1_preliminary_partial_and_turnaround_never_normal_growth_signal(self):
        for change in ({'basis':'half_year'},{'report_status':'preliminary'},
                       {'report_status':'revenue_only'},{'profit_comparison':'turnaround'},
                       {'profit_comparison':'one_off'}):
            with self.subTest(change=change):
                data,mk=complete_dataset();data['companies'][0]['financial'].update(change)
                row=build.assemble(data,mk,mk,NOW)[0]['companies'][0]
                self.assertFalse(row['financialSignalEligible'])
                if change.get('profit_comparison')=='turnaround': self.assertIsNone(row['earng'])
        data,mk=complete_dataset();data['companies'][0]['gm']=None
        self.assertFalse(build.assemble(data,mk,mk,NOW)[0]['companies'][0]['financialSignalEligible'])

    def test_multisource_conditions_are_preserved(self):
        data,mk=complete_dataset();f=data['companies'][0]['financial']
        f.update(conditions=['Mixed continuing/discontinued operations'],conditions_reviewed=True)
        row=build.assemble(data,mk,mk,NOW)[0]['companies'][0]
        self.assertEqual(row['provenance']['financial']['conditions'],f['conditions'])
        self.assertEqual(row['provenance']['financial']['verified_at'],'2026-10-16')

class DiagnosticTests(unittest.TestCase):
    def test_pe_missing_invalid_nonpositive_are_distinct(self):
        for v,state in [(None,'missing'),(0,'nonpositive'),(-1,'nonpositive'),('10','invalid'),(False,'invalid'),(float('nan'),'invalid'),(10,'available')]:
            self.assertEqual(pe_status(v),state)

    def test_yahoo_single_point_error_survives_isolation(self):
        with patch.object(quotes,'yahoo_daily',return_value={'bars':bars(1),'src':'yahoo','phase':'closed'}):
            row,_=probe.inspect('index-yahoo','399006.SZ','yahoo',probe.Budget(),
                lambda h:quotes.index_quote(h,'399006.SZ','sz399006',source='yahoo'),probe.index_quality)
        self.assertEqual(row['failure'],'yahoo_index_insufficient_daily_bars')
        self.assertEqual(row['details']['count'],1)
        self.assertEqual(row['requests'],[])

    def test_tencent_does_not_inherit_yahoo_phase_or_currency(self):
        from test_integrity import FakeHttp
        h=FakeHttp([['2026-10-16','1','1','2']],[])
        value=quotes.tencent_daily(h,'600000.SS')
        self.assertEqual(value['phase'],'unknown');self.assertIsNone(value['currency'])

    def test_monthly_one_point_not_sufficient_even_with_200(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo')
        fields,details,gate=probe.month_quality(record(bars=[['2026-10',100]],src='yahoo',asOf=None,current=None),h)
        self.assertFalse(fields['history120Completed']);self.assertFalse(gate)

    def test_short_history_actual_count_no_52_week_or_60_day_claim(self):
        m=build.metrics(bars(54))
        self.assertEqual(m['history']['count'],54)
        for key in ('hi52','dd52','r60','ytd'): self.assertIsNone(m[key])

if __name__=='__main__': unittest.main()
