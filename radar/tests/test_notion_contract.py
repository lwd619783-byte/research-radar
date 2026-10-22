"""Offline integrity checks for the supplied v3 contract and fixture registry."""
import json
from pathlib import Path
import re
import unicodedata
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'radar/tests/fixtures/notion_v3'
TABLES = {'industries', 'chokepoints', 'companies', 'financials', 'daily', 'weekly'}
PROPERTY_TYPES = {'title', 'rich_text', 'number', 'select', 'relation', 'date',
                  'formula', 'checkbox', 'url'}
LEVELS = {'row', 'judgment', 'evidence', 'optional', 'ignore'}


def strict_json(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f'Non-JSON numeric constant: {value}')

    return json.loads(path.read_text(encoding='utf-8'),
                      object_pairs_hook=unique_keys, parse_constant=reject_constant)


class NotionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = strict_json(ROOT / 'radar/data/notion_schema.json')
        cls.fixtures = strict_json(FIXTURES / 'cases.json')

    def test_six_tables_have_typed_and_leveled_properties(self):
        self.assertEqual(set(self.contract['tables']), TABLES)
        self.assertEqual(set(self.contract['levels']), LEVELS)
        for table_name, table in self.contract['tables'].items():
            with self.subTest(table=table_name):
                self.assertIsInstance(table['properties'], dict)
                self.assertTrue(table['properties'])
            for name, prop in table['properties'].items():
                with self.subTest(table=table_name, property=name):
                    self.assertTrue(name.strip())
                    self.assertIn(prop.get('type'), PROPERTY_TYPES)
                    self.assertIn(prop.get('level'), LEVELS)
                    if prop['type'] == 'relation':
                        self.assertIn(prop.get('target'), TABLES)

    def test_data_source_ids_match_brief_appendix_c(self):
        brief = (ROOT / 'docs/V3-BRIEF.md').read_text(encoding='utf-8')
        appendix = brief.split('## 附录 C · Notion 数据库 ID', 1)[1]
        appendix = appendix.split('\n## ', 1)[0]
        rows = re.findall(
            r'^\| `([a-z]+)` \| [^|]+ \| `([0-9a-f-]{36})` \| `([0-9a-f-]{36})` \|$',
            appendix, flags=re.MULTILINE)
        self.assertEqual(len(rows), 6)
        self.assertEqual({name for name, _, _ in rows}, TABLES)
        for name, database_id, data_source_id in rows:
            with self.subTest(table=name):
                self.assertEqual(self.contract['tables'][name]['database_id'], database_id)
                self.assertEqual(self.contract['tables'][name]['data_source_id'], data_source_id)
                self.assertNotEqual(database_id, data_source_id)

    def test_banned_and_prediction_word_lists_are_complete(self):
        for words, count in ((self.contract['banned_words'], 24),
                             (self.contract['prediction_words']['words'], 12)):
            with self.subTest(expected_count=count):
                self.assertIsInstance(words, list)
                self.assertEqual(len(words), count)
                normalized = []
                for word in words:
                    self.assertIsInstance(word, str)
                    value = re.sub(r'\s', '', unicodedata.normalize('NFKC', word))
                    self.assertTrue(value)
                    normalized.append(value)
                self.assertEqual(len(set(normalized)), count)

    def test_fixture_codes_and_judgment_reasons_are_registered(self):
        # The supplied code registry lives in cases.json, not notion_schema.json.
        registry = self.fixtures['codes']
        self.assertIsInstance(registry, dict)
        registered = set()
        for group, codes in registry.items():
            with self.subTest(group=group):
                self.assertIsInstance(codes, list)
                self.assertTrue(codes)
                for code in codes:
                    self.assertIsInstance(code, str)
                    self.assertRegex(code, r'^[a-z][a-z0-9_]*$')
                    registered.add(code)

        self.assertEqual(len(self.fixtures['cases']), 103)
        self.assertEqual(len({case['id'] for case in self.fixtures['cases']}), 103)
        for case in self.fixtures['cases']:
            with self.subTest(case=case['id']):
                used = set(case['expect']['codes'])
                for assertion in case['expect'].get('assert', []):
                    path = assertion['path']
                    used.update(re.findall(r'\[code=([^\]]+)\]', path))
                    if re.search(r'\.(?:code|reasons)$', path):
                        for operation in ('eq', 'ne', 'contains', 'not_contains'):
                            value = assertion.get(operation, [])
                            used.update([value] if isinstance(value, str) else value)
                self.assertFalse(used - registered,
                                 f'Unregistered codes: {sorted(used - registered)}')

        self.assertFalse(set(self.contract['judgment_rule']['reasons']) - registered)


if __name__ == '__main__':
    unittest.main()
