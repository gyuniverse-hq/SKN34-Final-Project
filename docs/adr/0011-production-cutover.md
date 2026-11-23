# ADR-0011 운영 컷오버: RDS 공용 원본, 덤프→시드 보정, 1차 범위

- 상태: 채택 (2026-11-22)

## 배경

팀 공용 개발 DB(Supabase, Render 경로) 용량이 한계에 닿아, 당분간 덤프를 나누고 각자 로컬 PostgreSQL로 개발해 왔다. 운영·시연에서는 다시 **한 원본 DB**를 써야 하고, 이미 정한 운영 골격(Terraform · EKS · Helm · Argo CD · Envoy Gateway · GHCR)은 바꾸지 않는다. 얼굴 영상은 기기 밖으로 보내지 않으며, GPU 추론 서버는 운영 1차 경로에 넣지 않는다.

## 결정

1. **골격 유지**  
   ADR-0003·0004·0008을 따른다. 이미지 레지스트리는 GHCR, 진입점은 Envoy Gateway, 인프라는 Terraform, 배포는 `values-prod.yaml` 태그 PR → Argo CD다.

2. **공용 원본 DB는 운영 RDS**  
   EKS의 `api`가 붙는 RDS PostgreSQL이 카탈로그·회원·주문 등의 원본이다. Auth는 계속 Supabase Auth다. RDS는 프라이빗 서브넷이라 앱·시연은 Gateway URL로 붙고, 노트북에서 DB에 직접 붙는 것은 기본이 아니다(필요 시 bastion은 별도 결정).

3. **초기 데이터: 덤프 복원 후 시드 보정**  
   - 로컬·공용에서 쓰던 PostgreSQL 덤프를 RDS에 한 번 복원한다.  
   - Pod 기동 시 Alembic으로 스키마를 맞춘다.  
   - Git의 `backend/api/seed/catalog.json`과 어긋나는 카탈로그만 시드로 맞춘다. 챗봇 지식은 Neo4j가 아니라 pgvector(ADR-0012)로 RDS에 둔다.  
   - 덤프가 카탈로그만이고 나머지를 버릴 수 있을 때는 시드만으로 단순화할 수 있다.

4. **운영 1차 범위 (지금 구축)**  
   - Terraform으로 VPC · EKS · RDS · ElastiCache · Secrets Manager · **S3**(백업·덤프·이후 에셋)  
   - 플랫폼: metrics-server, Envoy Gateway, External Secrets, Argo CD  
   - 시크릿·`values-prod` 채우기 → 첫 GitOps 배포  
   - **시연 외 기간 축소(pause) / 재개(resume)** 런북(노드 축소, RDS 정지 등)  
   - 시크릿 스캔 CI(gitleaks)  
   - 배포 후 경로 검증 스크립트(`/healthz`·핵심 API)

5. **1차에서 빼는 것 · 다음 단계**  
   - Runpod 등 GPU 서버, Karpenter, k6 부하는 필요해질 때  
   - Prometheus · Grafana · Langfuse는 ADR-0007의 관측 확장으로 클러스터 기동 이후(2차)

## 결과

- 덤프로 흩어졌던 데이터가 운영 RDS로 다시 모이고, 팀은 공용 API(Gateway)를 본다.  
- 시연이 아닐 때 pause로 고정비를 줄일 수 있다.  
- S3는 덤프·백업 보관과 이후 에셋 자리로 쓴다.  
- 로컬 개발은 계속 Compose(또는 덤프)로 가능하고, Render 경로는 당분간 보조·폐기 일정은 별도로 정한다.
