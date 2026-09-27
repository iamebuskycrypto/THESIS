"""Export a quiescent run, including complete ledgers and collected evidence."""
import hashlib
import io
import json
import time
import zipfile

from agent import canonical
from pipeline import SOURCES


def export_run(app):
    if app.worker and app.worker.is_alive() and not app.stop_event.is_set():
        raise ValueError('Pause paper monitoring before exporting this run.')
    if not app.cycle_lock.acquire(blocking=False):
        raise ValueError('A request is still finishing. Wait for it to finish, then export.')
    try:
        entries = {}
        total = 0
        def add(name, body):
            nonlocal total
            content = body if isinstance(body, bytes) else canonical(body).encode()
            total += len(content)
            if total > 100 * 1024 * 1024:
                raise ValueError('This run exceeds the 100 MB browser export limit. Copy the run-data folder after stopping THESIS for a full backup.')
            entries[name] = content
        profile_path = app.root / 'run-profile.json'
        profile = json.loads(profile_path.read_text()) if profile_path.exists() else None
        if profile:
            # Credentials are never part of the recorded profile; exclude endpoints
            # as well because operators may have supplied a provider URL with tokens.
            profile.pop('endpoint', None)
        for symbol in SOURCES:
            for kind in ('agent', 'benchmark'):
                ledger = app.ledger(symbol, kind)
                engine = app.engine(symbol, kind)
                try:
                    ledger['marks'] = [{'timestamp': row[0], 'equity': row[1], 'exposure': row[2], 'bid': row[3]}
                                       for row in engine.db.execute('SELECT ts,equity,exposure,bid FROM marks ORDER BY ts')]
                finally:
                    engine.db.close()
                add('ledgers/' + kind + '-' + symbol + '.json', ledger)
        with app.store.connect() as db:
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events ORDER BY published')]
        with app.reviews.connect() as db:
            reviews = [json.loads(row[0]) for row in db.execute('SELECT body FROM reviews ORDER BY started')]
        add('events.json', events)
        add('research-reviews.json', reviews)
        add('run.json', {'product_version': '0.6.0', 'exported_at': time.time(), 'profile': profile,
                         'mode': 'paper_only', 'last_observed': app.last_observed,
                         'markets': app.markets, 'notice': 'Separate accounts for each instrument and decision maker. Research reviews do not count as paper decisions. Simulated fills are not exchange orders. No advantage has been demonstrated.'})
        for directory in ('raw-news', 'raw-market'):
            root = app.root / directory
            if root.is_symlink():
                raise ValueError('Cannot export a linked evidence directory.')
            if root.exists():
                for path in sorted(root.rglob('*')):
                    if path.is_symlink():
                        raise ValueError('Cannot export linked evidence files.')
                    if path.is_file():
                        add(path.relative_to(app.root).as_posix(), path.read_bytes())
        add('README.txt', b'THESIS 0.6.0 evidence export\n\nPaper trading with simulated funds. Each ledger has its own initial balance.\nResearch reviews and observed paper decisions are separate. Source text can contain untrusted claims.\nmanifest.json hashes every included file except itself. Ledger hash chains are checked before export.\nHashes detect accidental changes; they are not external proof of collection time or correctness.\nNo provider API key, app settings, code backup, or synthetic demo is included.\n')
        manifest = {name: {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
                    for name, content in entries.items()}
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
            archive.writestr('manifest.json', canonical(manifest))
        return output.getvalue()
    finally:
        app.cycle_lock.release()
