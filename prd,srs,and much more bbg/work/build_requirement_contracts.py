from pathlib import Path
import json
from copy import deepcopy

OUT = Path('outputs/requirements-v1/contracts')
OUT.mkdir(parents=True, exist_ok=True)

def obj(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}

def enum(*values): return {'type': 'string', 'enum': list(values)}
def arr(item, minimum=0): return {'type': 'array', 'items': item, 'minItems': minimum}
def ref(name): return {'$ref': '#/$defs/' + name}
def nullable(value): return {'anyOf': [value, {'type': 'null'}]}
S = {'type': 'string', 'minLength': 1}
UUID = {'type': 'string', 'format': 'uuid'}
DT = {'type': 'string', 'format': 'date-time'}
POS = {'type': 'integer', 'minimum': 1}
NONNEG = {'type': 'integer', 'minimum': 0}
HASH = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
KINDS = ['source', 'source_version', 'evidence_span', 'claim', 'requirement', 'constraint',
         'assumption', 'parameter', 'model', 'snapshot', 'strategy', 'scenario', 'simulation',
         'comparison', 'optimization', 'challenge', 'verification', 'decision', 'task',
         'instance', 'investigation', 'policy', 'reservation', 'budget', 'review', 'experiment',
         'dataset', 'observation', 'hypothesis', 'memory', 'action', 'approval', 'usage', 'entity']
defs = {}
defs['ArtifactRef'] = obj({'kind': enum(*KINDS), 'id': UUID, 'revision': POS})
R = ref('ArtifactRef')
RS = arr(R)
defs['Scope'] = obj({'organization_refs': arr(R, 1), 'entity_refs': RS,
                     'geographies': arr(S), 'populations': arr(S), 'channels': arr(S),
                     'valid_from': nullable(DT), 'valid_to': nullable(DT)})
defs['TypedValue'] = {'oneOf': [
    obj({'type': {'const': 'NUMBER'}, 'value': {'type': 'number'}, 'unit': S,
         'currency': nullable({'type': 'string', 'pattern': '^[A-Z]{3}$'}),
         'tax_basis': nullable(enum('NET', 'GROSS', 'NOT_APPLICABLE', 'UNKNOWN'))}),
    obj({'type': {'const': 'DECIMAL'}, 'value': {'type': 'string', 'pattern': '^-?[0-9]+(\\.[0-9]+)?$'},
         'unit': S, 'currency': nullable({'type': 'string', 'pattern': '^[A-Z]{3}$'}),
         'tax_basis': nullable(enum('NET', 'GROSS', 'NOT_APPLICABLE', 'UNKNOWN'))}),
    obj({'type': {'const': 'TEXT'}, 'value': S}),
    obj({'type': {'const': 'BOOLEAN'}, 'value': {'type': 'boolean'}})]}
defs['Distribution'] = {'oneOf': [
    obj({'family': {'const': 'POINT'}, 'value': {'type': 'number'}}),
    obj({'family': {'const': 'UNIFORM'}, 'low': {'type': 'number'}, 'high': {'type': 'number'}}),
    obj({'family': {'const': 'TRIANGULAR'}, 'low': {'type': 'number'}, 'mode': {'type': 'number'}, 'high': {'type': 'number'}}),
    obj({'family': {'const': 'BETA'}, 'alpha': {'type': 'number', 'exclusiveMinimum': 0}, 'beta': {'type': 'number', 'exclusiveMinimum': 0}}),
    obj({'family': {'const': 'NORMAL'}, 'mean': {'type': 'number'}, 'stddev': {'type': 'number', 'exclusiveMinimum': 0}}),
    obj({'family': {'const': 'LOGNORMAL'}, 'log_mean': {'type': 'number'}, 'log_stddev': {'type': 'number', 'exclusiveMinimum': 0}}),
    obj({'family': {'const': 'EMPIRICAL'}, 'dataset_ref': R, 'column': S, 'weights_column': nullable(S)})]}
STOP = enum('CONVERGED', 'BUDGET_EXHAUSTED', 'TIME_EXHAUSTED', 'NEEDS_INPUT', 'NO_FEASIBLE_ACTION',
            'MODEL_NOT_IDENTIFIED', 'SOURCE_UNAVAILABLE', 'CANCELLED', 'SYSTEM_FAILURE')
