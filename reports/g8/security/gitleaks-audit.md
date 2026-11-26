# G8 Gitleaks 오탐 조사 및 최소 패치

작성일: 2026-11-26 (KST). 상태: 로컬 조사·패치·검증 완료, 원격 미반영.

## 전체 진행과 작업 분리

① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성** → ⑥ 통합 검증 → ⑦ PR 인계.
G8은 ⑤-1 N01 실제 품질·⑤-2 N02 첫 연결 상태를 유지한다. 이번 보안 부수 작업은 조사→검증된 예외→신규 기록 개선→로컬 검증→보고까지 진행했다.

원본 feat/compound-consultation HEAD 4173f36658fb96086388971ceb927a651deb147b와 미커밋 구현·테스트·trace는 수정하지 않았다. 독립 worktree g8-gitleaks-audit에서 fix/g8-evidence-secret-scan으로 준비했다. 시작 develop은 c70240a였고 조사 중 최신 원격을 확인해 38a15de0d4fd51a1c7fa99630474c114172ccafc로 작업 기준을 옮겼다. 두 기준의 secrets.yml/.gitleaks.toml은 동일했다. 커밋·push·PR·병합·배포는 수행하지 않았다.

## 실제 원인

CI: https://github.com/gyuniverse-hq/SKN34-Final-Project/actions/runs/45735521253
job 139627693743, Gitleaks 8.30.1, checkout 0473bf207e7885c3cee03a038e58da50ed6636bc.
PR #294 head f96b23be, base c70240a의 임시 병합 커밋이며 G8 4173f36은 이 커밋의 조상이 아님을 git merge-base --is-ancestor(exit 1)로 확인했다.

