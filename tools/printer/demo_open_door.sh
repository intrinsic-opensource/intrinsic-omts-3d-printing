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
# printer 21 cm further out and 20 cm to the robot's left (d 0.80, so the D
# handle's arc stays within the arm's reach), look for the marker,
# grab the bar of the purple D handle on the door (the bar turns on
# crank_pivot, so the wrist need not) and swing the door open along its arc in one blended planner
# call. sync_door streams Gazebo's door angle into the belief world meanwhile.
# Simulation only; real-printer behavior is unverified.
#
#   tools/printer/demo_open_door.sh [target_deg]     (default 115)
#
# 115 deg is the default: the arm's reach ends near 120, and 115 plans and
# swings without collisions (180 fails past the reach). Env: CHUNK (deg per
# planner call, default 115; 12 for stepwise swings), NO_GUI=1
# (do not restart the Gazebo GUI), NO_WRITE=1 (detect only, keep the configured
# printer pose). Needs the gz CLI and kubectl.
#
# Watch it in the Gazebo GUI (research/REBOT_OMTS_APP.md, "Look through the
# camera"). The last lines are the door angle and how far the printer base
# moved, read from Gazebo (the belief world does not follow a passive hinge).
# Simulation only.
set -euo pipefail
cd "$(dirname "$0")/../.."
A=--address=localhost:17080
TARGET=${1:-115}
TMP=$(mktemp -d)
echo ">>> Logs and pose recording: $TMP"
SYNC=""
REC=""
trap 'kill ${SYNC:+"$SYNC"} ${REC:+"$REC"} 2>/dev/null || true' EXIT

# The deploy puts the printer at the test layout with the door closed in the
# belief world; Gazebo keeps its previous state until it is reset, so the reset
# below syncs it. A Gazebo GUI that was open during the reset mis-draws the
# model, so the GUI is restarted after it (set NO_GUI=1 to skip that).
bazel run //:rebot_solution -c opt --//models/printer:door=closed \
  --//models/printer:hinge=passive \
  --//models/printer:layout=door_test -- $A >"$TMP/deploy.log" 2>&1 \
  || { tail -20 "$TMP/deploy.log"; exit 1; }
bazel build //tools/printer:open_door //tools/printer:sync_door \
  //research/tools:door_angle //tools/world:apply_scene_updates \
  >/dev/null
bazel-bin/tools/world/apply_scene_updates $A --reset_sim \
  --files configs/rebot/printer_door_test.updates.pbtxt \
  configs/rebot/printer_door_closed.updates.pbtxt >/dev/null

export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1
GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 \
  -o jsonpath='{.status.podIP}')
export GZ_RELAY

if [ -z "${NO_GUI:-}" ] && [ -n "${DISPLAY:-}" ]; then
  # the GUI's processes are gz-sim-main -g and gz-sim-gui-client
  pkill -f 'gz-sim-main -g' || true
  pkill -f 'gz-sim-gui-client' || true
  sleep 1
  (nohup gz sim -g >"$TMP/gui.log" 2>&1 &)
  echo ">>> Gazebo GUI restarted (fresh scene)."
  sleep 8
fi

OD="bazel-bin/tools/printer/open_door $A"
$OD --mode=look --joints 0.3055 -1.2202 -1.4196 0.1996 -0.0436 -1.5708
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
# The printer is attached to the ground in the cell, so no watchdog is needed.
# One planner call swings the door (CHUNK degrees, default 115 = the whole
# swing); a single IK failure anywhere in the arc fails the whole call, so
# CHUNK=12 gives stepwise swings. The belief world gets the real door angle
# from Gazebo through sync_door, so RViz shows the door moving.
bazel-bin/tools/printer/sync_door $A >"$TMP/sync.log" 2>&1 &
SYNC=$!
$OD --mode=pull --target_deg="$TARGET" --no_belief_door \
  --path=blended --chunk_deg="${CHUNK:-115}" --wp_deg=3 || true
sleep 3
kill "$SYNC" 2>/dev/null || true
sleep 1
kill $REC 2>/dev/null || true
echo "Belief door (synced from Gazebo), last lines:"
tail -2 "$TMP/sync.log"
bazel-bin/tools/printer/control_door $A --action=status | tail -1
echo "Gazebo, from the start of the pull to its end:"
bazel-bin/research/tools/door_angle "$TMP/poses.jsonl" --every 100000 \
  | tail -2
