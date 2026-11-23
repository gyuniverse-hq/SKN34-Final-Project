# VISHUE AWS 구성 공부 노트 (as-built)

> 기준: 2026-11 운영 컷오버 이후, 캠프 AWS 계정에서 **실제로 돌아가는 구성**.  
> 목표는 “어려운 용어”보다 **누가 무엇을 하고, 어떻게 이어지는지**를 이해하는 것.

관련 자료:

- 다이어그램: [`vishue-architecture.html`](./vishue-architecture.html) / [`vishue-architecture.png`](./vishue-architecture.png)
- 결정 기록: [ADR-0011](../adr/0011-production-cutover.md), [ADR-0012](../adr/0012-pgvector-instead-of-neo4j.md)
- 배포 절차: [`docs/DEPLOYMENT.md`](../DEPLOYMENT.md)

---

## 1. 한 줄 요약

폰의 Expo 앱이 **Gateway 주소 하나**로 요청을 보내고,  
AWS 서울 리전의 **EKS(쿠버네티스)** 위에서 api / chatbot이 처리한 뒤,  
**RDS PostgreSQL**에 있는 제품·룩 데이터를 돌려준다.  
로그인은 **Supabase Auth**만 담당한다 (제품 DB가 아님).

```
Expo 앱
  → NLB + Envoy Gateway
  → EKS (EC2 노드 2대 위 api / chatbot Pod)
  → RDS / Redis
```

---

## 2. 전체 그림

```
[사용자 폰 · Expo Go]
        │
        │  EXPO_PUBLIC_API_BASE_URL = Gateway NLB DNS
        │  (로그인 JWT는 Supabase에서 발급)
        │
        ▼
┌─────────────────── VPC (10.40.0.0/16) ───────────────────┐
│                                                          │
│  [퍼블릭]  NLB + Envoy Gateway  ← 인터넷에서 들어오는 문   │
│              │                                           │
│              ├─ /api/chat* → chatbot Pod                 │
│              └─ /api/*     → api Pod                     │
│                                                          │
│  [프라이빗]  EC2 ×2 (EKS 워커 노드, t3.large)              │
│              ├─ api Pod ×2                               │
│              └─ chatbot Pod ×2                           │
│                    │                                     │
│                    ├─► RDS PostgreSQL 17 (원본 DB)         │
│                    ├─► ElastiCache Redis                 │
│                    └─► (밖으로) LLM 등 ← NAT Gateway       │
│                                                          │
│  Secrets Manager → External Secrets → Pod 환경변수         │
│  S3 = 덤프·백업   ECR = 컨테이너 이미지(임시)                │
└──────────────────────────────────────────────────────────┘

[Supabase Auth] ── 로그인만 (앱 ↔ Supabase)
[외부 API] 네이버·유튜브·OpenAI·Toss 등 (키는 Secrets에)
```

---

## 3. 각 구성 요소와 역할

### 3.1 VPC (Virtual Private Cloud)

| 항목 | 내용 |
|------|------|
| **뭔가** | AWS 안에 만든 **우리 전용 네트워크** |
| **역할** | EC2·RDS·Redis·NLB가 같은 “울타리” 안에서 통신 |
| **지금** | `10.40.0.0/16`, AZ 2개 |
| **왜 필요** | RDS를 인터넷에 직접 안 열고, 서버만 사설망에 두기 위함 |

퍼블릭 서브넷에는 로드밸런서,  
프라이빗 서브넷에는 노드·DB·캐시가 있다.

---

### 3.2 EC2 (EKS 워커 노드) × 2

| 항목 | 내용 |
|------|------|
| **뭔가** | 빌린 **서버 컴퓨터** 2대 |
| **역할** | 그 위에서 api / chatbot **프로그램(Pod)** 실행 |
| **타입** | `t3.large`, 서로 다른 AZ (고가용성) |
| **주의** | EC2 ① = api, EC2 ② = chatbot **이 아님** |

보통 각 노드에 api·chatbot이 **나뉘어** 떠 있다.  
한 대가 죽어도 다른 대에 복제본이 남도록 하기 위해서다.

pause 시에는 노드 desired를 0으로 줄여 **이 EC2 비용을 끈다**.

---

### 3.3 EKS (Elastic Kubernetes Service)

| 항목 | 내용 |
|------|------|
| **뭔가** | 관리형 **쿠버네티스** |
| **역할** | “어떤 이미지를 몇 개 띄울지” 관리, 죽은 Pod 재시작, 롤링 배포 |
| **클러스터 이름** | `vishue` |

컨트롤 플레인(매니저)은 AWS가 돌리고,  
실제 일꾼은 위 EC2 노드다.  
pause해도 컨트롤 플레인은 남아 **고정비가 조금** 나온다.

