"""Export the v4 binary care models and ROI skin-type model for on-device inference."""

import argparse
from pathlib import Path

from .mobile_export import ROOT
from .mobile_export_v3 import export

DEFAULT_BUNDLE = ROOT / "ml/runs/skin-analysis-v4/bundle"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    print(export(parser.parse_args().bundle))


if __name__ == "__main__":
    main()
