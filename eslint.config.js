// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require("eslint-config-expo/flat");

// Layer boundaries from docs/ARCHITECTURE.md. Cross-folder imports use the `@/` alias so these
// patterns can see them. A later block replaces (does not merge) an earlier one for the same file.
const SERVER_ONLY = {
  group: ['@/server', '@/server/**', '@/data', '@/data/**'],
  message: 'Client code must not import server/ or data/. Fetch through /api with lib/queries.',
};
const PARENT_RELATIVE = {
  group: ['../*'],
  message: 'Import other folders through the `@/` alias so layer rules apply.',
};

function layer(files, patterns, ignores) {
  return {
    files,
    ...(ignores ? { ignores } : {}),
    rules: { 'no-restricted-imports': ['error', { patterns: [PARENT_RELATIVE, ...patterns] }] },
  };
}

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ["dist/*", "backend/**", "**/.venv/**", "ml/runs/**", "nia-private/**", "final_venv/**",
      "data/028.*/**", "data/14.*/**", "data/Skin-Problem-MultiLabel/**"],
  },

  // Client
  layer(['app/**'], [SERVER_ONLY], ['app/api/**']),
  layer(['hooks/**'], [
    SERVER_ONLY,
    { group: ['@/components', '@/components/**'], message: 'hooks/ sits below components/.' },
  ]),
  layer(['components/**'], [
    SERVER_ONLY,
    { group: ['@/hooks', '@/hooks/**'], message: 'components/ must not use hooks/; screens pass data via props.' },
    { group: ['@/lib/queries'], message: 'Fetch data in screens or hooks/, not components.' },
    { group: ['@/lib/nia'], message: 'NIA requests belong in screens or hooks; pass results and actions via props.' },
    {
      group: ['@/components/**', '!@/components/ui', '!@/components/ui/**'],
      message: 'Components may import only components/ui and their own folder.',
    },
  ]),
  layer(['components/ui/**'], [
    SERVER_ONLY,
    { group: ['@/hooks', '@/hooks/**'], message: 'components/ must not use hooks/; screens pass data via props.' },
    { group: ['@/lib/queries'], message: 'Fetch data in screens or hooks/, not components.' },
    { group: ['@/lib/nia'], message: 'NIA requests belong in screens or hooks; pass results and actions via props.' },
    { group: ['@/store', '@/store/**'], message: 'components/ui is generic; move state-aware components to components/<feature>/.' },
    { group: ['@/components/**'], message: 'components/ui must not depend on feature components.' },
  ]),
  layer(['lib/**', 'store/**'], [
    SERVER_ONLY,
    { group: ['@/components', '@/components/**', '@/hooks', '@/hooks/**'], message: 'lib/ and store/ sit below components/ and hooks/.' },
  ]),
  layer(['constants/**', 'types/**'], [
    { group: ['@/**'], message: 'constants/ and types/ must not import project code.' },
  ]),
  layer(['data/**'], [
    { group: ['@/**', '!@/types'], message: 'data/ may import only types/.' },
  ]),

  // Server
  layer(['app/api/**'], [
    {
      group: ['@/server/repositories/**', '@/server/clients/**', '@/data', '@/data/**'],
      message: 'Routes call server/services and server/lib only.',
    },
    {
      group: ['@/components/**', '@/hooks/**', '@/lib/**', '@/store/**'],
      message: 'Server code must not import client code.',
    },
  ]),
  layer(['server/**'], [
    {
      group: ['@/app/**', '@/components/**', '@/hooks/**', '@/lib/**', '@/store/**'],
      message: 'Server code must not import client code.',
    },
  ]),
  layer(['server/repositories/**'], [
    {
      group: ['@/server/services/**', '@/server/clients/**', '@/app/**', '@/components/**', '@/hooks/**', '@/lib/**', '@/store/**'],
      message: 'Repositories may import only data/, server/lib and types/.',
    },
  ]),
  layer(['server/clients/**'], [
    {
      group: ['@/server/services/**', '@/server/repositories/**', '@/server/clients/**', '@/data', '@/data/**', '@/app/**', '@/components/**', '@/hooks/**', '@/lib/**', '@/store/**'],
      message: 'Clients may import only server/lib and types/.',
    },
    { group: ['./*'], message: 'Clients must not depend on each other.' },
  ]),
  layer(['server/lib/**'], [
    {
      group: ['@/server/services/**', '@/server/repositories/**', '@/server/clients/**', '@/data', '@/data/**', '@/app/**', '@/components/**', '@/hooks/**', '@/lib/**', '@/store/**'],
      message: 'server/lib must not import other server layers.',
    },
  ]),
]);