---

### 3.4 Pod / Deployment (api, chatbot)

| 이름 | 역할 |
|------|------|
| **api** | 제품·룩·회원·추천 등 REST API. RDS가 원본 |
| **chatbot** | 상담·LLM·pgvector RAG. `/api/chat` |
| **Pod** | EC2 위에서 **지금 실행 중인** 컨테이너 인스턴스 |
| **Deployment** | “api를 2개 유지해” 같은 선언. HPA로 늘릴 수 있음 |

경로 분기:

- `/api/chat` → chatbot  
- 나머지 `/api/...` → api  

---

### 3.5 NLB + Envoy Gateway

| 항목 | 내용 |
|------|------|
| **뭔가** | 인터넷에서 보이는 **단일 입구** |
| **역할** | Expo가 붙는 URL. 경로에 따라 api/chatbot으로 전달 |
| **지금** | TLS(HTTPS 도메인) 미적용, NLB DNS를 `http://`로 사용 |
| **앱 설정** | `.env`의 `EXPO_PUBLIC_API_BASE_URL` |

팀원은 AWS 콘솔 없이 **이 URL만** `.env`에 넣으면 공용 백엔드를 쓴다.

---

### 3.6 RDS PostgreSQL

| 항목 | 내용 |
|------|------|
| **뭔가** | 관리형 **PostgreSQL** |
| **역할** | 제품·쉐이드·룩·회원·(챗봇) pgvector 지식 **원본 DB** |
| **클래스** | `db.t4g.micro` (프라이빗 서브넷) |
| **알림** | 앱이 RDS에 직접 붙지 않음. **api/chatbot만** 접속 |

덤프 복원은 S3 → 클러스터 Job → RDS 경로를 쓴다.  
노트북에서 DBeaver로 붙는 것은 기본이 아니다.

---

### 3.7 ElastiCache Redis

| 항목 | 내용 |
|------|------|
| **역할** | 캐시, 레이트 리밋 등 |
| **타입** | `cache.t4g.micro` |
| **비고** | pause 스크립트는 Redis를 안 끈다 (작아서 유지) |

---

### 3.8 NAT Gateway

| 항목 | 내용 |
|------|------|
| **역할** | 프라이빗 서브넷의 Pod가 **밖으로** (LLM API 등) 나갈 때 통로 |
| **비고** | 시간당 고정비. pause해도 VPC/NAT는 남는 편 |

---

### 3.9 S3

| 항목 | 내용 |
|------|------|
| **역할** | DB 덤프·백업·이후 에셋 보관 |
| **예** | `vishue-ops-.../dumps/vishue_db_....dump` |
| **주의** | AI-Hub 등이 섞인 덤프는 Git/공개 채널에 올리지 않음 |

---

### 3.10 Secrets Manager + External Secrets

| 항목 | 내용 |
|------|------|
| **Secrets Manager** | `DATABASE_URL`, LLM 키, Naver 키 등 **비밀 저장** |
| **External Secrets** | AWS 시크릿 → 쿠버네티스 Secret → Pod 환경변수 |

앱 `.env`에 서버 비밀을 넣지 않는 이유:  
운영 비밀은 여기 있고, 앱에는 `EXPO_PUBLIC_*`만 둔다.

---

### 3.11 ECR (임시) vs GHCR (목표)

| 항목 | 내용 |
|------|------|
| **하는 일** | 컨테이너 **이미지 창고** (역할은 GHCR과 같음) |
| **지금** | 캠프 계정 **ECR**에 push (권한·속도 때문에 임시) |
| **목표** | **GHCR** (`ghcr.io/gyuniverse-hq/...`)로 복귀 |

흐름:

```
Docker build → ECR(또는 GHCR) push → EKS가 pull → EC2에서 Pod 실행
```

쉬운 말:

1. Docker = 프로그램 **상자 만들기**  
2. ECR = 상자 **창고**  
3. 쿠버네티스 = 어디서 켤지 시키는 **매니저**  
4. EC2 + Pod = 상자 열어서 **실제로 실행**

---

### 3.12 Supabase Auth (AWS 밖이지만 같이 씀)

| 항목 | 내용 |
|------|------|
| **역할** | 회원가입·로그인·JWT 발급 |
| **아님** | 제품 카탈로그 DB |
| **연결** | 앱 ↔ Supabase / 백엔드는 JWT 검증 |

제품이 보인다 = **RDS**.  
로그인된다 = **Supabase**.

---

### 3.13 Argo CD

