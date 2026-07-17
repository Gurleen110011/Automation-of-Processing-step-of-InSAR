#!/usr/bin/env python3
"""Collect selected lightweight outputs from each staged PyGMTSAR AOI run."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import argparse
import shutil
from pathlib import Path

from workflow import add_aoi_selection_arguments, selected_aois

COLLECT_ITEMS = [
    "config.json",
    "workflow_summary.json",
    ".workflow_success",
    ".stage_markers",
]


def replace_copy(source: Path, destination: Path) -> None:
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_aoi_selection_arguments(parser)
    parser.add_argument("--master", default="LocalProcessing")
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--home-results", type=Path, required=True)
    parser.add_argument("--include-heavy", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    aois = selected_aois(args)
    source_master = args.scratch_root.expanduser().resolve() / args.master
    destination_master = args.home_results.expanduser().resolve() / args.master
    destination_master.mkdir(parents=True, exist_ok=True)

    for aoi in aois:
        print(f"\n===== Collecting {aoi} =====")
        source = source_master / aoi
        destination = destination_master / aoi
        destination.mkdir(parents=True, exist_ok=True)
        relative_items = list(COLLECT_ITEMS)
        relative_items.extend(
            [
                f"processing_{aoi}.log",
                f"Outputs_{aoi}/InSARExplorer",
                f"Outputs_{aoi}/LOS_Velocity",
                f"Outputs_{aoi}/mean_coherence.csv",
                f"Outputs_{aoi}/baseline_pairs_limited.csv",
                f"Outputs_{aoi}/baseline_network.png",
                f"Outputs_{aoi}/scenes.png",
            ]
        )
        if args.include_heavy:
            relative_items.extend(
                [
                    f"Outputs_{aoi}/Checkpoints",
                    f"Outputs_{aoi}/Ifg",
                    f"Outputs_{aoi}/Coh",
                    f"Outputs_{aoi}/Unwrapped",
                    f"Outputs_{aoi}/Stratified",
                    f"Outputs_{aoi}/Corrected",
                ]
            )

        for relative in relative_items:
            source_item = source / relative
            if not source_item.exists():
                print(f"Missing: {source_item}")
                continue
            destination_item = destination / relative
            replace_copy(source_item, destination_item)
            print(f"Copied: {source_item} -> {destination_item}")

    print(f"\nCollected results under {destination_master}")


if __name__ == "__main__":
    main()
