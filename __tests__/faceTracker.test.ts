import { FACE_TRACKER_HTML, MEDIAPIPE_VERSION } from '@/components/ar/faceTrackerHtml';

function moduleScript(html: string) {
  const match = html.match(/<script type="module">([\s\S]*?)<\/script>/);
  if (!match) throw new Error('module script not found');
  return match[1];
}

describe('face tracker page', () => {
  it('embeds a syntactically valid script', () => {
    // The page script lives inside a template string, so typecheck/lint never see it.
    expect(() => new Function(moduleScript(FACE_TRACKER_HTML))).not.toThrow();
  });

  it('pins the MediaPipe version and keeps the host protocol', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain(`'${MEDIAPIPE_VERSION}'`);
    for (const token of ["type: 'hello'", "type: 'status'", "msg.type === 'makeup'", "msg.type === 'compare'"]) {
      expect(script).toContain(token);
    }
  });

  it('never uploads or stores camera frames', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).not.toMatch(/fetch\(|XMLHttpRequest|localStorage|indexedDB|toDataURL|toBlob/);
  });
});