| 항목 | 내용 |
|------|------|
| **역할** | Git에 적힌 상태(Helm values) = 클러스터 상태가 되게 **자동 동기화** |
| **정석** | `values-prod.yaml`의 이미지 태그 PR → Argo가 배포 |
| **주의** | `helm upgrade` / `kubectl set image`를 섞으면 SSA(필드 소유권) 충돌이 날 수 있음 |

운영 Argo Application은 원래 **`main`** 을 본다.  
develop 머지 ≠ 곧바로 운영 반영일 수 있다.

---

## 4. 요청 한 번의 예 (제품 목록)

1. Expo가 Gateway로 `GET /api/products`  
2. Envoy가 **api Pod**로 전달  
3. api가 **RDS**에서 조회  
4. JSON 응답 → 앱 화면에 표시  

개발 모드에서 API가 실패하면, 앱이 **로컬 `lib/devCatalog`** 로 둘러보기 목록을 채울 수 있다.  
그건 RDS가 아니라 **개발용 안전망**이다. 운영 연동 확인 시에는 Gateway URL이 맞는지·Metro를 재시작했는지 확인한다.

피부 추천(`POST /api/recommendations/skincare/...`)은  
카탈로그 조회와 달리 **피부 프로필·로그인 등 조건**이 더 필요하다.

---

## 5. pause / resume (비용)

시연이 아닐 때:

| 줄이는 것 | 효과 |
|-----------|------|
| api/chatbot replicas → 0 | Pod 안 뜸 |
| EC2 노드 desired → 0 | **큰 비용** 감소 |
| RDS stop | 인스턴스 과금 감소 (스토리지는 남음) |

남겨 두는 것(대략): EKS 컨트롤 플레인, NAT, NLB, Redis, RDS 디스크 등  
→ pause 상태에서도 **하루 수 달러** 수준은 나올 수 있다.

스크립트: `infra/scripts/pause-prod.ps1`, `resume-prod.ps1`

---

## 6. 팀원이 AWS를 쓰는 법 (최소)

1. 인프라 담당이 resume 해 둔 상태인지 확인  
2. `.env`에 Gateway URL만 설정  

```env
EXPO_PUBLIC_API_BASE_URL=http://<Gateway-NLB-DNS>
EXPO_PUBLIC_SUPABASE_URL=...
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=...
```

3. `npx expo start` (`.env` 변경 시 **Ctrl+C 후 재시작**, 필요 시 `-c`)

AWS CLI·kubectl·RDS 직접 접속은 **인프라 담당**만 있어도 된다.

---

## 7. 용어 치트시트

| 용어 | 쉬운 말 |
|------|---------|
| VPC | 우리 전용 네트워크 울타리 |
| EC2 / 노드 | 서버 컴퓨터 |
| EKS | 쿠버네티스 매니저(관리형) |
| Pod | 컴퓨터에서 실행 중인 프로그램 |
| Deployment | “이 프로그램을 N개 유지” 설정 |
| Gateway / NLB | 바깥에서 들어오는 문·주소 |
| RDS | 관리형 PostgreSQL (제품 DB) |
| Redis | 빠른 임시 저장·제한 |
| ECR / GHCR | 컨테이너 이미지 창고 |
| Docker 이미지 | 실행용 프로그램 상자 |
| Secrets Manager | 비밀번호·API 키 금고 |
| Argo CD | Git 보고 클러스터 맞추는 배포 로봇 |
| NAT | 사설망 → 인터넷 출구 |
| S3 | 파일(덤프) 창고 |

---

## 8. 공부할 때 자주 하는 오해

1. **EC2 2대 = api 1 + chatbot 1** → 아님. 노드는 공용 컴퓨터, Pod가 나뉘어 올라감.  
2. **Supabase = 제품 DB** → 아님. Auth만. 제품은 RDS.  
3. **URL 잘못 넣었는데 둘러보기가 보임** → 개발 모드 **로컬 devCatalog fallback**일 수 있음.  
4. **Docker를 안 쓴다** → Compose로 운영을 안 돌릴 뿐, **이미지 빌드는 Docker**, 실행은 K8s.  
5. **ECR과 GHCR 역할이 다르다** → 역할은 같고 **집 주인(AWS vs GitHub)** 이 다름.  
6. **develop PR 머지 = 바로 AWS 반영** → 아닐 수 있음. 이미지 태그·Argo(`main`) 경로를 봐야 함.

---

## 9. 이 문서의 범위

- “지금 캠프 계정에 올라가 있는 **as-built**” 기준 설명이다.  
- Karpenter·도메인 HTTPS·Langfuse·Prometheus 등은 **다음 단계**이며 1차 컷오버에 필수는 아니다.  
- Render는 예전 팀 공용 경로이며, 공용 원본은 **RDS + Gateway** 쪽으로 옮긴 상태다.
