"""Read-only V3 output gates; scan content, never execute embedded JavaScript."""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit

from render_v3 import DISCLAIMER
from research_snapshot import ResearchAbort

UI_WORDS = ('核验', '核实', '核对', '待复核', '待核', '原评分', '原标记', '人工评分')
TEXT_ATTRS = {'data-tip', 'title', 'aria-label', 'placeholder', 'alt'}
PRIVATE_KEYS = {'created_by', 'last_edited_by', 'request_id', 'request_headers', 'access_token', 'authorization', 'notion_token'}
TOKEN = re.compile(r'(?:\bntn_[A-Za-z0-9_-]{12,}|\bsecret_[A-Za-z0-9_-]{20,}'
                   r'|\bgithub_pat_[A-Za-z0-9_]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}'
                   r'|\bBearer\s+[A-Za-z0-9._-]{20,})', re.I)
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


def normalized(text):
    return re.sub(r'\s', '', unicodedata.normalize('NFKC', text))


def embedded_data(html):
    match = re.search(r'<script\b[^>]*>\s*const\s+DATA\s*=\s*(.*?)\s*;\s*</script\s*>', html, re.S | re.I)
    if not match:
        raise ValueError('DATA script missing')
    def invalid(value):
        raise ValueError('Invalid JSON constant')
    return json.loads(match.group(1), parse_constant=invalid)


class OutputScanError(ResearchAbort):
    def __init__(self, issues):
        super().__init__(issues[0]['code'], codes=sorted({issue['code'] for issue in issues}), detail={'issues': issues})


class ContentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.visible = []
        self.interface = []
        self.attributes = []
        self.issues = []
        self.disclaimers = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent = self.stack[-1] if self.stack else {'hidden': False, 'notion': False}
        state = {'tag': tag, 'hidden': parent['hidden'] or tag in ('script', 'style', 'template') or 'hidden' in attrs,
                 'notion': parent['notion'] or attrs.get('data-src') == 'notion'}
        if attrs.get('id') == 'disclaimer':
            self.disclaimers += 1
        for name in TEXT_ATTRS:
            if attrs.get(name):
                self.attributes.append((attrs[name], state['notion']))
        if 'mock-note' in (attrs.get('class') or '').split():
            self.issues.append({'code': 'mock_note_in_output', 'path': 'HTML.class'})
        if tag == 'a' and attrs.get('href'):
            href = attrs['href']
            if not href.startswith('#'):
                try:
                    parts = urlsplit(href)
                    safe = parts.scheme in ('https', 'http') and parts.hostname and not parts.username and not parts.password and not any(ord(char) <= 32 for char in href)
                except ValueError:
                    safe = False
                if not safe:
                    self.issues.append({'code': 'unsafe_link_in_output', 'path': 'HTML.href'})
                if attrs.get('target') != '_blank' or not {'noopener', 'noreferrer'} <= set((attrs.get('rel') or '').split()):
                    self.issues.append({'code': 'unsafe_link_in_output', 'path': 'HTML.external-link-rel'})
        if tag not in VOID_TAGS:
            self.stack.append(state)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        state = self.stack[-1] if self.stack else {'hidden': False, 'notion': False}
        if not state['hidden']:
            self.visible.append(text)
            if not state['notion']:
                self.interface.append(text)


def scan_output(html_text, data, *, site_dir=None, require_v3=True):
    """Return safe location-only diagnostics; never echo potentially secret text."""
    issues = []
    contract = json.loads((Path(__file__).resolve().parents[1] / 'data/notion_schema.json').read_text('utf-8'))
    words = [normalized(word) for word in contract['banned_words']]

    def check_words(text, path, interface=False):
        clean = normalized(text)
        if any(word in clean for word in words):
            issues.append({'code': 'banned_words_in_output', 'path': path})
        if interface and any(word in clean for word in UI_WORDS):
            issues.append({'code': 'legacy_ui_words_in_output', 'path': path})

    def visit(value, path='DATA'):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in PRIVATE_KEYS:
                    issues.append({'code': 'private_metadata_in_output', 'path': path})
                safe_key = '<redacted>' if TOKEN.search(str(key)) else str(key)
                visit(item, path + '.' + safe_key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, path + f'[{index}]')
        elif isinstance(value, str):
            check_words(value, path)
            if TOKEN.search(value):
                issues.append({'code': 'secret_in_output', 'path': path})

    if not isinstance(data, dict) or not isinstance(data.get('meta'), dict) or any(not isinstance(data.get(table), list) for table in ('industries', 'chokepoints', 'companies')):
        issues.append({'code': 'invalid_data_shape', 'path': 'DATA'})
    else:
        visit(data)
    try:
        if embedded_data(html_text) != data:
            issues.append({'code': 'embedded_data_mismatch', 'path': 'HTML.DATA'})
    except (ValueError, TypeError, json.JSONDecodeError):
        issues.append({'code': 'invalid_embedded_data', 'path': 'HTML.DATA'})
    if TOKEN.search(html_text):
        issues.append({'code': 'secret_in_output', 'path': 'HTML'})
    parser = ContentParser()
    parser.feed(html_text)
    parser.close()
    issues.extend(parser.issues)
    visible = ''.join(parser.visible)
    check_words(visible, 'HTML.visible')
    check_words(''.join(parser.interface), 'HTML.interface', interface=True)
    for text, is_notion in parser.attributes:
        check_words(text, 'HTML.attribute', interface=not is_notion)
    if require_v3 and (visible.count(DISCLAIMER) != 1 or parser.disclaimers != 1):
        issues.append({'code': 'disclaimer_count', 'path': 'HTML.disclaimer'})
    if '.mock-note' in html_text:
        issues.append({'code': 'mock_note_in_output', 'path': 'HTML'})
    if site_dir is not None:
        for path in sorted(Path(site_dir).rglob('*')):
            if path.is_file() and path.suffix in ('.html', '.css', '.js'):
                text = path.read_text('utf-8')
                # Source contains no user-authored Notion text. Do not scan docs.
                if any(word in normalized(text) for word in UI_WORDS):
                    issues.append({'code': 'legacy_ui_words_in_output', 'path': 'site/' + path.name})
                if '.mock-note' in text:
                    issues.append({'code': 'mock_note_in_output', 'path': 'site/' + path.name})
    unique = {(item['code'], item['path']): item for item in issues}
    return [unique[key] for key in sorted(unique)]


def assert_output_safe(html_text, data, **kwargs):
    issues = scan_output(html_text, data, **kwargs)
    if issues:
        raise OutputScanError(issues)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scan a built radar V3 HTML file without executing it.')
    parser.add_argument('html', type=Path)
    parser.add_argument('--data', type=Path)
    args = parser.parse_args(argv)
    try:
        html = args.html.read_text('utf-8')
        data = json.loads(args.data.read_text('utf-8')) if args.data else embedded_data(html)
        issues = scan_output(html, data)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'ok': False, 'codes': ['invalid_output']}, ensure_ascii=False))
        return 2
    print(json.dumps({'ok': not issues, 'issues': issues}, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
