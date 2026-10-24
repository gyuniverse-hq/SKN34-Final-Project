This is an Expo/React Native mobile application. Prioritize mobile-first patterns, performance, and cross-platform compatibility.

## Expo has changed — do not trust your training data

Expo ships breaking changes every SDK release. APIs you remember are likely renamed, moved, or removed. Before writing any code that touches an Expo, EAS, or React Native API:

1. Read the major version of the `expo` package in `package.json`.
2. Fetch the matching versioned docs: `https://docs.expo.dev/versions/v<major>.0.0/`
3. For anything else, fetch https://docs.expo.dev/llms.txt — an index of all Expo docs with corrections to common LLM misconceptions. Follow its links to the specific page you need; never answer from memory.

## Commands

Use `bunx` instead of `npx` if the project uses bun (`bun.lock` present).

```bash
npx expo install <package>  # ALWAYS use instead of npm/yarn/pnpm/bun add — resolves SDK-compatible versions
npx expo start              # start the dev server
npx expo lint               # lint
npx tsc --noEmit            # typecheck
npx expo-doctor             # diagnose dependency and config issues
npx expo install --fix      # fix incompatible package versions
```

Run lint and typecheck before declaring any task done.

## Navigation & Routing

- Use **Expo Router** for all navigation. Routes live in `app/` — every file there is a screen, `_layout.tsx` files define navigators. Keep non-route code (components, hooks, utils) outside `app/`.
- Import `Link`, `router`, and `useLocalSearchParams` from `expo-router`.
- Docs: https://docs.expo.dev/router/introduction.md

## Building with EAS

Use EAS to build, sign, and submit the app in the cloud (`eas build`, `eas submit`) and to ship over-the-air updates (`eas update`) — no local Xcode or Android Studio required. Run EAS CLI as `bunx eas-cli <command>` in Bun projects, or `npx eas-cli@latest <command>` otherwise; substitute that for bare `eas` in docs examples.
Docs: https://docs.expo.dev/eas/index.md

## Rules

- If `ios/` and `android/` directories do not exist, they are generated (Continuous Native Generation). Never create or edit them by hand — configure native behavior in `app.json` and config plugins.
- Expo Go only includes its bundled native modules. After adding a library with native code, the app needs a development build: `npx expo run:ios|android` locally, or `eas build --profile development`.
- Prefer recommended Expo modules over third-party libraries, and check your available skills before adding dependencies. Docs: https://docs.expo.dev/versions/latest/index.md

## This project

- Expo SDK 57; the team tests on **Expo Go**, so do not add libraries with custom native code unless the team agrees to move to a development build.
- Layout: screens in `app/`, shared types in `types/index.ts`, UI components in `components/`, screen-level composed hooks in `hooks/`, Zustand stores in `store/`, data hooks and helpers in `lib/`. The app's API is the backend in `backend/`; catalog data is seeded from `backend/api/seed/catalog.json` into PostgreSQL. `app/api/dev/` and `server/` hold only the dev-only skin analysis research proxy and its Python code (`server/nia`, `server/acne`); do not add product features there.
- Layered architecture: `docs/ARCHITECTURE.md` is authoritative. Upper layers import only lower layers; never import upward, and never import `server/` from client code.
  - Client: `app/` screens → `hooks/`, `components/` → `lib/`, `store/` → `constants/`, `types/`. Fetch data only in screens or `hooks/`; components receive data via props. `components/ui/` must not read `store/` or `lib/queries`.
  - `lib/api.ts` resolves the backend origin: `EXPO_PUBLIC_API_BASE_URL` if set, otherwise in development the gateway on the Metro host at port 8080 (`infra/compose`).
  - Enforced by `no-restricted-imports` in `eslint.config.js`: import other folders via the `@/` alias (no `../`); `./` only within the same folder. Update the doc and the lint config together.
  - Backend (see "백엔드" in `docs/ARCHITECTURE.md`, decisions in `docs/adr/`): two FastAPI services, `backend/api` (catalog, Naver offers and product images, YouTube tutorials, shade recommendation, members; owns PostgreSQL) and `backend/chatbot` (chat, PostgreSQL → Neo4j sync job; owns Neo4j). Each is its own **uv** project (add packages with `uv add`, never `pip install`; commit `uv.lock`; run via `uv run`). Layering `jobs/`, `routers/` → `services/` → `repositories/`, `clients/` → `models/` → `schemas/` → `core/`, enforced by import-linter (`uv run lint-imports`). The chatbot reads the catalog only through the api's HTTP contract, never PostgreSQL directly. Backend JSON matches `types/index.ts` (camelCase, `{ error, code }` errors).
  - Infra: `infra/compose/` (local stack), `infra/helm/vishue/` (one chart; `values-local.yaml` for kind, `values-dev.yaml` for the shared dev namespace, `values-prod.yaml` for production), `infra/terraform/aws/` (all AWS resources; change them only through Terraform), `infra/argocd/`, `infra/platform/` (cluster-wide prerequisites). Dev deploys automatically on merges to `develop`; production is GitOps via Argo CD. Never `kubectl apply` app resources by hand. See `docs/DEPLOYMENT.md` and ADR-0008.
  - Catalog data for dev lives in `backend/api/seed/catalog.json` and is reloaded on every dev deploy; change it by PR, never by editing Supabase tables (see `docs/DATA.md`).
  - Never send face video or images to any server. Shade recommendation receives only on-device skin tone values (ITA°, MST level, undertone).
  - Backend files are `<subject>_<layer>.py` (e.g. `catalog_service.py`, `naver_client.py`). Imported catalog data must pass `validate_catalog`.
