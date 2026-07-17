#!/usr/bin/env python3
"""Step 07: align all reframed SLC scenes to the configured reference scene."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from workflow import StageContext, build_stack, dask_client, log, parser


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    ctx.require(ctx.checkpoint_dir / "dem_normalized.nc")
    sbas = build_stack(ctx)
    jobs = max(1, min(4, ctx.ncpus // 4))
    log(f"[{ctx.sub}] Computing alignment with n_jobs={jobs}")
    with dask_client(ctx):
        sbas.compute_align(n_jobs=jobs)


if __name__ == "__main__":
    main()
