#!/usr/bin/env python3
"""Shared AOI selection, staging, checkpoint, and PyGMTSAR utilities."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Iterable

AOI_PATTERN = re.compile(r"^([A-Ca-c])(\d+)$")
SUBSWATH_BY_GROUP = {"A": 1, "B": 2, "C": 3}


def parse_indices(value: str) -> list[int]:
    """Parse values such as ``1-10`` or ``1,2,5-7,10``."""
    numbers: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"Invalid descending index range: {token}")
            numbers.extend(range(start, end + 1))
        else:
            numbers.append(int(token))
    if not numbers:
        raise ValueError("No AOI indices were selected.")
    if any(number < 1 for number in numbers):
        raise ValueError("AOI indices must be positive integers.")
    return sorted(set(numbers))


def normalize_aoi(value: str) -> str:
    match = AOI_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(
            f"Invalid AOI '{value}'. Expected A1, B7, C10, and so on."
        )
    group, index = match.groups()
    return f"{group.upper()}{int(index)}"


def resolve_aois(
    explicit_aois: str | None,
    groups: str,
    indices: str,
) -> list[str]:
    """Resolve either an explicit AOI list or a groups/index cartesian product."""
    if explicit_aois and explicit_aois.strip():
        raw = explicit_aois.replace(" ", ",").split(",")
        aois = [normalize_aoi(value) for value in raw if value.strip()]
    else:
        normalized_groups = []
        for group in groups.replace(",", "").replace(" ", "").upper():
            if group not in SUBSWATH_BY_GROUP:
                raise ValueError(
                    f"Unsupported group '{group}'. Only A, B and C are supported."
                )
            if group not in normalized_groups:
                normalized_groups.append(group)
        if not normalized_groups:
            raise ValueError("No AOI groups were selected.")
        aois = [
            f"{group}{index}"
            for group in normalized_groups
            for index in parse_indices(indices)
        ]
    return sorted(
        set(aois),
        key=lambda item: ("ABC".index(item[0]), int(item[1:])),
    )


def read_geojson(aoi: str, aoi_root: Path, inline_file: Path | None = None) -> dict:
    if inline_file:
        if not inline_file.exists():
            raise FileNotFoundError(f"AOI inline mapping not found: {inline_file}")
        mapping = json.loads(inline_file.read_text(encoding="utf-8"))
        if aoi in mapping:
            return mapping[aoi]

    for extension in (".geojson", ".json"):
        candidate = aoi_root / f"{aoi}{extension}"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))

    raise FileNotFoundError(
        f"AOI GeoJSON not found for {aoi}. Expected {aoi_root / (aoi + '.geojson')}"
    )


def hardlink_or_copy(src: Path, dst: Path, mode: str = "hardlink") -> None:
    """Stage a path by hardlink, symlink, or copy, with safe fallbacks."""
    src = src.expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() or dst.is_symlink():
        return

    if mode == "copy":
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return

    if mode == "symlink":
        try:
            dst.symlink_to(src, target_is_directory=src.is_dir())
            return
        except OSError as exc:
            print(f"WARNING: symlink failed for {src}: {exc}; copying instead.")
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return

    try:
        if src.is_file():
            os.link(src, dst)
            return

        for root, directories, files in os.walk(src):
            root_path = Path(root)
            relative = root_path.relative_to(src)
            target_root = dst / relative
            target_root.mkdir(parents=True, exist_ok=True)
            for directory in directories:
                (target_root / directory).mkdir(exist_ok=True)
            for filename in files:
                source_file = root_path / filename
                target_file = target_root / filename
                if not target_file.exists():
                    os.link(source_file, target_file)
    except OSError as exc:
        print(f"WARNING: hardlink failed for {src}: {exc}; copying instead.")
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def add_aoi_selection_arguments(parser) -> None:
    parser.add_argument(
        "--aois",
        default="",
        help="Explicit AOIs, e.g. A1,A2,B4,C10. Overrides --groups/--indices.",
    )
    parser.add_argument(
        "--groups",
        default="ABC",
        help="AOI groups used when --aois is empty.",
    )
    parser.add_argument(
        "--indices",
        default="1-10",
        help="AOI indices used when --aois is empty, e.g. 1-10 or 1,3,5-8.",
    )


def selected_aois(args) -> list[str]:
    return resolve_aois(args.aois, args.groups, args.indices)


def summarize_paths(paths: Iterable[Path]) -> str:
    return "\n".join(f"  - {path}" for path in paths)

import argparse
import gc
import json
import os
import shutil
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

warnings.filterwarnings("ignore")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")


def log(message: str) -> None:
    print(message, flush=True)


@dataclass(frozen=True)
class StageContext:
    config_path: Path
    config: dict
    sub: str
    base_dir: Path
    workdir: Path
    datadir: Path
    dem_path: Path
    checkpoint_dir: Path
    marker_dir: Path
    ncpus: int
    memory_gb: int
    workers: int
    safe_hdf5_io: bool

    @classmethod
    def from_file(cls, config_path: str | Path) -> "StageContext":
        path = Path(config_path).expanduser().resolve()
        config = json.loads(path.read_text(encoding="utf-8"))
        base_dir = Path(config.get("base_dir", path.parent)).expanduser().resolve()
        sub = str(config["sub"])
        workdir = Path(config.get("workdir", base_dir / f"Outputs_{sub}")).expanduser().resolve()
        datadir = Path(config.get("datadir", base_dir / "Inputs")).expanduser().resolve()
        dem_path = Path(config.get("dem", datadir / "dem.nc")).expanduser().resolve()
        checkpoint_dir = workdir / "Checkpoints"
        marker_dir = base_dir / ".stage_markers"
        ncpus = int(os.environ.get("PBS_NCPUS", config.get("ncpus", 4)))
        memory_gb = int(config.get("memory_gb", 12))
        workers = int(config.get("dask_workers", min(ncpus, 24)))
        safe_hdf5_io = bool(config.get("safe_hdf5_io", True))
        workdir.mkdir(parents=True, exist_ok=True)
        datadir.mkdir(parents=True, exist_ok=True)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        marker_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            config_path=path,
            config=config,
            sub=sub,
            base_dir=base_dir,
            workdir=workdir,
            datadir=datadir,
            dem_path=dem_path,
            checkpoint_dir=checkpoint_dir,
            marker_dir=marker_dir,
            ncpus=ncpus,
            memory_gb=memory_gb,
            workers=workers,
            safe_hdf5_io=safe_hdf5_io,
        )

    def require(self, *paths: Path) -> None:
        missing = [path for path in paths if not path.exists()]
        if missing:
            lines = "\n".join(f"  - {path}" for path in missing)
            raise FileNotFoundError(
                f"Required checkpoint(s) are missing for {self.sub}:\n{lines}\n"
                "Run the preceding stage(s) first."
            )


def parser(description: str) -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=description)
    value.add_argument("--config", required=True, type=Path)
    return value


def safe_name(value) -> str:
    return str(value).replace(" ", "_").replace(":", "-").replace("/", "-")


@contextmanager
def dask_client(ctx: StageContext) -> Iterator[object]:
    """Start one safe nanny worker by default, or configured workers when enabled."""
    from dask.distributed import Client, LocalCluster

    requested = max(1, min(ctx.workers, ctx.ncpus))
    workers = 1 if ctx.safe_hdf5_io else requested
    mem_per_worker = max(2, int(ctx.memory_gb / workers))
    cluster = LocalCluster(
        n_workers=workers,
        threads_per_worker=1,
        processes=True,
        memory_limit=f"{mem_per_worker}GB",
        dashboard_address=None,
    )
    client = Client(cluster)
    log(
        "Dask cluster: "
        f"workers={workers}, threads_per_worker=1, "
        f"memory_per_worker={mem_per_worker}GB"
    )
    try:
        yield client
    finally:
        client.close()
        cluster.close()
        gc.collect()


def load_aoi(ctx: StageContext):
    import geopandas as gpd

    geojson = ctx.config.get("aoi_geojson")
    if not geojson or "features" not in geojson:
        raise RuntimeError("config.json does not contain a valid aoi_geojson FeatureCollection")
    return gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")


def scene_checkpoint(ctx: StageContext, reframed: bool = True) -> Path:
    reframed_path = ctx.checkpoint_dir / "scenes_reframed.pkl"
    raw_path = ctx.checkpoint_dir / "scenes_initial.pkl"
    if reframed and reframed_path.exists():
        return reframed_path
    return raw_path


def save_scenes(ctx: StageContext, sbas, reframed: bool) -> Path:
    path = ctx.checkpoint_dir / ("scenes_reframed.pkl" if reframed else "scenes_initial.pkl")
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = sbas.to_dataframe()
    dataframe.to_pickle(path)
    log(f"Saved scene metadata: {path}")
    return path


def build_stack(ctx: StageContext, prefer_reframed: bool = True):
    """Reopen a staged PyGMTSAR stack without deleting its existing outputs.

    PyGMTSAR's ``Stack`` constructor only accepts a brand-new base directory;
    it raises when the directory already exists unless ``drop_if_exists=True``.
    The numbered workflow intentionally starts a fresh Python process for each
    stage, so later stages must reconnect to the existing AOI work directory
    rather than recreate or delete it.

    We initialize ``Stack`` in a disposable directory, then point the instance
    at the existing work directory and restore the checkpointed scene table,
    reference date, and generated DEM path.
    """
    import tempfile

    import pandas as pd
    from pygmtsar import Stack

    path = scene_checkpoint(ctx, reframed=prefer_reframed)
    ctx.require(path)
    scenes = pd.read_pickle(path)
    reference = ctx.config.get("reference", "2025-01-11")

    ctx.workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"pygmtsar_{ctx.sub}_") as temp_root:
        bootstrap_dir = Path(temp_root) / "stack"
        sbas = Stack(str(bootstrap_dir), drop_if_exists=False)

    # Stack.__init__ only creates/assigns basedir. Repoint it to the persistent
    # AOI directory after the disposable initialization directory is removed.
    sbas.basedir = str(ctx.workdir)
    sbas.set_scenes(scenes).set_reference(reference)

    # load_dem() writes this canonical file. A newly reconstructed Stack needs
    # the filename restored explicitly before alignment/geocoding/topography.
    generated_dem = ctx.workdir / "DEM_WGS84.nc"
    if generated_dem.is_file():
        sbas.set_dem(str(generated_dem))

    return sbas


def select_dem_variable(dataset):
    if "elevation" in dataset.data_vars:
        return dataset["elevation"]
    candidates = [
        name for name, variable in dataset.data_vars.items() if len(variable.dims) == 2
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "Could not identify one 2D DEM variable. "
            f"Available variables: {list(dataset.data_vars)}"
        )
    return dataset[candidates[0]]


def normalize_dem(dem):
    rename_map = {}
    if "y" in dem.dims or "y" in dem.coords:
        rename_map["y"] = "lat"
    if "x" in dem.dims or "x" in dem.coords:
        rename_map["x"] = "lon"
    if rename_map:
        dem = dem.rename(rename_map)
    if "lat" not in dem.coords or "lon" not in dem.coords:
        raise RuntimeError(
            "DEM must contain latitude/longitude coordinates. "
            f"Found dims={dem.dims}, coords={list(dem.coords)}"
        )
    if dem.sizes["lat"] > 1 and float(dem["lat"].isel(lat=0)) > float(dem["lat"].isel(lat=-1)):
        dem = dem.sortby("lat")
    if dem.sizes["lon"] > 1 and float(dem["lon"].isel(lon=0)) > float(dem["lon"].isel(lon=-1)):
        dem = dem.sortby("lon")
    return dem.transpose("lat", "lon")


def save_nc(dataarray_or_dataset, path: Path, varname: str) -> None:
    import xarray as xr

    path.parent.mkdir(parents=True, exist_ok=True)
    obj = dataarray_or_dataset
    if isinstance(obj, xr.DataArray):
        obj = obj.rename(obj.name or varname).to_dataset()
    elif not isinstance(obj, xr.Dataset):
        raise TypeError(f"Expected xarray DataArray/Dataset, got {type(obj)}")
    obj = obj.compute()
    errors: list[str] = []
    for engine in ("netcdf4", "h5netcdf", "scipy"):
        try:
            obj.to_netcdf(path, engine=engine)
            log(f"Saved {path} using {engine}")
            return
        except Exception as exc:  # pragma: no cover - depends on installed engines
            errors.append(f"{engine}: {exc}")
    raise RuntimeError(f"Could not save NetCDF {path}: {'; '.join(errors)}")


def choose_dataarray(dataset, preferred: tuple[str, ...]):
    import xarray as xr

    if isinstance(dataset, xr.DataArray):
        return dataset
    for name in preferred:
        if name in dataset.data_vars:
            return dataset[name]
    if len(dataset.data_vars) == 1:
        return dataset[next(iter(dataset.data_vars))]
    raise RuntimeError(
        f"Could not choose variable from {list(dataset.data_vars)}; preferred={preferred}"
    )


def save_pair_stack(data, directory: Path, prefix: str, varname: str, overwrite: bool = True) -> None:
    """Save a pair stack as one NetCDF per pair while preserving the pair dimension."""
    directory.mkdir(parents=True, exist_ok=True)
    if "pair" not in data.dims:
        raise RuntimeError(f"Pair stack lacks 'pair' dimension: {data.dims}")
    if overwrite:
        for old in directory.glob(f"{prefix}_*.nc"):
            old.unlink()
    for index in range(data.sizes["pair"]):
        pair_label = safe_name(data["pair"].values[index])
        path = directory / f"{prefix}_{index:03d}_{pair_label}.nc"
        if path.exists() and not overwrite:
            continue
        subset = data.isel(pair=slice(index, index + 1))
        if hasattr(subset, "data") and hasattr(subset.data, "compute"):
            subset = subset.compute()
        save_nc(subset.rename(varname), path, varname)


def load_pair_stack(directory: Path, prefix: str, preferred: tuple[str, ...]):
    import xarray as xr

    files = sorted(directory.glob(f"{prefix}_*.nc"))
    if not files:
        raise FileNotFoundError(f"No pair checkpoints found: {directory}/{prefix}_*.nc")
    arrays = []
    for path in files:
        dataset = xr.open_dataset(path, chunks={})
        array = choose_dataarray(dataset, preferred)
        if "pair" not in array.dims:
            if "pair" in array.coords:
                array = array.expand_dims(pair=[array.coords["pair"].item()])
            else:
                array = array.expand_dims(pair=[path.stem])
        arrays.append(array)
    return xr.concat(arrays, dim="pair")


def regrid_to_target(data, target_y, target_x):
    import numpy as np
    import xarray as xr

    if "y" in data.dims and "x" in data.dims:
        same_shape = data.sizes["y"] == target_y.size and data.sizes["x"] == target_x.size
        if same_shape and np.allclose(data["y"].values, target_y.values) and np.allclose(data["x"].values, target_x.values):
            return data
    kwargs = {}
    if "y" in data.dims:
        kwargs["y"] = target_y
    if "x" in data.dims:
        kwargs["x"] = target_x
    if kwargs:
        try:
            return data.interp(method="linear", **kwargs)
        except Exception:
            pass
    template = xr.DataArray(
        np.zeros((target_y.size, target_x.size)),
        dims=("y", "x"),
        coords={"y": target_y, "x": target_x},
    )
    return data.reindex_like(template, method="nearest")


def export_raster(data, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(data.data, "compute"):
        data = data.compute()
    data.rio.to_raster(output, driver="GTiff")
    log(f"Saved raster: {output}")


def find_reference_point(displacement, output_dir: Path) -> None:
    import numpy as np

    first_dim = "date" if "date" in displacement.dims else "pair"
    first_map = displacement.isel({first_dim: 0})
    if hasattr(first_map.data, "compute"):
        first_map = first_map.compute()
    y_ref, x_ref = np.where(np.isclose(first_map.values, 0, atol=1e-6))
    output = output_dir / "reference_point.txt"
    if len(y_ref):
        y_coord = displacement["y"].values[y_ref[0]]
        x_coord = displacement["x"].values[x_ref[0]]
        output.write_text(f"lat: {y_coord}\nlon: {x_coord}\n", encoding="utf-8")
        log(f"Reference point: y={y_coord}, x={x_coord}")
    else:
        output.write_text("lat: None\nlon: None\n", encoding="utf-8")
        log("Reference point not found as an exact zero pixel.")


def clear_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)