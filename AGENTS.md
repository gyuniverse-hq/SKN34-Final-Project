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
- Layout: screens and API routes in `app/` (`app/api/**/*+api.ts` run on the server), server-only logic in `server/`, shared types in `types/index.ts`, catalog data in `data/catalog/`, UI components in `components/`, Zustand stores in `store/`, data hooks and helpers in `lib/`.
- API keys are read only by server code (`server/`, `app/api/`) from `.env`. Never prefix secrets with `EXPO_PUBLIC_` and never commit `.env`.
- UI text goes through `lib/i18n`. Add every new key to all four dictionaries (`en`, `ko`, `ja`, `zh`); typecheck fails if one is missing.
- The AR renderer is an HTML string in `components/ar/faceTrackerHtml.ts`; typecheck and lint do not see its script, so run `npm test` after editing it.
- Run `npm run check` (typecheck + lint + tests) before committing.

## Git & GitHub conventions (summary)

Full rules: `CONTRIBUTING.md`. PR template: `.github/PULL_REQUEST_TEMPLATE.md`.

- Never push directly to `main` or `develop`; merge through a PR. Work branches start from the latest `develop` and target `develop`.
- Branch name: `<type>/<issue-number>-<description>` with a real GitHub Issue number and lowercase English words joined by `-` (e.g. `feat/12-user-login`). Do not invent issue numbers; ask for one if it is missing.
- Branch types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `hotfix` (`hotfix/*` branches from `main` and is also applied to `develop`).
- Commit message: `<type>: <description>` — lowercase English type, Korean description, **no scope** (`feat: 로그인 API 구현`, not `feat(auth): ...`). Avoid vague descriptions such as `수정`, `작업 완료`, `최종`.
- Commit types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `style`, `build`, `ci`.
- Make atomic commits: one purpose per commit, implementation and its tests together, unrelated changes split out. Group by purpose, not by file count, and do not split artificially.
- Before committing, review the diff and actually run the relevant tests; do not report success based only on generated code.
- PR title follows the commit format. PR body needs **변경 사항** and **영향 범위** (real folder paths with a short description); add 검증, related issue (`Refs #12`), screenshots or deployment notes only when relevant.
- Do not force-push shared branches or overwrite other people's changes; delete the work branch after merging.
