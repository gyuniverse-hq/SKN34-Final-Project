// Browser and Node verification share the exact preprocessing implementation.
export function normalize(rgb) {
  const mean = [.485, .456, .406], std = [.229, .224, .225];
  const result = new Float32Array(3 * 256 * 256);
  for (let c = 0; c < 3; c++) for (let i = 0; i < 256 * 256; i++) {
    result[c * 256 * 256 + i] = (rgb[i * 3 + c] / 255 - mean[c]) / std[c];
  }
  return result;
}

function weights(input) {
  return Array.from({ length: 256 }, (_, x) => {
    const scale = input / 256, support = Math.max(1, scale), center = (x + .5) * scale;
    const start = Math.max(0, Math.trunc(center - support + .5));
    const end = Math.min(input, Math.trunc(center + support + .5));
    const raw = Array.from({ length: end - start }, (_, i) => Math.max(0, 1 - Math.abs((start + i - center + .5) / support)));
    const sum = raw.reduce((a, b) => a + b, 0);
    return { start, coefficients: raw.map(value => Math.trunc(value / sum * 2 ** 22 + .5)) };
  });
}

export function resizePillow(rgb, width, height) {
  let horizontal = rgb;
  if (width !== 256) {
    horizontal = new Uint8Array(height * 256 * 3);
    const kernels = weights(width);
    for (let y = 0; y < height; y++) for (let x = 0; x < 256; x++) for (let c = 0; c < 3; c++) {
      const kernel = kernels[x]; let value = 2 ** 21;
      kernel.coefficients.forEach((coefficient, i) => { value += rgb[(y * width + kernel.start + i) * 3 + c] * coefficient; });
      horizontal[(y * 256 + x) * 3 + c] = Math.min(255, Math.max(0, value >> 22));
    }
  }
  if (height === 256) return horizontal;
  const result = new Uint8Array(256 * 256 * 3), kernels = weights(height);
  for (let y = 0; y < 256; y++) for (let x = 0; x < 256; x++) for (let c = 0; c < 3; c++) {
    const kernel = kernels[y]; let value = 2 ** 21;
    kernel.coefficients.forEach((coefficient, i) => { value += horizontal[((kernel.start + i) * 256 + x) * 3 + c] * coefficient; });
    result[(y * 256 + x) * 3 + c] = Math.min(255, Math.max(0, value >> 22));
  }
  return result;
}

export function createPreprocessor(cv, jpegRoundTrip) {
  return async function tensor(rgba, bbox = null) {
    const rgb = new cv.Mat();
    cv.cvtColor(rgba, rgb, cv.COLOR_RGBA2RGB);
    try {
      if (!bbox) return normalize(resizePillow(rgb.data, rgb.cols, rgb.rows));
      const [x1, y1, x2, y2] = bbox;
      const cx = Math.floor((x1 + x2) / 2), cy = Math.floor((y1 + y2) / 2);
      const half = Math.floor(Math.max(x2 - x1, y2 - y1) / 2);
      const left = Math.max(0, cx - half), top = Math.max(0, cy - half);
      const right = Math.min(rgb.cols, cx + half), bottom = Math.min(rgb.rows, cy + half);
      if (right <= left || bottom <= top) throw new Error('photo');
      const crop = rgb.roi(new cv.Rect(left, top, right - left, bottom - top));
      const resized = new cv.Mat();
      try {
        cv.resize(crop, resized, new cv.Size(256, 256), 0, 0, cv.INTER_LINEAR);
        return normalize(jpegRoundTrip(resized.data));
      } finally { crop.delete(); resized.delete(); }
    } finally { rgb.delete(); }
  };
}

// The same rounded face-box proportions as the reference OpenCV pipeline.
export function detectRegions(cv, rgba, detector) {
  const small = new cv.Mat(), gray = new cv.Mat(), faces = new cv.RectVector();
  const round = value => { const floor = Math.floor(value); return value - floor === .5 ? (floor % 2 ? floor + 1 : floor) : Math.round(value); };
  try {
    const scale = Math.min(1, 900 / Math.max(rgba.cols, rgba.rows));
    cv.resize(rgba, small, new cv.Size(round(rgba.cols * scale), round(rgba.rows * scale)));
    cv.cvtColor(small, gray, cv.COLOR_RGBA2GRAY); cv.equalizeHist(gray, gray);
    detector.detectMultiScale(gray, faces, 1.1, 6, 0, new cv.Size(80, 80), new cv.Size());
    if (faces.size() !== 1) throw new Error('photo');
    const face = faces.get(0), x = face.x / scale, y = face.y / scale, w = face.width / scale, h = face.height / scale;
    return [[.22, -.08, .78, .22], [.42, .23, .58, .39], [.02, .28, .28, .47],
      [.72, .28, .98, .47], [.08, .48, .36, .73], [.64, .48, .92, .73]].map(p => {
      const box = [Math.max(0, round(x + p[0] * w)), Math.max(0, round(y + p[1] * h)),
        Math.min(rgba.cols, round(x + p[2] * w)), Math.min(rgba.rows, round(y + p[3] * h))];
      if (box[2] - box[0] < 4 || box[3] - box[1] < 4) throw new Error('photo');
      return box;
    });
  } finally { small.delete(); gray.delete(); faces.delete(); }
}
