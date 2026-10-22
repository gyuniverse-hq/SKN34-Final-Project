import * as ImagePicker from 'expo-image-picker';
import { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n';
import { niaRequest, saveNiaFile } from '@/lib/nia';
import { getNiaAcneView } from '@/lib/niaPhoto';
import type { NiaPhotoControls, NiaPhotoJob, NiaStatus } from '@/types/nia';

export function useNiaPhotoProfile(status?: NiaStatus): NiaPhotoControls {
  const { t } = useI18n();
  const [image, setImage] = useState<ImagePicker.ImagePickerAsset>();
  const [job, setJob] = useState<NiaPhotoJob>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [details, setDetails] = useState(false);
  const active = job?.status === 'queued' || job?.status === 'running';
  const jobId = active ? job.id : undefined;

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await niaRequest<NiaPhotoJob>(`job?id=${jobId}`, undefined, controller.signal);
        if (controller.signal.aborted) return;
        setJob(next);
        setError(next.error || '');
        if (next.status === 'queued' || next.status === 'running') timer = setTimeout(poll, 1000);
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(String(e));
          timer = setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return {
    image, job, busy, error, details, setDetails,
    pick: () => run(async () => {
      const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], base64: true, quality: 1 });
      if (picked.canceled) return;
      const asset = picked.assets[0];
      if (!asset.base64 || asset.base64.length > 16 * 1024 * 1024 || (asset.mimeType && !['image/jpeg', 'image/png'].includes(asset.mimeType))) {
        throw new Error(t('nia.invalidImage'));
      }
      setImage(asset); setJob(undefined); setDetails(false);
    }),
    analyze: () => run(async () => {
      if (!image) return;
      setJob(undefined); setDetails(false);
      const next = await niaRequest<{ id: string }>('profile', { image: image.base64 });
      setJob({ id: next.id, kind: 'profile', status: 'queued', completed: 0, total: null, report: null });
    }),
    exportJson: () => run(async () => {
      const report = job?.report;
      if (!report || getNiaAcneView(status, report).status === 'outdated') return;
      await saveNiaFile(JSON.stringify(report.ml_input, null, 2), 'nia-photo-features.json');
    }),
  };
}