TASKST = enum('PROPOSED', 'QUEUED', 'RUNNING', 'WAITING_DEPENDENCY', 'WAITING_INPUT', 'RETRY_PENDING',
              'SUCCEEDED', 'INCONCLUSIVE', 'FAILED', 'CANCELLED', 'EXPIRED')
def artifact(name, fields):
    props = {'artifact_type': {'const': name}, 'schema_version': {'const': '1.0'},
             'id': UUID, 'revision': POS, 'tenant_id': UUID, 'case_id': UUID,
             'origin': enum('REAL', 'FIXTURE'), 'created_at': DT, 'snapshot_ref': R}
    props.update(fields)
    defs[name] = obj(props)
    return defs[name]

claim = artifact('ClaimProposal', {
    'subject_ref': R, 'predicate': S, 'proposition': S, 'value': nullable(ref('TypedValue')),
    'scope': ref('Scope'), 'epistemic_state': enum('KNOWN', 'INFERRED', 'ASSUMED', 'UNKNOWN', 'CONTRADICTED'),
    'review_state': {'const': 'PROPOSED'}, 'material': {'type': 'boolean'},
    'evidence_refs': RS, 'derivation_refs': RS, 'assumption_refs': RS, 'competing_claim_refs': RS})
claim['allOf'] = []
for state, key, minimum in [('KNOWN', 'evidence_refs', 1), ('INFERRED', 'derivation_refs', 1),
                            ('ASSUMED', 'assumption_refs', 1), ('CONTRADICTED', 'competing_claim_refs', 2)]:
    claim['allOf'].append({'if': {'properties': {'epistemic_state': {'const': state}}},
                          'then': {'properties': {key: {'minItems': minimum}}}})
claim['allOf'].append({'if': {'properties': {'epistemic_state': {'const': 'UNKNOWN'}}},
                      'then': {'properties': {'value': {'type': 'null'}}}})
artifact('ParameterProposal', {
    'model_ref': R, 'parameter_key': S, 'scope': ref('Scope'), 'unit': S,
    'currency': nullable({'type': 'string', 'pattern': '^[A-Z]{3}$'}),
    'distribution': ref('Distribution'),
    'uncertainty_type': enum('PARAMETER', 'PROCESS', 'HETEROGENEITY', 'SCENARIO', 'NONE'),
    'basis': enum('MEASURED', 'FITTED', 'PUBLISHED', 'SCENARIO_ASSUMPTION', 'STRUCTURAL_ASSUMPTION'),
    'claim_refs': RS, 'dataset_refs': RS, 'assumption_refs': RS, 'derivation_refs': RS,
    'dependency_refs': RS, 'applicability_limits': arr(S), 'review_state': {'const': 'PROPOSED'}})
artifact('TaskRequest', {
    'capability_id': enum(*[f'A{i:02d}' for i in range(1, 24)]), 'template_version': S,
    'investigation_id': UUID, 'purpose': S, 'completion_test': S, 'requested_output_type': S,
    'input_refs': RS, 'dependency_refs': RS, 'parent_task_ref': nullable(R),
    'policy_ref': R, 'deadline': DT, 'delegation_depth': NONNEG,
    'status': {'const': 'PROPOSED'}})
artifact('AgentResult', {
    'task_id': UUID, 'instance_id': UUID, 'status': TASKST, 'artifact_refs': RS,
    'claim_refs': RS, 'evidence_refs': RS, 'assumption_refs': RS,
    'unresolved_issues': arr(S), 'requested_tasks': arr(ref('TaskRequest')),
    'concise_rationale': S, 'usage_ref': R, 'stop_reason': nullable(STOP)})
artifact('EventEnvelope', {
    'event_id': UUID, 'aggregate_id': UUID, 'aggregate_revision': POS, 'event_type': S,
    'occurred_at': DT, 'recorded_at': DT, 'correlation_id': UUID,
    'causation_id': nullable(UUID), 'actor_id': UUID, 'payload_refs': RS})
