"""Single stock/source catalogue shared by the local app and hosted reader."""

STOCKS = {
    'RAAPLUSDT': {'ticker': 'AAPL', 'company': 'Apple', 'feed': 'https://www.apple.com/newsroom/rss-feed.rss', 'hosts': ['www.apple.com', 'apple.com'], 'article_path': r'/newsroom/\d{4}/\d{2}/[\w-]+/?'},
    'RNVDAUSDT': {'ticker': 'NVDA', 'company': 'NVIDIA', 'feed': 'https://nvidianews.nvidia.com/cats/press_release.xml', 'hosts': ['nvidianews.nvidia.com', 'nvidia.com', 'www.nvidia.com'], 'article_path': r'/news/[\w-]+/?'},
    'RMSFTUSDT': {'ticker': 'MSFT', 'company': 'Microsoft', 'feed': 'https://news.microsoft.com/feed/', 'hosts': ['news.microsoft.com'], 'article_path': r'/(?:source/)?\d{4}/\d{2}/\d{2}/[\w-]+/?'},
    'RAMZNUSDT': {'ticker': 'AMZN', 'company': 'Amazon', 'feed': 'https://ir.aboutamazon.com/rss/pressrelease.aspx', 'hosts': ['ir.aboutamazon.com'], 'article_path': r'/news-release/news-release-details/\d{4}/[\w-]+/default.aspx'},
    'RMETAUSDT': {'ticker': 'META', 'company': 'Meta', 'feed': 'https://investor.atmeta.com/rss/pressrelease.aspx', 'hosts': ['investor.atmeta.com'], 'article_path': r'/investor-news/press-release-details/\d{4}/[\w-]+/default.aspx'},
    'RAMDUSDT': {'ticker': 'AMD', 'company': 'AMD', 'feed': 'https://ir.amd.com/news-events/press-releases/rss', 'hosts': ['ir.amd.com'], 'article_path': r'/news-events/press-releases/detail/\d+/[\w-]+/?'},
    'RINTCUSDT': {'ticker': 'INTC', 'company': 'Intel', 'feed': 'https://www.intc.com/news-events/press-releases/rss', 'hosts': ['www.intc.com'], 'article_path': r'/news-events/press-releases/detail/\d+/[\w-]+/?'},
    'RAVGOUSDT': {'ticker': 'AVGO', 'company': 'Broadcom', 'feed': 'https://investors.broadcom.com/rss/news-releases.xml', 'hosts': ['investors.broadcom.com'], 'article_path': r'/news-releases/news-release-details/[\w-]+/?'},
}

def public_stocks():
    return [{'symbol': symbol, 'ticker': row['ticker'], 'company': row['company'],
             'source_url': row['feed']} for symbol, row in STOCKS.items()]
