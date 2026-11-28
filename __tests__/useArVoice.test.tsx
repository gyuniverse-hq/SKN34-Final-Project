import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert } from 'react-native';
import { useArVoice } from '@/hooks/useArVoice';
import { apiPostOwned } from '@/lib/api';
import type { Language } from '@/lib/i18n/languages';
import * as Speech from 'expo-speech';

const mockDelete = jest.fn();
const mockRelease = jest.fn();
const mockStopRecording = jest.fn(async () => {});
const mockPermission = jest.fn(async () => ({ granted: true }));
const mockOnText = jest.fn(async (_text: string) => '이 색 어때요?');
let mockLevel: number | undefined = -90;
let mockLanguage: Language = 'ko';
let mockKeywords: string[] = [];
jest.mock('@/lib/api', () => ({ apiPostOwned: jest.fn(), subscribeArIdentityChange: () => () => {} }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ language: mockLanguage, t: (k: string) => k }) }));
jest.mock('expo-file-system', () => ({ File: class {
  exists = true;
  delete = mockDelete;
  async arrayBuffer() { return new ArrayBuffer(8); }
} }));
jest.mock('expo-audio', () => ({
  requestRecordingPermissionsAsync: () => mockPermission(),
  setAudioModeAsync: async () => {},
  RecordingPresets: { HIGH_QUALITY: { ios: {}, android: {} } },
  AudioModule: { AudioRecorder: class {
    uri = 'file:///command.m4a';
    record() {}
    getStatus() { return { isRecording: true, metering: mockLevel }; }
    async prepareToRecordAsync() {}
    stop = mockStopRecording;
    release = mockRelease;
  } },
}));
jest.mock('expo-speech', () => ({ speak: jest.fn(), stop: jest.fn(async () => {}) }));

let voice: ReturnType<typeof useArVoice>;
function Panel({ active }: { active: boolean }) {
  voice = useArVoice(active, mockOnText, () => mockKeywords);
  return null;
}
let tree: renderer.ReactTestRenderer;
beforeEach(async () => {
  jest.useFakeTimers();
  mockLevel = -90;
  mockLanguage = 'ko';
  mockKeywords = [];
  jest.clearAllMocks();
  mockPermission.mockResolvedValue({ granted: true });
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  await act(async () => { tree = renderer.create(<Panel active />); });
});
afterEach(async () => {
  await act(async () => { tree.unmount(); });
  jest.restoreAllMocks();
  jest.useRealTimers();
});

async function levels(db: number, milliseconds: number) {
  mockLevel = db;
  await act(async () => { jest.advanceTimersByTime(milliseconds); });
}

it('asks for microphone permission directly without an app popup', async () => {
  mockPermission.mockResolvedValueOnce({ granted: false });
  await act(async () => { voice.microphone(); });
  expect(Alert.alert).not.toHaveBeenCalled();
  expect(mockPermission).toHaveBeenCalledTimes(1);
  expect(voice.phase).toBe('idle');
  expect(voice.notice).toBe('ar.voice.permission');
  expect(apiPostOwned).not.toHaveBeenCalled();
});

it.each([
  ['ambient noise above the old cutoff', -38, -21],
  ['soft speech below the old cutoff', -74, -54],
])('ends the utterance after a pause with %s', async (_name, room, voiceLevel) => {
  const stt = jest.mocked(apiPostOwned);
  stt.mockResolvedValue({ data: { text: '립 발라줘' }, owner: { kind: 'guest', id: 'test' } });
  await act(async () => { voice.microphone(); });
  await levels(Number(room), 1800);
  expect(voice.phase).toBe('recording');
  await levels(Number(voiceLevel), 700);
  expect(voice.phase).toBe('hearing');
  await levels(Number(room), 700);
  await levels(Number(voiceLevel), 100); // A single background click during the pause.
  expect(stt).not.toHaveBeenCalled();
  await levels(Number(room), 600);
  expect(stt).toHaveBeenCalledTimes(1);
  expect(voice.phase).toBe('speaking');
});

it('explains unavailable metering instead of silently restarting each 30 seconds', async () => {
  mockLevel = undefined;
  await act(async () => { voice.microphone(); });
  await act(async () => { jest.advanceTimersByTime(1600); });
  expect(voice.phase).toBe('idle');
  expect(voice.notice).toBe('ar.voice.meterUnavailable');
  expect(apiPostOwned).not.toHaveBeenCalled();
});

