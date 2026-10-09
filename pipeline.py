"""Primary-feed ingestion and public Bitget adapters for THESIS."""
from __future__ import annotations

import hashlib
import html
import json
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from agent import canonical

from stocks import STOCKS as SOURCES


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.ignore = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignore:
            self.ignore -= 1

    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)


def plain(value):
    parser = TextOnly()
    parser.feed(html.unescape(value or ""))
    return " ".join(" ".join(parser.parts).split())


def trusted_url(url, hosts):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in hosts and parsed.port in (None, 443) and not parsed.username and not parsed.password


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl, self.hosts):
            raise ValueError("Feed redirect left the approved issuer domains")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        raise ValueError("Publication timestamp has no timezone")
    return parsed.timestamp()


def parse_feed(raw, source, symbol, observed_at):
    if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
        raise ValueError("XML entities and document types are not allowed")
    root = ET.fromstring(raw)
    atom = "{http://www.w3.org/2005/Atom}"
    entries = root.findall("./channel/item") or root.findall(atom + "entry")
    events = []
    for item in entries[:40]:
        try:
            is_atom = item.tag.startswith(atom)
            def text(tag):
                node = item.find((atom if is_atom else "") + tag)
                return "" if node is None else "".join(node.itertext()).strip()
            title = plain(text("title"))
            if is_atom:
                link = next((x.get("href", "") for x in item.findall(atom + "link") if x.get("rel", "alternate") == "alternate"), "")
                date = text("published") or text("updated")
                body = text("summary") or text("content")
            else:
                link, date, body = text("link"), text("pubDate"), text("description")
            if not trusted_url(link, source["hosts"]) or not title:
                continue
            published = timestamp(date)
            if published > observed_at + 2:
                continue
            # Source URL identifies an event; a revised headline does not cause a second trade.
            parsed = urllib.parse.urlsplit(link)
            normalized_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            sid = hashlib.sha256((symbol + normalized_url).encode()).hexdigest()[:24]
            text_value = (title + ". " + plain(body))[:5000]
            events.append({"id": sid, "symbol": symbol, "title": title, "text": text_value,
                           "url": link, "source_kind": "issuer", "evidence_scope": "issuer RSS/Atom excerpt",
                           "published_at": published, "observed_at": observed_at,
                           "text_sha256": hashlib.sha256(text_value.encode()).hexdigest()})
        except (ValueError, TypeError, AttributeError):
            continue
    return sorted(events, key=lambda x: x["published_at"], reverse=True)


def collect_feed(symbol, archive_dir=None):
    source = SOURCES[symbol]
    opener = urllib.request.build_opener(RestrictedRedirect(source["hosts"]))
    request = urllib.request.Request(source["feed"], headers={"User-Agent": "THESIS-Hackathon-Research/0.2", "Accept": "application/atom+xml, application/rss+xml, application/xml"})
    with opener.open(request, timeout=20) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Feed exceeds maximum size")
    observed_at = time.time()
    digest = hashlib.sha256(raw).hexdigest()
    events = parse_feed(raw, source, symbol, observed_at)
    if archive_dir:
        root = Path(archive_dir)
        root.mkdir(parents=True, exist_ok=True)
        file = root / (digest + ".xml")
        if not file.exists():
            file.write_bytes(raw)
    for event in events:
        event["feed_sha256"] = digest
    return events


