#!/usr/bin/env python3
import argparse
import re
import shutil
import calendar
import subprocess
import xarray as xr
from pathlib import Path
from datetime import datetime

def load_config(path):
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            config[key.strip()] = val.strip().strip('"')
    return config

def extract_date(filename):
    for pattern in [r'\d{8}', r'\d{6}', r'\d{4}']:
        m = re.search(pattern, Path(filename).name)
        if m:
            return m.group()
    return None

def in_range(filename, start_dt, end_dt):
    date_str = extract_date(filename)
    if date_str is None:
        return False
    for fmt in ['%Y%m%d', '%Y%m', '%Y']:
        try:
            date = datetime.strptime(date_str, fmt)
            return start_dt <= date <= end_dt
        except ValueError:
            continue
    return False

VARS = ["MSLP", "Z850", "Z300", "Z500","R850", "U10", "V10"]
LEVEL_VARS = ["Z850", "Z300", "Z500"]

def extract_level_value(level_str):
    if not level_str:
        return None
    val = float("".join(ch for ch in level_str if ch.isdigit() or ch == "."))
    if "Pa" in level_str and "hPa" not in level_str:
        val /= 100.0
    return val

def select_level(infile, outfile, varname, level_val, lat_name, lon_name):
    ds = xr.open_dataset(infile)
    da = ds[varname]
    level_dim = next(
        (d for d in da.dims if d not in (lat_name, lon_name, "valid_time", "time")),
        None,
    )
    if level_dim is not None:
        da = da.sel({level_dim: level_val}, method="nearest").drop_vars(level_dim)
    extra_coords = [c for c in da.coords if c not in da.dims]
    da = da.drop_vars(extra_coords, errors="ignore")
    da.to_dataset(name=varname).to_netcdf(outfile)
    ds.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",  required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()

    config   = load_config(args.config)
    dataname = config["DATANAME"]
    workdir  = Path(args.workdir)

    start_dt = datetime.strptime(config["START"], "%Y%m")
    end_ym   = datetime.strptime(config["END"], "%Y%m")
    last_day = calendar.monthrange(end_ym.year, end_ym.month)[1]
    end_dt   = end_ym.replace(day=last_day)

    lat_name = config["LATNAME"]
    lon_name = config["LONNAME"]

    updated     = {}
    config_path = Path(args.config)
    updated_config = config_path.parent / f"{dataname}_updated.conf"

    for var in VARS:
        tres      = config.get(f"{var}_TRES", "6h")
        indir     = config.get(f"{var}_DIR",  "")
        level_str = config.get(f"{var}_LEVEL", "") if var in LEVEL_VARS else ""
        varname   = config.get(var, "")
        if not indir:
            continue

        needs_tres  = tres != "6h"
        needs_level = bool(level_str)
        if not needs_tres and not needs_level:
            continue

        level_val = extract_level_value(level_str) if needs_level else None
        outdir = workdir / f"preproc_{var}"
        outdir.mkdir(parents=True, exist_ok=True)

        steps = []
        if needs_tres:
            steps.append(f"{tres} → 6h")
        if needs_level:
            steps.append(f"select {level_str}")
        print(f"[START] Processing {var} ({', '.join(steps)})...")

        for f in sorted(Path(indir).glob("*.nc*")):
            if not in_range(f.name, start_dt, end_dt):
                continue
            out = outdir / f.name
            if out.exists():
                print(f"  exists: {out}")
                continue

            src = f
            tmp = None
            if needs_tres:
                tmp = outdir / f"tmp_{f.name}"
                subprocess.run(["cdo", "selhour,0,6,12,18", str(src), str(tmp)], check=True)
                src = tmp

            if needs_level:
                select_level(src, out, varname, level_val, lat_name, lon_name)
            else:
                shutil.copy(src, out)

            if tmp is not None:
                tmp.unlink()
            print(f"  processed: {out}")

        updated[f"{var}_DIR"] = str(outdir.resolve())
        if needs_level:
            updated[f"{var}_LEVEL"] = ""
        print(f"[DONE] {var} → {outdir}")

    shutil.copy(args.config, updated_config)
    if updated:
        with open(updated_config, "a") as f:
            for key, val in updated.items():
                f.write(f'{key}="{val}"\n')

    print(f"[DONE] Updated config: {updated_config}")

if __name__ == "__main__":
    main()