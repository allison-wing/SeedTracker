#!/usr/bin/env python3
import argparse
import re
import numpy as np
import math
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--config",  required=True)
parser.add_argument("--workdir", required=True)
args = parser.parse_args()

config = {}
with open(args.config) as f:
    for line in f:
        if "=" in line and not line.strip().startswith("#"):
            key, val = line.strip().split("=", 1)
            config[key] = val.strip('"')

dataname     = config["DATANAME"]
rh_threshold = float(config["RH_THRESHOLD"])
z_unit       = config.get("Z850_UNIT", "m2s-2")
rh_unit      = config.get("R850_UNIT", "%")
fill_value   = float(config["FILL_VALUE"]) if config.get("FILL_VALUE") else None
g            = 9.80665
workdir      = Path(args.workdir)

pi = math.pi
vv = 2.0
R  = 500 * 1000.0

def coriolis(lat):
    omega = 7.2921e-5
    return 2 * omega * np.sin(np.deg2rad(lat))

r6 = 4.730 * 111 * 1000
r4 = 4.279 * 111 * 1000
a6 = pi * r6 * r6
a4 = pi * r4 * r4
rhmin = float(rh_threshold)

def extract_date(fname):
    for pattern in [r'\d{8}', r'\d{6}', r'\d{4}']:
        m = re.search(pattern, fname)
        if m:
            return m.group()
    return None

def filter_hemi(list_file, hemi):
    with open(list_file) as f:
        file_list = [l.strip() for l in f.readlines()]

    written_files = []

    for fname in file_list:
        date_str = extract_date(fname)
        if date_str is None:
            print(f"WARNING: Cannot extract date from {fname}, skipping")
            continue

        yyyy    = date_str[:4]
        outname = workdir / f"{dataname}_{date_str}_filtered{hemi}seed.txt"

        with open(fname) as f:
            lines = [l.strip() for l in f.readlines()]

        line4     = [l.split()[0] for l in lines]
        start_ind = [i for i, v in enumerate(line4) if v == yyyy]

        out_lines = []
        for a in range(len(start_ind)):
            header           = lines[start_ind[a]].split()
            yyyy_, mm, dd, nn, hh = header

            SIND = start_ind[a] + 1
            EIND = start_ind[a + 1] - 1 if a < len(start_ind) - 1 else len(lines) - 1

            nodes = []

            for b in range(SIND, EIND + 1):
                parts = lines[b].split()
                if len(parts) < 13:
                    continue
                ilon  = int(parts[0])
                ilat  = int(parts[1])
                clon  = float(parts[2])
                clat  = float(parts[3])
                vo    = float(parts[4])
                msl   = float(parts[5])
                zs    = float(parts[6])
                ws10  = float(parts[7])
                z0    = float(parts[8])
                z4    = float(parts[9])
                z6    = float(parts[10])
                rh3   = float(parts[11])
                rh5   = float(parts[12])

                if fill_value and any(abs(v) >= fill_value for v in [vo, msl, zs, ws10, z0, z4, z6, rh3, rh5]):
                    continue

                if rh_unit == "fraction":
                    rh3 = rh3 * 100.0

                if z_unit == "m":
                    z0 = z0 * g
                    z4 = z4 * g
                    z6 = z6 * g

                f  = coriolis(clat)
                zf = vv * (vv + (f if hemi == "NH" else np.abs(f)) * R)
                z5 = (z6 * a6 - z4 * a4) / (a6 - a4)

                lat_ok = (0 <= clat <= 45) if hemi == "NH" else (-45 <= clat <= 0)
                if (z0 + zf < z5) and (rh3 > rhmin) and lat_ok:
                    nodes.append([ilon, ilat, clon, clat, vo, msl, zs, ws10, rh3])

            if len(nodes) == 0:
                continue

            out_lines.append([int(yyyy_), int(mm), int(dd), len(nodes), int(hh)])
            out_lines.extend(nodes)

        if not out_lines:
            if outname.exists():
                outname.unlink()
            continue

        with open(outname, "w") as f:
            for row in out_lines:
                if len(row) == 5:
                    f.write("%d\t%d\t%d\t%d\t%d\n" % tuple(row))
                else:
                    f.write("\t%d\t%d\t%.6f\t%.6f\t%.6e\t%.6e\t%.6e\t%.6e\t%.6e\n" % tuple(row))

        written_files.append(str(outname))

    listname = workdir / f"{dataname}seed.filteredoutput.{hemi}.txt"
    with open(listname, "w") as f:
        for fname in written_files:
            f.write(f"{fname}\n")

filter_hemi(workdir / f"{dataname}seed.DNoutput.NH.txt", "NH")
filter_hemi(workdir / f"{dataname}seed.DNoutput.SH.txt", "SH")