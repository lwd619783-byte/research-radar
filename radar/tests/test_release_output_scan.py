"""The dependency-free Vercel verifier applies the same V3 output policy."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'radar/scripts'))
from output_scan import scan_output


class ReleaseOutputScanTests(unittest.TestCase):
    def run_js(self, code):
        script = "const assert=require('node:assert/strict');const {scanOutput,needsV3Scan,BANNED_WORDS,DISCLAIMER}=require(" + json.dumps(str(ROOT/'radar/scripts/verify-release.cjs')) + ");\n" + """
        const base=()=>({meta:{},industries:[],chokepoints:[],companies:[]});
        const page=(body,data=base())=>'<main>'+body+'<footer id="disclaimer">'+DISCLAIMER+'</footer><script>const DATA='+JSON.stringify(data).replaceAll('</','<\\\\/')+';</script></main>';
        """ + code
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_scanner_uses_exact_contract_words(self):
        contract = json.loads((ROOT/'radar/data/notion_schema.json').read_text('utf-8'))
        self.run_js('assert.deepEqual(BANNED_WORDS,'+json.dumps(contract['banned_words'])+');')

    def test_banned_output_in_text_attributes_and_nested_data(self):
        self.run_js("""
        assert.equal(scanOutput(page('<div data-src="notion">核对来源</div>'),base()),true);
        assert.equal(scanOutput(page('<script>const note="买入";</script><style>.x{}</style>'),base()),true);
        for(const body of ['买 入','买<span>入</span>','&#x4e70;&#20837;',
          '<i data-tip="买 入"></i>','<i title="卖出"></i>','<i aria-label="推荐"></i>',
          '<input placeholder="加仓">','<img alt="目标价">','<i data-src="notion">买入</i>']){
          assert.throws(()=>scanOutput(page(body),base()),/banned_words_in_output/);
        }
        const data={...base(),nested:[{text:'买　入'}]};
        assert.throws(()=>scanOutput(page('',data),data),/banned_words_in_output/);
        assert.throws(()=>scanOutput(page('<div>核对来源</div>'),base()),/legacy_ui_in_output/);
        assert.throws(()=>scanOutput(page('<div aria-label="待核"></div>'),base()),/legacy_ui_in_output/);
        """)

    def test_disclosure_links_and_private_metadata_are_enforced(self):
        self.run_js("""
        assert.throws(()=>scanOutput(page('').replace(DISCLAIMER,''),base()),/disclaimer_count/);
        assert.throws(()=>scanOutput(page(DISCLAIMER),base()),/disclaimer_count/);
        assert.throws(()=>scanOutput(page('<style>.mock-note{}</style>'),base()),/design_note_in_output/);
        assert.throws(()=>scanOutput(page('<div class="mock-note">note</div>'),base()),/design_note_in_output/);
        for(const extra of [{created_by:{}},{x:{last_edited_by:{id:'person'}}},{authorization:'private'}, {request_id:'opaque'}]){
          const data={...base(),...extra};assert.throws(()=>scanOutput(page('',data),data),/sensitive_output/);
        }
        const data={...base(),note:'ntn_'+'x'.repeat(30)};
        assert.throws(()=>scanOutput(page('',data),data),/sensitive_output/);
        for(const link of ['javascript:alert(1)','https://user:pass@example.com','/private'])
          assert.throws(()=>scanOutput(page('<a href="'+link+'">link</a>'),base()),/unsafe_output_link/);
        assert.throws(()=>scanOutput(page('<a href="https://issuer.example">link</a>'),base()),/unsafe_output_link/);
        assert.equal(scanOutput(page('<a href="http://issuer.example" target="_blank" rel="noopener noreferrer">link</a>'),base()),true);
        assert.equal(scanOutput(page('<a href="#overview">link</a>'),base()),true);
        """)

    def test_v3_triggers_cannot_be_removed_to_bypass_scan_and_v2_still_rolls_back(self):
        self.run_js("""
        assert.equal(needsV3Scan('<div id="heroProv"></div>',base(),{schemaVersion:2}),true);
        assert.equal(needsV3Scan('',{...base(),meta:{notion:{source:'notion'}}},{schemaVersion:2}),true);
        assert.equal(needsV3Scan('',base(),{schemaVersion:3}),true);
        assert.equal(needsV3Scan('',base(),{schemaVersion:2}),false);
        assert.throws(()=>scanOutput(page('',{}),{}),/invalid_data_shape/);
        assert.throws(()=>scanOutput(page('').replace('const DATA=','const OTHER='),base()),/invalid_embedded_data/);
        assert.throws(()=>scanOutput(page(''),{...base(),changed:1}),/embedded_data_mismatch/);
        """)

    def test_python_and_javascript_publication_decisions_agree(self):
        from render_v3 import DISCLAIMER
        data = {'meta': {}, 'industries': [], 'chokepoints': [], 'companies': []}
        samples = [
            '', '<p>普通研究文字</p>', '<p>买<span>入</span></p>', '<p>&#x4e70;&#20837;</p>',
            '<div hidden>买入</div>', '<template>买入</template>', '<style>.x{content:"买入"}</style>',
            '<script>const ignored="买入";</script>', '<p data-src="notion"><span title="核对来源">核对来源</span></p>',
            '<p data-src="notion"><span title="买入">说明</span></p>', '<p>核 验</p>',
            '<i aria-label="买入"></i>', '<p class="mock-note">说明</p>', '<p id="disclaimer"></p>',
            '<a href="#overview">总览</a>', '<a href="javascript:alert(1)">来源</a>',
            '<a href=" https://example.test" target="_blank" rel="noopener noreferrer">来源</a>',
            '<a href="https://example.test" target="_blank" rel="noopener noreferrer">来源</a>',
            '<p>ntn_TEST_DO_NOT_LOG_123456</p>',
        ]
        fixtures = []
        for content in samples:
            html = '<main>' + content + '<footer id="disclaimer">' + DISCLAIMER + '</footer><script>const DATA=' + json.dumps(data) + ';</script></main>'
            fixtures.append({'html': html, 'data': data, 'allowed': not scan_output(html, data)})
        self.run_js('for(const row of ' + json.dumps(fixtures, ensure_ascii=False) + '){let allowed=true;try{scanOutput(row.html,row.data);}catch{allowed=false;}assert.equal(allowed,row.allowed,row.html);}')


if __name__ == '__main__':
    unittest.main()
