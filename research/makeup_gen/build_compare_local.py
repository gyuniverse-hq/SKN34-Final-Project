"""One table and one figure for every lip variant measured so far (8회차 멘토링 후속 4단계, 2026-11-23).

    python research/makeup_gen/build_compare_local.py <root=research/data/makeup_gen> <out_md> <out_fig>

Reads only saved results (nothing is re-measured):
  eval/metrics.json            A bare, B AR default (3 frames), C MagicMakeup, D Stable-Makeup (11-20)
  eval/metrics_sweep.json      AR settings on the same frame (11-20)
  out_composite/…json          Stable-Makeup lip paste / colour only (step 1)
  out_composite_fpmt/…json     FPMT raw / lip paste / colour only (step 3)
  eval/metrics_texture.json    wrinkle correlation and strength without gloss spots (step 2)
  out_*/run_log.json           model run times
Colour and outside-lip values are at 512 for the 512 models, 1024 for MagicMakeup and the AR's own 720x960 frame.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_makeup import load  # noqa: E402
from region_composite import make_fig  # noqa: E402


def J(root, p):
    return json.load(open(os.path.join(root, p), encoding='utf-8'))


def main():
    root, out_md, out_fig = sys.argv[1:4]
    m = J(root, 'eval/metrics.json')
    sw = J(root, 'eval/metrics_sweep.json')['rows']
    cs = J(root, 'out_composite/metrics_composite.json')['summary_mean_min_max']
    cf = J(root, 'out_composite_fpmt/metrics_composite.json')['summary_mean_min_max']
    tx = J(root, 'eval/metrics_texture.json')['groups']
    mm = J(root, 'out_magicmakeup/run_log.json')
    sm = J(root, 'out_stable_makeup/run_log.json')
    fp = J(root, 'out_fpmt/run_log.json')

    def from_summary(s):
        g = lambda k: s[k]['mean'] if isinstance(s[k], dict) else s[k][0]
        return dict(vsE=g('dE00_lip_vs_E_real'), out=g('change_dE00_mean_outside_lip(face)'), ssim=g('SSIM_outside_lip(face)'),
                    iou=g('lip_shape_IoU_vs_bare'))

    def from_row(r):
        return dict(vsE=r['dE00_lip_vs_E_real'], out=r['change_dE00_mean_outside_lip(face)'], ssim=r['SSIM_outside_lip(face)'],
                    iou=r['lip_shape_IoU_vs_bare'])

    def tex(g):
        t = tx.get(g)
        return dict(wc=t['wrinkle_corr_nohl'][0], we=t['wrinkle_energy_nohl'][0], hl=t['highlight_share'][0]) if t else {}

    secs = lambda runs: f"{min(r['sec'] for r in runs):.0f}~{max(r['sec'] for r in runs):.0f} s"
    rt = 'real time (phone HUD 15~30 fps, 11-20)'
    rows = [
        ('A bare face', 'input', dict(vsE=m['rows']['A_bare']['dE00_lip_vs_E_real']), {}, '-', ''),
        ('B AR default #C77276 glossy 0.65', 'AR', from_summary(m['summary']['B_VISHUE_AR']), tex('B AR default #C77276 glossy 0.65'), rt, 'product hex'),
        ("B' AR #A26263 glossy 0.35", 'AR (colour from E)', from_row(sw['real_A26263_glossy_035']), tex('B AR #A26263 glossy 0.35'), rt, 'hex from E'),
        ("B'' AR #A26263 matte 0.5", 'AR (colour from E)', from_row(sw['real_A26263_matte_050']), tex('B AR #A26263 matte 0.50'), rt, 'hex from E'),
        ('C MagicMakeup (lip mode)', 'model output', from_summary(m['summary']['C_MagicMakeup']), tex('C MagicMakeup (lip)'),
         f"{secs(mm['runs'])} / image, RTX A6000", 'reference photo'),
        ('D Stable-Makeup', 'model output', from_summary(cs['raw_512']), tex('D Stable-Makeup raw (512)'),
         f"{secs(sm['runs'])} / image, Tesla T4", 'reference photo'),
        ('D + lip paste', 'post-processed', from_summary(cs['paste_512']), tex('D Stable-Makeup + A paste (512)'), 'D + CPU post-process', 'reference photo'),
        ('D + colour only', 'post-processed', from_summary(cs['delta_512']), tex('D Stable-Makeup + B colour only (512)'), 'D + CPU post-process', 'reference photo'),
        ('F FPMT', 'model output', from_summary(cf['raw_512']), tex('F FPMT raw (512)'),
         f"{fp['forward_s_warm_min']:.1f}~{fp['forward_s_warm_median']:.1f} s / image (+0.23 s parsing), laptop CPU", 'reference photo'),
        ('F + lip paste', 'post-processed', from_summary(cf['paste_512']), tex('F FPMT + A paste (512)'), 'F + CPU post-process', 'reference photo'),
        ('F + colour only', 'post-processed', from_summary(cf['delta_512']), tex('F FPMT + B colour only (512)'), 'F + CPU post-process', 'reference photo'),
    ]
    f = lambda v, d=2: '-' if v is None else f'{v:.{d}f}'
    lines = ['| method | kind | lip dE00 vs worn E | outside-lip dE00 | outside SSIM | lip shape IoU | wrinkle corr | wrinkle strength | gloss spots | time | colour input |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    table = []
    for name, kind, c, t, time_, inp in rows:
        lines.append(f"| {name} | {kind} | {f(c.get('vsE'))} | {f(c.get('out'))} | {f(c.get('ssim'), 3)} | {f(c.get('iou'), 3)} | "
                     f"{f(t.get('wc'), 3)} | {f(t.get('we'), 2)} | {f(t.get('hl') and 100 * t['hl'], 0)}{'%' if t.get('hl') is not None else ''} | {time_} | {inp} |")
        table.append(dict(name=name, kind=kind, **c, **t, time=time_, colour_input=inp))
    md = '\n'.join(lines) + '\n'
    open(out_md, 'w', encoding='utf-8').write(md)
    json.dump(table, open(os.path.splitext(out_md)[0] + '.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(md)

    # figure: two rows of five lip close-ups (seed 0 / frame 0)
    A = load(os.path.join(root, 'input/bare_crop_1024.png'))
    up = lambda p: np.asarray(Image.fromarray(load(p)).resize((1024, 1024), Image.LANCZOS))
    P = lambda p: os.path.join(root, p)
    row1 = [('A bare', A), ('B AR default', load(P('ar_out/ar_lip_0.png'))),
            ("B' AR A26263 glossy .35", load(P('ar_out_sweep/sweep_real_A26263_glossy_035.png'))),
            ("B'' AR A26263 matte .5", load(P('ar_out_sweep/sweep_real_A26263_matte_050.png'))),
            ('C MagicMakeup', load(P('out_magicmakeup/magicmakeup_seed0.png')))]
    row2 = [('D Stable-Makeup', up(P('out_stable_makeup/stablemakeup_seed0.png'))),
            ('D + colour only', up(P('out_composite/stablemakeup_delta_seed0_512.png'))),
            ('F FPMT', up(P('out_fpmt/fpmt_seed0.png'))),
            ('F + colour only', up(P('out_composite_fpmt/fpmt_delta_seed0_512.png'))),
            ('E worn (reference)', load(P('input/ref_crop_1024.png')))]
    tmp = [out_fig + '.r1.png', out_fig + '.r2.png']
    make_fig(row1, tmp[0])
    make_fig(row2, tmp[1])
    Image.fromarray(np.vstack([np.asarray(Image.open(t)) for t in tmp])).save(out_fig)
    for t in tmp:
        os.remove(t)


if __name__ == '__main__':
    main()
