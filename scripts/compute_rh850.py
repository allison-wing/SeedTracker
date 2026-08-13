#!/usr/bin/env python3
import argparse
import re
import shutil
import calendar
import numpy as np
import xarray as xr
from netCDF4 import Dataset
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


def compute_rh(temp, q, p):
    t_c = temp - 273.15
    es = 611.2 * np.exp((17.67 * t_c) / (t_c + 243.5))
    e = (q * p) / (0.622 + 0.378 * q)
    rh = 100.0 * e / es
    return np.clip(rh, 0.0, 100.0)


def in_range(filename, start_dt, end_dt):
    date_str = next(
        (m.group() for p in [r'\d{8}', r'\d{6}', r'\d{4}']
         for m in [re.search(p, Path(filename).name)] if m), None
    )
    if date_str is None:
        return False
    for fmt in ['%Y%m%d', '%Y%m', '%Y']:
        try:
            return start_dt <= datetime.strptime(date_str, fmt) <= end_dt
        except ValueError:
            continue
    return False


def extract_level(level_str):
    level_val = float("".join(filter(str.isdigit, level_str)))
    if "Pa" in level_str and "hPa" not in level_str:
        level_val /= 100.0
    return level_val


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    workdir = Path(args.workdir)
    outdir = workdir / "preproc_RH850"
    outdir.mkdir(parents=True, exist_ok=True)

    for tmp in outdir.glob("tmp_*.nc"):
        tmp.unlink()

    start_dt = datetime.strptime(config["START"], "%Y%m")
    end_ym = datetime.strptime(config["END"], "%Y%m")
    last_day = calendar.monthrange(end_ym.year, end_ym.month)[1]
    end_dt = end_ym.replace(day=last_day)

    t_level_str = config["T850_LEVEL"]
    q_level_str = config["Q850_LEVEL"]
    t_level = extract_level(t_level_str)
    q_level = extract_level(q_level_str)

    t_files = sorted(
        f for f in Path(config["T850_DIR"]).glob("*.nc*")
        if in_range(f.name, start_dt, end_dt)
    )

    for tfile in t_files:
        date_str = next(
            (m.group() for p in [r'\d{8}', r'\d{6}', r'\d{4}']
             for m in [re.search(p, tfile.name)] if m), None
        )
        if date_str is None:
            continue

        q_matches = sorted(Path(config["Q850_DIR"]).glob(f"*{date_str}*"))
        if not q_matches:
            print(f"WARNING: No Q file for {date_str}, skipping")
            continue

        outfile = outdir / f"rh850_{date_str}.nc"
        if outfile.exists():
            print(f"  exists: {outfile}")
            continue

        print(f"  processing: {date_str}")

        ds_t = xr.open_dataset(tfile)
        ds_q = xr.open_dataset(q_matches[0])

        temp = ds_t[config["T850"]].sel(pressure_level=t_level, method="nearest")
        q = ds_q[config["Q850"]].sel(pressure_level=q_level, method="nearest")

        lat_name = config["LATNAME"]
        lon_name = config["LONNAME"]
        lat = temp[lat_name].values
        lon = temp[lon_name].values
        pressure_pa = t_level * 100.0 if t_level_str.endswith("hPa") else t_level

        rh_data = xr.apply_ufunc(
            compute_rh,
            temp,
            q,
            kwargs={"p": pressure_pa},
            input_core_dims=[[lat_name, lon_name], [lat_name, lon_name]],
            output_core_dims=[[lat_name, lon_name]],
            vectorize=True,
        )
        rh_vals = rh_data.values
        ds_t.close()
        ds_q.close()

        with Dataset(str(tfile)) as src, Dataset(str(outfile), "w") as dst:
            dst.createDimension("time", None)
            dst.createDimension("lat", len(lat))
            dst.createDimension("lon", len(lon))

            time_name = "valid_time" if "valid_time" in src.variables else "time"
            t_src = src[time_name]
            t_dst = dst.createVariable("time", t_src.dtype, ("time",))
            t_dst.setncatts({k: t_src.getncattr(k) for k in t_src.ncattrs()})
            t_dst[:] = t_src[:]

            lat_dst = dst.createVariable("lat", "f4", ("lat",))
            lat_dst[:] = lat
            lon_dst = dst.createVariable("lon", "f4", ("lon",))
            lon_dst[:] = lon

            rh_dst = dst.createVariable("rh", "f4", ("time", "lat", "lon"), zlib=True)
            rh_dst.units = "%"
            rh_dst.long_name = "850hPa relative humidity"
            rh_dst[:] = rh_vals

        print(f"  computed: {outfile}")

    print(f"[DONE] RH850 written to {outdir}")

    updated_config = Path(args.config).parent / f"{config['DATANAME']}_updated.conf"
    if not updated_config.exists():
        shutil.copy(args.config, updated_config)
    with open(updated_config, "a") as f:
        f.write(f'\nRH850_DIR="{outdir.resolve()}"\n')
        f.write(f'RH850="rh"\n')
        f.write(f'RH850_LEVEL=""\n')
    print(f"[DONE] Updated config: {updated_config}")


if __name__ == "__main__":
    main()
