"""Bounded official-newsroom retrieval for research reviews only; stdlib only."""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 2_000_000
MAX_TEXT = 80_000
MODEL_TEXT_BUDGET = 5000
MAX_PASSAGES = 24
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
IGNORE = {'script','style','nav','footer','aside','form','button','noscript','iframe','svg','figure'}


def normalized(value):
    return re.sub(r'\s+', ' ', value).strip()


def approved_url(url, symbol):
    try:
        p = urllib.parse.urlsplit(url)
        if (p.scheme != 'https' or p.port not in (None, 443) or p.username or p.password
                or p.query or p.fragment or '\\' in url or any(ord(c) < 32 for c in url)):
            return False
        if symbol == 'RAAPLUSDT':
            return p.hostname in ('www.apple.com','apple.com') and bool(re.fullmatch(r'/newsroom/\d{4}/\d{2}/[\w-]+/?', p.path))
        return symbol == 'RNVDAUSDT' and p.hostname == 'nvidianews.nvidia.com' and bool(re.fullmatch(r'/news/[\w-]+/?', p.path))
    except (TypeError, ValueError):
        return False


def same_article(left, right, symbol):
    return (approved_url(left, symbol) and approved_url(right, symbol)
            and urllib.parse.urlsplit(left).path.rstrip('/') == urllib.parse.urlsplit(right).path.rstrip('/'))


class ArticleRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, url, symbol):
        self.url, self.symbol, self.count = url, symbol, 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > 3 or not same_article(self.url, newurl, self.symbol):
            raise ValueError('Article redirect did not preserve the approved issuer article')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()

    def text(self):
        if self.tag in IGNORE or 'hidden' in self.attrs or self.attrs.get('aria-hidden') == 'true':
            return ''
        return ''.join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node) and child.tag not in IGNORE:
                yield from child.walk()


class ArticleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node(); self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def extract_article(raw, event):
    parser = ArticleHTML()
    parser.feed(raw.decode('utf-8-sig', errors='replace'))
    nodes = list(parser.root.walk())
    titles = [normalized(n.text()) for n in nodes if n.tag == 'h1']
    title = next((t for t in titles if t), '')
    words = lambda s: set(re.findall(r'\w+', s.casefold()))
    expected = words(event['title']); actual = words(title)
    if len(expected & actual) < min(4, len(expected)) or len(expected & actual) / max(1, len(expected)) < .7:
        raise ValueError('Article title did not match the collected announcement')
    canonicals = [n.attrs.get('href','') for n in nodes if n.tag == 'link' and 'canonical' in n.attrs.get('rel','').split()]
    if canonicals and not all(same_article(event['url'], u, event['symbol']) for u in canonicals):
        raise ValueError('Article canonical address did not match the announcement')
    if event['symbol'] == 'RNVDAUSDT':
        roots = [n for n in nodes if n.has_class('article-body')]
        candidates = []
        for root in roots[:1]:
            for n in root.walk():
                if n.tag in ('p','li','h2','h3') and not any(c.tag in ('p','li') for c in n.walk() if c is not n):
                    candidates.append(normalized(n.text()))
    else:
        # Apple newsroom article prose; exclude captions, related news and navigation.
        candidates = [normalized(n.text()) for n in nodes if n.has_class('pagebody-copy')]
        if not candidates:
            for root in (n for n in nodes if n.has_class('pagebody')):
                candidates.extend(normalized(n.text()) for n in root.walk() if n.tag == 'p')
    paragraphs = []
    for value in candidates:
        if value and value not in paragraphs:
            paragraphs.append(value)
    body = '\n\n'.join(paragraphs)
    if len(body) < 200 or len(paragraphs) < 2:
        raise ValueError('Recognized article prose was unavailable; the page may have changed')
    if len(body) > MAX_TEXT:
        raise ValueError('Article text exceeded the review limit')
    return {'title': title, 'paragraphs': paragraphs, 'text_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'extraction_method': 'issuer-selectors-1', 'characters': len(body),
            'html_sha256': hashlib.sha256(raw).hexdigest()}


def select_passages(article):
    """Ordered prefix, not model-selected snippets. Partial coverage stays explicit."""
    rows = []; remaining = MODEL_TEXT_BUDGET
    for index, paragraph in enumerate(article['paragraphs'], 1):
        if remaining <= 0 or len(rows) >= MAX_PASSAGES:
            break
        text = paragraph[:remaining]
        partial = len(text) != len(paragraph)
        if partial:
            # End at a word boundary and disclose that this paragraph was cut.
            text = text.rsplit(' ', 1)[0]
        if len(text) < 8:
            break
        rows.append({'id': f'article_{index:03d}', 'kind': 'observed',
                     'title': f'Official article · passage {index}', 'text': text,
                     'url': article['final_url'], 'observed_at': article['retrieved_at'],
                     'paragraph_number': index, 'partial_paragraph': partial})
        remaining -= len(text)
        if partial:
            break
    return rows


def collect_article(event):
    started = time.time()
    result = {'status':'unavailable', 'requested_url':event['url'], 'attempted_at':started}
    if not approved_url(event['url'], event['symbol']):
        return {**result, 'reason':'The article address is outside the supported official newsroom paths.'}
    try:
        opener = urllib.request.build_opener(ArticleRedirect(event['url'], event['symbol']))
        request = urllib.request.Request(event['url'], headers={'User-Agent':'THESIS-Research/0.5',
            'Accept':'text/html', 'Accept-Encoding':'identity'})
        with opener.open(request, timeout=10) as response:
            if response.status != 200 or not same_article(event['url'], response.geturl(), event['symbol']):
                raise ValueError('The issuer did not return the requested article')
            if response.headers.get_content_type() not in ('text/html','application/xhtml+xml'):
                raise ValueError('The issuer response was not an HTML article')
            if response.headers.get('Content-Encoding','identity').lower() not in ('','identity'):
                raise ValueError('Unsupported article encoding')
            chunks = []; size = 0
            while True:
                if time.time() - started > 25:
                    raise TimeoutError('Article collection deadline')
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Article download exceeded the size limit')
                chunks.append(chunk)
            raw = b''.join(chunks)
            final_url = response.geturl()
        result.update(extract_article(raw, event))
        result.update(status='retrieved', final_url=final_url, retrieved_at=time.time())
        passages = select_passages(result)
        covered = sum(len(p['text']) for p in passages)
        result.update(passages=passages, supplied_characters=covered, supplied_passages=len(passages),
                      coverage='partial' if covered < sum(map(len,result['paragraphs'])) else 'all_extracted_prose')
    except Exception as exc:
        # Never save HTTP bodies, headers, cookies or provider error messages.
        result.update(reason='Official article could not be retrieved or verified (' + type(exc).__name__ + ').',
                      completed_at=time.time())
    return result


def attach_article(context, article):
    """Called only for new research context; old saved evidence is never enriched."""
    context['article'] = article
    if article['status'] == 'retrieved':
        note = (f"Official article prose was retrieved at {article['retrieved_at']}; "
                f"{article['supplied_passages']} passages ({article['supplied_characters']} characters) are supplied to the model. "
                + ('Some extracted article text was omitted to fit the local model. ' if article['coverage'] == 'partial' else '')
                + 'The page may include updates made after original publication. Issuer claims are not independently verified.')
        context['evidence'][1:1] = article['passages']
    else:
        note = 'Only the issuer feed excerpt is supplied. ' + article['reason']
    context['limitations'][0] = note
    for row in context['evidence']:
        if row['id'] == 'limits':
            row['text'] = ' '.join(context['limitations'])
    return context
