from pathlib import Path
from decimal import Decimal, ROUND_CEILING
from copy import deepcopy
import json, re, datetime
from jsonschema import Draft202012Validator, FormatChecker

root = Path('outputs/requirements-v1')
prd = (root/'PRD.md').read_text(encoding='utf-8')
srs = (root/'SRS.md').read_text(encoding='utf-8')
agents = (root/'AGENT_SPECIFICATIONS.md').read_text(encoding='utf-8')
acceptance = (root/'TRACEABILITY_AND_ACCEPTANCE.md').read_text(encoding='utf-8')
results = []
def check(name, condition, detail=''):
    results.append((name, bool(condition), detail))
    if not condition:
        raise AssertionError(f'{name}: {detail}')

check('20 distinct product requirements', re.findall(r'^### PRD-(\d{2}) ', prd, re.M) == [f'{i:02}' for i in range(1,21)])
check('62 sequential software requirements', re.findall(r'^## SRS-(\d{3}) ', srs, re.M) == [f'{i:03}' for i in range(1,63)])
check('23 distinct detailed agent capabilities', re.findall(r'^## A(\d{2}) ', agents, re.M) == [f'{i:02}' for i in range(1,24)])
check('All 23 detailed agent contracts included in SRS', re.findall(r'^## A(\d{2}) ', srs, re.M) == [f'{i:02}' for i in range(1,24)])
check('24 user stories', re.findall(r'^\| US-(\d{2}) ', prd, re.M) == [f'{i:02}' for i in range(1,25)])
check('50 acceptance test families', re.findall(r'^\| AT-(\d{3}) ', acceptance, re.M) == [f'{i:03}' for i in range(1,51)])
check('12 explicit owner decisions', re.findall(r'^\| OD-(\d{2}) ', prd, re.M) == [f'{i:02}' for i in range(1,13)])
check('Full-system scope; obsolete release gates removed', not re.search(r'\bR[012]\b', prd+srs))

broken=[]; refs=[]; linkcount=0
for path in root.rglob('*.md'):
    text=path.read_text(encoding='utf-8')
    for prefix, maximum in [('PRD',20),('SRS',62),('AT',50),('OD',12)]:
        for match in re.finditer(r'\b'+prefix+r'-(\d+)\b', text):
            if not 1 <= int(match.group(1)) <= maximum: refs.append((path.name,match.group(0)))
    for dest in re.findall(r'\]\(([^)]+)\)',text):
        if dest.startswith(('https://','http://','#')): continue
        dest=dest.split('#')[0]
        if dest=='SPECIFICATION_VALIDATION.md': continue
        linkcount+=1
        if not (path.parent/dest).exists(): broken.append((str(path),dest))
    check('Balanced fenced blocks: '+str(path.relative_to(root)), len(re.findall(r'^```',text,re.M))%2==0)
check('Internal requirement references resolve', not refs, str(refs))
check('Local document/schema links resolve', not broken, f'{linkcount} checked; broken={broken}')

schema=json.loads((root/'contracts/core.schema.json').read_text())
Draft202012Validator.check_schema(schema)
check('Core schema valid under Draft 2020-12', True)
formats=FormatChecker()
@formats.checks('date-time')
def rfc3339(value):
    if not isinstance(value,str): return True
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})',value): return False
    try:
        return datetime.datetime.fromisoformat(value.upper().replace('Z','+00:00')).tzinfo is not None
    except ValueError:
        return False
validator=Draft202012Validator(schema,format_checker=formats)
examples=json.loads((root/'contracts/examples.json').read_text())['artifacts']
for ex in examples: validator.validate(ex)
check('All 11 independent structural fixture examples validate',len(examples)==11)

bad=[]
def mutant(index, key, value, name):
    item=deepcopy(examples[index]); item[key]=value; bad.append((name,item))
mutant(0,'tenant_id','not-a-uuid','bad UUID')
mutant(0,'review_state','ACCEPTED','model cannot submit accepted claim')
mutant(0,'evidence_refs',[],'known without evidence')
mutant(0,'extra_untyped_field','x','unexpected property')
mutant(0,'created_at','yesterday','invalid datetime')
mutant(0,'revision',0,'zero revision')
x=deepcopy(examples[0]); x['epistemic_state']='UNKNOWN'; bad.append(('unknown with selected value',x))
x=deepcopy(examples[0]); x['epistemic_state']='INFERRED'; bad.append(('inferred without derivation',x))
x=deepcopy(examples[0]); x['epistemic_state']='ASSUMED'; bad.append(('assumed without assumption',x))
x=deepcopy(examples[0]); x['epistemic_state']='CONTRADICTED'; bad.append(('contradicted without alternatives',x))
mutant(1,'distribution',{'family':'BETA','alpha':0,'beta':1},'invalid beta support parameters')
mutant(2,'capability_id','A24','unregistered role')
mutant(2,'delegation_depth',-1,'negative depth')
mutant(7,'draw_count',0,'zero draws')
mutant(8,'status','RELEASED','model cannot directly release decision')
mutant(9,'payload_hash','not-a-hash','invalid action hash')
for name,item in bad:
    check('Schema rejects '+name, not validator.is_valid(item))

