#!/usr/bin/env python3
"""Step 09: create and checkpoint the limited small-baseline interferogram network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from workflow import StageContext, build_stack, log, parser


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    sbas = build_stack(ctx)
    days = int(ctx.config.get("basedays", 60))
    meters = int(ctx.config.get("basemeters", 250))
    limit = int(ctx.config.get("limit", 2))
    pairs = sbas.baseline_pairs(days=days, meters=meters)
    limited = pairs.groupby("ref", group_keys=False).head(limit).reset_index(drop=True)
    limited = limited.groupby("rep", group_keys=False).head(limit).reset_index(drop=True)
    log(f"[{ctx.sub}] Original pairs={len(pairs)}; limited pairs={len(limited)}")
    if limited.empty:
        raise RuntimeError("The configured baseline constraints produced no pairs")
    limited.to_pickle(ctx.checkpoint_dir / "baseline_pairs_limited.pkl")
    limited.to_csv(ctx.workdir / "baseline_pairs_limited.csv", index=False)
    with plt.rc_context({"figure.dpi": 150}):
        sbas.plot_baseline(limited)
        plt.title(f"Baseline Network limit={limit}")
        plt.grid(True, linestyle="--", alpha=0.5)
        plt.savefig(ctx.workdir / "baseline_network.png", bbox_inches="tight")
        plt.close("all")


if __name__ == "__main__":
    main()
