"""Run FPMT (Sun, Xiong, Rong, Pattern Recognition 2026; github.com/Snowfallingplum/FPMT, CC BY-NC-SA 4.0) on the CPU.

    python research/makeup_gen/run_fpmt.py <fpmt/quick_start> <data_root> <out_dir> [repeats=10]

data_root holds images/non_makeup/*, images/makeup/* and seg1/{non_makeup,makeup}/<same stem>.png (19-class face parsing in
the zllrunning/face-parsing.PyTorch label order). Uses the repo's own MakeupDataset (resize 573, centre crop 512, its region
split) and FPMTNet with the released L=3 / 512 weights; nothing in the repo is edited. The weights are loaded with
map_location='cpu' (the repo's resume() assumes the device they were saved on), and the two CUDA-only spots
(utils.init_net's assert, Lap_Pyramid_Conv.gauss_kernel's 'cuda' default) are replaced at import time with CPU versions.

Per pair: <out>/fpmt_<src>__<ref>.png (the 512 transfer only, in the model's 1.12x zoomed crop), _srcframe.png (the same
mapped back onto the source photo's pixels by the exact inverse of resize 573 + centre crop 512; the ~27 px border the crop
drops stays the source) and _panel.png (source | reference | aligned reference | transfer, as the repo's examples_results). Timing: model load, then `repeats` forward passes of the first pair
(first one dropped as warm-up), median and min; face parsing is not included. run_log.json records the commit, weight sha256,
torch version, threads and CPU.
"""
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time

import cv2
import numpy as np
import torch
from PIL import Image


def main():
    qs, data_root, out_dir = sys.argv[1:4]
    repeats = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    qs = os.path.abspath(qs)
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, qs)
    sys.argv = [sys.argv[0], '--gpu', '-1']          # the repo's Options parser reads sys.argv
    # The released code is CUDA-only in two places; swap them for CPU versions before the model module imports them
    # (same maths: the 5x5 binomial kernel and the weight init, minus the CUDA assert and the 'cuda' default device).
    import networks
    import utils
    _gk = networks.Lap_Pyramid_Conv.gauss_kernel
    networks.Lap_Pyramid_Conv.gauss_kernel = lambda self, device=torch.device('cpu'), channels=3: _gk(self, device, channels)

    def init_net_cpu(net, gpu, init_type='normal', gain=0.02):
        net.to(gpu)
        utils.init_weights(net, init_type, gain)
        return net
    utils.init_net = init_net_cpu
    from dataset import MakeupDataset
    from model import FPMT
    from options import Options

    opts = Options().parse()
    opts.phase = 'test_pair'
    opts.data_root = os.path.join(data_root, 'images')
    ds = MakeupDataset(opts)
    srcs = [os.path.splitext(os.path.basename(p))[0] for p in ds.non_makeup_path]
    refs = [os.path.splitext(os.path.basename(p))[0] for p in ds.makeup_path]

    wpath = os.path.join(qs, 'weights', 'FPMT_L3_512.pth')
    t0 = time.perf_counter()
    model = FPMT(opts)
    ck = torch.load(wpath, map_location='cpu', weights_only=False)
    missing = model.gen.load_state_dict(ck['gen'], strict=False)
    model.eval()
    load_s = time.perf_counter() - t0
    n_params = sum(p.numel() for p in model.gen.parameters())

    def to_img(t):
        return Image.fromarray(((t[0].clamp(-1, 1).permute(1, 2, 0).numpy() + 1) * 127.5).round().astype(np.uint8))

    times = []
    pairs = []
    for i in range(len(ds)):
        data = {k: v[None] for k, v in ds[i].items()}
        model.test_load_data(data)
        src, ref = srcs[i // len(refs)], refs[i % len(refs)]
        runs = repeats if i == 0 else 1
        for _ in range(runs):
            t = time.perf_counter()
            with torch.no_grad():
                panel = model.test_pair()
            times.append(time.perf_counter() - t) if i == 0 else None
        out_img = to_img(model.transfer_img)
        out_img.save(os.path.join(out_dir, f'fpmt_{src}__{ref}.png'))
        # back to the source photo's frame: exact inverse of resize(S) + centre crop(C), pixels outside the crop = source
        src_img = np.asarray(Image.open(ds.non_makeup_path[i // len(refs)]).convert('RGB'))
        H, W = src_img.shape[:2]
        S, C = opts.resize_size, opts.crop_size
        o = (S - C) // 2
        M = np.float32([[W / S, 0, o * W / S], [0, H / S, o * H / S]])
        warped = cv2.warpAffine(np.asarray(out_img), M, (W, H), flags=cv2.INTER_LANCZOS4)
        cover = cv2.warpAffine(np.ones((C, C), np.float32), M, (W, H), flags=cv2.INTER_LINEAR)[..., None]
        back = np.clip(warped * cover + src_img * (1 - cover), 0, 255).round().astype(np.uint8)
        Image.fromarray(back).save(os.path.join(out_dir, f'fpmt_{src}__{ref}_srcframe.png'))
        to_img(panel).save(os.path.join(out_dir, f'fpmt_{src}__{ref}_panel.png'))
        pairs.append(f'{src}__{ref}')

    try:
        commit = subprocess.check_output(['git', '-C', qs, 'rev-parse', 'HEAD'], text=True).strip()
    except Exception:
        commit = None
    try:
        cpu = subprocess.check_output(['powershell', '-NoProfile', '-Command',
                                       '(Get-CimInstance Win32_Processor).Name'], text=True).strip()
    except Exception:
        cpu = platform.processor()
    warm = times[1:] if len(times) > 1 else times
    log = {'repo_commit': commit, 'weights': os.path.basename(wpath),
           'weights_sha256': hashlib.sha256(open(wpath, 'rb').read()).hexdigest(),
           'params': n_params, 'missing_or_unexpected_keys': [list(missing.missing_keys), list(missing.unexpected_keys)],
           'torch': torch.__version__, 'threads': torch.get_num_threads(), 'cpu': cpu, 'device': 'cpu',
           'preprocess': 'repo MakeupDataset test_pair: resize 573, centre crop 512, 7-channel region split',
           'model_load_s': round(load_s, 3),
           'forward_s_warm_median': round(statistics.median(warm), 4), 'forward_s_warm_min': round(min(warm), 4),
           'forward_s_first': round(times[0], 4), 'repeats': len(times), 'face_parsing_time_included': False,
           'pairs': pairs}
    json.dump(log, open(os.path.join(out_dir, 'run_log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in log.items() if k != 'pairs'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
