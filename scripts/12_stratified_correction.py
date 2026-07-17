#!/usr/bin/env python3
"""Step 12: regress topographic/incidence trends and save corrected unwrapped phase."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import xarray as xr

from workflow import (
    StageContext,
    build_stack,
    dask_client,
    load_pair_stack,
    log,
    parser,
    regrid_to_target,
    save_pair_stack,
)


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    phase = load_pair_stack(ctx.workdir / "Unwrapped", "unwrap", ("phase",))
    coherence = load_pair_stack(ctx.workdir / "Coh", "coh", ("coherence", "correlation", "corr"))
    threshold = float(ctx.config.get("corr_limit", 0.2))
    sbas = build_stack(ctx)

    with dask_client(ctx):
        topo = sbas.get_topo()
        try:
            incidence = sbas.incidence_angle()
        except Exception:
            incidence = xr.full_like(topo, 0.45)
        target_y, target_x = phase["y"], phase["x"]
        topo_target = regrid_to_target(topo, target_y, target_x)
        incidence_target = regrid_to_target(incidence, target_y, target_x)
        yy_grid, xx_grid = xr.broadcast(topo_target, topo_target)
        regressors = [
            topo_target,
            topo_target * yy_grid,
            topo_target * xx_grid,
            topo_target * yy_grid * xx_grid,
            topo_target ** 2,
            (topo_target ** 2) * yy_grid,
            (topo_target ** 2) * xx_grid,
            (topo_target ** 2) * yy_grid * xx_grid,
            topo_target ** 3,
            (topo_target ** 3) * yy_grid,
            (topo_target ** 3) * xx_grid,
            (topo_target ** 3) * yy_grid * xx_grid,
            incidence_target,
            incidence_target * yy_grid,
            incidence_target * xx_grid,
            incidence_target * yy_grid * xx_grid,
            yy_grid,
            xx_grid,
            yy_grid ** 2,
            xx_grid ** 2,
            yy_grid * xx_grid,
            yy_grid ** 3,
            xx_grid ** 3,
            (yy_grid ** 2) * xx_grid,
            (xx_grid ** 2) * yy_grid,
        ]
        coherence_target = regrid_to_target(coherence, target_y, target_x)
        phase_masked = phase.where(coherence_target >= threshold)
        log(f"[{ctx.sub}] Running stratified regression")
        trend = sbas.regression(phase_masked, regressors, coherence_target)
        corrected = phase - trend
        save_pair_stack(trend, ctx.workdir / "Stratified", "trend", "trend")
        save_pair_stack(corrected, ctx.workdir / "Corrected", "corrected", "corrected_phase")


if __name__ == "__main__":
    main()
