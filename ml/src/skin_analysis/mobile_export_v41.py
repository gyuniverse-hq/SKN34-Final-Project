"""Export the v4.1 skin models for on-device inference."""

from .mobile_export import ROOT
from .mobile_export_common import export


def main():
    print(export(ROOT / "ml/runs/skin-analysis-v4.1/skin-analysis-v4.1"))


if __name__ == "__main__":
    main()