it('sends speech after a pause, waits for TTS, and hears a second request without a tap', async () => {
  jest.mocked(apiPostOwned).mockResolvedValue({ data: { text: ' 은은한 립 발라줘 ' }, owner: { kind: 'guest', id: 'test' } });
  mockLanguage = 'en';
  mockKeywords = ['로즈 틴트'];
  await act(async () => { tree.update(<Panel active />); });
  await act(async () => { voice.microphone(); });
  expect(voice.phase).toBe('recording');
  await levels(-90, 2000);
  await levels(-25, 400);
  await levels(-90, 700);
  expect(apiPostOwned).not.toHaveBeenCalled();
  await levels(-25, 300);
  await levels(-90, 1300);
  expect(voice.phase).toBe('speaking');
  const stt = jest.mocked(apiPostOwned);
  const context = (index: number) => JSON.parse(decodeURIComponent(stt.mock.calls[index][2]!.transcriptionContext!));
  expect(stt).toHaveBeenCalledWith('/api/chat/ar-control/transcribe', expect.any(ArrayBuffer), expect.anything());
  expect(context(0)).toEqual({ language: 'en', keywords: ['로즈 틴트'] });
  expect(Speech.speak).toHaveBeenCalledWith('이 색 어때요?', expect.objectContaining({ language: 'en-US' }));
  expect(mockOnText).toHaveBeenCalledWith('은은한 립 발라줘', expect.objectContaining({ aborted: false }), expect.any(Function));
  expect(mockDelete).toHaveBeenCalledTimes(1);
  await levels(-20, 3000);
  expect(apiPostOwned).toHaveBeenCalledTimes(1);
  mockKeywords = ['말린 장미'];
  await act(async () => { jest.mocked(Speech.speak).mock.calls[0][1]?.onDone?.(); });
  expect(voice.phase).toBe('recording');
  await levels(-25, 400);
  await levels(-90, 1300);
  expect(mockOnText).toHaveBeenCalledTimes(2);
  expect(Speech.speak).toHaveBeenCalledTimes(2);
  expect(context(1)).toEqual({ language: 'en', keywords: ['말린 장미'] });
});

it('drops a silent segment and a transcript arriving after the conversation ends', async () => {
  let resolveTranscript!: (value: { data: { text: string }; owner: { kind: 'guest'; id: string } }) => void;
  jest.mocked(apiPostOwned).mockImplementationOnce(() => new Promise(resolve => { resolveTranscript = resolve; }));
  await act(async () => { voice.microphone(); });
  await levels(-90, 30_000);
  expect(apiPostOwned).not.toHaveBeenCalled();
  await levels(-25, 400);
  await levels(-90, 1300);
  expect(voice.phase).toBe('transcribing');
  await act(async () => { voice.microphone(); });
  await act(async () => { resolveTranscript({data: {text: '이전 요청'}, owner: {kind:'guest', id:'test'}}); });
  expect(mockOnText).not.toHaveBeenCalled();
  expect(voice.phase).toBe('idle');
});

it('stops waiting for a stalled transcription and ignores a late response', async () => {
  let respond!: () => void;
  let signal: AbortSignal | undefined;
  jest.mocked(apiPostOwned).mockImplementationOnce((_path, _bytes, options) => {
    signal = options?.signal;
    return new Promise(resolve => { respond = () => resolve({ data: { text: '늦은 응답' }, owner: { kind: 'guest', id: 'test' } }); });
  });
  await act(async () => { voice.microphone(); });
  await levels(-90, 500);
  await levels(-25, 400);
  await levels(-90, 1300);
  expect(voice.phase).toBe('transcribing');
  await act(async () => { jest.advanceTimersByTime(15_000); });
  expect(signal?.aborted).toBe(true);
  expect(voice.phase).toBe('idle');
  expect(voice.notice).toBe('ar.voice.timeout');
  await act(async () => { respond(); });
  expect(mockOnText).not.toHaveBeenCalled();
});

it('can retry when native recording finalization stalls before an upload', async () => {
  let finishStop!: () => void;
  mockStopRecording.mockImplementationOnce(() => new Promise(resolve => { finishStop = resolve; }));
  await act(async () => { voice.microphone(); });
  await levels(-90, 500);
  await levels(-25, 400);
  await levels(-90, 1300);
  expect(voice.phase).toBe('transcribing');
  await act(async () => { jest.advanceTimersByTime(15_000); });
  expect(voice.phase).toBe('idle');
  expect(voice.notice).toBe('ar.voice.timeout');
  expect(mockRelease).toHaveBeenCalledTimes(1);
  expect(apiPostOwned).not.toHaveBeenCalled();
  await act(async () => { voice.microphone(); finishStop(); });
  expect(voice.phase).toBe('recording');
  expect(mockOnText).not.toHaveBeenCalled();
});

it('discards a recording on exit and does not speak muted or late replies', async () => {
  const pending = voice.beginReply();
  await act(async () => { voice.toggleSound(); });
  pending('지금 립이에요');
  expect(Speech.speak).not.toHaveBeenCalled();
  await act(async () => { voice.toggleSound(); voice.microphone(); });
  expect(voice.phase).toBe('recording');
  await act(async () => { tree.update(<Panel active={false} />); });
  pending('지난 화면의 답변');
  expect(apiPostOwned).not.toHaveBeenCalled();
  expect(mockDelete).toHaveBeenCalledTimes(1);
  expect(mockOnText).not.toHaveBeenCalled();
  expect(Speech.speak).not.toHaveBeenCalled();
});
