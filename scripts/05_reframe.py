#!/usr/bin/env python3
"""Step 05: reframe Sentinel-1 scenes to the AOI and checkpoint scene metadata."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from workflow import StageContext, build_stack, dask_client, load_aoi, log, parser, save_scenes


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    ctx.require(ctx.checkpoint_dir / "scenes_initial.pkl")
    sbas = build_stack(ctx, prefer_reframed=False)
    aoi = load_aoi(ctx)
    jobs = max(1, min(4, ctx.ncpus // 4))
    log(f"[{ctx.sub}] Computing reframe with n_jobs={jobs}")
    with dask_client(ctx):
        sbas.compute_reframe(aoi, n_jobs=jobs)
    save_scenes(ctx, sbas, reframed=True)


if __name__ == "__main__":
    main()
