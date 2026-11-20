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

# Simulation demo: deploy the reBot cell with a passive door hinge and the
# printer at 0.70 m, shifted 0.3 m to the robot's left, look for the marker,
# grab the clip's lever on the door handle with the wrist fixed (the ball joint
# turns instead) and swing the door open by moving the arm along its arc.
#
#   tools/printer/demo_open_door.sh [target_deg]     (default 90)
#
# Watch it in the Gazebo GUI (research/REBOT_OMTS_APP.md, "Look through the
# camera"). The last lines are the door angle and how far the printer base
# moved, read from Gazebo (the belief world does not follow a passive hinge).
# Simulation only.
set -euo pipefail
cd "$(dirname "$0")/../.."
A=--address=localhost:17080
TARGET=${1:-90}
TMP=$(mktemp -d)

# The deploy puts the printer at the test layout with the door closed in the
# belief world; Gazebo keeps its previous state until it is reset, so the reset
# below syncs it. A Gazebo GUI that was open during the reset mis-draws the
# model, so the GUI is restarted after it (set NO_GUI=1 to skip that).
bazel run //:rebot_solution -c opt --//models/printer:door=closed \
  --//models/printer:hinge=passive --//models/printer:layout=door_test \
  -- $A >"$TMP/deploy.log" 2>&1 \
  || { tail -20 "$TMP/deploy.log"; exit 1; }
bazel build //tools/printer:open_door //tools/world:apply_scene_updates \
  >/dev/null
bazel-bin/tools/world/apply_scene_updates $A --reset_sim \
  --files configs/rebot/printer_door_test.updates.pbtxt \
  configs/rebot/printer_door_closed.updates.pbtxt >/dev/null

export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1
GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 \
  -o jsonpath='{.status.podIP}')
export GZ_RELAY

if [ -z "${NO_GUI:-}" ] && [ -n "${DISPLAY:-}" ]; then
  pkill -f 'gz sim -g' || true
  sleep 1
  (nohup gz sim -g >"$TMP/gui.log" 2>&1 &)
  echo ">>> Gazebo GUI restarted (fresh scene)."
  sleep 8
fi

OD="bazel-bin/tools/printer/open_door $A"
$OD --mode=look --joints 0.2647 -1.1813 -1.3964 0.2152 -0.4335 -1.5709
if $OD --mode=discover ${NO_WRITE:+--no_write_pose}; then
  echo ">>> Printer pose source: MEASURED (marker detected)."
else
  echo ">>> Printer pose source: CONFIGURED, NOT measured (no marker found)."
  echo ">>> The arm looked at the marker's expected place and the pull is"
  echo ">>> planned from the configured printer pose. Detection is not yet"
  echo ">>> part of this demo's result."
fi
gz topic -e -t /world/default/pose/info --json-output >"$TMP/poses.jsonl" &
REC=$!
$OD --mode=pull --grip=lever --target_deg="$TARGET" --step_deg=3
sleep 3
kill $REC 2>/dev/null || true
echo "Gazebo, from the start of the pull to its end:"
bazel run //research/tools:door_angle -- "$TMP/poses.jsonl" --every 100000 \
  2>/dev/null | tail -2
