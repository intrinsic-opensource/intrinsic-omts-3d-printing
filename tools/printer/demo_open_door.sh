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

# Simulation demo (real-printer behavior is unverified): deploy the reBot cell
# with a passive door hinge and the printer 21 cm further from the robot
# (d 0.80, in line with the arm), then run the door-opening behavior tree
# (tools/printer/open_door_bt: installed skills, parameters in the door
# section of configs/rebot/app_config.yaml): look at the marker, find the
# printer, grab the bar of the purple D handle and swing the door open along its
# arc. sync_door streams Gazebo's door angle into the belief world meanwhile.
#
#   tools/printer/demo_open_door.sh [target_deg]     (default 135)
#
# The arm's reach ends near 145 deg; the tree falls back to shorter arcs (114,
# 90, 60 deg) when the target cannot be planned. Env: NO_GUI=1 (do not restart
# the Gazebo GUI). Needs the gz CLI and kubectl.
#
# Watch it in the Gazebo GUI (research/REBOT_OMTS_APP.md, "Look through the
# camera"). The last lines are the belief door angle, the door angle read from
# Gazebo and how far the printer base moved.
set -euo pipefail
cd "$(dirname "$0")/../.."
A=--address=localhost:17080
TARGET=${1:-135}
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
bazel build //tools/printer:open_door_bt //tools/printer:sync_door \
  //tools/printer:control_door //research/tools:door_angle \
  //tools/world:apply_scene_updates \
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

gz topic -e -t /world/default/pose/info --json-output >"$TMP/poses.jsonl" &
REC=$!
bazel-bin/tools/printer/sync_door $A >"$TMP/sync.log" 2>&1 &
SYNC=$!
rc=0
bazel-bin/tools/printer/open_door_bt $A --target_deg="$TARGET" || rc=$?
sleep 3
kill "$SYNC" 2>/dev/null || true
sleep 1
kill "$REC" 2>/dev/null || true
echo "open_door_bt exit code: $rc"
echo "Belief door (synced from Gazebo), last lines:"
tail -2 "$TMP/sync.log"
bazel-bin/tools/printer/control_door $A --action=status | tail -1 || true
echo "Gazebo, from the start of the pull to its end:"
bazel-bin/research/tools/door_angle "$TMP/poses.jsonl" --every 100000 \
  | tail -2 || true
exit "$rc"
