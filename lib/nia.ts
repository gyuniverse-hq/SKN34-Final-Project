import { Platform, Share } from 'react-native';
import { ApiError } from './api';

export async function niaRequest<T>(action: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/dev/nia/${action}`, {
    method: body === undefined ? 'GET' : 'POST', signal,
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.error || `HTTP ${response.status}`, response.status, data.code);
  return data as T;
}

export async function exportNiaReport(id: string, format: 'csv' | 'json') {
  const response = await fetch(`/api/dev/nia/export?id=${encodeURIComponent(id)}&format=${format}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const content = await response.text();
  await saveNiaFile(content, `nia-evaluation.${format}`, format === 'csv' ? 'text/csv' : 'application/json');
}

export async function saveNiaFile(content: string, filename: string, type = 'application/json') {
  if (Platform.OS === 'web') {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } else {
    await Share.share({ message: content });
  }
}