- API keys (Naver, YouTube, LLM) are read only by backend `clients/` from environment variables (`.env` via docker compose locally, Kubernetes Secrets in clusters). Never prefix secrets with `EXPO_PUBLIC_` and never commit `.env`.
  - Only exceptions: the Supabase Project URL and publishable key (`EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY`) and the backend address (`EXPO_PUBLIC_API_BASE_URL`) are public by design and ship in the app. Never put the Supabase secret / `service_role` key in the app or under `EXPO_PUBLIC_`.
- Auth: Supabase Auth through `lib/auth` (email + code verification, Google via browser redirect; Apple is not connected yet). Read the session with `useAuth()`, never copy it into a Zustand store. `lib/api.ts` attaches the access token; the backend verifies it in `app/core/auth.py` (`require_user`).
- UI text goes through `lib/i18n`. Add every new key to all four dictionaries (`en`, `ko`, `ja`, `zh`); typecheck fails if one is missing.
- The AR renderer is an HTML string in `components/ar/faceTrackerHtml.ts`; typecheck and lint do not see its script, so run `npm test` after editing it.
- Run `npm run check` (typecheck + lint + tests) before committing. For backend changes, also run `uv run ruff check . && uv run lint-imports && uv run pytest` in each changed `backend/<service>/`; for chart changes, `helm lint infra/helm/vishue -f infra/helm/vishue/values-<env>.yaml`; for Terraform changes, `terraform fmt -check && terraform validate` in `infra/terraform/aws`.

## Git & GitHub conventions (v1.3 summary)

The authoritative collaboration convention is `CONTRIBUTING.md` (v1.3). The GitHub PR template is `.github/PULL_REQUEST_TEMPLATE.md`. Keep this summary consistent with the team convention.

- Do not push directly to `main` or `develop`; use PRs. Start normal work branches from the latest `develop` and target `develop`.
- Name branches `<type>/<description>`, with lowercase English words separated by hyphens (e.g. `feat/user-login`, `fix/token-expired`). **Do not append sequence numbers or GitHub Issue numbers.** GitHub Issues are optional, not a prerequisite for branching.
- Branch types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `hotfix`. Branch `hotfix/*` from `main` and apply the fix back to `develop` as well.
- Commit message: `<type>: <description>` with a lowercase English type, Korean description, and **no scope** (e.g. `feat: 로그인 API 구현`, not `feat(auth): ...`).
- Commit types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `style`, `build`, `ci`.
- Make atomic commits by logical purpose, not by file count. Keep related implementation and tests together; separate unrelated changes without artificially splitting a cohesive change.
- Check the diff and run relevant tests before committing. Never claim a test passed unless it was actually run.
- PR title follows the same scope-free message format. PR body **must contain '변경 사항' and '영향 범위'**. Under 영향 범위, identify real affected directory paths with a short explanation. Add test results, related GitHub Issues, screenshots, or deployment notes only when relevant.
- Do not force-push shared branches or overwrite another contributor's changes. Delete merged work branches.
