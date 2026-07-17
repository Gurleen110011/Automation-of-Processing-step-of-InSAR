#!/usr/bin/env python3
"""Step 11: unwrap filtered interferograms with SNAPHU and checkpoint phase per pair."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from workflow import (
    StageContext,
    build_stack,
    dask_client,
    load_pair_stack,
    log,
    parser,
    save_pair_stack,
)


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    if shutil.which("snaphu") is None:
        raise RuntimeError("The external 'snaphu' executable is not available on PATH")
    interferogram = load_pair_stack(ctx.workdir / "Ifg", "ifg", ("interferogram", "phase"))
    coherence = load_pair_stack(ctx.workdir / "Coh", "coh", ("coherence", "correlation", "corr"))
    threshold = float(ctx.config.get("corr_limit", 0.2))
    sbas = build_stack(ctx)
    with dask_client(ctx):
        mask = coherence >= threshold
        log(f"[{ctx.sub}] Running SNAPHU with coherence threshold={threshold}")
        unwrap = sbas.unwrap_snaphu(interferogram, coherence.where(mask)).persist()
        from pygmtsar import tqdm_dask
        tqdm_dask(unwrap, desc="SNAPHU unwrapping")
        phase = unwrap.phase if hasattr(unwrap, "phase") else unwrap
        save_pair_stack(phase, ctx.workdir / "Unwrapped", "unwrap", "phase")
        try:
            sbas.plot_phases(
                phase.where(mask).isel(pair=slice(0, 3)),
                cols=3,
                size=3,
                caption="Unwrapped Phase [rad] (Masked)",
                quantile=[0.01, 0.99],
            )
            plt.savefig(
                ctx.workdir / "Unwrapped_Phase_subset_masked.jpg",
                dpi=150,
                bbox_inches="tight",
            )
            plt.close("all")
        except Exception as exc:
            log(f"[{ctx.sub}] Skipping unwrap preview plot: {exc}")


if __name__ == "__main__":
    main()
