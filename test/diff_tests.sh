#!/bin/bash
set -euo pipefail
shopt -s nullglob
cd "$(dirname "$0")"

check() {
    local cmd=("$@")
    if "${cmd[@]}" "$prog" < "$data" > /dev/null 2>&1; then
        echo "0"
    else
        echo "$?"
    fi
}

for prog in diff/test_*_prog; do
    base="${prog%_prog}"
    echo "${base}"
    data="${base}"_data

    expected=$(check ../third_party/checktestdata)
    got=$(check python3 ../checktestdata/)

    #echo "Got: ${got}, expected: ${expected}"

    # we expect to get a different result
    if (( (expected == 0) == (got == 0) )); then
        echo "Got: ${got}, expected: ${expected}"
        exit 1
    fi
done
