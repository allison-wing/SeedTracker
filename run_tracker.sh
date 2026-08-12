#!/bin/bash

DATASET=${1:?"Usage: bash run_tracker.sh <DATASET> [--skip-detect] [--skip-preproc] [--skip-rv] [--skip-filter] [--skip-tc] [--skip-stitch]"}
SKIP_DETECT=false
SKIP_PREPROC=false
SKIP_RV=false
SKIP_FILTER=false
SKIP_TC=false
SKIP_STITCH=false

for arg in "$@"; do
    [ "$arg" = "--skip-detect" ] && SKIP_DETECT=true
done

for arg in "$@"; do
    [ "$arg" = "--skip-preproc" ] && SKIP_PREPROC=true
done

for arg in "$@"; do
    [ "$arg" = "--skip-rv" ] && SKIP_RV=true
done

for arg in "$@"; do                                                                                                          
    [ "$arg" = "--skip-filter" ] && SKIP_FILTER=true
done

for arg in "$@"; do                                                                                                          
    [ "$arg" = "--skip-tc" ] && SKIP_TC=true
done

for arg in "$@"; do
    [ "$arg" = "--skip-stitch" ] && SKIP_STITCH=true
done

CONFIG="config/${DATASET}.conf"
[ ! -f "$CONFIG" ] && echo "ERROR: config not found → ${CONFIG}" && exit 1
source "$CONFIG"

WORKDIR="work/${DATANAME}"
OUTDIR="output/${DATANAME}"
mkdir -p "$WORKDIR" "$OUTDIR"

echo "==============================="
echo " SeedTracker: ${DATASET}"
echo " Period: ${START} - ${END}"
echo "==============================="

if [ "$SKIP_PREPROC" = false ]; then

	echo "[START] Preprocessing..."
	python scripts/preprocess.py --config "$CONFIG" --workdir "$WORKDIR"
	echo "[DONE] Preprocessing done"

fi

if [ "$SKIP_RV" = false ]; then
	if [ -z "$RV850_DIR" ]; then
    	echo "[START] Computing RV850..."
	    python scripts/compute_rv850.py --config "$CONFIG" --workdir "$WORKDIR"
    	echo "[DONE] RV850 computed"
	fi
fi

CONFIG="config/${DATASET}_updated.conf"
source "$CONFIG"
echo "[START] Generating file list..."
python scripts/filelist_generation.py --config "$CONFIG" --workdir "$WORKDIR"
echo "[DONE] File list generated"
INPUT_LIST="${WORKDIR}/${DATANAME}seed.input.txt"
OUTPUT_NH="${WORKDIR}/${DATANAME}seed.DNoutput.NH.txt"
OUTPUT_SH="${WORKDIR}/${DATANAME}seed.DNoutput.SH.txt"

format_var() {
    local varname=$1
    local level=$2
    if [ -z "$level" ]; then
        echo "${varname}"
    else
        local val="${level//[a-zA-Z]/}"
        local unit="${level//[0-9]/}"
        if [ "$unit" = "Pa" ]; then
            val=$(echo "$val / 100" | bc)
        fi
        echo "${varname}(${val}${unit})"
    fi
}

MSLP_CMD=$(format_var "$MSLP"   "$MSLP_LEVEL")
Z850_CMD=$(format_var "$Z850"   "$Z850_LEVEL")
RV850_CMD=$(format_var "$RV850" "$RV850_LEVEL")
R850_CMD=$(format_var "$R850"   "$R850_LEVEL")
U10_CMD=$(format_var "$U10"     "$U10_LEVEL")
V10_CMD=$(format_var "$V10"     "$V10_LEVEL")
ZS_CMD=$(format_var "$ZS"       "$ZS_LEVEL")

OUTPUTCMD="${MSLP_CMD},min,3;${ZS_CMD},max,2;_VECMAG(${U10_CMD},${V10_CMD}),max,3;${Z850_CMD},min,0;${Z850_CMD},avg,4.279;${Z850_CMD},avg,4.730;${R850_CMD},avg,3;${R850_CMD},avg,5"

if [ "$SKIP_DETECT" = false ]; then
    echo "[START] DetectNodes: NH..."
    DetectNodes \
    --in_data_list     "$INPUT_LIST" \
    --out_file_list    "$OUTPUT_NH" \
    --searchbymin      "$Z850_CMD" \
    --closedcontourcmd "${Z850_CMD},1e-5,4.504,0" \
    --mergedist        5.0 \
    --latname          "$LATNAME" \
    --lonname          "$LONNAME" \
    --outputcmd        "${RV850_CMD},max,1;${OUTPUTCMD}" \
    --minlat 0 --maxlat 45
    echo "[DONE] DetectNodes: NH"

    echo "[START] DetectNodes: SH..."
    DetectNodes \
    --in_data_list     "$INPUT_LIST" \
    --out_file_list    "$OUTPUT_SH" \
    --searchbymin      "$Z850_CMD" \
    --closedcontourcmd "${Z850_CMD},1e-5,4.504,0" \
    --mergedist        5.0 \
    --latname          "$LATNAME" \
    --lonname          "$LONNAME" \
    --outputcmd        "${RV850_CMD},min,1;${OUTPUTCMD}" \
    --minlat -45 --maxlat 0
    echo "[DONE] DetectNodes: SH"

	mkdir -p log
	mv log*txt log
