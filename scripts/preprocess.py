#!/usr/bin/env python3
import argparse
import shutil
import subprocess
from pathlib import Path

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

VARS = ["MSLP", "Z850", "R850", "U10", "V10"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",  required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()

    config   = load_config(args.config)
    dataname = config["DATANAME"]
    workdir  = Path(args.workdir)

    updated  = {}
    config_path = Path(args.config)
    updated_config = config_path.parent / f"{dataname}_updated.conf"

    for var in VARS:
        tres  = config.get(f"{var}_TRES", "6h")
        indir = config.get(f"{var}_DIR",  "")
        if tres == "6h" or not indir:
            continue

        outdir = workdir / f"preproc_{var}"
        outdir.mkdir(parents=True, exist_ok=True)

        print(f"[START] Subsampling {var} ({tres} → 6h)...")
        for f in sorted(Path(indir).glob("*.nc*")):
            out = outdir / f.name
            if out.exists():
                print(f"  exists: {out}")
                continue
            subprocess.run(["cdo", "selhour,0,6,12,18", str(f), str(out)], check=True)
            print(f"  subsampled: {out}")

        updated[f"{var}_DIR"] = str(outdir.resolve())
        print(f"[DONE] {var} subsampled → {outdir}")

    shutil.copy(args.config, updated_config)
    if updated:
        with open(updated_config, "a") as f:
            for key, val in updated.items():
                f.write(f'{key}="{val}"\n')

    print(f"[DONE] Updated config: {updated_config}")

if __name__ == "__main__":
    main()