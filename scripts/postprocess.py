#!/usr/bin/env python3
import argparse
import numpy as np
import netCDF4 as nc
from datetime import datetime
from pathlib import Path
from collections import defaultdict

FILL_F     = np.float32(-9999.0)
FILL_I     = np.int32(-9999)
MATCH_DIST = 2.0
TIME_THR_H = 12
DIST_THR   = 6.0

BASINS = ['NI', 'WP', 'EP', 'NA', 'SI', 'AU', 'SP']
BASIN_DEF = {
    'NI': (  0,  40,  60, 100),
    'WP': (  0,  40, 100, 180),
    'EP': (  0,  40, 180, 260),
    'NA': (  0,  40, 290, 350),
    'SI': (-40,   0,  50,  90),
    'AU': (-40,   0,  90, 160),
    'SP': (-40,   0, 160, 240),
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",  required=True)
    parser.add_argument("--outdir",  required=True)
    args = parser.parse_args()

    config   = load_config(args.config)
    dataname = config["DATANAME"]
    outdir   = Path(args.outdir)

    tc_txt = outdir / f"{dataname}TCtracks.txt"
    tc_tracks    = parse_tc_tracks(tc_txt) if tc_txt.exists() else []
    tc_time_maps = build_tc_time_maps_txt(tc_tracks)
    print(f"[INFO] TC tracks loaded: {len(tc_tracks)}")

    for hemi in ("NH", "SH"):
        seed_txt   = outdir / f"{dataname}seedtracks.{hemi}.txt"
        merged_txt = outdir / f"{dataname}seedtracks.{hemi}.merged.txt"
        if not seed_txt.exists():
            print(f"[SKIP] {seed_txt}")
            continue
        print(f"[START] Merging {hemi} seeds...")
        merge_seeds(seed_txt, merged_txt, tc_time_maps)
        print(f"[DONE] {hemi} seeds merged")

    nh_txt = outdir / f"{dataname}seedtracks.NH.merged.txt"
    sh_txt = outdir / f"{dataname}seedtracks.SH.merged.txt"
    if not nh_txt.exists():
        nh_txt = outdir / f"{dataname}seedtracks.NH.txt"
    if not sh_txt.exists():
        sh_txt = outdir / f"{dataname}seedtracks.SH.txt"

    tracks_nh = parse_seed_tracks(nh_txt) if nh_txt.exists() else []
    tracks_sh = parse_seed_tracks(sh_txt) if sh_txt.exists() else []
    print(f"[INFO] Seeds loaded: NH={len(tracks_nh)}, SH={len(tracks_sh)}")

    seed_nc = outdir / f"{dataname}seedtracks.nc"
    print("[START] Writing seed NC...")
    write_nc(tracks_nh, tracks_sh, tc_tracks, str(seed_nc))
    print(f"[DONE] NC written: {seed_nc}")

    print("[START] Computing istc...")
    compute_istc(str(seed_nc))
    print(f"[DONE] istc added: {seed_nc}")

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

def to_dt(yyyy, mm, dd, hh):
    return datetime(int(yyyy), int(mm), int(dd), int(hh))

def get_basin(lat, lon):
    if lon < 0:
        lon += 360.0
    for idx, name in enumerate(BASINS, start=1):
        slat, elat, slon, elon = BASIN_DEF[name]
        if slat < lat < elat and slon < lon < elon:
            return idx
    if lat > 0 and 260 < lon < 290:
        threshold = lon * (-25.0 / 30.0) + 25.0 * 290.0 / 30.0
        return 3 if lat <= threshold else 4
    return 0

def parse_seed_tracks(filepath):
    tracks, current = [], None
    with open(filepath) as f:
        for raw in f:
            parts = raw.strip().split()
            if not parts:
                continue
            if parts[0] == 'start':
                if current is not None:
                    tracks.append(current)
                current = {'raw_header': raw, 'n_pts': int(parts[1]), 'points': []}
            else:
                if current is None:
                    continue
                current['points'].append({
                    'raw':  raw,
                    'lon':  float(parts[2]),
                    'lat':  float(parts[3]),
                    'rv':   float(parts[4]),
                    'slp':  float(parts[5]),
                    'zs':   float(parts[6]),
                    'ws':   float(parts[7]),
                    'rh':   float(parts[8]),
                    'yyyy': int(parts[9]),
                    'mm':   int(parts[10]),
                    'dd':   int(parts[11]),
                    'hh':   int(parts[12]),
                    'time': to_dt(parts[9], parts[10], parts[11], parts[12]),
                })
    if current is not None:
        tracks.append(current)
    return tracks

def parse_tc_tracks(filepath):
    tracks, current = [], None
    with open(filepath) as f:
        for raw in f:
            parts = raw.strip().split()
            if not parts:
                continue
            if parts[0] == 'start':
                if current is not None:
                    tracks.append(current)
                current = {'n_pts': int(parts[1]), 'points': []}
            else:
                if current is None:
                    continue
                lon = float(parts[2])
                if lon < 0:
                    lon += 360.0
                current['points'].append({
                    'lon':  lon,
                    'lat':  float(parts[3]),
                    'slp':  float(parts[4]),
                    'ws':   float(parts[5]),
                    'zs':   float(parts[6]),
                    'yyyy': int(parts[7]),
                    'mm':   int(parts[8]),
                    'dd':   int(parts[9]),
                    'hh':   int(parts[10]),
                    'time': to_dt(parts[7], parts[8], parts[9], parts[10]),
                })
    if current is not None:
        tracks.append(current)
    return tracks

def build_tc_time_maps_txt(tc_tracks):
    return [{pt['time']: (pt['lat'], pt['lon']) for pt in tc['points']} for tc in tc_tracks]

def find_tc_match(seed, tc_time_maps):
    match_by_tc = {}
    for pt in seed['points']:
        slon = pt['lon'] if pt['lon'] >= 0 else pt['lon'] + 360.0
        for tc_idx, tmap in enumerate(tc_time_maps):
            if pt['time'] not in tmap:
                continue
            tlat, tlon = tmap[pt['time']]
            dist = np.sqrt((pt['lat'] - tlat)**2 + (slon - tlon)**2)
            if dist < MATCH_DIST:
                match_by_tc.setdefault(tc_idx, [])
                match_by_tc[tc_idx].append(pt['time'])
    for tc_idx, times in match_by_tc.items():
        times = sorted(times)
        for i in range(1, len(times)):
            if (times[i] - times[i-1]).total_seconds() / 3600.0 <= 6.0:
                return tc_idx
    return None

def can_merge(s1, s2):
    times1 = [p['time'] for p in s1['points']]
    times2 = [p['time'] for p in s2['points']]
    if max(times1) <= min(times2):
        end_pt   = max(s1['points'], key=lambda p: p['time'])
        start_pt = min(s2['points'], key=lambda p: p['time'])
    else:
        end_pt   = max(s2['points'], key=lambda p: p['time'])
        start_pt = min(s1['points'], key=lambda p: p['time'])
    dt_h = abs((start_pt['time'] - end_pt['time']).total_seconds()) / 3600.0
    elon = end_pt['lon'] if end_pt['lon'] >= 0 else end_pt['lon'] + 360.0
    slon = start_pt['lon'] if start_pt['lon'] >= 0 else start_pt['lon'] + 360.0
    dist = np.sqrt((end_pt['lat'] - start_pt['lat'])**2 + (elon - slon)**2)
    return dt_h <= TIME_THR_H and dist <= DIST_THR

def merge_two_seeds(s1, s2):
    all_points = s1['points'] + s2['points']
    all_points = sorted(all_points, key=lambda p: p['time'])
    seen, merged_pts = set(), []
    for pt in all_points:
        if pt['time'] not in seen:
            seen.add(pt['time'])
            merged_pts.append(pt)
    first_pt   = merged_pts[0]
    raw_header = (
        f"start\t{len(merged_pts)}\t"
        f"{first_pt['time'].year}\t{first_pt['time'].month}\t"
        f"{first_pt['time'].day}\t{first_pt['time'].hour}\n"
    )
    return {'raw_header': raw_header, 'n_pts': len(merged_pts), 'points': merged_pts}

def merge_seeds(seed_txt, out_txt, tc_time_maps):
    seeds = parse_seed_tracks(seed_txt)
    print(f"  Original seeds: {len(seeds)}")

    seed_tc = {}
    for i, seed in enumerate(seeds):
        tc_idx = find_tc_match(seed, tc_time_maps)
        if tc_idx is not None:
            seed_tc[i] = tc_idx

    tc_to_seeds = defaultdict(list)
    for seed_idx, tc_idx in seed_tc.items():
        tc_to_seeds[tc_idx].append(seed_idx)

    merged_into = {}
    for tc_idx, seed_idxs in tc_to_seeds.items():
        if len(seed_idxs) < 2:
            continue
        for i in range(len(seed_idxs)):
            for j in range(i+1, len(seed_idxs)):
                a, b = seed_idxs[i], seed_idxs[j]
                if a in merged_into or b in merged_into:
                    continue
                if can_merge(seeds[a], seeds[b]):
                    print(f"  Merged: seed {a} + seed {b} → TC {tc_idx}")
                    seeds[a] = merge_two_seeds(seeds[a], seeds[b])
                    merged_into[b] = a

    final_tracks = [seeds[i] for i in range(len(seeds)) if i not in merged_into]
    print(f"  Seeds after merge: {len(final_tracks)}")

    with open(out_txt, 'w') as f:
        for trk in final_tracks:
            f.write(trk['raw_header'])
            for pt in sorted(trk['points'], key=lambda p: p['time']):
                f.write(pt['raw'])

def write_nc(tracks_nh, tracks_sh, tc_tracks, out_path):
    tracks_all    = tracks_nh + tracks_sh
    n_storm_nh    = len(tracks_nh)
    n_storm_sh    = len(tracks_sh)
    n_storm       = len(tracks_all)
    n_tc          = len(tc_tracks)
    seed_time_max = max(len(t['points']) for t in tracks_all) if tracks_all else 1
    tc_time_max   = max(len(t['points']) for t in tc_tracks)  if tc_tracks  else 1
    hemi_arr      = np.array([0]*n_storm_nh + [1]*n_storm_sh, dtype=np.int32)

    ds = nc.Dataset(out_path, 'w', format='NETCDF4')
    ds.createDimension('seed_storm', n_storm)
    ds.createDimension('seed_time',  seed_time_max)
    ds.createDimension('tc_storm',   n_tc)
    ds.createDimension('tc_time',    tc_time_max)

    kw_f = dict(fill_value=FILL_F)
    kw_i = dict(fill_value=FILL_I)

    sv_lat   = ds.createVariable('seed_lat',   'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_lon   = ds.createVariable('seed_lon',   'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_rv    = ds.createVariable('seed_rv',    'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_slp   = ds.createVariable('seed_slp',   'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_zs    = ds.createVariable('seed_zs',    'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_ws    = ds.createVariable('seed_ws',    'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_rh    = ds.createVariable('seed_rh',    'f4', ('seed_storm', 'seed_time'), **kw_f)
    sv_yyyy  = ds.createVariable('seed_yyyy',  'i4', ('seed_storm', 'seed_time'), **kw_i)
    sv_mm    = ds.createVariable('seed_mm',    'i4', ('seed_storm', 'seed_time'), **kw_i)
    sv_dd    = ds.createVariable('seed_dd',    'i4', ('seed_storm', 'seed_time'), **kw_i)
    sv_hh    = ds.createVariable('seed_hh',    'i4', ('seed_storm', 'seed_time'), **kw_i)
    sv_basin = ds.createVariable('seed_basin', 'i4', ('seed_storm', 'seed_time'), **kw_i)
    sv_ntime = ds.createVariable('seed_ntime', 'i4', ('seed_storm',))
    sv_hemi  = ds.createVariable('seed_hemi',  'i4', ('seed_storm',))

    sv_lat.units       = 'degrees_north'
    sv_lon.units       = 'degrees_east'
    sv_rv.units        = 's-1'
    sv_rv.long_name    = 'Relative Vorticity'
    sv_slp.units       = 'Pa'
    sv_slp.long_name   = 'Sea Level Pressure'
    sv_zs.long_name    = 'Surface Geopotential'
    sv_ws.units        = 'm s-1'
    sv_ws.long_name    = '10m Wind Speed'
    sv_rh.units        = '%'
    sv_rh.long_name    = 'Relative Humidity at 3deg radius'
    sv_basin.long_name = 'Basin index (1=NI,2=WP,3=EP,4=NA,5=SI,6=AU,7=SP)'
    sv_ntime.long_name = 'Number of valid time steps per seed'
    sv_hemi.long_name  = 'Hemisphere (0=NH, 1=SH)'
    ds.n_storm_nh      = n_storm_nh
    ds.n_storm_sh      = n_storm_sh

    for s, trk in enumerate(tracks_all):
        pts = trk['points']
        for t, pt in enumerate(pts):
            sv_lat[s, t]   = pt['lat']
            sv_lon[s, t]   = pt['lon']
            sv_rv[s, t]    = pt['rv']
            sv_slp[s, t]   = pt['slp']
            sv_zs[s, t]    = pt['zs']
            sv_ws[s, t]    = pt['ws']
            sv_rh[s, t]    = pt['rh']
            sv_yyyy[s, t]  = pt['yyyy']
            sv_mm[s, t]    = pt['mm']
            sv_dd[s, t]    = pt['dd']
            sv_hh[s, t]    = pt['hh']
            sv_basin[s, t] = get_basin(pt['lat'], pt['lon'])
        sv_ntime[s] = len(pts)
    sv_hemi[:] = hemi_arr

    tv_lat   = ds.createVariable('tc_lat',   'f4', ('tc_storm', 'tc_time'), **kw_f)
    tv_lon   = ds.createVariable('tc_lon',   'f4', ('tc_storm', 'tc_time'), **kw_f)
    tv_slp   = ds.createVariable('tc_slp',   'f4', ('tc_storm', 'tc_time'), **kw_f)
    tv_ws    = ds.createVariable('tc_ws',    'f4', ('tc_storm', 'tc_time'), **kw_f)
    tv_zs    = ds.createVariable('tc_zs',    'f4', ('tc_storm', 'tc_time'), **kw_f)
    tv_yyyy  = ds.createVariable('tc_yyyy',  'i4', ('tc_storm', 'tc_time'), **kw_i)
    tv_mm    = ds.createVariable('tc_mm',    'i4', ('tc_storm', 'tc_time'), **kw_i)
    tv_dd    = ds.createVariable('tc_dd',    'i4', ('tc_storm', 'tc_time'), **kw_i)
    tv_hh    = ds.createVariable('tc_hh',    'i4', ('tc_storm', 'tc_time'), **kw_i)
    tv_basin = ds.createVariable('tc_basin', 'i4', ('tc_storm', 'tc_time'), **kw_i)
    tv_ntime = ds.createVariable('tc_ntime', 'i4', ('tc_storm',))

    tv_lat.units       = 'degrees_north'
    tv_lon.units       = 'degrees_east'
    tv_slp.units       = 'Pa'
    tv_slp.long_name   = 'Sea Level Pressure'
    tv_ws.units        = 'm s-1'
    tv_ws.long_name    = '10m Wind Speed'
    tv_zs.long_name    = 'Surface Geopotential'
    tv_basin.long_name = 'Basin index (1=NI,2=WP,3=EP,4=NA,5=SI,6=AU,7=SP)'
    tv_ntime.long_name = 'Number of valid time steps per TC'

    for t, trk in enumerate(tc_tracks):
        pts = trk['points']
        for i, pt in enumerate(pts):
            tv_lat[t, i]   = pt['lat']
            tv_lon[t, i]   = pt['lon']
            tv_slp[t, i]   = pt['slp']
            tv_ws[t, i]    = pt['ws']
            tv_zs[t, i]    = pt['zs']
            tv_yyyy[t, i]  = pt['yyyy']
            tv_mm[t, i]    = pt['mm']
            tv_dd[t, i]    = pt['dd']
            tv_hh[t, i]    = pt['hh']
            tv_basin[t, i] = get_basin(pt['lat'], pt['lon'])
        tv_ntime[t] = len(pts)

    ds.close()

def build_tc_time_maps_nc(tc_lats, tc_lons, tc_yyyy, tc_mm, tc_dd, tc_hh, tc_ntime):
    tc_time_maps = []
    for t in range(len(tc_ntime)):
        npt  = int(tc_ntime[t])
        tmap = {}
        for i in range(npt):
            if tc_yyyy[t, i] <= 0 or tc_lats[t, i] <= -9998:
                continue
            time = datetime(int(tc_yyyy[t,i]), int(tc_mm[t,i]), int(tc_dd[t,i]), int(tc_hh[t,i]))
            tmap[time] = (tc_lats[t, i], tc_lons[t, i])
        tc_time_maps.append(tmap)
    return tc_time_maps

def match_seed_to_tc(slats, slons, seed_times, npt, tc_time_maps):
    match_by_tc = {}
    for t_idx in range(npt):
        slat = slats[t_idx]
        slon = slons[t_idx]
        if slat <= -9998 or slon <= -9998:
            continue
        stime = seed_times[t_idx]
        for tc_idx, tmap in enumerate(tc_time_maps):
            if stime not in tmap:
                continue
            tlat, tlon = tmap[stime]
            dist = np.sqrt((slat - tlat)**2 + (slon - tlon)**2)
            if dist < MATCH_DIST:
                match_by_tc.setdefault(tc_idx, [])
                match_by_tc[tc_idx].append(t_idx)
    return match_by_tc

def find_developing_start(match_by_tc):
    developing = []
    for tc_idx, tidxs in match_by_tc.items():
        tidxs   = sorted(set(tidxs))
        run_len = 1
        for i in range(1, len(tidxs)):
            if tidxs[i] == tidxs[i-1] + 1:
                run_len += 1
                if run_len >= 2:
                    developing.append((tc_idx, tidxs[0], tidxs[-1]))
                    break
            else:
                run_len = 1
    return developing

def try_merge_seeds(dev_list, slats, slons, seed_times):
    if len(dev_list) <= 1:
        return dev_list
    by_tc  = defaultdict(list)
    for item in dev_list:
        by_tc[item[0]].append(item)
    merged = []
    for tc_idx, items in by_tc.items():
        items  = sorted(items, key=lambda x: x[1])
        groups = [items[0]]
        for i in range(1, len(items)):
            prev      = groups[-1]
            curr      = items[i]
            prev_time = seed_times[prev[2]]
            curr_time = seed_times[curr[1]]
            dt_h      = abs((curr_time - prev_time).total_seconds()) / 3600.0
            dist      = np.sqrt(
                (slats[prev[2]] - slats[curr[1]])**2 +
                (slons[prev[2]] - slons[curr[1]])**2
            )
            if dt_h <= TIME_THR_H and dist <= DIST_THR:
                groups[-1] = (tc_idx, prev[1], curr[2])
            else:
                groups.append(curr)
        merged.extend(groups)
    return merged

def compute_istc(seed_nc_path):
    ds      = nc.Dataset(seed_nc_path, 'a')
    n_storm = ds.dimensions['seed_storm'].size
    n_time  = ds.dimensions['seed_time'].size

    s_lats  = np.ma.filled(ds.variables['seed_lat'][:],  -9999.0).astype(np.float32)
    s_lons  = np.ma.filled(ds.variables['seed_lon'][:],  -9999.0).astype(np.float32)
    s_yyyy  = np.ma.filled(ds.variables['seed_yyyy'][:], -9999).astype(np.int32)
    s_mm    = np.ma.filled(ds.variables['seed_mm'][:],   -9999).astype(np.int32)
    s_dd    = np.ma.filled(ds.variables['seed_dd'][:],   -9999).astype(np.int32)
    s_hh    = np.ma.filled(ds.variables['seed_hh'][:],   -9999).astype(np.int32)
    s_ntime = ds.variables['seed_ntime'][:].astype(np.int32)

    tc_lats  = np.ma.filled(ds.variables['tc_lat'][:],  -9999.0).astype(np.float32)
    tc_lons  = np.ma.filled(ds.variables['tc_lon'][:],  -9999.0).astype(np.float32)
    tc_yyyy  = np.ma.filled(ds.variables['tc_yyyy'][:], -9999).astype(np.int32)
    tc_mm    = np.ma.filled(ds.variables['tc_mm'][:],   -9999).astype(np.int32)
    tc_dd    = np.ma.filled(ds.variables['tc_dd'][:],   -9999).astype(np.int32)
    tc_hh    = np.ma.filled(ds.variables['tc_hh'][:],   -9999).astype(np.int32)
    tc_ntime = ds.variables['tc_ntime'][:].astype(np.int32)

    tc_time_maps = build_tc_time_maps_nc(tc_lats, tc_lons, tc_yyyy, tc_mm, tc_dd, tc_hh, tc_ntime)

    if 'istc' not in ds.variables:
        v_istc = ds.createVariable('istc', 'i4', ('seed_storm', 'seed_time'), fill_value=FILL_I)
        v_istc.long_name = 'Developing seed flag (1=developing, 0=non-developing)'
    else:
        v_istc = ds.variables['istc']

    istc_arr = np.full((n_storm, n_time), FILL_I, dtype=np.int32)

    for s in range(n_storm):
        npt = int(s_ntime[s])
        if npt == 0:
            continue

        istc_arr[s, :npt] = 0

        seed_times = []
        for t in range(npt):
            if s_yyyy[s, t] <= 0:
                break
            seed_times.append(
                datetime(int(s_yyyy[s,t]), int(s_mm[s,t]), int(s_dd[s,t]), int(s_hh[s,t]))
            )
        npt = len(seed_times)
        if npt == 0:
            continue

        slats = s_lats[s, :npt]
        slons = s_lons[s, :npt]

        match_by_tc = match_seed_to_tc(slats, slons, seed_times, npt, tc_time_maps)
        if not match_by_tc:
            continue

        dev_list = find_developing_start(match_by_tc)
        if not dev_list:
            continue

        dev_list    = try_merge_seeds(dev_list, slats, slons, seed_times)
        first_match = min(item[1] for item in dev_list)
        istc_arr[s, first_match:npt] = 1

    v_istc[:] = istc_arr
    ds.close()

    ds       = nc.Dataset(seed_nc_path, 'r')
    istc     = ds.variables['istc'][:]
    hemi     = ds.variables['seed_hemi'][:]
    n_total  = ds.dimensions['seed_storm'].size
    n_dev    = np.sum(np.any(istc == 1, axis=1))
    n_dev_nh = np.sum(np.any(istc[hemi==0] == 1, axis=1))
    n_dev_sh = np.sum(np.any(istc[hemi==1] == 1, axis=1))
    ds.close()

    print(f"  Total seeds    : {n_total}")
    print(f"  Developing     : {n_dev} (NH={n_dev_nh}, SH={n_dev_sh})")
    print(f"  Non-developing : {n_total - n_dev}")

if __name__ == "__main__":
    main()
