#!/bin/bash
set -euo pipefail
shopt -s nullglob
cd "$(dirname "$0")"

checksucc() {
    if python3 ../checktestdata/ "$prog" < "$data" > /dev/null 2>&1; then
        our_status=0
    else
        our_status=$?
    fi

    if [[ $our_status -ne 0 ]]; then
        echo "PYCTD ERROR: Expected exit code 0 but got $our_status"
        echo "  Program: $prog"
        echo "  Data:    $data"
        exit 1
    fi

    if $(../third_party/checktestdata "$prog" < "$data" > /dev/null 2>&1); then
        ctd_status=0
    else
        ctd_status=$?
    fi

    if [[ $ctd_status -ne 0 ]]; then
        echo "CTD ERROR: Expected exit code 0 but got $ctd_status"
        echo "  Program: $prog"
        echo "  Data:    $data"
        exit 1
    fi
}

checkfail() {
    if python3 ../checktestdata/ "$prog" < "$data" > /dev/null 2>&1; then
        our_status=0
    else
        our_status=$?
    fi

    if [[ $our_status -eq 0 ]]; then
        echo "PYCTD ERROR: Expected exit code != 0 but got $our_status"
        echo "  Program: $prog"
        echo "  Data:    $data"
        exit 1
    fi

    if $(../third_party/checktestdata "$prog" < "$data" > /dev/null 2>&1); then
        ctd_status=0
    else
        ctd_status=$?
    fi

    if [[ $ctd_status -eq 0 ]]; then
        echo "CTD ERROR: Expected exit code != 0 but got $ctd_status"
        echo "  Program: $prog"
        echo "  Data:    $data"
        exit 1
    fi

    if (( ctd_status != our_status )); then
        echo "  WARNING: pyctd: ${our_status}, ctd: ${ctd_status}"
    fi
}

for prog in additional/test_*_prog.in; do
    base="${prog%_prog.*}"
    echo "${base}"

    # Successful cases
    for data in "${base}"_data.in*; do
        checksucc
    done

    # Expected failure cases (.err data)
    for data in "${base}"_data.err*; do
        checkfail
    done

    # Program error cases
    data="${base}_data.in"
    for prog in "${base}"_prog.err*; do
        checkfail
    done
done
