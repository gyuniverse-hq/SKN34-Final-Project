"""Synthetic camera clips for the page-side grain scale (the 0.45 factor) and the env checks.

    python research/env_eval/headless/make_env_y4m.py <face.png> <out_dir> [clips...]

720x960, 30 frames, looping. The face is scaled to 0.72 of the frame on a neutral grey textured wall. Noise uses the same
shot + read model as lapa_env_eval.noisy (1/5 of the light, 400 photons at full scale). Seeded, so clips are repeatable.
The face photo stays under the git-ignored research/data/.
"""
import sys

import cv2
import numpy as np

W, H = 720, 960
rng = np.random.default_rng(3)
WALL = np.clip(125 + 36 * cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 3), 0, 255).astype(np.uint8)[..., None].repeat(3, 2).copy()
for _ in range(6):
    x = int(rng.integers(0, W))
    cv2.line(WALL, (x, 0), (x + 40, H), (95, 95, 95), 3)


def fit(img, scale=0.72):
    h, w = img.shape[:2]
    s = min(W / w, H / h) * scale
    r = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    f = WALL.copy()
    y0, x0 = (H - r.shape[0]) // 2, (W - r.shape[1]) // 2
    f[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
    return f


def lin(u8):
    c = u8.astype(np.float32) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(l):
    l = np.clip(l, 0, 1)
    return np.clip(np.round(np.where(l <= 0.0031308, l * 12.92, 1.055 * l ** (1 / 2.4) - 0.055) * 255), 0, 255).astype(np.uint8)


def noisy(l, ph):
    return rng.poisson(np.clip(l, 0, None) * ph).astype(np.float32) / ph + rng.normal(0, 2 / ph, l.shape).astype(np.float32)


def clip(out_dir, name, frames):
    with open(f'{out_dir}/{name}.y4m', 'wb') as fh:
        fh.write(b'YUV4MPEG2 W%d H%d F30:1 Ip A1:1 C420jpeg\n' % (W, H))
        for f in frames:
            fh.write(b'FRAME\n')
            fh.write(cv2.cvtColor(f, cv2.COLOR_BGR2YUV_I420).tobytes())
    print(name)


def main():
    src, out_dir = cv2.imread(sys.argv[1]), sys.argv[2]
    want = set(sys.argv[3:]) or {'normal', 'dark', 'dark_ae'}
    base = fit(src)
    L = lin(base)
    if 'normal' in want:
        clip(out_dir, 'normal', [base] * 30)
    if 'dark' in want:
        clip(out_dir, 'dark', [srgb(noisy(L * 0.2, 400)) for _ in range(30)])
    if 'dark_ae' in want:
        clip(out_dir, 'dark_ae', [srgb(noisy(L * 0.2, 400) * 5) for _ in range(30)])
    if 'lamp' in want:
        # 11-20 phone capture "stand only": the face and wall at 1/10 of the light, a warm lamp (full scale, about 2 % of the
        # frame) above the head with a soft glow, so the frame mean stays up while the face is darker than the dark room.
        yy, xx = np.mgrid[0:H, 0:W]
        d = np.hypot(xx - W / 2, yy - 90)
        lamp = np.clip(1.0 - (d - 70) / 30, 0, 1)[..., None] * np.array([0.55, 0.85, 1.0])   # BGR, warm
        glow = (0.25 * np.exp(-(d / 260) ** 2))[..., None] * np.array([0.35, 0.7, 1.0])
        clip(out_dir, 'lamp', [srgb(np.maximum(noisy(L * 0.1 + glow, 400), lamp)) for _ in range(30)])


if __name__ == '__main__':
    main()
