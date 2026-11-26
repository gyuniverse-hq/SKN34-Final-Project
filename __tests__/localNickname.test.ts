import AsyncStorage from '@react-native-async-storage/async-storage';
import { defaultNickname, readNickname, saveNickname } from '@/lib/localNickname';

beforeEach(async () => { await AsyncStorage.clear(); });

test('defaults are stable, and edited nicknames persist separately for each account', async () => {
  const original = await readNickname('a');
  expect(original).toBe(defaultNickname('a'));
  const decomposed = '립바르는비슈'.normalize('NFD');
  expect(await saveNickname('a', ' ' + decomposed + ' ')).toBe('립바르는비슈');
  expect(await readNickname('a')).toBe('립바르는비슈');
  expect(await readNickname('b')).toBe(defaultNickname('b'));
  await expect(saveNickname('b', '립바르는비슈')).resolves.toBe('립바르는비슈');
  for (const invalid of ['가', '가'.repeat(17), '공백 포함', '기호!']) {
    await expect(saveNickname('a', invalid)).rejects.toThrow('invalid_nickname');
  }
  expect(await readNickname('a')).toBe('립바르는비슈');
});
