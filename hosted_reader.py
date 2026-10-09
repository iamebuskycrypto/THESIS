"""Stateless public-source reader. No credentials, orders or model calls."""
import math
import time
from pipeline import Bitget, SOURCES, collect_feed
from issuer_article import collect_article, select_passages
from stocks import public_stocks


def read(action, symbol=None, event_id=None):
    if action == 'stocks':
        return {'stocks': public_stocks(), 'key_required': False, 'mode': 'source_reader'}
    if symbol not in SOURCES:
        raise ValueError('Choose one of the supported stocks.')
    if action == 'quote':
        quote = Bitget().quote(symbol)
        if (any(not math.isfinite(v) for v in quote.values()) or quote['bid'] <= 0
                or quote['ask'] < quote['bid'] or min(quote['bid_size'], quote['ask_size']) < 0
                or quote['timestamp'] > time.time() + 10):
            raise ValueError('The exchange returned an unusable quote.')
        mid = (quote['bid'] + quote['ask']) / 2
        return {'symbol': symbol, 'quote': quote, 'midpoint': mid,
                'spread_bps': (quote['ask'] - quote['bid']) / mid * 10000,
                'instrument_type': 'Bitget stock token',
                'source_url': 'https://api.bitget.com/api/v3/market/tickers?category=SPOT&symbol=' + symbol}
    if action not in ('news', 'source'):
        raise ValueError('Unknown reader action.')
    events = collect_feed(symbol)
    if action == 'news':
        return {'symbol': symbol, 'events': events, 'collected_at': time.time(),
                'source_url': SOURCES[symbol]['feed']}
    # Clients send an ID, never a URL; articles must come from the approved feed.
    event = next((e for e in events if e['id'] == event_id), None)
    if event is None:
        raise ValueError('This announcement is no longer in the company feed. Refresh news.')
    article = collect_article(event)
    passages = select_passages(article) if article['status'] == 'retrieved' else []
    return {'mode': 'source_reader', 'model_calls': 0, 'event': event,
            'article': {k: article[k] for k in ('status', 'reason', 'retrieved_at', 'characters') if k in article},
            'passages': passages, 'captured_at': time.time(),
            'scope': 'Issuer statements copied from public sources. No AI assessment or trade was made.'}
