#!/usr/bin/env python3
"""Step 13: invert corrected pair phases into radar-coordinate displacement and velocity."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from workflow import (
    StageContext,
    build_stack,
    dask_client,
    load_pair_stack,
    log,
    parser,
    save_nc,
)


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    phase = load_pair_stack(ctx.workdir / "Corrected", "corrected", ("corrected_phase", "phase"))
    coherence = load_pair_stack(ctx.workdir / "Coh", "coh", ("coherence", "correlation", "corr"))
    threshold = float(ctx.config.get("corr_limit", 0.2))
    required = {"pair", "y", "x"}
    missing = required.difference(phase.dims)
    if missing:
        raise RuntimeError(f"Corrected phase is missing dimensions {sorted(missing)}")
    phase = phase.transpose("pair", "y", "x").chunk(
        {
            "pair": -1,
            "y": min(256, phase.sizes["y"]),
            "x": min(256, phase.sizes["x"]),
        }
    )
    sbas = build_stack(ctx)
    with dask_client(ctx):
        mean_coherence = coherence.mean(dim="pair", skipna=True).persist()
        accepted = (mean_coherence >= threshold).sum().compute()
        log(f"[{ctx.sub}] Accepted pixels={int(accepted)} / {mean_coherence.size}")
        phase_masked = phase.where(mean_coherence >= threshold).compute()
        phase_masked = phase_masked.chunk(
            {
                "pair": phase_masked.sizes["pair"],
                "y": min(256, phase_masked.sizes["y"]),
                "x": min(256, phase_masked.sizes["x"]),
            }
        )
        log(f"[{ctx.sub}] Running SBAS least-squares inversion")
        displacement_phase = sbas.lstsq(phase_masked, weight=None).compute()
        displacement = sbas.los_displacement_mm(displacement_phase)
        if hasattr(displacement.data, "compute"):
            displacement = displacement.compute()
        velocity = sbas.velocity(displacement)
        if hasattr(velocity.data, "compute"):
            velocity = velocity.compute()
        save_nc(displacement.rename("displacement_mm"), ctx.checkpoint_dir / "displacement_radar.nc", "displacement_mm")
        save_nc(velocity.rename("velocity_mm_per_year"), ctx.checkpoint_dir / "velocity_radar.nc", "velocity_mm_per_year")


if __name__ == "__main__":
    main()