defs['EventEnvelope']['properties']['case_id'] = nullable(UUID)
defs['EventEnvelope']['properties']['snapshot_ref'] = nullable(R)
artifact('Challenge', {
    'target_refs': arr(R, 1), 'failure_proposition': S, 'material': {'type': 'boolean'},
    'severity': enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'), 'test_plan': S,
    'reversal_criterion': S, 'evidence_refs': RS,
    'status': enum('OPEN', 'TESTING', 'RESOLVED', 'UNRESOLVED', 'REJECTED', 'SUPERSEDED'),
    'resolution_refs': RS})
artifact('ScenarioPatch', {
    'semantic_type': enum('SENSITIVITY', 'STRUCTURAL_INTERVENTION', 'CAUSAL_COUNTERFACTUAL'),
    'patches': arr(obj({'parameter_key': S, 'distribution': ref('Distribution'), 'unit': S,
                      'rationale': S, 'evidence_refs': RS, 'assumption_refs': RS}), 1),
    'model_ref': R, 'held_constant_refs': RS, 'identification_review_ref': nullable(R)})
defs['Metric'] = obj({'key': S, 'value': nullable({'type': 'number'}), 'unit': S,
                      'currency': nullable({'type': 'string', 'pattern': '^[A-Z]{3}$'}),
                      'availability': enum('AVAILABLE', 'NOT_APPLICABLE', 'UNAVAILABLE'),
                      'reason': nullable(S)})
artifact('SimulationResult', {
    'strategy_refs': arr(R, 1), 'model_refs': arr(R, 1), 'parameter_refs': RS,
    'manifest_hash': HASH, 'seed': NONNEG, 'rng_version': S, 'environment_ref': S,
    'draw_count': POS, 'invalid_draw_count': NONNEG, 'horizon_days': POS,
    'metrics_by_strategy': arr(obj({'strategy_ref': R, 'feasible': {'type': 'boolean'},
                                  'violations': arr(S), 'metrics': arr(ref('Metric'))}), 1),
    'output_object_hashes': arr(HASH), 'conditionality': S,
    'status': enum('SUCCEEDED', 'FAILED', 'CANCELLED'), 'diagnostics': arr(S)})
artifact('DecisionProposal', {
    'outcome': enum('RECOMMEND', 'CONDITIONAL', 'DEFER', 'NO_FEASIBLE_ACTION', 'ABSTAIN'),
    'selected_strategy_ref': nullable(R), 'alternative_refs': RS, 'result_refs': RS,
    'objective_ref': R, 'constraint_refs': RS, 'claim_refs': RS, 'assumption_refs': RS,
    'challenge_refs': RS, 'verification_refs': RS, 'experiment_refs': RS,
    'summary': S, 'conditions': arr(S), 'unresolved_issues': arr(S),
    'confidence_dimensions': obj({'evidence': S, 'parameter': S, 'model_validation': S,
                                  'numerical': S, 'robustness': S}),
    'reversal_conditions': arr(S), 'stop_reason': STOP, 'status': {'const': 'DRAFT'}})
artifact('ApprovalRecord', {
    'approval_type': enum('FACT_REVIEW', 'ASSUMPTION_USE', 'BUDGET', 'DECISION_REVIEW', 'ACTION'),
    'subject_ref': R, 'payload_hash': HASH, 'reviewer_id': UUID, 'policy_ref': R,
    'scope_description': S, 'expires_at': DT, 'revoked_at': nullable(DT),
    'currency': nullable({'type': 'string', 'pattern': '^[A-Z]{3}$'}),
    'max_minor_units': nullable(NONNEG), 'allowed_attempts': POS,
    'destination_refs': arr(S), 'status': enum('APPROVED', 'REVOKED', 'EXPIRED')})
artifact('VerificationReport', {
    'subject_ref': R, 'check_suite_version': S,
    'checks': arr(obj({'check_id': S, 'mandatory': {'type': 'boolean'},
                       'outcome': enum('PASS', 'FAIL', 'NOT_APPLICABLE'),
                       'affected_refs': RS, 'diagnostic': S}), 1),
    'blockers': arr(S), 'reviewer_refs': RS,
    'allowed_outcomes': arr(enum('RECOMMEND', 'CONDITIONAL', 'DEFER', 'NO_FEASIBLE_ACTION', 'ABSTAIN'))})

