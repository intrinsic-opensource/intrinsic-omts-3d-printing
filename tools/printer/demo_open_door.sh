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

# Simulation demo: deploy the reBot cell with a passive door hinge, put the
# printer at 0.675 m, find it by its markers, grab the door's handle and pull
# the door open (about 42 deg at most).
#
#   tools/printer/demo_open_door.sh [target_deg]     (default 42)
#
# Watch it in the Gazebo GUI (research/REBOT_OMTS_APP.md, "Look through the
# camera"). The last lines are the door angle and how far the printer base
# moved, read from Gazebo (the belief world does not follow a passive hinge).
# Simulation only.
set -euo pipefail
cd "$(dirname "$0")/../.."
A=--address=localhost:17080
TARGET=${1:-42}
TMP=$(mktemp -d)

bazel run //:rebot_solution -c opt --//models/printer:door=closed \
  --//models/printer:hinge=passive -- $A >"$TMP/deploy.log" 2>&1 \
  || { tail -20 "$TMP/deploy.log"; exit 1; }
bazel build //tools/world:apply_scene_updates //tools/printer:control_door \
  //tools/printer:open_door >/dev/null

sed 's/x: 0.5895/x: 0.675/; s/y: -0.0064/y: 0/' \
  configs/rebot/printer.updates.pbtxt >"$TMP/printer.pbtxt"
bazel-bin/tools/world/apply_scene_updates $A --files "$TMP/printer.pbtxt" \
  --reset_sim >/dev/null
bazel-bin/tools/printer/control_door $A --action=set --theta_deg=0 >/dev/null

export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1
GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 \
  -o jsonpath='{.status.podIP}')
export GZ_RELAY

OD="bazel-bin/tools/printer/open_door $A"
$OD --mode=look --joints -0.8678 -0.5884 -0.8892 0.3008 -0.8676 -1.5708
$OD --mode=discover
gz topic -e -t /world/default/pose/info --json-output >"$TMP/poses.jsonl" &
REC=$!
$OD --mode=pull --grasp_h=0.30 --target_deg="$TARGET" --step_deg=6
sleep 3
kill $REC 2>/dev/null || true
echo "Gazebo, from the start of the pull to its end:"
bazel run //research/tools:door_angle -- "$TMP/poses.jsonl" --every 100000 \
  2>/dev/null | tail -2
