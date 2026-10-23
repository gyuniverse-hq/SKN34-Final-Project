export class CaptureGate {
  reset() { this.since = null; this.previous = null; this.lastAt = null; }
  update(faces, now) {
    const face = faces[0];
    // Match the displayed guide (70% wide, 68% high, centered at .5/.46).
    // A width-only threshold rejects a correctly framed face in short previews,
    // or forces it outside the forehead/chin limits in tall previews.
    const guideFit = face ? Math.max(face.width / .70, (face.bottom - face.top) / .68) : 0;
    const guidance = !faces.length ? 'noFace' : faces.length !== 1 ? 'multipleFaces'
      : !face.frontal ? 'straight' : guideFit < .55 || guideFit > 1.10 ? 'distance'
        : Math.abs(face.cx - .5) > .10 || Math.abs(face.cy - .46) > .12 ||
          face.cx - face.width / 2 < .05 || face.cx + face.width / 2 > .95 ? 'center'
          : face.top < .08 || face.top > .32 || face.bottom > .84 ? 'forehead' : 'hold';
    if (guidance !== 'hold') { this.reset(); return { guidance, progress: 0 }; }
    const last = this.previous;
    if (!last || Math.abs(face.cx - last.cx) > .02 || Math.abs(face.cy - last.cy) > .02 ||
      Math.abs(face.width - last.width) > .03 || now - this.lastAt > 600) this.since = now;
    this.previous = face; this.lastAt = now;
    return { guidance, progress: Math.min(1, (now - this.since) / 1500) };
  }
}

export function previewFace(points, videoWidth, videoHeight, width, height) {
  const scale = Math.max(width / videoWidth, height / videoHeight);
  const left = Math.min(...points.map(p => p.x)), right = Math.max(...points.map(p => p.x));
  const top = Math.min(...points.map(p => p.y)), bottom = Math.max(...points.map(p => p.y));
  const eyeA = points[33], eyeB = points[263], nose = points[1], chin = points[152];
  const eyes = Math.hypot(eyeA.x - eyeB.x, eyeA.y - eyeB.y);
  const roll = Math.atan2(Math.abs(eyeA.y - eyeB.y), Math.abs(eyeA.x - eyeB.x)) * 180 / Math.PI;
  const pitchRatio = (nose.y - (eyeA.y + eyeB.y) / 2) / Math.max(.001, chin.y - (eyeA.y + eyeB.y) / 2);
  // Pose is a landmark-based approximation; final ROIs still use the reference Haar detector.
  return {
    cx: 1 - (((left + right) / 2 * videoWidth * scale - (videoWidth * scale - width) / 2) / width),
    cy: ((top + bottom) / 2 * videoHeight * scale - (videoHeight * scale - height) / 2) / height,
    width: (right - left) * videoWidth * scale / width,
    top: (top * videoHeight * scale - (videoHeight * scale - height) / 2) / height,
    bottom: (bottom * videoHeight * scale - (videoHeight * scale - height) / 2) / height,
    frontal: roll <= 12 && Math.abs(nose.x - (eyeA.x + eyeB.x) / 2) / Math.max(.001, eyes) <= .25 && pitchRatio > .18 && pitchRatio < .65,
  };
}
