# ADR-0012 챗봇 지식 저장소는 Neo4j 대신 PostgreSQL pgvector를 쓴다

- 상태: 채택 (2026-11-22). [ADR-0002](0002-postgres-source-neo4j-copy.md)의 Neo4j 사본 부분은 이 결정으로 대체한다.

## 배경

챗봇은 제품·성분·룩 관계를 Neo4j(AuraDB) 사본에서 읽도록 설계했다. 운영에서는 AuraDB 계정·동기화 잡·별도 시크릿이 필요하고, 팀 공용 DB도 이미 PostgreSQL(RDS)로 모이므로 그래프 DB를 하나 더 두는 비용·운영 부담이 크다. 벡터 검색(유사 제품·상담 근거)은 RDS의 `pgvector`로 충분하다고 판단했다.

## 결정

1. **운영·개발 모두 Neo4j / AuraDB를 쓰지 않는다.** 새 배포에 `NEO4J_*`·`sync-graph`·AuraDB 시크릿을 넣지 않는다.
2. **지식·임베딩 원본은 PostgreSQL(운영은 RDS)** 이다. `pgvector` 확장으로 임베딩을 저장·검색한다.
3. **소유권:** 스키마·마이그레이션은 `backend/api`(또는 합의한 단일 DB 소유 서비스)가 관리하고, `chatbot`은 읽기(필요 시 제한된 쓰기)만 한다. 챗봇이 별도 그래프 DB 비밀번호를 갖지 않는다.
4. **기존 `sync_graph`(api HTTP → Neo4j)는 폐기**하고, 적재는 마이그레이션·시드·배치 잡이 PostgreSQL에 직접 한다.
5. **인프라:** Terraform/Helm에서 Neo4j 인클러스터·AuraDB 전제 values는 제거·비활성한다. RDS에 `vector` 확장을 허용한다.

## 결과

- DB·시크릿·동기화 경로가 하나로 줄어 컷오버가 단순해진다.
- GraphRAG 전제 코드(`graph_repository`, Neo4j 드라이버)는 pgvector 조회로 바꿔야 하며, 바꾸기 전까지 챗봇 그래프 기능은 꺼 두거나 카탈로그 API만 쓸 수 있다.
- ADR-0002의 “챗봇은 PostgreSQL에 직접 붙지 않는다” 조항은 이 결정으로 철회된다. 최소 권한 DB 역할로 범위를 제한한다.