else
    echo "[SKIP] DetectNodes skipped"
fi

if [ "$SKIP_FILTER" = false ]; then
	echo "[START] Filtering TC seeds..."
	python scripts/filtering.py --config "$CONFIG" --workdir "$WORKDIR"
	echo "[DONE] Filtering done"
else
	echo "[SKIP] Filtering skipped"
fi

INPUT_LIST_NH="${WORKDIR}/${DATANAME}seed.filteredoutput.NH.txt"
INPUT_LIST_SH="${WORKDIR}/${DATANAME}seed.filteredoutput.SH.txt"
OUTPUT_TRACKS_NH="${OUTDIR}/${DATANAME}seedtracks.NH.txt"
OUTPUT_TRACKS_SH="${OUTDIR}/${DATANAME}seedtracks.SH.txt"

if [ "$ZS_UNIT" = "m" ]; then
    ZS_THRESHOLD="100."
else
    ZS_THRESHOLD="980."
fi
if [ "$SKIP_STITCH" = false ]; then
	echo "[START] StitchNodes: NH..."
	StitchNodes \
	  --in_list   "$INPUT_LIST_NH" \
	  --out       "$OUTPUT_TRACKS_NH" \
	  --in_fmt    "lon,lat,rv,slp,zs,ws,rh" \
	  --range     3.0 \
	  --minlength 4 \
	  --maxgap    2 \
	  --threshold "zs,<=,${ZS_THRESHOLD},4;lat,<=,25,4.;lat,>=,-25,4.;rv,>,1e-5,all"
	echo "[DONE] StitchNodes: NH"

	echo "[START] StitchNodes: SH..."
	StitchNodes \
	  --in_list   "$INPUT_LIST_SH" \
	  --out       "$OUTPUT_TRACKS_SH" \
	  --in_fmt    "lon,lat,rv,slp,zs,ws,rh" \
	  --range     3.0 \
	  --minlength 4 \
	  --maxgap    2 \
	  --threshold "zs,<=,${ZS_THRESHOLD},4;lat,<=,25,4.;lat,>=,-25,4.;rv,<,-1e-5,all"
	echo "[DONE] StitchNodes: SH"
else
    echo "[SKIP] StitchNodes skipped"
fi

Z300_CMD=$(format_var "$Z300" "$Z300_LEVEL")
Z500_CMD=$(format_var "$Z500" "$Z500_LEVEL")

if [ "$Z850_UNIT" = "m" ]; then
    WARMCORE_THRESHOLD="-6.0"
else
    WARMCORE_THRESHOLD="-58.8"
fi

if [ "$ZS_UNIT" = "m" ]; then
    TC_ZS_THRESHOLD="150.0"
else
    TC_ZS_THRESHOLD="1471.5"
fi

if [ "$MSLP_UNIT" = "hPa" ]; then
    TC_MSL_THRESHOLD="2.0"
else
    TC_MSL_THRESHOLD="200.0"
fi

TC_INPUT_LIST="${WORKDIR}/${DATANAME}TC.input.txt"
TC_OUTPUT="${WORKDIR}/${DATANAME}TC.DNoutput.txt"
TC_TRACKS="${OUTDIR}/${DATANAME}TCtracks.txt"

echo "[START] Generating TC file list..."
python scripts/filelist_generation_tc.py --config "$CONFIG" --workdir "$WORKDIR"
echo "[DONE] TC file list generated"

if [ "$SKIP_TC" = false ]; then
	echo "[START] DetectNodes: TC..."
	DetectNodes \
	    --in_data_list     "$TC_INPUT_LIST" \
	    --out_file_list    "$TC_OUTPUT" \
	    --searchbymin      "$MSLP_CMD" \
	    --closedcontourcmd "${MSLP_CMD},${TC_MSL_THRESHOLD},5.5,0;_DIFF(${Z300_CMD},${Z500_CMD}),${WARMCORE_THRESHOLD},6.5,1.0" \
	    --mergedist        6.0 \
	    --latname          "$LATNAME" \
	    --lonname          "$LONNAME" \
	    --outputcmd        "${MSLP_CMD},min,0;_VECMAG(${U10_CMD},${V10_CMD}),max,2;${ZS_CMD},min,0"
	echo "[DONE] DetectNodes: TC"

	echo "[START] StitchNodes: TC..."
	StitchNodes \
	    --in_list   "$TC_OUTPUT" \
	    --out       "$TC_TRACKS" \
    	--in_fmt    "lon,lat,slp,wind,zs" \
	    --range     8.0 \
    	--mintime   "54h" \
	    --maxgap    "24h" \
    	--threshold "wind,>=,10.0,10;lat,<=,50.0,10;lat,>=,-50.0,10;zs,<=,${TC_ZS_THRESHOLD},10"
	echo "[DONE] StitchNodes: TC"
else
	echo "[SKIP] TC tracking skipped"
fi

echo "[START] Postprocessing..."
python scripts/postprocess.py --config "$CONFIG" --outdir "$OUTDIR"
echo "[DONE] Postprocessing done"
