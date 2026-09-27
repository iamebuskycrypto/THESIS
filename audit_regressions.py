"""Ask local Qwen to audit saved mistakes from the user's development run.

These known examples informed the audit prompt. This is a development regression
check, not a hidden benchmark or a measurement of general accuracy.
"""
import argparse
import copy
import json
from pathlib import Path
import time

from agent import canonical
from evidence_audit import AUDIT_PROMPT, audit_input, audit_schema, validate_audit, audit_summary, instruction_reason
from research import ReviewLLM
from review_steps import structured_format


def run(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(Path(__file__).with_name('tests').joinpath('fixtures/fictional-evaluation-056.json').read_text())
    model = ReviewLLM('http://127.0.0.1:11434/v1/chat/completions', 'qwen3:8b', '')
    expected = {'01': ['business_impact'], '04': ['invalidation'], '05': ['invalidation'], '08': ['business_impact']}
    report = {'notice': __doc__, 'model': model.model, 'prompt': AUDIT_PROMPT, 'cases': []}
    for case in fixture['cases']:
        if case['id'] not in expected:
            continue
        step = case['steps'][1]
        focused = copy.deepcopy(step['input'])
        focused['evidence'] = [row for row in focused['evidence'] if not instruction_reason(row)]
        inputs = audit_input(step['model_response'], case['steps'][0]['model_response'], focused)
        result = {'id': case['id'], 'expected_flagged_fields': expected[case['id']], 'input': inputs}
        started = time.monotonic()
        print('  Checking saved mistake in case ' + case['id'] + '...', flush=True)
        try:
            fmt = structured_format(model, audit_schema(inputs), 'thesis_audit')
            result['response'] = model._request({'model': model.model, 'temperature': 0, 'response_format': fmt,
                'messages': [{'role': 'system', 'content': AUDIT_PROMPT}, {'role': 'user', 'content': canonical(inputs)}]})
            validated = validate_audit(result['response'], inputs)
            result['audit'] = audit_summary(validated)
            result['caught_expected_issue'] = all(validated[field]['status'] != 'supported' for field in expected[case['id']])
        except Exception as exc:
            result['error'] = str(exc)[:500]
            result['caught_expected_issue'] = False
        result['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report['cases'].append(result)
        (output_dir / 'saved-mistakes-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report['all_expected_issues_flagged'] = all(case['caught_expected_issue'] for case in report['cases'])
    (output_dir / 'saved-mistakes-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path.home() / 'Downloads' / 'THESIS-Audit-check')
    args = parser.parse_args()
    result = run(args.output_dir)
    print('Saved issues flagged:', sum(x['caught_expected_issue'] for x in result['cases']), '/', len(result['cases']))
    print('Report:', args.output_dir / 'saved-mistakes-audit.json')