class Bitget:
    def __init__(self, archive_dir=None):
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self.cache, self.last_call, self.lock = {}, {}, threading.Lock()

    def get(self, path, ttl=0, **params):
        url = "https://api.bitget.com" + path + ("?" + urllib.parse.urlencode(params) if params else "")
        with self.lock:
            cached = self.cache.get(url)
            if cached and time.time() - cached[0] < ttl:
                return cached[1]
            if path.startswith("/api/v3/reality/"):
                pause = 1.05 - (time.monotonic() - self.last_call.get(path, 0))
                if pause > 0:
                    time.sleep(pause)
            req = urllib.request.Request(url, headers={"User-Agent": "THESIS-Hackathon-Research/0.2"})
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(3_000_001)
            self.last_call[path] = time.monotonic()
            if len(raw) > 3_000_000:
                raise ValueError("API response too large")
            result = json.loads(raw)
            if result.get("code") != "00000":
                raise RuntimeError("Bitget response code " + str(result.get("code")))
            observed = time.time()
            if self.archive_dir:
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                record = {"url": url, "observed_at": observed, "response": result}
                digest = hashlib.sha256(canonical(record).encode()).hexdigest()
                (self.archive_dir / (digest + ".json")).write_text(canonical(record))
            self.cache[url] = (observed, result["data"])
            return result["data"]

    def instrument(self, symbol):
        rows = self.get("/api/v3/market/instruments", ttl=300, category="SPOT", symbol=symbol)
        row = next((x for x in rows if x.get("symbol") == symbol), None)
        if row is None:
            raise ValueError("Requested instrument is unavailable")
        return {"symbol": symbol, "status": row["status"], "is_reality": str(row.get("isReality", "")).lower() == "yes",
                "quantity_precision": int(row["quantityPrecision"]), "min_notional": float(row["minOrderAmount"])}

    def quote(self, symbol):
        rows = self.get("/api/v3/market/tickers", category="SPOT", symbol=symbol)
        row = next((x for x in rows if x.get("symbol") == symbol), None)
        if row is None:
            raise ValueError("No ticker for the requested instrument")
        return {"bid": float(row["bid1Price"]), "ask": float(row["ask1Price"]),
                "bid_size": float(row["bid1Size"]), "ask_size": float(row["ask1Size"]),
                "timestamp": int(row["ts"]) / 1000, "collected_at": time.time()}

    def session(self, symbol, now=None):
        stocks = self.get("/api/v3/reality/market/stock-info", ttl=300, symbol=symbol)
        stock = next((x for x in stocks if x.get("symbol") == symbol), None)
        calendar = self.get("/api/v3/reality/market/calendar", ttl=300)
        sessions = self.get("/api/v3/reality/market/states", ttl=300)
        return resolve_session(stock, calendar, sessions, time.time() if now is None else now)

    def reference(self, symbol, published_at):
        end = int(published_at // 60 * 60 * 1000) - 1
        rows = self.get("/api/v3/market/history-candles", ttl=300, category="SPOT", symbol=symbol,
                        interval="1m", startTime=end - 600_000, endTime=end, limit="10")
        eligible = [x for x in rows if int(x[0]) / 1000 + 60 <= published_at and float(x[4]) > 0]
        if not eligible:
            return None
        row = max(eligible, key=lambda x: int(x[0]))
        return {"price": float(row[4]), "bar_open_at": int(row[0]) / 1000, "bar_close_at": int(row[0]) / 1000 + 60,
                "description": "Last retrieved fully closed 1-minute candle before publication; not proof of event causation"}


def resolve_session(stock, calendar, sessions, now):
    local = datetime.fromtimestamp(now, ZoneInfo("America/New_York"))
    if not stock or not isinstance(calendar, dict):
        return {"tradable": False, "reason": "Trading metadata unavailable"}
    if isinstance(sessions, list):
        sessions = next((x for x in sessions if x.get("market") == "US"), {})
    expected = "dst" if local.dst() else "standard"
    daylight_conflict = sessions.get("daylightType") != expected
    coverage = [False] * 1440
    for row in sessions.get("stateList", []):
        try:
            sh, sm = map(int, row["startTime"].split(":"))
            eh, em = map(int, row["endTime"].split(":"))
            start, end = sh * 60 + sm, eh * 60 + em
            if not (0 <= start < 1440 and 0 <= end < 1440):
                raise ValueError("Bad session boundary")
            if row["state"] in stock.get("tradingPeriod", []):
                for minute in range(1440):
                    if (start <= minute < end if start < end else minute >= start or minute < end):
                        coverage[minute] = True
        except (KeyError, ValueError, TypeError):
            return {"tradable": False, "reason": "Unrecognized session metadata"}
    full_day = all(coverage)
    # A timezone offset cannot change eligibility when every minute is supported.
    # Partial-day instruments still require consistent timezone metadata.
    if daylight_conflict and not full_day:
        return {"tradable": False, "reason": "Exchange daylight metadata needs reconciliation", "session": "unverified"}
    for closure in calendar.get("specificConfig", []):
        try:
            start = datetime.fromisoformat(closure["startTime"]).replace(tzinfo=local.tzinfo)
            end = datetime.fromisoformat(closure["endTime"]).replace(tzinfo=local.tzinfo)
            if daylight_conflict:
                start, end = start - timedelta(hours=1), end + timedelta(hours=1)
            if start <= local < end:
                return {"tradable": False, "reason": "Market holiday or special closure"}
        except (KeyError, ValueError, TypeError):
            return {"tradable": False, "reason": "Unrecognized market calendar entry"}
    # Conservatively defer weekends until token-specific closure precedence is established.
    if local.strftime("%A").upper() in calendar.get("regularConfig", []):
        return {"tradable": False, "reason": "Calendar closure; token weekend precedence is not yet verified"}
    if daylight_conflict and full_day:
        return {"tradable": True, "session": "all_daily_sessions", "reason": "All daily sessions supported; daylight label conflict recorded for review", "metadata_warning": "Exchange daylight label differs from America/New_York; full 24-hour coverage makes the offset immaterial outside closures"}
    minute = local.hour * 60 + local.minute
    for row in sessions.get("stateList", []):
        try:
            sh, sm = map(int, row["startTime"].split(":"))
            eh, em = map(int, row["endTime"].split(":"))
            start, end = sh * 60 + sm, eh * 60 + em
            inside = start <= minute < end if start < end else minute >= start or minute < end
            if inside:
                allowed = row["state"] in stock.get("tradingPeriod", [])
                return {"tradable": allowed, "session": row["state"], "reason": "Supported trading session" if allowed else "Instrument unavailable in this session"}
        except (KeyError, ValueError, TypeError):
            return {"tradable": False, "reason": "Unrecognized session metadata"}
    return {"tradable": False, "reason": "No verified current trading session"}


def build_packet(event, market, session, reference=None):
    quote = market["quote"]
    midpoint = (quote["bid"] + quote["ask"]) / 2
    reaction = (midpoint / reference["price"] - 1) * 10000 if reference else None
    return {"event_id": event["id"], "evidence_mode": "observed", "symbol": event["symbol"],
            "session_tradable": session["tradable"], "session_details": session,
            "quote": quote, "instrument": market["instrument"], "evidence": [event],
            "pre_event_reference": reference, "price_reaction_bps": reaction,
            "reference_limitations": "Observed price change is not causal attribution. Missing reference means the already-priced-in hypothesis cannot be evaluated."}


def benchmark_decision(packet, state, policy):
    """Predeclared simple momentum rule; this is not an AI model."""
    reaction = packet.get("price_reaction_bps")
    weight = state["quantity"] * packet["quote"]["bid"] / max(1, state["cash"] + state["quantity"] * packet["quote"]["bid"])
    buy = reaction is not None and 20 <= reaction <= 100 and weight < 0.049
    sell = reaction is not None and reaction < -20 and state["quantity"] > 0
    return {"action": "buy" if buy else "sell" if sell else "hold", "target_weight": 0.05 if buy else 0.0 if sell else weight,
            "expected_remaining_move_bps": 100.0 if buy else 0.0, "source_ids": [packet["evidence"][0]["id"]],
            "thesis": "Fixed comparison rule: buy a 20–100 bps response; reduce below −20 bps; otherwise hold.",
            "priced_in_assessment": "No semantic interpretation; the 100 bps remaining-move estimate is a fixed heuristic.",
            "invalidation": "Identical fixed stop, expiry and execution constraints apply."}
