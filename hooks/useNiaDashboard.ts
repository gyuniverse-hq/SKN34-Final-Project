import { useState } from 'react';
import { exportNiaReport, niaRequest } from '@/lib/nia';
import type { NiaDashboardControls, NiaPreprocessing } from '@/types/nia';

export function useNiaDashboard(jobId?: string): NiaDashboardControls {
  const [preview, setPreview] = useState<{ uri: string; index: number; jobId: string }>();
  const [failure, setFailure] = useState<{ message: string; jobId: string }>();

  async function run(action: () => Promise<unknown>) {
    if (!jobId) return;
    setFailure(undefined);
    try { await action(); }
    catch (e) { setFailure({ message: e instanceof Error ? e.message : String(e), jobId }); }
  }

  return {
    preview: preview?.jobId === jobId ? preview : undefined,
    error: failure?.jobId === jobId ? failure?.message || '' : '',
    exportReport: format => run(() => exportNiaReport(jobId!, format)),
    showSample: index => run(async () => {
      const result = await niaRequest<NiaPreprocessing>(`sample?id=${jobId}&index=${index}`);
      if (result.preview) setPreview({ uri: result.preview, index, jobId: jobId! });
    }),
  };
}
