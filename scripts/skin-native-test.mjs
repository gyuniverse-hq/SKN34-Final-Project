import { copyFileSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = fileURLToPath(new URL('../', import.meta.url));
const folder = resolve(root, '.gradle-local/skin-math-tests');
const socketFolder = resolve(root, 'ml/.socket-tmp');
mkdirSync(folder, { recursive: true }); mkdirSync(socketFolder, { recursive: true });
copyFileSync(resolve(root, 'scripts/skin-native-math.gradle'), resolve(folder, 'build.gradle'));
writeFileSync(resolve(folder, 'settings.gradle'), "rootProject.name = 'skin-native-math'\n");
const windows = process.platform === 'win32';
const wrapper = resolve(root, windows ? 'android/gradlew.bat' : 'android/gradlew');
if (!existsSync(wrapper)) throw new Error('Run npx expo prebuild --platform android --no-install first.');
const env = { ...process.env, GRADLE_USER_HOME: resolve(root, '.gradle-local'),
  JAVA_TOOL_OPTIONS: `${process.env.JAVA_TOOL_OPTIONS || ''} -Djava.io.tmpdir="${socketFolder}" -Djdk.net.unixdomain.tmpdir="${socketFolder}"`.trim() };
const args = ['-p', folder, `-Dskin.root=${root}`, '--no-daemon', 'test'];
// PowerShell invokes the batch wrapper with literal, individually quoted arguments.
const psQuote = value => `'${value.replaceAll("'", "''")}'`;
const result = windows
  ? spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    `& ${psQuote(wrapper)} ${args.map(psQuote).join(' ')}; exit $LASTEXITCODE`], { cwd: root, env, stdio: 'inherit' })
  : spawnSync(wrapper, args, { cwd: root, env, stdio: 'inherit' });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
