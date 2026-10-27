"""Synthetic regressions; no fixture expectations, live fetching or publication."""
import copy
import datetime as dt
import hashlib
import json
import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import equity_close_proof as proof
from snapshot import equity_bar_final


NOW = dt.datetime.fromisoformat('2026-10-27T17:00:00+08:00')
DAY = '2026-10-27'
IDENTITY = {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1'}


def epoch(day, time):
    return int(dt.datetime.fromisoformat(day+'T'+time+'+08:00').timestamp())


def packet():
    """Provider-shaped synthetic prices; not admitted real market evidence."""
    record = {'schemaVersion': 2, 'src': 'yahoo', 'currency': 'TWD', 'priceBasis': 'raw',
        'returnBasis': 'yahoo-adjclose', 'timezone': 'Asia/Taipei', 'phase': 'unknown',
        'asOf': DAY, 'receivedAt': '2026-10-27T16:58:01+08:00',
        'bars': [['2026-10-22', 5070., 5070., 5485.], [DAY, 4750., 4750., 5200.]],
        'barTimestamps': {'2026-10-22': epoch('2026-10-22', '09:00:00'),
                          DAY: epoch(DAY, '13:30:15')},
        'finality': {'method': 'provider-session-boundary', 'start': epoch(DAY, '09:00:00'),
                     'end': epoch(DAY, '13:30:00')}}
    document = {'stat': 'OK', 'date': '20261027', 'title': '115年10月 2383 台光電 各日成交資訊',
        'fields': list(proof.FIELDS),
        'data': [['115/10/27', '4,968,686', '24,296,839,577', '5,200.00',
                  '5,200.00', '4,685.00', '4,750.00', '-320.00', '48,800', '']]}
    official = {'sourceUrl': proof.official_url(DAY), 'httpStatus': 200, 'sha256': 'b'*64,
                'receivedAt': '2026-10-27T16:59:00+08:00'}
    yahoo = {'sourceUrl': proof.YAHOO_URL, 'httpStatus': 200, 'sha256': 'c'*64,
             'receivedAt': '2026-10-27T16:58:00+08:00'}
    return record, document, official, yahoo


def create(record=None, document=None, official=None, yahoo=None, *, day=DAY, now=NOW, execution=IDENTITY):
    defaults = packet()
    record, document, official, yahoo = (value if value is not None else default
        for value, default in zip((record, document, official, yahoo), defaults))
    return proof.make_proof(record, document, official_event=official, yahoo_event=yahoo,
                            expected_day=day, now=now, execution=execution)


def reseal(value):
    """Exercise all field validation in addition to the integrity checksum."""
    value['checksum'] = hashlib.sha256(json.dumps(
        {key: child for key, child in value.items() if key != 'checksum'},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return value


class TwseCloseProofTests(unittest.TestCase):
    def test_complete_independent_evidence_accepts_without_changing_provider_inputs(self):
        record, document, official, yahoo = packet()
        before = copy.deepcopy((record, document, official, yahoo))
        result = create(record, document, official, yahoo)
        self.assertIsNotNone(result)
        self.assertEqual((record, document, official, yahoo), before)
        self.assertFalse(equity_bar_final(DAY, record['barTimestamps'][DAY], record['timezone'],
                                         record['finality'], record['receivedAt']))
        self.assertTrue(proof.valid_summary(result, now=NOW, execution=IDENTITY))
        enriched = {**record, proof.PROOF_KEY: result}
        with patch.dict(os.environ, IDENTITY):
            self.assertTrue(proof.valid_proof(enriched, result, symbol=proof.SYMBOL, day=DAY, now=NOW))
            self.assertTrue(proof.record_bar_final(enriched, DAY, symbol=proof.SYMBOL, now=NOW))
        self.assertEqual(enriched['phase'], 'unknown')
        self.assertEqual(result['officialRow']['close'], '4750')
        self.assertEqual(result['high'], '5200')

    def test_fifteen_seconds_without_independent_proof_still_rejects(self):
        record = packet()[0]
        with patch.dict(os.environ, IDENTITY):
            self.assertFalse(proof.record_bar_final(record, DAY, symbol=proof.SYMBOL, now=NOW))
        self.assertEqual(record['barTimestamps'][DAY]-record['finality']['end'], 15)

    def test_old_provider_proof_path_remains_available_to_other_equities(self):
        record = packet()[0]
        record['barTimestamps'][DAY] = epoch(DAY, '09:00:00')
        self.assertTrue(proof.record_bar_final(record, DAY, symbol='OTHER', now=NOW))
        self.assertTrue(equity_bar_final(DAY, record['barTimestamps'][DAY], record['timezone'],
                                        record['finality'], record['receivedAt']))

    def test_only_fixed_symbol_and_original_record_can_use_proof(self):
        record = packet()[0]
        result = create()
        for symbol in ('2382.TW', '2383', 'USD/TWD', None):
            with self.subTest(symbol=symbol):
                self.assertFalse(proof.valid_proof(record, result, symbol=symbol, day=DAY, now=NOW, execution=IDENTITY))
        changed = copy.deepcopy(record)
        changed['bars'][0][1] += 1
        self.assertFalse(proof.valid_proof(changed, result, symbol=proof.SYMBOL, day=DAY, now=NOW, execution=IDENTITY))
        self.assertEqual(proof.record_digest({**record, proof.PROOF_KEY: result}), proof.record_digest(record))

    def test_identity_is_bound_to_this_sha_run_and_first_attempt(self):
        result = create()
        for key, value in (('GITHUB_SHA', 'd'*40), ('GITHUB_RUN_ID', '54321'), ('GITHUB_RUN_ATTEMPT', '2')):
            other = {**IDENTITY, key: value}
            with self.subTest(key=key):
                self.assertFalse(proof.valid_summary(result, now=NOW, execution=other))
        for invalid in ({}, {'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '0', 'GITHUB_RUN_ATTEMPT': '1'},
                        {**IDENTITY, 'GITHUB_RUN_ATTEMPT': 1}):
            self.assertIsNone(create(execution=invalid))

    def test_official_response_status_title_code_and_month_are_required(self):
        for key, value in (('stat', 'No data'), ('date', '20261026'), ('title', '115年10月 2382 台光電 各日成交資訊'),
                           ('title', '115年9月 2383 台光電 各日成交資訊'), ('title', '114年10月 2383 台光電 各日成交資訊')):
            document = packet()[1]
            document[key] = value
            with self.subTest(key=key, value=value):
                self.assertIsNone(create(document=document))

    def test_missing_duplicate_malformed_or_future_official_rows_reject(self):
        document = packet()[1]
        variants = [[], document['data']*2, [['115/10/27']],
                    [document['data'][0][:]], [document['data'][0][:]], [document['data'][0][:]]]
        variants[3][0][0] = '115/10/22'
        variants[4][0][0] = '115/10/28'
        variants[5][0][0] = '115/02/30'
        for rows in variants:
            with self.subTest(rows=rows):
                self.assertIsNone(create(document={**document, 'data': rows}))

    def test_unreviewed_note_or_ambiguous_field_mapping_reject(self):
        document = packet()[1]
        document['data'][0][-1] = '**'
        self.assertIsNone(create(document=document))
        document = packet()[1]
        document['fields'][0] = '最高價'
        self.assertIsNone(create(document=document))

    def test_price_adjclose_and_high_must_match_exactly_without_tolerance(self):
        for index, value in ((1, 4750.00001), (2, 4749.99), (2, None), (3, 5199.99), (3, None)):
            record = packet()[0]
            record['bars'][-1][index] = value
            with self.subTest(index=index, value=value):
                self.assertIsNone(create(record=record))
        for index, value in ((6, '4,750.01'), (4, '5,199.99'), (6, '--'), (6, 'NaN'), (6, '4,75.00')):
            document = packet()[1]
            document['data'][0][index] = value
            with self.subTest(index=index, value=value):
                self.assertIsNone(create(document=document))

    def test_record_source_currency_timezone_and_original_basis_required(self):
        for key, value in (('src', 'tencent'), ('currency', 'USD'), ('timezone', 'Asia/Shanghai'),
                           ('priceBasis', 'adjusted'), ('returnBasis', 'other'), ('phase', 'closed'),
                           ('phase', 'intraday'), ('asOf', '2026-10-22'), ('schemaVersion', 1)):
            record = packet()[0]
            record[key] = value
            with self.subTest(key=key):
                self.assertIsNone(create(record=record))

    def test_fixed_origin_url_status_and_hash_required_for_both_sources(self):
        for which in ('official', 'yahoo'):
            for key, value in (('sourceUrl', 'http://www.twse.com.tw/'), ('sourceUrl', 'https://evil.example/'),
                               ('httpStatus', 302), ('httpStatus', 403), ('httpStatus', True),
                               ('sha256', 'bad'), ('sha256', None)):
                source = packet()[2 if which == 'official' else 3]
                source[key] = value
                with self.subTest(which=which, key=key, value=value):
                    self.assertIsNone(create(**{which: source}))

    def test_receipts_require_actual_after_close_non_future_and_timezone(self):
        for which in ('official', 'yahoo'):
            for receipt in ('2026-10-27T13:29:59+08:00', '2026-10-27T17:00:01+08:00',
                            '2026-10-25T17:00:00+08:00', '2026-10-27T16:58:00'):
                source = packet()[2 if which == 'official' else 3]
                source['receivedAt'] = receipt
                with self.subTest(which=which, receipt=receipt):
                    self.assertIsNone(create(**{which: source}))
        source = packet()[3]
        source['receivedAt'] = '2026-10-27T16:58:02+08:00'
        self.assertIsNone(create(yahoo=source))

    def test_missing_future_or_wrong_day_provider_metadata_rejects(self):
        for fault in ('missing_finality', 'missing_timestamp', 'future', 'old_day', 'short_session',
                      'early_end', 'bool_epoch', 'float_epoch', 'early_timestamp'):
            record = packet()[0]
            if fault == 'missing_finality': record.pop('finality')
            elif fault == 'missing_timestamp': record.pop('barTimestamps')
            elif fault == 'future': record['barTimestamps'][DAY] = epoch(DAY, '18:00:00')
            elif fault == 'old_day': record['barTimestamps'][DAY] = epoch('2026-10-22', '13:30:15')
            elif fault == 'short_session': record['finality']['start'] = record['finality']['end']
            elif fault == 'early_end': record['finality']['end'] -= 60
            elif fault == 'bool_epoch': record['barTimestamps'][DAY] = True
            elif fault == 'float_epoch': record['barTimestamps'][DAY] = float(record['barTimestamps'][DAY])
            else: record['barTimestamps'][DAY] = epoch(DAY, '13:29:59')
            with self.subTest(fault=fault): self.assertIsNone(create(record=record))

    def test_calendar_and_current_expected_day_still_govern_admission(self):
        self.assertIsNone(create(day='2026-10-22'))
        self.assertIsNone(create(now=dt.datetime.fromisoformat('2026-10-27T13:29:59+08:00')))
        self.assertIsNone(create(now=NOW.replace(tzinfo=None)))
        result = create()
        self.assertFalse(proof.valid_summary(result, now=NOW+dt.timedelta(days=2), execution=IDENTITY))

    def test_safe_summary_checksum_and_complete_schema_required(self):
        result = create()
        for key in proof.SUMMARY_KEYS:
            changed = copy.deepcopy(result)
            changed.pop(key)
            with self.subTest(missing=key):
                self.assertFalse(proof.valid_summary(changed, now=NOW, execution=IDENTITY))
        for extra in ({'verified': True}, {'rawbody': 'not exported'}, {'other': 'field'}):
            changed = reseal({**result, **extra})
            self.assertFalse(proof.valid_summary(changed, now=NOW, execution=IDENTITY))
        changed = copy.deepcopy(result)
        changed['close'] = '4750.01'
        self.assertFalse(proof.valid_summary(changed, now=NOW, execution=IDENTITY))
        self.assertFalse(proof.valid_proof(packet()[0], {'verified': True}, symbol=proof.SYMBOL,
                                          day=DAY, now=NOW, execution=IDENTITY))

    def test_checksum_is_not_a_substitute_for_all_value_and_time_checks(self):
        original = create()
        changes = (('currency', 'USD'), ('symbol', '2382.TW'), ('day', '2026-10-22'),
                   ('close', '4751'), ('adjclose', '4751'), ('high', '5199'),
                   ('officialReceivedAt', '2026-10-27T13:00:00+08:00'),
                   ('barTimestamp', epoch(DAY, '18:00:00')), ('sessionEnd', epoch(DAY, '13:29:00')),
                   ('sourcePhase', 'closed'), ('officialResponseDate', '20261026'))
        for key, value in changes:
            changed = reseal({**original, key: value})
            with self.subTest(key=key):
                self.assertFalse(proof.valid_summary(changed, now=NOW, execution=IDENTITY))

    def test_summary_is_sensitive_scan_safe_and_contains_no_original_response(self):
        import acceptance_bundle
        result = create()
        acceptance_bundle.check_sensitive(result)
        self.assertNotIn('data', result)
        self.assertNotIn('fields', result)
        self.assertNotIn('verified', result)
        self.assertLess(len(json.dumps(result, ensure_ascii=False).encode()), 8192)

    def test_next_local_day_does_not_reuse_independent_same_day_proof(self):
        later = dt.datetime.fromisoformat('2026-10-28T06:00:00+08:00')
        self.assertEqual(proof.market_calendar.context(proof.SYMBOL, later)['expectedCompletedDate'], DAY)
        self.assertIsNone(create(now=later))
        self.assertFalse(proof.valid_summary(create(), now=later, execution=IDENTITY))

    def test_no_environment_or_secret_is_read_when_execution_supplied(self):
        with patch.object(os, 'environ', {}):
            result = create()
            self.assertTrue(proof.valid_proof(packet()[0], result, symbol=proof.SYMBOL,
                                             day=DAY, now=NOW, execution=IDENTITY))
            self.assertFalse(proof.valid_proof(packet()[0], result, symbol=proof.SYMBOL, day=DAY, now=NOW))


if __name__ == '__main__':
    unittest.main()
