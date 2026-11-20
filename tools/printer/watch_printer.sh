#!/bin/bash
# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Fails fast when the printer moves: samples the printer's pose in Gazebo about
# once a second; if it ever differs from the first sample by more than
# TOL_MM (default 2), prints FAIL, stops the arm program (PID given as $1) and
# exits 1. Needs the GZ_* variables of the demo. Run it in the background.
#
#   tools/printer/watch_printer.sh <pid-to-stop> [tol_mm]
PID=${1:?pid to stop}
TOL=${2:-2}
first=""
while kill -0 "$PID" 2>/dev/null; do
  now=$(timeout 5 gz topic -e -t /world/default/pose/info -n 1 --json-output \
    2>/dev/null | python3 -c '
import json, sys
m = json.loads(sys.stdin.readline())
for p in m["pose"]:
  if p["name"] == "printer":
    q = p["position"]
    print(q.get("x", 0), q.get("y", 0)); break
') || now=""
  if [ -n "$now" ]; then
    [ -z "$first" ] && first=$now
    moved=$(python3 -c "
a=list(map(float,'$first'.split())); b=list(map(float,'$now'.split()))
print(round(1000*((a[0]-b[0])**2+(a[1]-b[1])**2)**0.5,1))")
    if python3 -c "import sys; sys.exit(0 if $moved > $TOL else 1)"; then
      echo "FAIL: the printer moved ${moved} mm (limit ${TOL} mm). Stopping." >&2
      kill "$PID" 2>/dev/null
      exit 1
    fi
  fi
  sleep 0.5
done
exit 0
