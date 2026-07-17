#!/usr/bin/env python3
"""Step 15: export GeoTIFF velocity, displacement time slices and reference point."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import numpy as np
import xarray as xr

from workflow import (
    StageContext,
    choose_dataarray,
    export_raster,
    find_reference_point,
    log,
    parser,
)


def main() -> None:
    args = parser(__doc__).parse_args()
    import rioxarray  # noqa: F401
    ctx = StageContext.from_file(args.config)
    disp_path = ctx.checkpoint_dir / "displacement_geo.nc"
    velocity_path = ctx.checkpoint_dir / "velocity_geo.nc"
    ctx.require(disp_path, velocity_path)
    displacement = choose_dataarray(
        xr.open_dataset(disp_path, chunks={}),
        ("displacement_mm", "displacement"),
    ).rio.write_crs("EPSG:4326")
    velocity = choose_dataarray(
        xr.open_dataset(velocity_path, chunks={}),
        ("velocity_mm_per_year", "velocity"),
    ).rio.write_crs("EPSG:4326")

    velocity_dir = ctx.workdir / "LOS_Velocity"
    export_raster(velocity, velocity_dir / "LOS_Velocity_mm_per_yr.tif")
    explorer = ctx.workdir / "InSARExplorer"
    timeseries = explorer / "timeseries"
    timeseries.mkdir(parents=True, exist_ok=True)
    if "date" in displacement.dims:
        time_dim = "date"
    elif "pair" in displacement.dims:
        time_dim = "pair"
    else:
        raise RuntimeError("Geocoded displacement has neither date nor pair dimension")
    for index in range(displacement.sizes[time_dim]):
        layer = displacement.isel({time_dim: index})
        if time_dim == "date":
            label = np.datetime_as_string(displacement[time_dim].values[index], unit="D").replace("-", "")
        else:
            label = f"pair_{index + 1:03d}"
        export_raster(layer, timeseries / f"{label}_displacement.tif")
    export_raster(velocity, explorer / "LOS_Velocity.tif")
    find_reference_point(displacement, explorer)
    log(f"[{ctx.sub}] Export complete")


if __name__ == "__main__":
    main()
