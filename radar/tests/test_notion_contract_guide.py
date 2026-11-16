"""The checked-in maintenance guide covers and tracks the property contract."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('generate_notion_contract',
                                             ROOT / 'radar/tools/generate_notion_contract.py')
guide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guide)


class NotionContractGuideTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / 'radar/data/notion_schema.json').read_text(encoding='utf-8'))
        self.document = (ROOT / 'docs/NOTION-CONTRACT.md').read_text(encoding='utf-8')

    def test_committed_guide_matches_schema(self):
        self.assertEqual(self.document, guide.render_guide(self.schema),
                         'Run python -B radar/tools/generate_notion_contract.py')

    def test_each_table_lists_every_property_and_an_example(self):
        sections = {heading: content for heading, content in
                    (section.split('\n', 1) for section in self.document.split('\n## ')[1:])}
        for table in self.schema['tables'].values():
            with self.subTest(table=table['label']):
                rows = [line[2:-2].split(' | ') for line in sections[table['label']].splitlines()
                        if line.startswith('| ') and line.endswith(' |')][2:]
                self.assertEqual([row[0] for row in rows], list(table['properties']))
                for row in rows:
                    self.assertEqual(len(row), 6)
                    self.assertTrue(row[-1].strip('` '), row[0])

    def test_word_lists_are_complete(self):
        banned, prediction = self.document.split('\n### 禁用词\n', 1)[1].split('\n### 预测词\n', 1)
        self.assertIn(self.schema['prediction_words']['applies_to'], prediction)
        for section, words in ((banned, self.schema['banned_words']),
                               (prediction, self.schema['prediction_words']['words'])):
            for word in words:
                self.assertIn(f'`{word}`', section)


if __name__ == '__main__':
    unittest.main()
