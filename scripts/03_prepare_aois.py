#!/usr/bin/env python3
"""Create input and configuration directories for each selected AOI."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from workflow import (
    SUBSWATH_BY_GROUP,
    add_aoi_selection_arguments,
    hardlink_or_copy,
    read_geojson,
    selected_aois,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_aoi_selection_arguments(parser)
    parser.add_argument("--master", default="LocalProcessing")
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--slc-source", type=Path, required=True)
    parser.add_argument("--dem-root", type=Path, required=True)
    parser.add_argument("--aoi-root", type=Path, required=True)
    parser.add_argument("--aoi-inline-file", type=Path)
    parser.add_argument("--orbit-dir", type=Path)
    parser.add_argument("--link-mode", choices=["hardlink", "symlink", "copy"], default="hardlink")
    parser.add_argument("--orbit-link-mode", choices=["hardlink", "symlink", "copy"], default="hardlink")
    parser.add_argument("--copy-dem", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-download-orbits", action="store_true")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--corr-limit", type=float, default=0.2)
    parser.add_argument("--basedays", type=int, default=60)
    parser.add_argument("--basemeters", type=int, default=250)
    parser.add_argument("--reference", default="2025-01-11")
    parser.add_argument("--ncpus", type=int, default=4)
    parser.add_argument("--memory-gb", type=int, default=12)
    parser.add_argument("--dask-workers", type=int, default=2)
    parser.add_argument("--allow-parallel-hdf5", action="store_true")
    return parser



def main() -> None:
    args = build_parser().parse_args()
    aois = selected_aois(args)
    scratch_root = args.scratch_root.expanduser().resolve()
    master_dir = scratch_root / args.master
    slc_source = args.slc_source.expanduser().resolve()
    dem_root = args.dem_root.expanduser().resolve()
    aoi_root = args.aoi_root.expanduser().resolve()
    orbit_dir = args.orbit_dir.expanduser().resolve() if args.orbit_dir else None

    safe_dirs = sorted(slc_source.glob("*.SAFE"))
    if not safe_dirs:
        raise FileNotFoundError(f"No .SAFE directories found in {slc_source}")
    orbit_files = sorted(orbit_dir.glob("*.EOF")) if orbit_dir and orbit_dir.exists() else []

    master_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[str] = []
    for aoi in aois:
        print(f"\n===== Preparing {aoi} =====", flush=True)
        aoi_dir = master_dir / aoi
        inputs_dir = aoi_dir / "Inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        for safe_dir in safe_dirs:
            hardlink_or_copy(safe_dir, inputs_dir / safe_dir.name, args.link_mode)
        for orbit_file in orbit_files:
            hardlink_or_copy(orbit_file, inputs_dir / orbit_file.name, args.orbit_link_mode)

        dem_source = dem_root / aoi / "dem.nc"
        if not dem_source.exists():
            raise FileNotFoundError(f"DEM missing for {aoi}: {dem_source}")
        dem_destination = inputs_dir / "dem.nc"
        if not dem_destination.exists():
            if args.copy_dem:
                shutil.copy2(dem_source, dem_destination)
            else:
                hardlink_or_copy(dem_source, dem_destination, args.link_mode)

        config = {
            "sub": aoi,
            "base_dir": str(aoi_dir),
            "workdir": str(aoi_dir / f"Outputs_{aoi}"),
            "datadir": str(inputs_dir),
            "dem": str(dem_destination),
            "aoi_geojson": read_geojson(aoi, aoi_root, args.aoi_inline_file),
            "limit": args.limit,
            "corr_limit": args.corr_limit,
            "subswath": SUBSWATH_BY_GROUP[aoi[0]],
            "basedays": args.basedays,
            "basemeters": args.basemeters,
            "reference": args.reference,
            "ncpus": args.ncpus,
            "memory_gb": args.memory_gb,
            "dask_workers": args.dask_workers,
            "safe_hdf5_io": not args.allow_parallel_hdf5,
            "drop_if_exists": not args.resume,
            "download_orbits": not args.no_download_orbits,
        }
        (aoi_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        prepared.append(aoi)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "master": args.master,
        "aois": prepared,
        "count": len(prepared),
        "slc_source": str(slc_source),
        "dem_root": str(dem_root),
        "aoi_root": str(aoi_root),
        "orbit_dir": str(orbit_dir) if orbit_dir else None,
        "processing_scripts": [
            "04_scan_scenes.py", "05_reframe.py", "06_load_dem.py",
            "07_align.py", "08_geocode.py", "09_baseline_pairs.py",
            "10_interferograms.py", "11_unwrap.py",
            "12_stratified_correction.py", "13_sbas_inversion.py",
            "14_geocode_products.py", "15_export_results.py",
            "16_finalize.py",
        ],
    }
    (master_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nPrepared {len(prepared)} AOI(s) under {master_dir}")


if __name__ == "__main__":
    main()
