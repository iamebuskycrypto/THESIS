"""Public read-only routes cannot turn visitor input into arbitrary fetches."""
import time
import unittest
from unittest.mock import patch
from hosted_reader import read
from issuer_article import approved_url
from stocks import STOCKS

class ReaderTests(unittest.TestCase):
    def test_catalogue_covers_eight_stocks_without_keys(self):
        result=read('stocks')
        self.assertFalse(result['key_required'])
        self.assertEqual(len(result['stocks']),8)
        self.assertEqual(len({s['ticker'] for s in result['stocks']}),8)
        for s in result['stocks']:
            self.assertNotIn('key',s)
            self.assertTrue(s['source_url'].startswith('https://'))

    def test_unknown_symbols_and_actions_do_not_make_requests(self):
        with patch('hosted_reader.collect_feed') as collect, patch('hosted_reader.Bitget') as market:
            for action,symbol in [('news','https://localhost/'),('trade','RAAPLUSDT')]:
                with self.assertRaises(ValueError):read(action,symbol)
            collect.assert_not_called();market.assert_not_called()

    def test_source_ids_must_resolve_in_current_allowlisted_feed(self):
        with patch('hosted_reader.collect_feed',return_value=[]), patch('hosted_reader.collect_article') as article:
            with self.assertRaises(ValueError):read('source','RAMDUSDT','untrusted-url')
            article.assert_not_called()

    def test_excerpt_fallback_copies_source_and_discloses_no_model(self):
        event={'id':'known','symbol':'RAMDUSDT','url':'https://ir.amd.com/news-events/press-releases/detail/123/test','text':'Original issuer text'}
        with patch('hosted_reader.collect_feed',return_value=[event]),patch('hosted_reader.collect_article',return_value={'status':'unavailable','reason':'Fixture'}):
            result=read('source','RAMDUSDT','known')
        self.assertEqual(result['model_calls'],0)
        self.assertEqual(result['event']['text'],'Original issuer text')
        self.assertEqual(result['passages'],[])
        self.assertEqual(result['article']['status'],'unavailable')

    def test_nonfinite_and_crossed_quotes_rejected(self):
        q={'bid':10.,'ask':11.,'bid_size':1.,'ask_size':2.,'timestamp':time.time(),'collected_at':time.time()}
        for changes in [{'bid':float('nan')},{'ask':9.},{'ask_size':-1.},{'timestamp':time.time()+30}]:
            with patch('hosted_reader.Bitget') as market:
                market.return_value.quote.return_value={**q,**changes}
                with self.assertRaises(ValueError):read('quote','RAMDUSDT')

    def test_approved_article_paths_remain_issuer_specific(self):
        fixtures={'RAAPLUSDT':'https://www.apple.com/newsroom/2026/10/example/', 'RNVDAUSDT':'https://nvidianews.nvidia.com/news/example', 'RMSFTUSDT':'https://news.microsoft.com/source/2026/10/08/example/', 'RAMZNUSDT':'https://ir.aboutamazon.com/news-release/news-release-details/2026/Example/default.aspx', 'RMETAUSDT':'https://investor.atmeta.com/investor-news/press-release-details/2026/Example/default.aspx', 'RAMDUSDT':'https://ir.amd.com/news-events/press-releases/detail/123/example','RINTCUSDT':'https://www.intc.com/news-events/press-releases/detail/123/example','RAVGOUSDT':'https://investors.broadcom.com/news-releases/news-release-details/example'}
        self.assertEqual(set(fixtures),set(STOCKS))
        for symbol,url in fixtures.items():
            self.assertTrue(approved_url(url,symbol),url)
            self.assertFalse(approved_url(url+'?redirect=http://localhost',symbol))
            self.assertFalse(approved_url(url.replace('https://','http://'),symbol))
            self.assertFalse(approved_url('https://evil.test/news/example',symbol))
