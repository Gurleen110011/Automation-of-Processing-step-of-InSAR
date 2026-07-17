# Single-runner PyGMTSAR workflow

This package uses **one shell runner** and one flat numbered sequence of executable Python scripts. There is no separate outer wrapper and no second PyGMTSAR runner copied into each AOI directory.

## Normal command

Edit `config/workflow.env`, then run:

```bash
chmod +x run_all.sh
./run_all.sh all
```

`run_all.sh all` executes scripts `01` through `17` in numerical order. For scientific steps `04` through `16`, it runs the current step for every selected AOI before moving to the next step.

For example, the order is:

```text
04_scan_scenes.py for A1, A2, ... C10
05_reframe.py for A1, A2, ... C10
06_load_dem.py for A1, A2, ... C10
...
16_finalize.py for A1, A2, ... C10
17_collect_results.py
```

## Complete script order

| No. | Script | Function |
|---:|---|---|
| 01 | `01_validate.py` | Validate paths, AOIs, DEM files and optional runtime dependencies |
| 02 | `02_unzip_slcs.py` | Extract Sentinel-1 ZIP products into `.SAFE` directories |
| 03 | `03_prepare_aois.py` | Create AOI input directories and per-AOI `config.json` files |
| 04 | `04_scan_scenes.py` | Scan SLC scenes, check/download orbits and initialize the stack |
| 05 | `05_reframe.py` | Reframe scenes to each AOI |
| 06 | `06_load_dem.py` | Normalize and load the AOI DEM |
| 07 | `07_align.py` | Align scenes to the reference acquisition |
| 08 | `08_geocode.py` | Compute radar/geographic lookup grids |
| 09 | `09_baseline_pairs.py` | Build and save the limited small-baseline network |
| 10 | `10_interferograms.py` | Generate interferograms and coherence |
| 11 | `11_unwrap.py` | Unwrap phase using SNAPHU |
| 12 | `12_stratified_correction.py` | Remove topographic/incidence-correlated trends |
| 13 | `13_sbas_inversion.py` | Run SBAS inversion and calculate radar-coordinate velocity |
| 14 | `14_geocode_products.py` | Geocode displacement and velocity products |
| 15 | `15_export_results.py` | Export GeoTIFF velocity and displacement time slices |
| 16 | `16_finalize.py` | Verify expected outputs and write the AOI summary |
| 17 | `17_collect_results.py` | Copy selected results to the configured results directory |

The `scripts/lib/workflow.py` file is a shared Python library used by the numbered scripts. It is not a separately executed workflow step.

## AOI selection

All AOIs from A1 through C10:

```bash
AOI_GROUPS="ABC"
AOI_INDICES="1-10"
AOI_LIST=""
```

Specific AOIs only:

```bash
AOI_LIST="A1,A2,B4,C10"
```

An explicit `AOI_LIST` overrides `AOI_GROUPS` and `AOI_INDICES`.

## Running multiple AOIs

The default processes one AOI at a time within each scientific step:

```bash
MAX_PARALLEL_AOIS=1
```

Two AOIs simultaneously:

```bash
MAX_PARALLEL_AOIS=2
```

Approximate maximum resource use is:

```text
CPUs = MAX_PARALLEL_AOIS x NCPUS_PER_AOI
RAM  = MAX_PARALLEL_AOIS x MEMORY_GB_PER_AOI
```

Start with `MAX_PARALLEL_AOIS=1`, especially for NetCDF/HDF5-heavy steps.

## Checkpoints and restarting

Each scientific step writes a success or failure marker under:

```text
ProcessingRuns/<MASTER_NAME>/<AOI>/.stage_markers/
```

A successful step is skipped during later runs. Logs are saved under:

```text
ProcessingRuns/<MASTER_NAME>/<AOI>/logs/
ProcessingRuns/<MASTER_NAME>/<AOI>/processing_<AOI>.log
```

Run one numbered step:

```bash
./run_all.sh step 05
```

Restart from step 10 through collection:

```bash
./run_all.sh from 10
```

Run a limited range:

```bash
./run_all.sh range 04 08
```

Force the selected scientific step and invalidate its downstream markers:

```bash
FORCE_STEPS=1 ./run_all.sh from 10
```

List the sequence:

```bash
./run_all.sh list
```

## Generated AOI structure

After step 03, each AOI directory looks like:

```text
ProcessingRuns/LocalProcessing/A1/
├── Inputs/
│   ├── *.SAFE/
│   ├── *.EOF
│   └── dem.nc
├── config.json
├── logs/
├── .stage_markers/
└── Outputs_A1/
```

The executable scripts remain centrally located in `scripts/`; they are not duplicated into each AOI.

## Dependencies

The scientific steps require a Linux/WSL/HPC environment with PyGMTSAR and its Python dependencies installed. Phase unwrapping also requires `snaphu` on `PATH`.

Set this in the configuration to verify runtime dependencies during step 01:

```bash
CHECK_RUNTIME_DEPS=1
```
