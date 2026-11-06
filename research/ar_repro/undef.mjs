// Finds identifiers the page script uses without defining them (the class of bug behind "W is not defined").
import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(process.cwd() + '/');
const { Linter } = require('eslint');
const globals = require('globals');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = scripts[scripts.length - 1];
const linter = new Linter();
const messages = linter.verify(code, {
  languageOptions: { ecmaVersion: 2022, sourceType: 'module', globals: { ...globals.browser, ...globals.es2021 } },
  rules: { 'no-undef': 'error' },
});
console.log('script bytes', code.length, 'messages', messages.length);
for (const m of messages.slice(0, 20)) console.log(m.line + ':' + m.column, m.message, '|', code.split('\n')[m.line - 1].trim().slice(0, 100));
