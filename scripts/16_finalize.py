#!/usr/bin/env python3
"""Step 16: verify expected final outputs and write a compact completion summary."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import json
from datetime import datetime, timezone

from workflow import StageContext, parser


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    expected = [
        ctx.workdir / "LOS_Velocity" / "LOS_Velocity_mm_per_yr.tif",
        ctx.workdir / "InSARExplorer" / "LOS_Velocity.tif",
        ctx.workdir / "InSARExplorer" / "reference_point.txt",
        ctx.workdir / "mean_coherence.csv",
        ctx.workdir / "baseline_pairs_limited.csv",
    ]
    ctx.require(*expected)
    summary = {
        "aoi": ctx.sub,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "workdir": str(ctx.workdir),
        "outputs": [str(path) for path in expected],
    }
    output = ctx.base_dir / "workflow_summary.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[{ctx.sub}] Workflow summary: {output}", flush=True)


if __name__ == "__main__":
    main()
