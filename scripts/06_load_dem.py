#!/usr/bin/env python3
"""Step 06: normalize the AOI DEM and load it into the PyGMTSAR stack."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import xarray as xr

from workflow import (
    StageContext,
    build_stack,
    dask_client,
    load_aoi,
    log,
    normalize_dem,
    parser,
    save_nc,
    select_dem_variable,
)


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    ctx.require(ctx.checkpoint_dir / "scenes_reframed.pkl", ctx.dem_path)
    dataset = xr.open_dataset(ctx.dem_path, chunks="auto")
    dem = normalize_dem(select_dem_variable(dataset))
    log(
        f"[{ctx.sub}] DEM variable={dem.name}, shape={dem.shape}, "
        f"lat=({float(dem.lat.min())}, {float(dem.lat.max())}), "
        f"lon=({float(dem.lon.min())}, {float(dem.lon.max())})"
    )
    normalized = ctx.checkpoint_dir / "dem_normalized.nc"
    save_nc(dem.rename("elevation"), normalized, "elevation")
    sbas = build_stack(ctx)
    with dask_client(ctx):
        sbas.load_dem(dem, load_aoi(ctx))


if __name__ == "__main__":
    main()
