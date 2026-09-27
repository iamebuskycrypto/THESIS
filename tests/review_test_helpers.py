"""Hand-written fixture conversion for one-call source selection tests; no model claims."""
import copy


def assessment_only(legacy):
    return {key:copy.deepcopy(value) for key,value in legacy.items()
            if key not in ('event_classification','supporting_evidence')}


def passing_audit(ref='issuer'):
    # Hand-written transport fixture, not an observed model judgment.
    from evidence_audit import FIELDS
    return {name: {'status': 'supported', 'reason': 'Transport fixture only.', 'source_ids': [ref]} for name in FIELDS}


def model_responses(legacy, repeats=1):
    primary=legacy['event_classification']['source_id']
    other=[]
    for item in legacy['supporting_evidence']:
        for ref in item['source_ids']:
            if ref!=primary and ref not in other: other.append(ref)
    selection={'category':legacy['event_classification']['category'],
               'primary_source_id':primary,'supporting_source_ids':other[:2]}
    return [copy.deepcopy(item) for _ in range(repeats) for item in (selection,)]