names = [n for n in defs if n not in ['ArtifactRef', 'Scope', 'TypedValue', 'Distribution', 'Metric']]
schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
          '$id': 'urn:company-market-twin:core-contracts:1.0',
          'title': 'Company and Market Twin Core Transport Contracts',
          'description': 'Structural contracts only. Authorization, references, entailment, units and state transitions require SRS semantic validators.',
          'oneOf': [ref(n) for n in names], '$defs': defs}
(OUT/'core.schema.json').write_text(json.dumps(schema, indent=2, allow_nan=False)+'\n', encoding='utf-8')

uid = '11111111-1111-4111-8111-111111111111'
uid2 = '22222222-2222-4222-8222-222222222222'
def r(kind, n=1): return {'kind': kind, 'id': uid if n == 1 else uid2, 'revision': 1}
scope = {'organization_refs': [r('entity')], 'entity_refs': [], 'geographies': ['fictional test geography'],
         'populations': ['fixture cohort'], 'channels': [], 'valid_from': None, 'valid_to': None}
def base(name): return {'artifact_type': name, 'schema_version': '1.0', 'id': uid, 'revision': 1,
                       'tenant_id': uid, 'case_id': uid, 'origin': 'FIXTURE',
                       'created_at': '2026-10-24T00:00:00Z', 'snapshot_ref': r('snapshot')}
examples = []
def ex(name, fields):
    value = base(name); value.update(fields); examples.append(value); return value
ex('ClaimProposal', {'subject_ref': r('entity'), 'predicate': 'has_listed_price',
    'proposition': 'The fictional offer lists INR 699 net of tax.',
    'value': {'type': 'DECIMAL', 'value': '699.00', 'unit': 'INR/unit', 'currency': 'INR', 'tax_basis': 'NET'},
    'scope': scope, 'epistemic_state': 'KNOWN', 'review_state': 'PROPOSED', 'material': True,
    'evidence_refs': [r('evidence_span')], 'derivation_refs': [], 'assumption_refs': [], 'competing_claim_refs': []})
ex('ParameterProposal', {'model_ref': r('model'), 'parameter_key': 'acquisition_cost', 'scope': scope,
    'unit': 'INR/new_customer', 'currency': 'INR', 'distribution': {'family': 'POINT', 'value': 140},
    'uncertainty_type': 'SCENARIO', 'basis': 'SCENARIO_ASSUMPTION', 'claim_refs': [], 'dataset_refs': [],
    'assumption_refs': [r('assumption')], 'derivation_refs': [], 'dependency_refs': [],
    'applicability_limits': ['Fictional single-order-per-customer fixture only'], 'review_state': 'PROPOSED'})
task = ex('TaskRequest', {'capability_id': 'A03', 'template_version': '1.0', 'investigation_id': uid,
    'purpose': 'Inspect a fictional competitor offer.', 'completion_test': 'Return a price span with tax and date scope.',
    'requested_output_type': 'ClaimProposal', 'input_refs': [r('source_version')], 'dependency_refs': [],
    'parent_task_ref': None, 'policy_ref': r('policy'), 'deadline': '2026-10-24T01:00:00Z',
    'delegation_depth': 0, 'status': 'PROPOSED'})
ex('AgentResult', {'task_id': uid, 'instance_id': uid2, 'status': 'SUCCEEDED', 'artifact_refs': [r('claim')],
    'claim_refs': [r('claim')], 'evidence_refs': [r('evidence_span')], 'assumption_refs': [],
    'unresolved_issues': [], 'requested_tasks': [], 'concise_rationale': 'Fixture span was extracted for review.',
    'usage_ref': r('usage'), 'stop_reason': None})
ex('EventEnvelope', {'event_id': uid, 'aggregate_id': uid2, 'aggregate_revision': 2,
    'event_type': 'claim.accepted', 'occurred_at': '2026-10-24T00:00:00Z',
    'recorded_at': '2026-10-24T00:00:01Z', 'correlation_id': uid, 'causation_id': None,
    'actor_id': uid2, 'payload_refs': [r('claim')]})
