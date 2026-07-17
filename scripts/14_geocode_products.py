#!/usr/bin/env python3
"""Step 14: geocode radar-coordinate displacement and velocity products."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import xarray as xr

from workflow import StageContext, build_stack, choose_dataarray, dask_client, log, parser, save_nc


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    displacement_path = ctx.checkpoint_dir / "displacement_radar.nc"
    velocity_path = ctx.checkpoint_dir / "velocity_radar.nc"
    ctx.require(displacement_path, velocity_path)
    displacement = choose_dataarray(
        xr.open_dataset(displacement_path, chunks={}),
        ("displacement_mm", "displacement", "phase"),
    )
    velocity = choose_dataarray(
        xr.open_dataset(velocity_path, chunks={}),
        ("velocity_mm_per_year", "velocity"),
    )
    sbas = build_stack(ctx)
    with dask_client(ctx):
        log(f"[{ctx.sub}] Geocoding displacement")
        disp_geo = sbas.cropna(sbas.ra2ll(displacement).compute())
        log(f"[{ctx.sub}] Geocoding velocity")
        velocity_geo = sbas.cropna(sbas.ra2ll(velocity).compute())
        rename_disp = {name: new for name, new in (("lat", "y"), ("lon", "x")) if name in disp_geo.dims}
        rename_vel = {name: new for name, new in (("lat", "y"), ("lon", "x")) if name in velocity_geo.dims}
        disp_geo = disp_geo.rename(rename_disp)
        velocity_geo = velocity_geo.rename(rename_vel)
        save_nc(disp_geo.rename("displacement_mm"), ctx.checkpoint_dir / "displacement_geo.nc", "displacement_mm")
        save_nc(velocity_geo.rename("velocity_mm_per_year"), ctx.checkpoint_dir / "velocity_geo.nc", "velocity_mm_per_year")


if __name__ == "__main__":
    main()
