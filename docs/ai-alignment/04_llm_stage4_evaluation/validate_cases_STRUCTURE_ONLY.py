#!/usr/bin/env python3
"""STATIC STRUCTURE ONLY. No G1 runner, API/LLM/AR calls, or predicate execution."""
from pathlib import Path
from collections import Counter
import csv, json, re

ROOT=Path(__file__).resolve().parent
CASE_FILE=ROOT/'g1_cases_PROPOSED.jsonl'
MANIFEST_FILE=ROOT/'g1_manifest_PROPOSED.json'
REGISTRY_FILE=ROOT/'g1_predicate_registry_PROPOSED.json'
CSV_FILE=ROOT/'g1_human_review_TEMPLATE.csv'


def validate_contract(rows, manifest, registry, human_rows):
    errors=[]
    def check(ok, message):
        if not ok: errors.append(message)
    ids=[r.get('caseId') for r in rows]
    check(len(rows)==47, f'case count expected 47, got {len(rows)}')
    check(len(set(ids))==47,'duplicate case IDs')
    check(Counter(x.get('family') for x in rows)=={'conversation':12,'catalog':14,'fault':10,'suite':11},'family counts changed')
    prednames=[p['name'] for p in registry['predicates']]
    check(len(prednames)==70 and len(set(prednames))==70,'70 unique predicate registry required')
    check(registry.get('implementedPredicateCount')==0 and registry.get('predicateRegistryStatus')=='SPEC_ONLY_NOT_IMPLEMENTED','runtime predicate implementation must not be claimed')
    check(manifest.get('runnerImplemented') is False and manifest.get('implementedPredicateCount')==0,'automated runner must remain unimplemented')
    check(manifest.get('caseCount')==47,'manifest case count mismatch')
    human_ids=[r.get('caseId') for r in human_rows]
    check(len(human_ids)==27 and len(set(human_ids))==27,'human review template count/uniqueness mismatch')
    valid_env={f'E{i}' for i in range(8)}
    valid_cap={f'C{i:02d}' for i in range(1,15)}
    valid_sce={f'S{i:02d}' for i in range(1,13)}
    recorded_human=set(manifest['humanCoreGate']['requiredCases'])
    check(len(recorded_human)==18,'human core merge gate count mismatch')
    snapshot=manifest['catalogFixtureBinding']
    target=snapshot['fixtureRowValue']
    check(target['productId'] and target['shadeId'] and target['foreignProductId'] != target['productId'] and target['foreignShadeId'] and target['targetContainsForeignShade'] is False,'catalog fixture does not establish foreign shade ownership')
    check(bool(re.fullmatch('[0-9a-f]{64}',snapshot['fixtureRowSha256PostgresJsonbText'])),'fixture observation checksum malformed')
    check(snapshot['snapshotIntegrityLevel']=='selected_DB_rows_fingerprinted_not_full_DB_snapshot','do not overclaim full immutable DB snapshot')
    resolver_keys={'FIXTURE.'+k for k in ('productId','shadeId','foreignProductId','foreignShadeId')}
    resolver_keys.update(manifest['sessionFixtureResolver']['fixtureKeys'])
    resolver_keys.update(manifest['arRegressionFixtureResolver']['fixtureKeys'])
    resolver_keys.update({'RUN.sourceSnapshotId'})
    automated_used=set()
    for x in rows:
        cid=x.get('caseId','?')
        required=set(x['environments']['required']);optional=set(x['environments']['optional'])
        declared=required|optional
        check(bool(required),f'{cid}: no required environments')
        check(not required&optional, f'{cid}: required and optional overlap')
        check(len(required)+len(optional)==len(x['environments']['required'])+len(x['environments']['optional']),f'{cid}: duplicate environment')
        check(declared<=valid_env,f'{cid}: invalid env')
        check(set(x['capabilityIds'])<=valid_cap and set(x['scenarioIds'])<=valid_sce,f'{cid}: invalid C/S mapping')
        check(x.get('reviewStatus')=='PROPOSED' and x.get('goldStatus')=='NOT_APPROVED',f'{cid}: falsely claimed gold/review')
        check(x['gStage']=='G1' and x['input'].get('locale','ko')=='ko',f'{cid}: wrong G/locale (ACK has no locale)')
        check(x['assertions']['automaticReadinessStatus']=='SPEC_ONLY_NOT_IMPLEMENTED',f'{cid}: false automatic readiness')
        entries=x['assertions']['automaticByEnvironment']
        names=[z['predicate'] for z in entries]
        automatic=x['assertions']['automatic']
        check(len(names)==len(set(names)) and set(names)==set(automatic) and len(automatic)==len(set(automatic)),f'{cid}: auto predicates duplicate or different from mapping')
        check(set(names)<=set(prednames),f'{cid}: predicate absent from registry')
        covered=set()
        for a in entries:
            applies=a['appliesTo'];covered.update(applies)
            check(bool(applies),f'{cid}: no appliesTo for {a["predicate"]}')
            check(len(set(applies))==len(applies) and set(applies)<=declared,f'{cid}: {a["predicate"]} references undeclared env')
            check(a.get('implementationStatus')=='TO_IMPLEMENT' and a.get('unobservedVerdict')=='NOT_RUN',f'{cid}: invalid predicate status')
        check(required<=covered,f'{cid}: required env without automatic assertion {required-covered}')
        check(optional<=covered,f'{cid}: declared optional env with no assertions {optional-covered}')
        check(set(x['evidenceByEnvironment'])==declared,f'{cid}: missing evidence artifact contract for environments')
        for env_name, contract in x['evidenceByEnvironment'].items():
            check(contract.get('mandatory')==(env_name in required) and bool(contract.get('requiredArtifacts')),f'{cid}: evidence requirements inconsistent for {env_name}')
        check(bool(x['expected'].get('factsOrBehaviors')) and bool(x['expected'].get('forbiddenClaims')),f'{cid}: missing factual/behavioral oracle or forbidden claims')
        check(isinstance(x.get('caseRevision'),int) and x['caseRevision']>=1,f'{cid}: caseRevision missing or invalid')
        check(not (set(x['expected'].get('requiredTools',[])) & set(x['expected'].get('optionalTools',[]))),f'{cid}: same Tool both required and optional')
        if x['family']=='catalog' and x['expected'].get('requiredTools'):
            check('E1' in required, f'{cid}: required Catalog Tool but E1 is not mandatory')
            check(bool(x['expected'].get('requiredHttpPaths')),f'{cid}: Catalog Tool with no actual HTTP contract')
        if cid in {'G1-REG-04','G1-REG-05'}:
            check(x['input'].get('chatContext',{}).get('session')=='${SESSION.sameOwnerSessionRef}' and 'R0' in str(x.get('executionRecipe',{})),f'{cid}: repeatable unexpired same-owner session scenario missing')
        automated_used.update(names)
        placeholders=set()
        def walk(v):
            if isinstance(v,dict):
                for y in v.values():walk(y)
            elif isinstance(v,list):
                for y in v:walk(y)
            elif isinstance(v,str):
                placeholders.update(re.findall(r'\$\{([^}]+)\}',v))
        walk(x['input']);walk(x['data']);walk(x['expected'])
        unknown=placeholders-resolver_keys
        check(not unknown,f'{cid}: unknown binding: {unknown}')
        data_keys=x['data']['fixtureKeys']
        check(set(placeholders)-{'RUN.sourceSnapshotId'}<=set(data_keys),f'{cid}: placeholder without declared data.fixtureKeys')
        if 'E1' in declared or ('E5' in declared and x['data']['kind']=='real_catalog'):
            check(x['data'].get('catalogFixtureRef')==snapshot['fixtureSnapshotId'],f'{cid}: declared actual Catalog environment missing pinned source fixture')
        gate=x['assertions'].get('humanGate',{})
        if cid in recorded_human:
            oracle=x['expected'].get('semanticOracle',{})
            check(gate.get('mergeBlocking') is True and oracle.get('humanRequired') is True and len(oracle.get('essentialBehaviors',[]))>=2,f'{cid}: missing semantic core merge gate')
            check(cid in human_ids,f'{cid}: not present in human scoring CSV')
        if cid=='G1-CAT-09':
            check('catalog.search_products' in x['expected']['requiredTools'] and 'GET /api/products' in x['expected']['requiredHttpPaths'] and {'E1','E5'} <= required,'G1-CAT-09 clear typo recommendation must execute real Catalog and UI')
            check(any(a['predicate']=='trace.catalog_called' and {'E1','E3'}<=set(a['appliesTo']) for a in entries),'G1-CAT-09 missing Catalog invocation assertion')
        if cid=='G1-CAT-14':
            check('catalog.search_products' in x['expected']['requiredTools'] and 'GET /api/products' in x['expected']['requiredHttpPaths'] and 'E1' in required,'G1-CAT-14 required Catalog Tool/E1 mismatch')
            check(any(z['predicate']=='trace.catalog_called' and 'E1' in z['appliesTo'] for z in entries),'G1-CAT-14 E1 tool trace missing')
            check(not x['expected'].get('optionalTools') and '검색을 다음 턴으로 미루면 불합격' in x['expected'].get('conditionalRule',''),'G1-CAT-14 cannot be optional/deferred search')
        if cid=='G1-CAT-01':
            vv=x['input'].get('requiredVariants',[])
            check({z['variantId'] for z in vv}=={'category_entry','free_chat'} and {z['requestType'] for z in vv}=={'chat','beauty_consultation'},'G1-CAT-01 must require both input routes')
            check(x['assertions'].get('variantExecutionPolicy')=='ALL_REQUIRED_VARIANTS_IN_EACH_MANDATORY_ENV','G1-CAT-01 variants not enforced')
        if cid=='G1-ERR-10':
            ctx=x['input']['chatContext']['session']
            check(ctx['expiresAt']=='${SESSION.expiresAt}' and ctx['stateVersion']=='${SESSION.stateVersion}', 'foreign owner fixture is incorrectly expired/static')
            check({'E0','E2'}<=required and x['expected'].get('httpStatus')==403 and x['expected'].get('errorCode')=='chat_session_forbidden','foreign owner must be active with 403 not 410')
        if cid=='G1-REG-03':
            check(x['input'].get('payloadSchema')=='ArAckRequest' and set(x['input']['body'])=={'requestId','commandId','sessionId','status','actualStateVersion'},'ACK request schema must be distinct from ChatRequest')
    check(set(prednames)==automated_used,f'predicate registry has unused/untracked keys {set(prednames)^automated_used}')
    check(recorded_human<=set(human_ids),'human gate requires missing CSV rows')
    for h in human_rows:
        check(h.get('coreGateRequired_yes_no')==('YES' if h['caseId'] in recorded_human else 'NO'),f'{h["caseId"]}: human template incorrect gate')
        check(not h.get('coreRequirementsMet_yes_no') and not h.get('semanticReviewStatus'),f'{h["caseId"]}: human score/result was fabricated')
    return errors


def main():
    rows=[json.loads(s) for s in CASE_FILE.read_text(encoding='utf-8').splitlines() if s.strip()]
    manifest=json.loads(MANIFEST_FILE.read_text(encoding='utf-8'))
    registry=json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))
    with CSV_FILE.open(encoding='utf-8-sig',newline='') as fh:
        human_rows=list(csv.DictReader(fh))
    errors=validate_contract(rows,manifest,registry,human_rows)
    if errors:
        for e in errors:print('STRUCTURE_FAIL:',e)
        raise SystemExit(2)
    print('STATIC_CONTRACT_ONLY_PASS:',len(rows),'cases;',len(registry['predicates']),'predicate specs;',len(manifest['humanCoreGate']['requiredCases']),'human core gates')
    print('Verified: mapping/fixture reference shapes and review template only; snapshot DB/API preflight NOT executed.')
    print('AUTOMATED_EVALUATION_NOT_READY: 70/70 predicate functions unimplemented; all E0-E7/LLM/Catalog/APP/AR outcomes NOT_RUN; Gold=0.')

if __name__=='__main__':main()
