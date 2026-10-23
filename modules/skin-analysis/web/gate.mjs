export class CaptureGate {
  reset() { this.since = null; this.previous = null; this.lastAt = null; }
  update(faces, now) {
    const face = faces[0];
    const guidance = !faces.length ? 'noFace' : faces.length !== 1 ? 'multipleFaces'
      : !face.frontal ? 'straight' : face.width < .4 || face.width > .65 ? 'distance'
        : Math.abs(face.cx - .5) > .08 || Math.abs(face.cy - .48) > .10 ? 'center'
          : face.top < .10 || face.top > .27 || face.bottom > .80 ? 'forehead' : 'hold';
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
