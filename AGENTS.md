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
- Layout: screens and API routes in `app/` (`app/api/**/*+api.ts` run on the server), server-only logic in `server/`, shared types in `types/index.ts`, catalog data in `data/catalog/`, UI components in `components/`, screen-level composed hooks in `hooks/`, Zustand stores in `store/`, data hooks and helpers in `lib/`.
- Layered architecture: `docs/ARCHITECTURE.md` is authoritative. Upper layers import only lower layers; never import upward, and never import `server/` or `data/` from client code.
  - Client: `app/` screens → `hooks/`, `components/` → `lib/`, `store/` → `constants/`, `types/`. Fetch data only in screens or `hooks/`; components receive data via props. `components/ui/` must not read `store/` or `lib/queries`.
  - Server: `app/api/` routes (parse, validate, respond) → `server/services/` (business logic) → `server/repositories/` (data access) and `server/clients/` (external APIs; the only place API keys are used) → `server/lib/` (http, cache, env). Routes must not reach repositories, clients, or `data/` directly.
  - Repository functions stay `async` even over static data so a DB can replace them without touching callers. Name files `<subject><Layer>.ts` (e.g. `catalogService.ts`, `naverClient.ts`).
- API keys are read only by server code (`server/`, `app/api/`) from `.env`. Never prefix secrets with `EXPO_PUBLIC_` and never commit `.env`.
- UI text goes through `lib/i18n`. Add every new key to all four dictionaries (`en`, `ko`, `ja`, `zh`); typecheck fails if one is missing.
- The AR renderer is an HTML string in `components/ar/faceTrackerHtml.ts`; typecheck and lint do not see its script, so run `npm test` after editing it.
- Run `npm run check` (typecheck + lint + tests) before committing.

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
