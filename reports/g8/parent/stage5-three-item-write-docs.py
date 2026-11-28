import json,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent'
record=json.loads((OUT/'stage5-three-item-record.json').read_text(encoding='utf-8'))
assert record['security']['status']=='PASS'
app=json.loads((OUT/'stage5-three-item-app-pg.json').read_text(encoding='utf-8'))
ui=json.loads((OUT/'stage5-three-item-ui-observations.json').read_text(encoding='utf-8'))
assert app['result']=='PASS' and ui['cardDetailAfterRestore']=='PASS'
suite=ET.parse(OUT/'stage5-three-item-backend.xml').getroot()
total=sum(int(s.get('tests',0)) for s in suite.iter('testsuite'))
skip=sum(int(s.get('skipped',0)) for s in suite.iter('testsuite'))
assert sum(int(s.get('failures',0))+int(s.get('errors',0)) for s in suite.iter('testsuite'))==0
rows=[json.loads(x) for x in (OUT/'stage5-three-item-app-turns.jsonl').read_text(encoding='utf-8').splitlines()]
generation=sum(json.loads(x).get('event')=='start' for x in (OUT/'stage5-three-item-model-events.jsonl').read_text(encoding='utf-8').splitlines())
phases=[]
for name in ['live-initial','live-before-pending-case','live-pending-failure','live-debug','live-before-owner-normalize','live-owner-normalize-failure','live-before-omission-repair','live-before-clause-anchor','live']:
 p=OUT/f'stage5-three-item-{name}.json'
 if p.exists():
  r=json.loads(p.read_text(encoding='utf-8'));phases.append({'phase':name,'cases':len(r['cases']),'passed':sum(c['pass'] for c in r['cases']),'http':len(r['events'])})
