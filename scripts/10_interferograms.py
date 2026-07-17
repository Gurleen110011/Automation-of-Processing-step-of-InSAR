#!/usr/bin/env python3
"""Step 10: form multilooked interferograms, coherence and Goldstein-filtered phase."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import pandas as pd
from joblib import parallel_backend

from workflow import (
    StageContext,
    build_stack,
    dask_client,
    log,
    parser,
    safe_name,
    save_pair_stack,
)


def main() -> None:
    args = parser(__doc__).parse_args()
    ctx = StageContext.from_file(args.config)
    pairs_path = ctx.checkpoint_dir / "baseline_pairs_limited.pkl"
    ctx.require(pairs_path)
    pairs = pd.read_pickle(pairs_path)
    sbas = build_stack(ctx)
    jobs = max(1, min(2, ctx.ncpus // 8))

    with dask_client(ctx):
        topo = sbas.get_topo()
        log(f"[{ctx.sub}] Computing interferograms/coherence")
        with parallel_backend("threading", n_jobs=jobs):
            data = sbas.open_data()
            try:
                _ = sbas.sync_stack(data, "slc")
            except BlockingIOError as exc:
                raise RuntimeError(
                    "NetCDF/HDF5 locking failed while writing the SLC stack. "
                    "Keep safe_hdf5_io enabled and remove incomplete stage outputs before retrying."
                ) from exc
            intensity = sbas.multilooking(
                data.real ** 2 + data.imag ** 2,
                wavelength=30,
                coarsen=(4, 20),
            )
            phase = sbas.phasediff(pairs, data, topo)
            phase_mlook = sbas.multilooking(phase, wavelength=30, coarsen=(4, 20))
            coherence = sbas.correlation(phase_mlook, intensity)
            filtered = sbas.goldstein(phase_mlook, coherence, 16)
            interferogram = sbas.interferogram(filtered)

        interferogram = interferogram.persist()
        coherence = coherence.persist()
        from pygmtsar import tqdm_dask
        tqdm_dask([interferogram, coherence], desc="Persist IFG/coherence")
        save_pair_stack(interferogram, ctx.workdir / "Ifg", "ifg", "interferogram")
        save_pair_stack(coherence, ctx.workdir / "Coh", "coh", "coherence")
        pair_ids = [safe_name(value) for value in interferogram.pair.values]
        mean_corr = coherence.mean(dim=["y", "x"]).compute().values
        pd.DataFrame({"pair": pair_ids, "mean_corr": mean_corr}).to_csv(
            ctx.workdir / "mean_coherence.csv", index=False
        )


if __name__ == "__main__":
    main()
