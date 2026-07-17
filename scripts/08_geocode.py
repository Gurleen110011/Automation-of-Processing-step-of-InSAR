#!/usr/bin/env python3
"""Step 08: compute radar-to-geographic and geographic-to-radar lookup grids."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from joblib import parallel_backend

from workflow import StageContext, build_stack, dask_client, log, parser


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    sbas = build_stack(ctx)
    jobs = max(1, min(2, ctx.ncpus // 8))
    log(f"[{ctx.sub}] Computing geocode lookup grids with n_jobs={jobs}")
    with dask_client(ctx), parallel_backend("threading", n_jobs=jobs):
        sbas.compute_geocode()


if __name__ == "__main__":
    main()