checkout fetch-depth=0은 +refs/heads/*:refs/remotes/origin/* 및 tags를 가져왔다. Gitleaks 기본 Git 명령은 git log -p -U0 --full-history --all --diff-filter=tuxdb다. 따라서 PR 변경이나 조상만이 아니라 가져온 다른 브랜치 이력도 검사했다. 이는 검증된 설정 동작이며 이번 패치에서 검사 범위를 줄이지 않는다.

- 공식 구현: https://github.com/gitleaks/gitleaks/blob/v8.30.1/sources/git.go
- 공식 generic-api-key 규칙: https://github.com/gitleaks/gitleaks/blob/v8.30.1/config/gitleaks.toml

검출 경로를 JSON key로 기록한 auth.py, internal_deletion_auth.py, test_g7_conversation_api_pg.py의 auth/Api 단어와 뒤의 고엔트로피 SHA256 값이 generic-api-key 패턴에 맞았다. 64자리라는 이유만으로 오탐이라고 판정하지 않았다. 아래 22건을 실제 소스 바이트로 재계산했다.

## 22건 개별 증명

전체 fingerprint, trace 필드 경로, 소스 commit/blob, 바이트 수, 재구성 방법은 source-proof.json에 있다. 검출값 자체는 보고서·출력에 포함하지 않았다. 동일 fingerprint의 복수 항목도 각각 확인했다. 모든 행은 UTF-8 CRLF 기준이며 Git LF blob 그대로의 해시와 구분한다.

소스 약어: A = backend/chatbot/app/core/auth.py; D = backend/chatbot/app/core/internal_deletion_auth.py; T = backend/chatbot/tests/test_g7_conversation_api_pg.py.
trace 약어: F = reports/g8/first-compound/trace.jsonl; N = reports/g8/n01/trace.jsonl.

| # | 검출 commit | trace:행 | 소스 | 재계산 기준 commit | 판정 |
|---|---|---|---|---|---|
| 1 | 4173f36 | N:146 | T | 8cade25 | 일치 |
| 2 | 4173f36 | N:156 | T | 8cade25 | 일치 |
| 3 | 1dceb38 | N:93 | T | 3bb4798 | 일치 |
| 4 | 1dceb38 | N:141 | T | 3bb4798 | 일치 |
| 5 | 1dceb38 | N:145 | T | 3bb4798 | 일치 |
| 6 | 5ed8ac1 | F:1 | A | 8bde587 | 일치 |
| 7 | 5ed8ac1 | F:1 | D | 8bde587 | 일치 |
| 8 | 5ed8ac1 | F:1 | T | 0e3973f | 일치 (미커밋 복원) |
| 9 | 5ed8ac1 | F:4 | A | 8bde587 | 일치 |
| 10 | 5ed8ac1 | F:4 | D | 8bde587 | 일치 |
| 11 | 5ed8ac1 | F:6 | A | 8bde587 | 일치 |
| 12 | 5ed8ac1 | F:6 | D | 8bde587 | 일치 |
| 13 | 5ed8ac1 | F:9 | A | 8bde587 | 일치 |
| 14 | 5ed8ac1 | F:9 | D | 8bde587 | 일치 |
| 15 | 5ed8ac1 | F:9 | T | 0e3973f | 일치 |
| 16 | 5ed8ac1 | F:14 | T | 0e3973f | 일치 |
| 17 | 64188a2 | N:1 | T | 9b1df1d | 일치 |
| 18 | 64188a2 | N:16 | T | 9b1df1d | 일치 |
| 19 | 64188a2 | N:32 | T | 9b1df1d | 일치 |
| 20 | f7b97e1 | N:49 | T | b0435a6 | 일치 |
| 21 | f7b97e1 | N:74 | T | b0435a6 | 일치 |
| 22 | f7b97e1 | N:92 | T | b0435a6 | 일치 |

21건은 Git blob을 LF→CRLF로 직렬화한 바이트와 일치했다. 1건(F:1의 T)은 당시 미커밋 상태다. 0e3973f의 테스트 파일에서 후속 checkpoint namespace/raw marker 검사와 [1] 인용 표시 검사 변경을 정확한 문자열 anchor로 역변경한 55,539바이트 CRLF가 일치했다. scripts/audit_g8_gitleaks.py의 restore_initial_test가 Git 자료만으로 재현한다.

재구성 근거는 당시 로컬 실행 기록의 2026-11-25T16:06:40.415Z와 16:17:01.991Z 변경이다. 최초 trace 시각 15:54:03.580567Z보다 늦다. 원본 세션 로그는 게시하지 않고 재현에 필요한 해당 테스트 코드 변환만 도구에 넣었다. 최종 커밋 파일을 당시 실행 파일과 같다고 주장하지 않는다.

결론: 확정된 소스 해시 오탐 22건, 미확정 0건, unique fingerprint 16개. 이는 두 trace의 모든 종류 개인정보까지 없다는 포괄 판정은 아니다.

## 최소 예외 선택

.gitleaksignore에 위 16개 fingerprint만 추가했다. 각 fingerprint는 commit/path/rule/line으로 한정되며 같은 그룹의 모든 검출값을 재계산한 뒤에만 등록했다. 스크립트는 한 그룹에 미확정 항목이 있으면 그 fingerprint를 생성하지 않는다.

.gitleaks.toml에 경로+개별 hash 허용을 추가하는 대안은 같은 값이 미래 다른 커밋에 사용돼도 숨길 수 있고 별도의 패턴 유지가 필요하므로 채택하지 않았다. reports/g8 경로 전체, 64자리 전체, generic-api-key 규칙 전체의 제외는 없다. secrets.yml/.gitleaks.toml은 변경하지 않았다. 과거 trace와 Git 이력도 그대로다.

## 재발 방지 및 호환성

저장소 조사에서 G8 JSONL 전용 writer나 sourceSha256 맵을 읽는 프로그램 소비자는 발견되지 않았다. graph는 메모리 trace 리스트를, 테스트는 record_property를 제공했고 실제 파일 기록은 임시 검증 실행 코드가 담당했다. 이를 대신할 scripts/g8_evidence.py를 추가했다.

새 sourceManifestVersion=2는 동일 해시 필드를 [{"path":"relative/file.py","sha256":"…"}]로 기록한다. 파일은 정확한 worktree 바이트 그대로 해시하고 sourceByteBasis=worktree-exact로 표시한다. 숨겨진 LF 정규화는 없다. read_manifest는 과거 map과 새 list를 모두 읽으며 의미 보존을 검증했다. 작업 결과·모델 모드·호출 수·평가 필드는 그대로 둔다.

writer는 CI와 동일한 Gitleaks 8.30.1을 확인하고, 새 레코드의 JSON key/value 전체를 빈 history ignore로 검사한 뒤 append한다. 검출·잘못된 설정·실행 실패 시 저장하지 않고 원문 없는 오류만 반환한다. 과거 trace를 다시 쓰지 않는다. Gitleaks는 개인정보/동의 검사의 대체 수단이 아니며 기존 비식별·외부 전송 정책도 적용해야 한다.

G1~G9 조사에서는 tests/run_product_eval.py의 sourceHashes와 G1 증빙 소비 계약을 확인했다. 해당 기존 계약은 변경하지 않았다. G1 sanitization은 키의 민감 필드명과 값의 패턴 검사이므로 이것을 실제 Gitleaks 검증과 동일시하면 안 된다. 다른 기록 전체 리팩터링은 하지 않았다.

현재 원본 G8 미커밋 신규 53개는 구형 형식 때문에 오탐 2건이 남아 있다. 복사본을 v2로 변환하면 0건이며 의미는 보존된다. 원본 미커밋 작업을 보존하라는 지시에 따라 원본 209개 trace는 변경하지 않았다. **향후 G8 게시 전에 이 53개에 대한 보존·변환 방식을 명시적으로 정하고 새 writer를 적용해야 한다.** 이미 게시된 156개는 그대로 유지한다. 아직 존재하지 않는 미래 commit fingerprint를 미리 허용하지 않는다.

## 실제 검증

ci-reproduction.json은 CI metadata 및 fingerprint 다중집합 비교, validation.json은 형식·음성/양성 대조 결과다.

| 검사 | 전 / 후 | 범위 |
|---|---|---|
| CI 원본 | 22건 실패 | 710 commits, 8.30.1 |
| 로컬 Windows 전체 이력 | 22 → 0 | 현재 공유 Git 이력, 같은 규칙; CI의 ref snapshot과 다름 |
| Linux PR #294 정확한 checkout | 22 → 0, exit 1 → 0 | CI와 동일 명령·버전·설정, 현재 확보 참조 712 commits |
| CI vs Linux 검출 | 22건 fingerprint 다중집합 완전 일치 | 중복 6건도 포함 |
| 기존 검출 manifest 16개 형식 비교 | 구형 22 → v2 0 | 임시 복사본, 원본 불변 |
| 미커밋 신규 기록 53개 | 구형 2 → v2 0 | 임시 복사본, 원본 불변 |
| 가상 키 보안 대조 | 2건 정상 검출(exit 1) | 같은 G8 경로·행의 새 임시 commit 및 다른 파일; generic-api-key/openai-api-key |
| writer·재계산 unittest | 5 통과 | 22건 재계산, 미확정 값 거부, 호환성, 바이트 기준, 원본 보존, 실제 scanner 거부 |
| G8 관련 회귀 | 67 통과 | 보존한 원본 worktree의 N01·N02 모의 테스트, 실제 모델 0회 |
| 린트·앱 | Python Ruff, npm typecheck/lint 통과 | 앱 소스 변경 없음, 앱 검사는 원본 worktree |

CI 시점의 모든 ref SHA 목록은 로그에 없으므로 그때의 정확한 710개 ref 집합을 복원했다고 주장하지 않는다. 로컬 Linux 검사 712개와 이 차이를 명시한다. PR #294의 원격 CI는 재실행하지 않았다. 이번 패치가 원격 CI에 반영됐다고 보고하지 않는다.

최초 Linux /tmp 준비 경로가 다음 호출에 유지되지 않아 실행하지 못한 시도는 제외했다. /var/tmp 기반 복제본과 외부 로그 보존으로 재실행했다. 일부 샌드박스 Ruff cache 접근 실패는 --no-cache/허용된 실행 환경으로 해결했다. 중간 줄 길이 린트 실패를 수정 후 재검사했다. 가상 키는 오직 임시 저장소에서 생성·검출했으며 외부 API로 전송하지 않았다.

## 재현 명령

설정·이력을 보존한 checkout에서 CI 재현:
```sh
gitleaks version
gitleaks detect --source . --config .gitleaks.toml --verbose --redact
```

기존 22건을 다시 증명하려면 **빈 .gitleaksignore 경로를 명시**하여 비공개 임시 JSON 보고서를 생성한다. raw report는 Git 밖에 두고 콘솔·공유 보고서에 출력하지 않는다. 이후:
```sh
python scripts/audit_g8_gitleaks.py --findings PRIVATE_REPORT.json --proof SAFE_PROOF.json
GITLEAKS_BINARY=/path/to/gitleaks python -m unittest discover -s scripts -p test_g8_evidence.py -v
```
Windows에서는 환경변수를 PowerShell 방식으로 지정한다. .gitleaksignore 생성 옵션은 새 경로에만 허용하며 기존 파일을 덮어쓰지 않는다.

새 증빙 추가:
```sh
python scripts/g8_evidence.py --record NEW_RECORD.json --output TRACE.jsonl --root . --source backend/chatbot/app/services/chat_service.py --gitleaks /path/to/gitleaks --config .gitleaks.toml
```
NEW_RECORD는 비식별화된 신규 한 레코드다. 기존 전체 trace를 입력해 재저장하는 명령이 아니다. 향후 CI Gitleaks 버전 변경 시 writer의 pin도 함께 갱신해야 한다.

## 권장 PR 구성·반영 순서와 협의

1. 공용 보안 패치: .gitleaksignore + audit_g8_gitleaks.py + source-proof.json + ci-reproduction.json + 이 조사 기록. 인프라 담당자는 16개 fingerprint, 기본 --all 정책 유지, CI 버전 일치를 검토한다. CI 범위를 PR diff로 축소하는 변경은 이번 범위 밖이다.
2. 기록 도구 패치: g8_evidence.py + test_g8_evidence.py + validation.json 및 사용법. 별도 논리 commit으로 분리한다. 테스트의 역사 재계산은 1번 증빙에 의존하므로 순서를 유지한다.
3. 승인 후 공용 패치를 반영하고 영향 받은 PR에서 실제 CI를 재실행한다. 그때까지 원격 해결은 NOT_RUN이다.
4. G8 기능 branch 게시 전 미커밋 신규 기록의 v2 전환을 처리하고 Gitleaks를 다시 통과시킨다. 과거 게시 이력은 재작성하지 않는다.

G8 기능·공용 API·평가 판정은 변경하지 않았다. 이 조사 때문에 N01/N02 미완료를 완료로 바꾸지 않는다. 인프라 담당자에게 메시지를 보내거나 PR을 만들지는 않았다.

## 후속 드래프트 게시 준비

2026-11-26 후속 사용자 지시로 이 보안 패치를 develop 대상 드래프트 PR에 게시한다. 앞 절의 미커밋·원격 미반영은 조사 완료 당시 기록이다. 기능 G8 작업은 별도 worktree에 보존하며 이 PR에 포함하지 않는다. 최신 develop 38a15de 기준의 이 worktree에서 잠금 의존성을 설치하고 npm run check -- -- --runInBand --silent를 실행해 타입·린트·107개 suite/1,321건 통과(112.26초)를 확인했다. 보안 도구 unittest 5건(54.021초)·Ruff 통과, 현재 전체 이력 Gitleaks 8.30.1 검사 725 commits/0건을 확인했다. 이력·환경별 커밋 수 차이는 앞의 CI 710개 및 Linux 재현 712개와 구분한다. 상세 게시 검사 결과는 validation.json의 draftPublicationChecks다. 병합·배포는 별도 지시 대상이다.