events=[]
for p in phases:events+=json.loads((OUT/f"stage5-three-item-{p['phase']}.json").read_text(encoding='utf-8'))['events']
standalone=len({(e.get('at'),e.get('model'),e.get('path')) for e in events})
embed=0
p=OUT/'stage5-three-item-g5-models.jsonl'
if p.exists():embed=sum(json.loads(x).get('event')=='start' and json.loads(x).get('path')=='/v1/embeddings' for x in p.read_text().splitlines())
text=f"""
## 최신 실행 — 잔여 세 항목 마감 및 ⑤ 종료 판정 (2026-11-28)

전체 **① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → ⑤ 협력 완성 종료 → ⑥ 통합 검증 착수 대기 → ⑦ PR 인계**. 이번 범위는 번호 선택, 답변 반복·모순, 명시 상품 종류 검색 연결의 세 항목으로 고정했다. 새 기능/시나리오를 추가하지 않았다. 사용자 승인 17개 기존 파일 중 제품·테스트 14개와 이 두 관리 문서·trace만 수정하며, 신규 증빙은 `reports/g8/parent/stage5-three-item-*`다. 이전 WIP/과거 실행·실패 trace를 보존한다. 개발 하위 에이전트/commit/push/PR/배포 없음.

기준 HEAD `3a8ee1c5d44214623487e5f07717500368259900`, branch `feat/compound-consultation`. develop 로컬 참조 `991dd634dba33b99ceeb1c03de4dd8d921ce07f9`; 원격 최신 조회를 했다는 뜻이 아니다. 미커밋 소스는 baseline/source diff, uncommitted-source, release-sources 및 각 실제 서버의 immutable sourceSnapshot으로 식별한다. 최종 record가 원본 경로/해시를 연결한다.

### 세 항목의 결과

1. **번호 선택:** 현재 선택지 위치를 서버가 실제 task ID로 바인딩한다. 구버전·범위 밖·번호/ID 불일치는 거절한다. 실제 앱의 `2번 결과 보여줘`는 재질문 없이 피부 결과·카드를 표시했고 Catalog 호출은 0회였다. 질문 소유권은 보존하며 다른 작업 질문을 결과에 끼워 넣지 않는다.
2. **답변:** 원인·효능 미입증 고정 문구를 제거했다. 실제 G5 설명과 Catalog 판정을 나누고, 누락은 검증된 필수 설명 요구에서 생성하며 인용된 원문 적용 범위는 유지한다. 개인 진단/특정 상품 효능 입증을 일반 관리 상담의 새 필수 조건으로 요구하지 않는다. 이번 실제 결과에 특정 개인의 효능이 입증됐다고 기록하지 않는다.
3. **종류·실행:** enum 피부 종류 외 명시한 상품명 종류를 name_term으로 보존한다. 상위 전체 인용과 위임 절이 달라도 종류 단어는 양쪽에 실제 존재해야 한다. 오래된 후보로 새 Catalog 읽기를 막지 않고 사용자 필터만 유지해 재조회한다. 동일 질문 소유자의 중복 표현은 정확히 동일한 경우만 정규화한다. 읽기 절이 미배정된 보존 전용 계획은 기존 deadline 안에서 1회만 재계획한다(설정·근거·초과 동작은 최신 SPEC). 실제 Catalog의 lip 후보를 상품명 근거로 판정해 립펜슬 6개를 표시했다. 피부·룩 결과와 정확한 판매 옵션은 PG에서 보존됐다.

### 실제·모의 증거

- **계약·모의 전체:** 최종 챗봇 {total-skip} PASS / {skip} SKIP (`backend.xml/log`), ruff PASS, 계층 3 KEPT. 최초 fixture/저장 결과 누락/저장 위치 문제와 중간 기존 카드 회귀 실패를 별도 XML/log에 보존했다. 정상 일반 상품 복수 카드 계약은 바꾸지 않았다. 앱 typecheck/lint PASS이며 앱/인증 소스는 수정하지 않았다.
- **실제 PG + 주요 모델/인증 모의:** `vishue_chat_test`, 27 PASS / 4 SKIP / 2 DESELECTED (`pg.log/xml`). 로그인 앱 검증과 합산하지 않는다.
- **실제 모델/합성 상태:** 최종 고정 3사례×3회 9/9 PASS. 단계별 원본/제안/거절/HTTP 수는 live*.json/log다. 최종 이전 실패와 통과를 하나의 성공률로 합산하지 않는다. 전체 독립 해석 검증 generation HTTP는 {standalone}회이며 단계 목록은 아래/record에 보존한다.
- **실제 모델·G5·Catalog·PG·로그인 앱:** Aside 지속 REPL의 실제 기존 Supabase/G7 동의 세션. 신규 로그인/동의 변경 없음. 전체 {len(rows)}턴, generation HTTP {generation}회, G5 API embedding {embed}회. G5 generation은 chatbot events에 포함되므로 이중 합산하지 않는다. 모델 alias는 gpt-6-luna/gpt-6.1-terra, embedding text-embedding-3-large; provider 고정 snapshot ID는 수집하지 않았다. live 설정과 실제 호출은 턴별로 분리했다. replay/mock 앱 턴 없음. 저장 결과 show/후보 재사용을 새 모델 호출로 세지 않는다.
- **최종 소스 연결:** 실제 종류 조회와 G5 설명 생성은 app-pg의 producerEvidence가 가리키는 sourceSnapshot에서 확인했다. 해당 Product/G5/계획 스키마·서비스 해시는 최종 소스와 같으며 마지막 차이는 부모의 동일 보존 안내 중복 제거다. 최종 sourceSnapshot과 일치하는 앱 턴 {app['finalSourceTurns']}개에서는 그 실제 결과를 번호로 재표시했다. 이를 최종 소스의 새 G5 생성 호출로 바꾸어 기록하지 않는다. PG의 typed parent가 실제 앱 최종 응답과 동일하고, 검색 전후 피부·룩 결과/판매 옵션이 같았다. `app-pg.json`, `dialogue.txt`, `app-turns.jsonl`이 원문이다. 조회 요청/전문 작업별 결과와 V4 버전 `local-20261104-conservative-v1-20261123T111457291156Z` 및 정확 옵션 근거를 보존했다. 전체 Catalog DB의 전역 snapshot은 고정하지 못했다.
- **앱 복원·상세:** 최근 상담의 카드와 결과를 복원하고 상품 보기로 실제 상세에 이동했다. URL의 optionId와 화면 판매 옵션을 저장된 옵션과 대조했다(`ui-observations.json`). 판매 옵션 결제/장바구니 쓰기/AR 실행/기억 쓰기는 하지 않았다. 캡처가 실제 저장된 경우만 파일을 증빙으로 센다.
- **보안:** Gitleaks 8.30.1 / 빈 ignore / redact, 실제 런타임 인증값·DB owner 식별자 비교 통과. 최종 파일 수/해시는 record.security 및 security.log를 따른다. 마지막 문서까지 재검사 후 trace에 한 행만 추가한다. 공용 보안 설정/이력/검사 범위는 변경하지 않는다.

### 실패·한계 보존

초기 uv 캐시 접근 실패, 테스트 임시 디렉터리/fixture 실패, 중간 카드 집계 회귀, 실제 모델의 인용/중복 표현 거절과 읽기 누락, 과거 후보 만료에 따른 조회 차단, G5 오류, 서버 시작 중 UI 네트워크 오류를 통과로 바꾸지 않았다. G5의 한 오류는 당시 상세 코드를 수집하지 못했고, 다른 오류는 invalid_requirements로 거절된 것을 trace에서 확인했다. 장시간 실행 중 401 뒤 정상 GET 200과 UI 재전송을 관측했으며 인증 소스를 수정하거나 SDK 결함으로 단정하지 않았다. 원문·실패 sourceSnapshot·재실행을 모두 남겼다. 최신 source/최종 통과만 종료 근거로 사용한다. 자연스러운 상담 표현의 광범위 안정성, G5 실패율/지연, 모바일 터치는 ⑥에서 평가한다.

### 6묶음 종료표와 다음 단계

| 묶음 | ⑤ 판정 근거 | ⑥에 남는 구분 |
|---|---|---|
| 1 공통 계획 진입 | 기존 최초/후속/작업 ID 구조 유지 + 실제 명시 종류 검색 실행, 누락 읽기 재계획 | 별도 표현·다른 데이터의 전체 평가 |
| 2 결과 기반 협력 | 기존 결과 binding 유지 + 실제 G5/정확 옵션 입력·결과, 관련 전체 회귀 | 원래 N01/N02/E01/B01 연속 종단 전체 판정 |
| 3 후속·질문 | 동일 owner 정규화·충돌 거절·형제 보존 + 실제 PG/앱 상태 비교 | 자유 지시어·생략 표현 안정성 |
| 4 실행 제어 | 기존 실행 중 취소/교체/final commit 계약과 관련 회귀 유지; 이전 실제 증거는 당시 source로 구분 | 이번 중단 전체 종단은 재실행하지 않음. ⑥에서 최신 소스 연속 평가 |
| 5 판정·답변·복원 | 실제 번호 표시·종류 카드·저장/복원/정확 옵션 상세, 완료·부분/질문/실패 회귀 | 원래 상황별 UX·휴대폰 터치·사람 검토 |
| 6 증거 정합성 | 현재 source/diff, 실제·모의·실패·보안/원본 대조 | 전역 데이터 snapshot/성능/전체 평가 결과 |

**⑤ 구조 구현 및 고정 세 항목의 마감 기준 충족으로 종료한다. G8 전체 완료가 아니다.** 다음은 ⑥의 원래 14능력/12시나리오와 N01/N02/E01/B01 지정 환경·별도 표현/데이터·로그인 앱 연속 종단·모바일·성능·사람 검토다. 이번에 그 범위를 실행했다고 주장하지 않는다. PR은 아직 생성하지 않는다. 현재 추가 사용자 정책 판단 없음.

독립 실제 모델 실행 단계(성공률 합산 금지): `{json.dumps(phases,ensure_ascii=False)}`.

"""
p=ROOT/'docs/ai-design/G8-WORKLOG.md';s=p.read_text(encoding='utf-8');title,rest=s.split('\n',1)
p.write_text(title+'\n'+text+rest,encoding='utf-8')
print('Updated canonical worklog after actual checks and security preflight')
