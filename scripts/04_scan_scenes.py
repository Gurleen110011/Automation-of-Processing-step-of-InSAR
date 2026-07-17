#!/usr/bin/env python3
"""Step 04: scan SLCs, acquire/check orbits, initialize the stack and plot scenes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from workflow import StageContext, load_aoi, log, parser, save_scenes


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    from pygmtsar import S1, Stack

    log(f"[{ctx.sub}] Scanning SLC scenes in {ctx.datadir}")
    slc_list = S1.scan_slc(str(ctx.datadir))
    if len(slc_list) == 0:
        raise RuntimeError(f"No valid Sentinel-1 SLC scenes found in {ctx.datadir}")
    log(f"[{ctx.sub}] Found {len(slc_list)} valid SLC scenes")
    if ctx.config.get("download_orbits", True):
        log(f"[{ctx.sub}] Downloading/checking precise orbits")
        S1.download_orbits(str(ctx.datadir), slc_list)

    subswath = int(ctx.config.get("subswath", 1))
    scenes = S1.scan_slc(str(ctx.datadir), subswath=subswath)
    reference = ctx.config.get("reference", "2025-01-11")
    sbas = (
        Stack(str(ctx.workdir), drop_if_exists=bool(ctx.config.get("drop_if_exists", True)))
        .set_scenes(scenes)
        .set_reference(reference)
    )
    save_scenes(ctx, sbas, reframed=False)
    log(str(sbas.to_dataframe()))

    aoi = load_aoi(ctx)
    try:
        with plt.rc_context({"figure.dpi": 150}):
            sbas.plot_scenes(AOI=aoi)
            plt.savefig(ctx.workdir / "scenes.png", dpi=150, bbox_inches="tight")
        log(f"[{ctx.sub}] Saved optional scene overview: {ctx.workdir / 'scenes.png'}")
    except Exception as exc:
        # Scene plotting is diagnostic only. Some PyGMTSAR/GeoPandas
        # combinations fail when an empty geometry subset is plotted,
        # producing: ValueError: aspect must be finite and positive.
        warning = (
            f"[{ctx.sub}] WARNING: scene overview plot was skipped: "
            f"{type(exc).__name__}: {exc}"
        )
        log(warning)
        (ctx.workdir / "scenes_plot_warning.txt").write_text(warning + "\n", encoding="utf-8")
    finally:
        plt.close("all")


if __name__ == "__main__":
    main()