money=Decimal
price=money('699'); cost=money('315'); fulfill=money('60'); fee=price*money('0.03'); fixed=money('120000')
contribution=price-cost-fulfill-fee-money('140')
stress=price-cost-fulfill-fee-money('196')
be=int((fixed/contribution).to_integral_value(rounding=ROUND_CEILING))
stress_be=int((fixed/stress).to_integral_value(rounding=ROUND_CEILING))
check('Golden base accounting', (fee,contribution,be,900*contribution-fixed)==(money('20.97'),money('163.03'),737,money('26727')))
check('Golden CAC stress accounting', (stress,stress_be,900*stress-fixed)==(money('107.03'),1122,money('-23673')))
threshold=price-cost-fulfill-fee-fixed/money('900')
check('Golden CAC switching threshold', abs(threshold-money('169.6966667'))<money('0.0000001'))

arch=(root/'ARCHITECTURE_AND_DATA_CONTRACTS.md').read_text(encoding='utf-8')
build=arch.split('## 7 Dependency graph for implementation')[1].split('```mermaid')[1].split('```')[0]
edges=[]
for line in build.splitlines():
    match=re.search(r'^\s*(\w+)(?:\[[^\]]*\])?\s*-->\s*(\w+)',line)
    if match: edges.append(match.groups())
nodes=set(sum(([a,b] for a,b in edges),[])); visiting=set(); visited=set()
def visit(n):
    if n in visiting: return False
    if n in visited: return True
    visiting.add(n)
    for a,b in edges:
        if a==n and not visit(b): return False
    visiting.remove(n); visited.add(n); return True
check('Implementation dependency graph is acyclic',all(visit(n) for n in nodes),f'{len(nodes)} nodes; {len(edges)} edges')
check('Architecture and SRS embedded annexes agree', arch.strip() in srs.replace('## Architecture, Data Relationships and Runtime Interworking','# Architecture, Data Relationships and Runtime Interworking',1))
check('Agent catalog and SRS embedded annex agree',agents.strip() in srs.replace('## Complete Agent and Service Specifications','# Complete Agent and Service Specifications',1))

report=['# Specification Package Validation','', 'Date: 24 October 2026', '',
        'These are checks of the authored specifications, schemas and fictional arithmetic only. No application, live integration, empirical model, production deployment or AT acceptance suite has been implemented or tested by this report.', '',
        f'**{len(results)} document/schema/arithmetic checks passed.**', '',
        '| Check | Result | Detail |','|---|---|---|']
for name,ok,detail in results: report.append(f'| {name} | {"PASS" if ok else "FAIL"} | {detail.replace("|","/")} |')
report+=['','## Document sizes','', '| Document | Approximate words |','|---|---:|']
for name in ['PRD.md','SRS.md','AGENT_SPECIFICATIONS.md','ARCHITECTURE_AND_DATA_CONTRACTS.md','TRACEABILITY_AND_ACCEPTANCE.md','AI_IMPLEMENTATION_CONTRACT.md']:
    report.append(f'| {name} | {len((root/name).read_text(encoding="utf-8").split()):,} |')
report+=['','## Limits of validation','',
         'Schema tests prove only the stated structural acceptance/rejection. Referential integrity, entailment, authorization, state machines, numerical model validity and all production behaviors require implementation tests. Mermaid fence structure and the implementation DAG were checked; this report does not claim a rendered visual QA pass. External source links were retained from researched official documentation; this check did not probe every URL. Owner decisions remain explicitly unresolved.', '',
         'The 50 AT families define future full-system acceptance obligations, not completed tests. All 23 capabilities remain required. No MVP or reduced release gate substitutes for the complete system.','']
(root/'SPECIFICATION_VALIDATION.md').write_text('\n'.join(report),encoding='utf-8')
print(f'PASS: {len(results)} specification checks; {len(examples)} positive and {len(bad)} negative schema fixtures.')
print('PRD words:', len(prd.split()), 'SRS words:',len(srs.split()))
