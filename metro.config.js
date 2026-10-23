const path = require('node:path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const directory = relative => new RegExp(`^${escape(path.resolve(__dirname, relative))}[/\\\\]`);
const original = config.resolver.blockList;

// Python environments, checkpoints and raw datasets are not app modules. Keeping
// them outside Metro's file map prevents ML writes from flooding its watcher.
config.resolver.blockList = [
  ...(Array.isArray(original) ? original : original ? [original] : []),
  ...[
    'ml', 'nia-private', 'final_venv', 'server/nia/.venv', '.gradle-local',
    'modules/skin-analysis/android/src/main/assets/skin',
    'modules/skin-analysis/android/build',
    'backend/api/.venv', 'backend/chatbot/.venv',
  ].map(directory),
  new RegExp(`^${escape(path.resolve(__dirname, 'data'))}[/\\\\](?!catalog(?:[/\\\\]|$))`),
];

if (process.env.EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS === '1') {
  const assets = require('./scripts/skin-web-middleware.cjs')(__dirname);
  const enhance = config.server.enhanceMiddleware;
  config.server.enhanceMiddleware = (middleware, server) => {
    const next = enhance ? enhance(middleware, server) : middleware;
    return (req, res, done) => assets(req, res, () => next(req, res, done));
  };
}

module.exports = config;
