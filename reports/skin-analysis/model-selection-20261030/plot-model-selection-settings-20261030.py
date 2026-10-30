"""Reproduce model-setting plots from the aggregate evidence JSON."""

import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
from matplotlib import pyplot as plt

BASE = Path(__file__).resolve().parent
DATA = json.loads((BASE / 'model-selection-settings-evidence-20261030.json').read_text(encoding='utf8'))
FIGURES = BASE / 'figures'
FIGURES.mkdir(parents=True, exist_ok=True)


def make_plot(section, names, title, destination):
    fig, ax = plt.subplots(figsize=(9, 5))
    max_epoch = 0
    for key, label in names:
        run = DATA[section]['runs'][key]
        history = run['history']
        epochs = [row['epoch'] for row in history]
        scores = [row['valid_macro_f1'] for row in history]
        line = ax.plot(epochs, scores, label=label)[0]
        ax.scatter([run['selected_epoch']], [run['validation_macro_f1']],
                   marker='*', s=110, color=line.get_color(), zorder=4)
        max_epoch = max(max_epoch, max(epochs))
    ax.set_title(title)
    ax.set_xlabel('Epoch')
    ax.set_ylabel('Validation Macro-F1')
    ax.set_xticks(range(1, max_epoch + 1, 2))
    ax.grid(alpha=.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / destination, dpi=160)
    plt.close(fig)


make_plot('batch32_vs16', [('32', 'Batch 32'), ('16', 'Batch 16')],
          'Pore grade classification: batch comparison', 'batch-size-validation.png')
make_plot('head_warmup', [('1', 'Head-only 1 epoch'), ('2', 'Head-only 2 epochs'), ('4', 'Head-only 4 epochs')],
          'Pore grade classification: head warm-up', 'head-warmup-validation.png')
