"""Bounded public-data HTTP reads with a single Eastmoney request lane."""
import gzip
import json
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class _NoRedirect(HTTPRedirectHandler):
    # A redirect must not initiate another provider request outside the limiter.
    def redirect_request(self, *args):
        return None


class PublicHttp:
    def __init__(self, *, open_request=None, clock=time.monotonic, sleep=time.sleep):
        self.open = open_request or build_opener(_NoRedirect).open
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.last_eastmoney = None

    def _request(self, url, *, params=None, form=None, headers=None):
        if params:
            url += ('&' if '?' in url else '?') + urlencode(params, doseq=True)
        host = urlsplit(url).hostname or ''
        if urlsplit(url).scheme != 'https':
            raise ValueError('public providers require HTTPS')
        req = Request(url, data=urlencode(form, doseq=True).encode() if form is not None else None,
                      headers={'User-Agent': 'Mozilla/5.0 (compatible; ResearchRadar/4.0)',
                               'Accept': '*/*', **(headers or {})})

        def fetch():
            with self.open(req, timeout=8) as response:
                data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise ValueError('provider response too large')
                if response.headers.get('Content-Encoding') == 'gzip':
                    import io
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                        data = stream.read(8_000_001)
                    if len(data) > 8_000_000:
                        raise ValueError('decoded provider response too large')
                return data

        if host != 'eastmoney.com' and not host.endswith('.eastmoney.com'):
            return fetch()
        with self.lock:
            if self.last_eastmoney is not None:
                delay = 1.5 - (self.clock() - self.last_eastmoney)
                if delay > 0:
                    self.sleep(delay)
            try:
                return fetch()
            finally:
                # Failed requests and paginated reads count against the same interval.
                self.last_eastmoney = self.clock()

    def get_json(self, url, params=None, headers=None):
        return json.loads(self._request(url, params=params, headers=headers))

    def get_text(self, url, params=None, encoding='utf-8', headers=None):
        return self._request(url, params=params, headers=headers).decode(encoding)

    def post_form_json(self, url, params, headers=None):
        return json.loads(self._request(url, form=params, headers=headers))
