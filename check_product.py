"""THESIS acceptance check: read-only services and isolated fictional model tests.

Run with paper monitoring paused. No observed paper records or Mac settings are
changed. A complete report still needs human review; no return claim is tested.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path.home() / 'Downloads' / 'THESIS-Acceptance-results')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--reviews-only', action='store_true', help='Run the focused source-brief check without repeating market or paper checks')
    group.add_argument('--services-only', action='store_true', help='Check connectivity without model generation')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    out = args.output_dir.expanduser() / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=True)
    report = {'version': '0.6.1', 'mode': 'acceptance_check', 'notice': __doc__, 'checks': [], 'scope': 'reviews_only' if args.reviews_only else 'services_only' if args.services_only else 'full', 'started_at': time.time()}
    def save():
        (out / 'acceptance.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    def check(name, operation):
        print(name + '...', flush=True)
        start = time.monotonic()
        try:
            details = operation()
            row = {'name': name, 'status': 'passed', 'details': details}
        except Exception as exc:
            row = {'name': name, 'status': 'failed', 'error': str(exc)[:500]}
        row['seconds'] = round(time.monotonic() - start, 2)
        report['checks'].append(row)
        save()
        print('  ' + row['status'].upper() + (': ' + row['error'] if row.get('error') else ''), flush=True)
        return row['status'] == 'passed'
    print('THESIS 0.6.1 acceptance check. Keep Ollama open and paper monitoring paused.\n', flush=True)
    # A running UI is optional. If it is reachable, prevent competing model calls.
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/status', timeout=4) as response:
            status = json.load(response)
        if status.get('busy') or status.get('running'):
            print('Pause monitoring in THESIS and wait for the active request to finish, then run this command again.', flush=True)
            return 1
    except OSError:
        pass
    spec = importlib.util.spec_from_file_location('thesis_app_launcher', root / 'launch.py')
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    original = socket.getaddrinfo
    socket.getaddrinfo = launch.BitgetResolver(original)
    try:
        from pipeline import SOURCES, Bitget, collect_feed
        from agent import Engine, LLM, synthetic_packet
        from evaluate import model_metadata
        market = Bitget(out / 'collected-market')
        for symbol in ([] if args.reviews_only else SOURCES):
            check(SOURCES[symbol]['company'] + ' official news', lambda symbol=symbol: {
                'announcements': len(collect_feed(symbol, out / 'collected-news'))})
            check(symbol + ' public market data', lambda symbol=symbol: {
                'instrument': market.instrument(symbol), 'session': market.session(symbol), 'quote': market.quote(symbol)})
        ready = check('Local Qwen model installed', model_metadata)
        if ready and not args.services_only:
            def paper_call():
                model = LLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
                now = time.time()
                packet = synthetic_packet(now)
                engine = Engine(':memory:', packet['symbol'], mode='synthetic')
                try:
                    row = engine.step(packet, model, now=now)
                    report['fictional_paper_call'] = row
                    if row.get('decision') is None:
                        raise RuntimeError(row.get('reason', 'No valid decision returned'))
                    engine.export()
                    return {'action': row['decision']['action'], 'outcome': row['status'],
                            'notice': 'Real Qwen call on fictional inputs; isolated in-memory ledger and fixed fixture clock. A HOLD or execution rejection is valid. This does not test investment performance.'}
                finally:
                    engine.db.close()
            if not args.reviews_only:
                check('Paper decision adapter with fictional evidence', paper_call)
            print('\nChecking eight fictional source briefs. One model call per case; no retries. These test source copying and selection, not business reasoning or trading returns.', flush=True)
            result = subprocess.run([sys.executable, str(root / 'evaluate.py'), '--app-dir', str(root),
                                     '--output-dir', str(out / 'evaluation'), '--no-open'])
            report['evaluation_exit_code'] = result.returncode
            save()
            report['review_scope'] = 'The 0.6.0 same-model audit missed all four previously identified issues in the uploaded Mac report. This workflow replaces generated business claims with exact source passages; it does not fix or certify that auditor.'
        report['status'] = 'checks_finished_human_review_required'
    finally:
        socket.getaddrinfo = original
        report['completed_at'] = time.time()
        save()
        archive = out.with_suffix('.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(out.rglob('*')):
                if path.is_file():
                    z.write(path, path.relative_to(out))
        print('\nCHECK FINISHED. Upload this ZIP for final review:\n' + str(archive), flush=True)
        if sys.platform == 'darwin':
            subprocess.run(['open', '-R', str(archive)], check=False)
    complete = all(x['status'] == 'passed' for x in report['checks'])
    if not args.services_only:
        complete = complete and report.get('evaluation_exit_code') == 0
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