ex('Challenge', {'target_refs': [r('strategy')], 'failure_proposition': 'Higher CAC can reverse profit.',
    'material': True, 'severity': 'HIGH', 'test_plan': 'Evaluate CAC 196 with fixed acquired units.',
    'reversal_criterion': 'Profit is negative.', 'evidence_refs': [], 'status': 'OPEN', 'resolution_refs': []})
ex('ScenarioPatch', {'semantic_type': 'SENSITIVITY', 'patches': [{'parameter_key': 'acquisition_cost',
    'distribution': {'family': 'POINT', 'value': 196}, 'unit': 'INR/new_customer',
    'rationale': 'Fictional stress assumption.', 'evidence_refs': [], 'assumption_refs': [r('assumption')]}],
    'model_ref': r('model'), 'held_constant_refs': [r('parameter')], 'identification_review_ref': None})
ex('SimulationResult', {'strategy_refs': [r('strategy')], 'model_refs': [r('model')], 'parameter_refs': [r('parameter')],
    'manifest_hash': 'a'*64, 'seed': 7, 'rng_version': 'fixture-deterministic-v1', 'environment_ref': 'fixture-only',
    'draw_count': 1, 'invalid_draw_count': 0, 'horizon_days': 90,
    'metrics_by_strategy': [{'strategy_ref': r('strategy'), 'feasible': True, 'violations': [],
        'metrics': [{'key': 'profit', 'value': 26727, 'unit': 'INR', 'currency': 'INR',
                     'availability': 'AVAILABLE', 'reason': None}]}],
    'output_object_hashes': [], 'conditionality': 'Conditional fictional inputs; not a market forecast.',
    'status': 'SUCCEEDED', 'diagnostics': []})
ex('DecisionProposal', {'outcome': 'CONDITIONAL', 'selected_strategy_ref': r('strategy'),
    'alternative_refs': [], 'result_refs': [r('simulation')], 'objective_ref': r('requirement'),
    'constraint_refs': [], 'claim_refs': [], 'assumption_refs': [r('assumption')],
    'challenge_refs': [r('challenge')], 'verification_refs': [], 'experiment_refs': [],
    'summary': 'Fictional positive contribution scenario requires further demand evidence.',
    'conditions': ['Obtain actual eligible customer response data.'], 'unresolved_issues': ['Demand is not identified.'],
    'confidence_dimensions': {'evidence': 'fixture only', 'parameter': 'assumed', 'model_validation': 'SCENARIO_ONLY',
                              'numerical': 'deterministic accounting fixture', 'robustness': 'sensitive to CAC'},
    'reversal_conditions': ['CAC exceeds the stated break-even threshold.'], 'stop_reason': 'MODEL_NOT_IDENTIFIED', 'status': 'DRAFT'})
ex('ApprovalRecord', {'approval_type': 'ASSUMPTION_USE', 'subject_ref': r('assumption'), 'payload_hash': 'b'*64,
    'reviewer_id': uid2, 'policy_ref': r('policy'), 'scope_description': 'Fictional scenario only; no external effects.',
    'expires_at': '2026-10-25T00:00:00Z', 'revoked_at': None, 'currency': None,
    'max_minor_units': None, 'allowed_attempts': 1, 'destination_refs': [], 'status': 'APPROVED'})
ex('VerificationReport', {'subject_ref': r('decision'), 'check_suite_version': 'fixture-v1',
    'checks': [{'check_id': 'grounding', 'mandatory': True, 'outcome': 'FAIL', 'affected_refs': [r('claim')],
                'diagnostic': 'Illustrative failure: live evidence unavailable.'}],
    'blockers': ['Live evidence unavailable'], 'reviewer_refs': [r('review')], 'allowed_outcomes': ['ABSTAIN']})
(OUT/'examples.json').write_text(json.dumps({'fixture_only': True, 'note': 'Independent structural examples, not a persisted connected graph or actual approvals/results.',
                                           'artifacts': examples}, indent=2, allow_nan=False)+'\n', encoding='utf-8')
print(f'Wrote {len(names)} core contracts and {len(examples)} structural examples.')
