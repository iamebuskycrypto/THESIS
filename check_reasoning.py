#!/usr/bin/env python3
"""Real local model calls on disclosed fictional development inputs.

Uses the installed assessment prompt, schema, adapter and validator. Source
selection is fixed by this test, not performed by the model. No trading records
are opened. A mechanical completion is not a semantic or investment score.
"""
from __future__ import annotations

import argparse
import html
import json
import time
import uuid
import zipfile
from pathlib import Path

from evaluate import (CASES, ENDPOINT, MODEL, canonical, digest, make_packet,
                      model_metadata, request_recorded, atomic_write, utc_now)
from evidence_brief import build_brief
from research import EVENT_TYPES, ReviewLLM
from research_reasoning import VERSION, PROMPT, make_input, schema, validate
from review_steps import structured_format

SCOPE = ('Fictional development cases with real local Qwen calls. Fixed source '
         'selection; one assessment call per case, no retries. Format and source '
         'reference checks do not verify business reasoning. Human review is pending. '
         'These examples informed development; they are not an unseen benchmark '
         'or trading-performance evidence.')

# A diagnostic variation, written after the observed condition-mixing error.
# It is a development probe, not an independent or hidden benchmark.
PERMIT_FINANCING_CASE = {
    'id': '09', 'title': 'Permit explicitly required for funding; approval already obtained',
    'expected_categories': ['capital_or_management'],
    'passages': [
        'Fictional company Arbor Components signed a financing agreement for a planned manufacturing facility. No financing funds have been released.',
        'Investor approval has already been obtained. The agreement explicitly requires the planning authority to issue the construction permit before the financing funds can be released. The permit has not yet been issued.',
        'Separately, operating the completed facility will require a utility inspection. That inspection is not a condition for releasing the financing funds.',
        'Arbor plans to report the permit decision and financing release in its next quarterly filing. Facility construction and production have not begun.'
    ],
    'human_review_focus': [
        'Keep investor approval satisfied, rather than calling it a pending financing condition.',
        'The construction permit really IS a financing-release condition in this case; retain that explicit link.',
        'Keep the utility inspection attached to operating the facility, not financing release.',
        'A relevant next check is the permit decision or financing release in Arbor\'s next quarterly filing.'
    ]}


def cases_for_run(condition_check=False):
    if condition_check:
        return [next(case for case in CASES if case['id'] == '04'), PERMIT_FINANCING_CASE]
    return [case for case in CASES if case['id'] in ('01', '04', '05', '08')]


def fixture(spec):
    packet = make_packet(spec)
    brief = build_brief(packet, {'category': spec['expected_categories'][0],
        'primary_source_id': 'article_001', 'supporting_source_ids': []}, EVENT_TYPES)
    return brief, make_input(brief, packet)


def run_case(spec, model, request_fn=request_recorded):
    brief, inputs = fixture(spec)
    fmt = structured_format(model, schema(inputs), 'thesis_interpretation')
    payload = {'model': model.model, 'temperature': 0, 'response_format': fmt,
               'messages': [{'role': 'system', 'content': PROMPT},
                            {'role': 'user', 'content': canonical(inputs)}]}
    record = {'case_id': spec['id'], 'title': spec['title'], 'status': 'running',
              'started_at': utc_now(), 'human_review': 'pending',
              'human_review_focus_not_sent_to_model': spec['human_review_focus'],
              'source_selection': 'fixed_test_fixture_not_model_selected',
              'brief': brief, 'request': payload, 'request_settings': model.request_settings,
              'interpretation': None, 'error': None}
    started = time.monotonic()
    try:
        response = request_fn(model, payload, record)
        record['parsed_response'] = response
        record['interpretation'] = validate(response, inputs)
        record['status'] = 'structure_and_references_checked'
    except Exception as exc:
        record['status'] = 'failed'
        record['error'] = type(exc).__name__ + ': ' + str(exc)
    record['elapsed_seconds'] = round(time.monotonic() - started, 2)
    record['completed_at'] = utc_now()
    return record


