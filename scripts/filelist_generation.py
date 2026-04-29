#!/usr/bin/env python3
import argparse
import re
import calendar
from pathlib import Path
from datetime import datetime

VARS = ["MSLP", "Z850", "RV850", "R850", "U10", "V10"]

DATE_PATTERNS = [
    (r'\d{8}', '%Y%m%d'),
    (r'\d{6}', '%Y%m'),
    (r'\d{4}', '%Y'),
]

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
    for pattern, fmt in DATE_PATTERNS:
        match = re.search(pattern, Path(filename).name)
        if match:
            try:
                return datetime.strptime(match.group(), fmt), fmt
            except ValueError:
                continue
    return None, None

def get_files_in_range(directory, start_dt, end_dt):
    d = Path(directory)
    if not d.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    files = {}
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        date, fmt = extract_date(f.name)
        if date is None:
            continue
        if start_dt <= date <= end_dt:
            files[date] = (str(f), fmt)
    return files

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",  required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()

    config   = load_config(args.config)
    dataname = config["DATANAME"]
    workdir  = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    start_dt = datetime.strptime(config["START"], "%Y%m")
    end_ym   = datetime.strptime(config["END"], "%Y%m")
    last_day = calendar.monthrange(end_ym.year, end_ym.month)[1]
    end_dt   = end_ym.replace(day=last_day)

    var_files = {}
    for var in VARS:
        dir_key = f"{var}_DIR"
        if dir_key not in config or not config[dir_key]:
            print(f"  Skipping {var}: no directory specified")
            continue
        print(f"  Scanning {var}: {config[dir_key]}")
        var_files[var] = get_files_in_range(config[dir_key], start_dt, end_dt)
        print(f"    → {len(var_files[var])} files found")

    zs_dir = Path(config["ZS_DIR"])
    if zs_dir.is_file():
        zs_invariant = str(zs_dir)
        get_zs = lambda date: zs_invariant
        zs_dates = None
    elif zs_dir.is_dir():
        zs_files = get_files_in_range(str(zs_dir), start_dt, end_dt)
        get_zs = lambda date: zs_files.get(date, (None,))[0]
        zs_dates = set(zs_files.keys())
    else:
        raise FileNotFoundError(f"ZS_DIR not found: {zs_dir}")

    date_sets = [set(v.keys()) for v in var_files.values()]
    if zs_dates is not None:
        date_sets.append(zs_dates)

    common_dates = sorted(set.intersection(*date_sets))
    if not common_dates:
        print("ERROR: No common dates found across all variables")
        return

    _, date_fmt = var_files["MSLP"][common_dates[0]]
    date_str    = lambda d: d.strftime(date_fmt)

    active_vars = [v for v in VARS if v in var_files]

    with open(workdir / f"{dataname}seed.input.txt", "w") as f:
        for date in common_dates:
            line = ";".join(
                [var_files[var][date][0] for var in active_vars] + [get_zs(date)]
            ) + "\n"
            f.write(line)

    for hemi in ("NH", "SH"):
        with open(workdir / f"{dataname}seed.DNoutput.{hemi}.txt", "w") as f:
            for date in common_dates:
                f.write(f"{workdir}/{dataname}_{date_str(date)}_{hemi}seed.txt\n")

    print(f"\n[DONE] {dataname}: {len(common_dates)} time steps")
    print(f"       {date_str(common_dates[0])} ~ {date_str(common_dates[-1])}")

if __name__ == "__main__":
    main()