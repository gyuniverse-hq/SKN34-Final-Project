"""19-class face parsing (zllrunning/face-parsing.PyTorch, MIT, BiSeNet `79999_iter.pth`) on the CPU, for FPMT inputs.

    python research/makeup_gen/face_parse.py <face_parsing repo> <79999_iter.pth> <out_dir> <image> [<image> ...]

Same steps as the repo's test.py: resize to 512 (bilinear), ImageNet normalisation, argmax of the main output. Writes
<out_dir>/<stem>.png (labels 0..18, 512x512, the order FPMT's split_parse expects: 1 skin, 2/3 brows, 4/5 eyes, 6 glasses,
10 nose, 11 mouth, 12/13 lips, 14 neck, 17 hair ...) and <stem>_vis.png (colour overlay for a visual check).
The backbone's ImageNet download in Resnet18.init_weight is skipped: the 79999 checkpoint holds every weight.
"""
import os
import sys
import time

import numpy as np
import torch
from PIL import Image

COLORS = np.array([[0, 0, 0], [255, 200, 160], [120, 60, 20], [120, 60, 20], [0, 120, 255], [0, 120, 255], [180, 180, 180],
                   [255, 160, 200], [255, 160, 200], [255, 0, 255], [0, 200, 120], [60, 0, 60], [230, 0, 40], [160, 0, 30],
                   [200, 200, 0], [255, 120, 0], [0, 255, 255], [90, 50, 0], [0, 0, 160]], np.uint8)


def main():
    repo, ckpt, out_dir, *imgs = sys.argv[1:]
    sys.path.insert(0, os.path.abspath(repo))
    import resnet
    resnet.Resnet18.init_weight = lambda self: None
    from model import BiSeNet
    os.makedirs(out_dir, exist_ok=True)
    net = BiSeNet(n_classes=19)
    net.load_state_dict(torch.load(ckpt, map_location='cpu'))
    net.eval()
    mean = np.array([0.485, 0.456, 0.406], np.float32)
    std = np.array([0.229, 0.224, 0.225], np.float32)
    for p in imgs:
        img = Image.open(p).convert('RGB').resize((512, 512), Image.BILINEAR)
        x = (np.asarray(img, np.float32) / 255 - mean) / std
        t = time.perf_counter()
        with torch.no_grad():
            out = net(torch.from_numpy(x.transpose(2, 0, 1))[None])[0]
        dt = time.perf_counter() - t
        lab = out[0].argmax(0).numpy().astype(np.uint8)
        stem = os.path.splitext(os.path.basename(p))[0]
        Image.fromarray(lab).save(os.path.join(out_dir, stem + '.png'))
        vis = (0.5 * np.asarray(img) + 0.5 * COLORS[lab]).astype(np.uint8)
        Image.fromarray(vis).save(os.path.join(out_dir, stem + '_vis.png'))
        print(stem, 'labels', np.unique(lab).tolist(), 'forward_s', round(dt, 3))


if __name__ == '__main__':
    main()
