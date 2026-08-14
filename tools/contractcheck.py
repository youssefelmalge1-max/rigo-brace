"""Headless guard: the #48 contract's machine-readable block must exist,
parse, and carry every threshold the gates use (hardening Wave 0).

Run:  python tools/contractcheck.py   (no Blender needed; exit 0 = consistent)
"""

import sys

import quality_contract


def main():
    try:
        thresholds = quality_contract.load()
    except Exception as exc:  # noqa: BLE001
        print(f"CONTRACT INCONSISTENT: {exc}")
        return 1
    print("contract thresholds OK:")
    for section in sorted(thresholds):
        print(f"  {section}: {thresholds[section]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
