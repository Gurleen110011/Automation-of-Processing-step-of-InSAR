#!/usr/bin/env python3
"""Unzip Sentinel-1 products into .SAFE directories."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import argparse
import os
import shutil
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def unzip_one(zip_path: str) -> str:
    archive = Path(zip_path)
    try:
        with zipfile.ZipFile(archive) as handle:
            names = handle.namelist()
            safe_roots = sorted(
                {
                    name.split("/")[0]
                    for name in names
                    if name.split("/")[0].endswith(".SAFE")
                }
            )
            if safe_roots and all((archive.parent / root).exists() for root in safe_roots):
                return f"SKIP {archive.name}: SAFE already exists"

            temp_dir = archive.parent / f"{archive.stem}_extracting"
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True)
            handle.extractall(temp_dir)

            moved: list[str] = []
            for root in safe_roots:
                source = temp_dir / root
                destination = archive.parent / root
                if not destination.exists():
                    shutil.move(str(source), str(destination))
                    moved.append(destination.name)
            shutil.rmtree(temp_dir, ignore_errors=True)
        return f"OK {archive.name}: {', '.join(moved) if moved else 'extracted'}"
    except Exception as exc:  # noqa: BLE001 - report each archive independently.
        return f"ERR {archive.name}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Unzip Sentinel-1 SLC ZIP files.")
    parser.add_argument("--slc-source", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 4))
    args = parser.parse_args()

    source = args.slc_source.expanduser().resolve()
    archives = sorted(str(path) for path in source.glob("*.zip"))
    print(f"Found {len(archives)} ZIP file(s) in {source}")
    if not archives:
        return

    had_error = False
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(unzip_one, archive) for archive in archives]
        for future in as_completed(futures):
            result = future.result()
            print(result, flush=True)
            had_error = had_error or result.startswith("ERR ")
    if had_error:
        raise SystemExit("One or more ZIP files could not be extracted.")


if __name__ == "__main__":
    main()