def save(report, directory):
    atomic_write(directory / 'report.json', json.dumps(report, indent=2, ensure_ascii=False))
    esc = html.escape
    cards = []
    for item in report['cases']:
        body = item.get('interpretation') or item.get('parsed_response') or {'error': item['error']}
        cards.append('<article><h2>' + esc(item['case_id'] + ' · ' + item['title']) + '</h2><p>' +
            esc(item['status'] + ' · ' + str(item['elapsed_seconds']) + ' seconds') + '</p><pre>' +
            esc(json.dumps(body, indent=2, ensure_ascii=False)) + '</pre><h3>Human review questions</h3><ul>' +
            ''.join('<li>' + esc(q) + '</li>' for q in item['human_review_focus_not_sent_to_model']) +
            '</ul><details><summary>Exact eligible source passages</summary>' +
            ''.join('<h4>' + esc(p['id']) + '</h4><p>' + esc(p['text']) + '</p>' for p in item['brief']['passages']) +
            '</details></article>')
    document = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>THESIS assessment check</title><style>body{font:16px system-ui;color:#103045;'
        'background:#edf8fc;max-width:1000px;margin:40px auto;padding:0 20px}article{background:white;'
        'padding:24px;border:1px solid #c8e2eb;border-radius:18px;margin:24px 0}pre{white-space:pre-wrap;'
        'overflow-wrap:anywhere;background:#f1f6f8;padding:18px;border-radius:10px}p,li{line-height:1.6}'
        'summary{cursor:pointer}</style><h1>THESIS · Assessment check</h1><p>' + esc(SCOPE) + '</p>' +
        ('<p>' + esc(report['setup_error']) + '</p>' if report.get('setup_error') else '') + ''.join(cards))
    atomic_write(directory / 'report.html', document)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path.home() / 'Downloads' / 'THESIS-Reasoning-results')
    parser.add_argument('--condition-check', action='store_true',
        help='Two focused development cases: separate conditions, then an explicitly linked permit condition')
    args = parser.parse_args(argv)
    specs = cases_for_run(args.condition_check)
    planned = len(specs)
    directory = args.output_dir / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    report = {'version': VERSION, 'scope': SCOPE, 'started_at': utc_now(), 'cases': [],
              'endpoint': ENDPOINT, 'model': MODEL, 'prompt_sha256': digest(PROMPT),
              'module_sha256': digest(Path(__file__).with_name('research_reasoning.py').read_bytes()),
              'script_sha256': digest(Path(__file__).read_bytes()), 'setup_error': None,
              'planned_case_ids': [case['id'] for case in specs],
              'fixture_sha256': digest(canonical(specs)),
              'check_focus': 'condition_binding' if args.condition_check else 'original_four_cases'}
    print('\nTHESIS 0.7.1: FICTIONAL ASSESSMENT CHECK\n', flush=True)
    print(SCOPE + f'\n\nKeep Ollama open and paper monitoring paused. {planned} model calls.\n', flush=True)
    if args.condition_check:
        print('Focused check: keep each condition attached to its own outcome.\n'
              'The second case deliberately makes the permit a financing condition.\n'
              'These cases cannot establish general reasoning quality.\n', flush=True)
    print('Reports: ' + str(directory), flush=True)
    try:
        report['model_metadata'] = model_metadata()
        model = ReviewLLM(ENDPOINT, MODEL, '')
        for index, spec in enumerate(specs, 1):
            print(f"\n[{index}/{planned}] {spec['title']}\n  Assessing...", flush=True)
            record = run_case(spec, model)
            report['cases'].append(record)
            save(report, directory)
            print('  ' + record['status'].upper() + f" — {record['elapsed_seconds']}s", flush=True)
            if record['error']:
                print('  ' + record['error'], flush=True)
            if record['interpretation']:
                result = record['interpretation']
                print('  Change: ' + result['change']['text'], flush=True)
                print('  Business meaning: ' + result['business_effect']['text'], flush=True)
                print('  Limitation: ' + result['limitation']['text'], flush=True)
                print('  Next check: ' + result['next_check']['observation'], flush=True)
                print('  Future source: ' + result['next_check']['source_to_check'], flush=True)
                print('  Research action: ' + result['research_action'], flush=True)
                print('  Action reason: ' + result['action_reason']['text'], flush=True)
                print('  Effect category/status: ' + result['business_effect']['channel'] +
                      ' / ' + result['business_effect']['status'], flush=True)
            if args.condition_check:
                print('  Human review focus: ' + ' '.join(spec['human_review_focus']), flush=True)
    except Exception as exc:
        report['setup_error'] = type(exc).__name__ + ': ' + str(exc)
        print(report['setup_error'], flush=True)
    report['completed_at'] = utc_now()
    count = sum(row['status'] == 'structure_and_references_checked' for row in report['cases'])
    report['mechanical_completions'] = count
    report['planned_cases'] = planned
    save(report, directory)
    archive = directory.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in ('report.json', 'report.html'):
            bundle.write(directory / name, directory.name + '/' + name)
    print(f'\n{count}/{planned} completed the format and reference checks. Meaning still needs human review.', flush=True)
    print('Upload this report ZIP:\n' + str(archive), flush=True)
    return 0 if count == planned and not report['setup_error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
