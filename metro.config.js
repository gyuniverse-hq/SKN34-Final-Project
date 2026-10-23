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
    'ml', 'nia-private', 'final_venv', 'server/nia/.venv',
    'backend/api/.venv', 'backend/chatbot/.venv',
  ].map(directory),
  new RegExp(`^${escape(path.resolve(__dirname, 'data'))}[/\\\\](?!catalog(?:[/\\\\]|$))`),
];

module.exports = config;
