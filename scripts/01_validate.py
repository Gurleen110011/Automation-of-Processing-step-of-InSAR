#!/usr/bin/env python3
"""Validate AOI, DEM, SLC, and optional runtime prerequisites."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

from workflow import add_aoi_selection_arguments, selected_aois

REQUIRED_PYTHON_MODULES = [
    "dask",
    "geopandas",
    "matplotlib",
    "numpy",
    "pandas",
    "rioxarray",
    "xarray",
    "distributed",
    "joblib",
    "scipy",
    "pygmtsar",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate PyGMTSAR workflow inputs.")
    add_aoi_selection_arguments(parser)
    parser.add_argument("--slc-source", type=Path, required=True)
    parser.add_argument("--dem-root", type=Path, required=True)
    parser.add_argument("--aoi-root", type=Path, required=True)
    parser.add_argument("--aoi-inline-file", type=Path)
    parser.add_argument("--orbit-dir", type=Path)
    parser.add_argument("--require-unzipped", action="store_true")
    parser.add_argument("--check-runtime-deps", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    aois = selected_aois(args)
    errors: list[str] = []
    warnings: list[str] = []

    slc_source = args.slc_source.expanduser().resolve()
    dem_root = args.dem_root.expanduser().resolve()
    aoi_root = args.aoi_root.expanduser().resolve()
    orbit_dir = args.orbit_dir.expanduser().resolve() if args.orbit_dir else None

    if not slc_source.exists():
        errors.append(f"SLC source does not exist: {slc_source}")
    else:
        safe_count = len(list(slc_source.glob("*.SAFE")))
        zip_count = len(list(slc_source.glob("*.zip")))
        if safe_count == 0 and (args.require_unzipped or zip_count == 0):
            errors.append(
                f"No .SAFE directories found in {slc_source}. ZIP files found: {zip_count}."
            )
        elif safe_count == 0:
            warnings.append(
                f"No .SAFE directories yet; {zip_count} ZIP file(s) can be unzipped first."
            )

    if not dem_root.exists():
        errors.append(f"DEM root does not exist: {dem_root}")
    if not aoi_root.exists() and not args.aoi_inline_file:
        errors.append(f"AOI root does not exist: {aoi_root}")

    if args.aoi_inline_file and not args.aoi_inline_file.exists():
        errors.append(f"AOI inline file does not exist: {args.aoi_inline_file}")

    for aoi in aois:
        dem = dem_root / aoi / "dem.nc"
        if not dem.exists():
            errors.append(f"Missing DEM for {aoi}: {dem}")

        if args.aoi_inline_file:
            # The prepare step validates the mapping key and JSON body.
            pass
        elif not any((aoi_root / f"{aoi}{ext}").exists() for ext in (".geojson", ".json")):
            errors.append(
                f"Missing AOI geometry for {aoi}: {aoi_root / (aoi + '.geojson')}"
            )

    if orbit_dir:
        if not orbit_dir.exists():
            warnings.append(f"Orbit directory does not exist: {orbit_dir}")
        elif not list(orbit_dir.glob("*.EOF")):
            warnings.append(
                f"No .EOF orbit files found in {orbit_dir}; PyGMTSAR may download them."
            )

    if args.check_runtime_deps:
        for module in REQUIRED_PYTHON_MODULES:
            if importlib.util.find_spec(module) is None:
                errors.append(f"Missing Python module: {module}")
        if shutil.which("snaphu") is None:
            errors.append("Missing executable on PATH: snaphu")

    print(f"Selected AOIs ({len(aois)}): {', '.join(aois)}")
    for message in warnings:
        print(f"WARNING: {message}")
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        raise SystemExit(f"Validation failed with {len(errors)} error(s).")
    print("Validation passed.")


if __name__ == "__main__":
    main()
