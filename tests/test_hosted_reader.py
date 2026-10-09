"""Public read-only routes cannot turn visitor input into arbitrary fetches."""
import time
import unittest
from unittest.mock import patch
from hosted_reader import read
from issuer_article import approved_url
from stocks import STOCKS
from pathlib import Path

class ReaderTests(unittest.TestCase):
    def test_catalogue_covers_nineteen_stocks_without_keys(self):
        result=read('stocks')
        self.assertFalse(result['key_required'])
        self.assertEqual(len(result['stocks']),19)
        self.assertEqual(len({s['ticker'] for s in result['stocks']}),19)
        for s in result['stocks']:
            self.assertNotIn('key',s)
            self.assertTrue(s['source_url'].startswith('https://'))
            self.assertRegex(s['logo'], r'^/logos/[A-Z0-9]+\.(png|svg)$')
            self.assertTrue((Path(__file__).parents[1] / 'public' / s['logo'].lstrip('/')).is_file())

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
        fixtures.update({'RGOOGLUSDT': 'https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Date-of-Third-Quarter-2026-Financial-Results-Conference-Call-2026-8tpGZsLS6v/default.aspx', 'RNFLXUSDT': 'https://ir.netflix.net/investor-news-and-events/financial-releases/press-release-details/2026/Netflix-to-Announce-Third-Quarter-2026-Financial-Results/default.aspx', 'RCOINUSDT': 'https://investor.coinbase.com/news/news-details/2026/Coinbase-to-Participate-in-Citis-2026-Global-TMT-Conference/default.aspx', 'RCRMUSDT': 'https://investor.salesforce.com/news/news-details/2026/Live-Nation-Makes-Show-Day-Easier-for-Fans-With-Salesforces-Agentforce/default.aspx', 'RQCOMUSDT': 'https://investor.qualcomm.com/news-events/press-releases/news-details/2026/Qualcomm-Announces-Multi-Generational-Product-Collaboration-with-Amazon-to-Build-Next-Generation-AI-Data-Center-Infrastructure/default.aspx', 'RPYPLUSDT': 'https://investor.pypl.com/news-and-events/news-details/2026/The-Venmo-Credit-Card-Now-Pays-Up-to-4-Cash-Back-When-You-Split-with-Friends/default.aspx', 'RUBERUSDT': 'https://investor.uber.com/news-events/news/press-release-details/2026/Sur-la-table-Arrives-on-Uber-Eats-Delivering-Chef-Trusted-Kitchen-Gear-to-Customers-Nationwide/default.aspx', 'RNKEUSDT': 'https://investors.nike.com/investors/news-events-and-reports/investor-news/investor-news-details/2026/NIKE-Inc--Reports-Fiscal-2027-First-Quarter-Results/default.aspx', 'RKOUSDT': 'https://investors.coca-colacompany.com/news-events/press-releases/detail/1173/the-coca-cola-company-announces-timing-of-third-quarter-2026-earnings-release', 'RVUSDT': 'https://investor.visa.com/news/news-details/2026/Visa-to-Announce-Fiscal-Fourth-Quarter-and-Full-Year-2026-Financial-Results-on-October-27-2026/default.aspx', 'RMAUSDT': 'https://investor.mastercard.com/investor-news/investor-news-details/2026/Mastercard-Incorporated-to-Host-Conference-Call-on-Third-Quarter-2026-Financial-Results/default.aspx'})
        self.assertEqual(set(fixtures),set(STOCKS))
        for symbol,url in fixtures.items():
            self.assertTrue(approved_url(url,symbol),url)
            self.assertFalse(approved_url(url+'?redirect=http://localhost',symbol))
            self.assertFalse(approved_url(url.replace('https://','http://'),symbol))
            self.assertFalse(approved_url('https://evil.test/news/example',symbol))
