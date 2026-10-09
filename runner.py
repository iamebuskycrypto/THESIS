"""THESIS application state, feed polling and bounded paper-only execution."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path

from agent import Engine, LLM, Policy, SYSTEM_PROMPT, canonical, synthetic_decision, synthetic_packet
from pipeline import Bitget, SOURCES, benchmark_decision, build_packet, collect_feed
from research import ResearchReviews
from stocks import public_stocks


class EventStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = str(self.directory / "events.db")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, published REAL, body TEXT)")

    def connect(self):
        return sqlite3.connect(self.database, timeout=10)

    def add(self, events):
        with self.connect() as db:
            for event in events:
                db.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?)", (event["id"], event["published_at"], canonical(event)))

    def events(self, limit=30):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY published DESC LIMIT ?", (limit,))]

    def get(self, event_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM events WHERE id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None


def mechanical_demo():
    """A repeatable story built from the actual executor, with scripted decisions."""
    engine = Engine(":memory:", "DEMO_STOCK", mode="synthetic")
    packet = synthetic_packet(1000)
    scenarios = []
    def run(title, note, changes=None, decision_changes=None, clock=1000):
        p = copy.deepcopy(packet)
        p["event_id"] = "demo-" + str(len(scenarios))
        p["quote"]["timestamp"] = clock
        if changes:
            changes(p)
        def scripted_demo(*args):
            return {**synthetic_decision(*args), **(decision_changes or {})}
        row = engine.step(p, scripted_demo, now=clock)
        scenarios.append({"title": title, "note": note, "result": row})
    run("A possible opportunity", "A scripted buy clears the entry checks. The simulator charges fees and adverse slippage.")
    run("The price already moved", "The scripted decision waits because the example assumes little remaining upside.",
        decision_changes={"action": "hold", "thesis": "The example assumes the price has absorbed the news.", "expected_remaining_move_bps": 10.0})
    run("Costs remove the opportunity", "The proposed extra position is rejected because its estimated move does not cover the cost buffer.",
        decision_changes={"target_weight": 0.08, "expected_remaining_move_bps": 20.0})
    run("Too little stock available", "A good-looking idea cannot ignore the quantity offered at the quoted price.",
        changes=lambda p: p["quote"].update(ask_size=0.1), decision_changes={"target_weight": 0.08})
    run("The quote is too old", "The system refuses to use a price that is no longer fresh.",
        changes=lambda p: p["quote"].update(timestamp=900))
    run("Reduce the position", "A scripted exit sells the simulated holding and records costs on the sale.",
        decision_changes={"action": "sell", "target_weight": 0.0, "thesis": "The demonstration closes its simulated position."})
    engine.export()
    engine.db.close()
    return {"mode": "synthetic", "label": "Scripted demonstration — not AI reasoning or performance evidence", "scenarios": scenarios}


class Application:
    def __init__(self, directory="run-data"):
        self.root = Path(directory)
        self.store = EventStore(self.root)
        self.market = Bitget(self.root / "raw-market")
        self.policy = Policy()
        self.lock, self.cycle_lock = threading.RLock(), threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        self.model = None
        self.status = "Ready to collect observations"
        self.error = None
        self.busy = False
        self.last_observed = None
        self.markets = {}
        self.feed_polled_at = {}
        saved = self.root / "observations.json"
        if saved.exists():
            previous = json.loads(saved.read_text())
            self.markets, self.last_observed = previous.get("markets", {}), previous.get("last_observed")
        try:
            self.model = LLM()
            self.status = "Model configured from environment; ready for a connection test"
        except ValueError:
            pass
        self.reviews = ResearchReviews(self.root / "research-reviews", self)

    def engine(self, symbol, kind="agent"):
        if symbol not in SOURCES or kind not in ("agent", "benchmark"):
            raise ValueError("Unknown ledger")
        return Engine(str(self.root / ("v02-" + kind + "-" + symbol + ".db")), symbol, policy=self.policy)

    def connect_model(self, endpoint, model, key):
        with self.cycle_lock:
            candidate = LLM(endpoint=endpoint, model=model, key=key)
            self.check_profile(candidate)
            candidate.ping()
            with self.lock:
                self.model = candidate
                self.status, self.error = "Model connected; paper trading is available", None

    def check_profile(self, candidate, save=False):
        profile = {"model": candidate.model, "endpoint": candidate.endpoint,
                   "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), "policy": asdict(self.policy),
                   "benchmark": "price-response-rule-v1",
                   "request_settings": copy.deepcopy(getattr(candidate, "request_settings", None))}
        path = self.root / "run-profile.json"
        if path.exists():
            previous = json.loads(path.read_text())
            if previous != profile:
                legacy = {key: value for key, value in profile.items() if key != "request_settings"}
                # A monitoring-only run can adopt recorded request settings.
                # Any existing ledger record requires a separate evaluation run.
                if previous != legacy or self._has_ledger_records():
                    raise ValueError("This run already uses another model, prompt, policy or request settings. Start a new --data directory for a separate evaluation.")
                if save:
                    archive = self.root / "run-profile-before-local-fix.json"
                    if not archive.exists():
                        archive.write_text(canonical(previous))
                    temporary = path.with_suffix(".json.tmp")
                    temporary.write_text(canonical(profile))
                    temporary.replace(path)
        if save and not path.exists():
            path.write_text(canonical(profile))

    def _has_ledger_records(self):
        for symbol in SOURCES:
            for kind in ("agent", "benchmark"):
                path = self.root / ("v02-" + kind + "-" + symbol + ".db")
                if path.exists():
                    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
                    try:
                        if connection.execute("SELECT 1 FROM ledger LIMIT 1").fetchone():
                            return True
                    finally:
                        connection.close()
        return False

    def observe(self, force_feeds=False):
        """Collect data only. Does not call an LLM or start a trading loop."""
        markets, errors = {}, []
        for symbol in SOURCES:
            if force_feeds or time.time() - self.feed_polled_at.get(symbol, 0) > 300:
                try:
                    self.store.add(collect_feed(symbol, self.root / "raw-news"))
                    self.feed_polled_at[symbol] = time.time()
                except Exception as exc:
                    errors.append(SOURCES[symbol]["company"] + " news: " + type(exc).__name__)
            try:
                instrument = self.market.instrument(symbol)
                session = self.market.session(symbol)
                # Fetch the short-lived quote last.
                quote = self.market.quote(symbol)
                markets[symbol] = {"symbol": symbol, "company": SOURCES[symbol]["company"],
                                   "instrument": instrument, "session": session, "quote": quote}
                for kind in ("agent", "benchmark"):
                    engine = self.engine(symbol, kind)
                    try:
                        engine.mark(quote)
                    finally:
                        engine.db.close()
            except Exception as exc:
                errors.append(SOURCES[symbol]["company"] + " market: " + type(exc).__name__)
        with self.lock:
            self.markets, self.last_observed = markets, time.time()
            self.error = "; ".join(errors) or None
            self.status = "Observations updated" if markets else "No usable market observations collected"
            (self.root / "observations.json").write_text(canonical({"markets": markets, "last_observed": self.last_observed, "error": self.error}))
        return markets

    def _monitor(self, symbol, market):
        quote = market["quote"]
        sid = "quote-" + symbol + "-" + str(quote["timestamp"])
        event = {"id": sid, "symbol": symbol, "source_kind": "exchange", "url": "https://api.bitget.com/api/v3/market/tickers",
                 "published_at": quote["timestamp"], "observed_at": quote["collected_at"],
                 "text": "Observed exchange quote for fixed position monitoring."}
        packet = build_packet(event, market, market["session"])
        for kind in ("agent", "benchmark"):
            engine = self.engine(symbol, kind)
            try:
                engine.monitor(packet)
            finally:
                engine.db.close()

    def run_once(self):
        if self.model is None:
            raise ValueError("Connect an AI model before starting a paper run")
        self.check_profile(self.model, save=True)
        markets = self.observe()
        for symbol, market in markets.items():
            if market["session"]["tradable"]:
                self._monitor(symbol, market)
        considered = 0
        for event in reversed(self.store.events(80)):
            symbol = event["symbol"]
            if self.stop_event.is_set() or symbol not in markets:
                continue
            market = markets[symbol]
            if not market["session"]["tradable"] or time.time() - event["published_at"] > self.policy.max_event_age_seconds:
                continue
            engine = self.engine(symbol)
            try:
                if engine.db.execute("SELECT 1 FROM ledger WHERE event_id=?", (event["id"],)).fetchone():
                    continue
                reference = self.market.reference(symbol, event["published_at"])
                fresh_market = {**market, "quote": self.market.quote(symbol)}
                packet = build_packet(event, fresh_market, market["session"], reference)
                result = engine.step(packet, self.model, refresh_quote=lambda: self.market.quote(symbol))
                considered += 1
                # Run the comparison only for a validated AI decision. An outage is not an AI strategy result.
                if result.get("decision") is not None and result.get("execution_packet"):
                    baseline = self.engine(symbol, "benchmark")
                    try:
                        baseline.step(result["execution_packet"], benchmark_decision, now=result["decision_time"])
                    finally:
                        baseline.db.close()
            finally:
                engine.db.close()
        with self.lock:
            self.status = f"Paper cycle complete: {considered} new event(s) considered"
        return considered

    def job(self, operation):
        if not self.cycle_lock.acquire(blocking=False):
            raise ValueError("Another collection or paper cycle is still running")
        self.busy = True
        self.error = None
        def work():
            try:
                if operation == "observe":
                    self.observe(force_feeds=True)
                elif operation == "cycle":
                    self.stop_event.clear()
                    self.run_once()
                else:
                    raise ValueError("Unknown job")
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)[:200] if isinstance(exc, ValueError) else type(exc).__name__
                    self.status = "Action stopped; inspect the status message"
            finally:
                self.busy = False
                self.cycle_lock.release()
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.model is None:
            raise ValueError("Connect an AI model first")
        if self.busy:
            raise ValueError("Wait for the current review or collection to finish before starting monitoring")
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                if self.cycle_lock.acquire(blocking=False):
                    self.busy = True
                    try:
                        self.run_once()
                    except Exception as exc:
                        with self.lock:
                            self.error = type(exc).__name__
                    finally:
                        self.busy = False
                        self.cycle_lock.release()
                self.stop_event.wait(60)
        self.worker = threading.Thread(target=loop, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status = "Monitoring paused; an in-flight request may finish"

    def ledger(self, symbol, kind="agent"):
        engine = self.engine(symbol, kind)
        try:
            rows = engine.export()
            state = engine.state()
            marks = [{"timestamp": x[0], "equity": x[1], "exposure": x[2]} for x in engine.db.execute("SELECT ts, equity, exposure FROM marks ORDER BY ts DESC LIMIT 240")][::-1]
            fees = sum((r.get("fill") or {}).get("fee", 0) for r in rows)
            # Fixed position exits and data failures are records, not AI decisions.
            decisions = sum(r.get('decision') is not None and any(
                e.get('source_kind') != 'exchange' for e in r.get('packet', {}).get('evidence', [])) for r in rows)
            equity = state['cash'] + state['quantity'] * state['last_bid']
            return {"symbol": symbol, "kind": kind, "state": state, "records": rows,
                    "summary": {"decisions": decisions, "records": len(rows), "fills": sum(bool(r["fill"]) for r in rows), "fees": fees,
                                "equity": equity, 'net_change': equity - self.policy.initial_cash,
                                'drawdown': max(0, 1 - equity / state['peak_equity']),
                                'marked_at': marks[-1]['timestamp'] if marks else None}, "marks": marks}
        finally:
            engine.db.close()

    def snapshot(self):
        with self.lock:
            result = {"status": self.status, "error": self.error, "busy": self.busy,
                      "running": bool(self.worker and self.worker.is_alive() and not self.stop_event.is_set()),
                      "model": {"configured": self.model is not None, "name": self.model.model if self.model else None},
                      "last_observed": self.last_observed, "markets": copy.deepcopy(self.markets)}
        events = self.store.events(16)
        result['stocks'] = public_stocks()
        result["events"] = [{k: e[k] for k in ("id", "symbol", "title", "url", "published_at", "observed_at", "evidence_scope")} for e in events]
        result["research"] = self.reviews.snapshot()
        result["ledgers"] = []
        for symbol in SOURCES:
            for kind in ("agent", "benchmark"):
                value = self.ledger(symbol, kind)
                value["records"] = value["records"][-20:]
                result["ledgers"].append(value)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["observe", "once", "run", "demo"])
    parser.add_argument("--data", default="run-data")
    args = parser.parse_args()
    if args.command == "demo":
        print(json.dumps(mechanical_demo(), indent=2))
        return
    app = Application(args.data)
    if args.command == "observe":
        app.observe(force_feeds=True)
    elif args.command == "once":
        app.run_once()
    else:
        app.start()
        try:
            while app.worker.is_alive():
                app.worker.join(1)
        except KeyboardInterrupt:
            app.stop()
    result = app.snapshot()
    print(json.dumps({"status": result["status"], "error": result["error"], "markets": len(result["markets"]), "events": len(result["events"]), "model_configured": result["model"]["configured"]}))


if __name__ == "__main__":
    main()
