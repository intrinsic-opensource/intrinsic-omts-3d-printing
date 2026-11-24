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

"""Streams Gazebo's real door angle into the belief world.

The door hinge is passive in simulation, so the belief joints never follow the
physics. This tool reads door_link and crank_handle from Gazebo's
/world/default/pose/info (needs the gz CLI and the GZ_* environment of the
simulation, as for recording poses) and writes the door_hinge and crank_pivot
joints of the printer in the belief world, so RViz and the planner see the
real door. Simulation only: needs the gz CLI with GZ_PARTITION=intrinsic_sim,
GZ_IP=10.42.0.1 and GZ_RELAY=<Gazebo pod IP> (see demo_open_door.sh). Only the
joints door_hinge and crank_pivot are written, at --rate_hz, skipping changes
under --min_change_deg. Stop it with Ctrl-C (or --duration).
"""

import argparse
import json
import math
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

from intrinsic.solutions import deployments

from src.core import door

PRINTER_OBJECT_NAME = "printer"
DOOR_JOINT_NAME = "door_hinge"
CRANK_JOINT_NAME = "crank_pivot"
DOOR_LINK = "door_link"
CRANK_LINK = "crank_handle"
POSE_TOPIC = "/world/default/pose/info"


def yaw(q: dict) -> float:
  """Yaw of a quaternion given as a JSON dict."""
  x, y, z, w = (float(q.get(k, 0.0)) for k in "xyzw")
  return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def joints_from_poses(msg: dict) -> tuple[float, float] | None:
  """(door q, crank pivot angle) in radians from a pose message, or None."""
  door_yaw = crank_yaw = None
  for pose in msg.get("pose", []):
    name = pose.get("name")
    if name == DOOR_LINK:
      door_yaw = yaw(pose.get("orientation", {}))
    elif name == CRANK_LINK:
      crank_yaw = yaw(pose.get("orientation", {}))
  if door_yaw is None or crank_yaw is None:
    return None
  # Wrap to [-90, 270) and clamp: a door resting at either hinge limit can
  # read a hair outside [0, 180] (closed: just below 0; open: just above 180).
  theta = (-math.degrees(door_yaw) + 90.0) % 360.0 - 90.0
  q = door.theta_to_q(min(max(theta, 0.0), 180.0))
  pivot = math.atan2(
    math.sin(crank_yaw - door_yaw), math.cos(crank_yaw - door_yaw)
  )
  return q, pivot


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument("--rate_hz", type=float, default=10.0)
  parser.add_argument(
    "--min_change_deg",
    type=float,
    default=0.2,
    help="Skip belief writes for changes smaller than this.",
  )
  parser.add_argument(
    "--duration",
    type=float,
    default=0.0,
    help="Stop after this many seconds (0: until interrupted).",
  )
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = parse_args(argv)
  # A plain kill (SIGTERM) should stop it as cleanly as Ctrl-C.
  signal.signal(signal.SIGTERM, signal.default_int_handler)
  solution = deployments.connect(address=args.address)
  world = solution.world
  printer = world.get_kinematic_object(PRINTER_OBJECT_NAME)
  names = list(printer.joint_entity_names)
  i_door = names.index(DOOR_JOINT_NAME)
  i_crank = names.index(CRANK_JOINT_NAME) if CRANK_JOINT_NAME in names else -1

  proc = subprocess.Popen(
    ["gz", "topic", "-e", "-t", POSE_TOPIC, "--json-output"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
  )
  print(f"Syncing the belief door from Gazebo ({POSE_TOPIC}); Ctrl-C stops.")
  start = time.monotonic()
  last_write = 0.0
  last = None
  writes = 0
  try:
    for line in proc.stdout:
      now = time.monotonic()
      if args.duration and now - start > args.duration:
        break
      if not line.startswith("{") or now - last_write < 1.0 / args.rate_hz:
        continue
      joints = joints_from_poses(json.loads(line))
      if joints is None:
        continue
      moved = last is None or any(
        abs(math.degrees(a - b)) >= args.min_change_deg
        for a, b in zip(joints, last, strict=True)
      )
      if not moved:
        continue
      positions = [float(v) for v in printer.joint_positions]
      positions[i_door] = joints[0]
      if i_crank >= 0:
        positions[i_crank] = joints[1]
      world.update_joint_positions(printer, positions)
      printer = world.get_kinematic_object(PRINTER_OBJECT_NAME)
      last, last_write, writes = joints, now, writes + 1
      print(
        f"  door {door.q_to_theta(joints[0]):6.1f} deg"
        f" crank {math.degrees(joints[1]):7.1f} deg",
        flush=True,
      )
  except KeyboardInterrupt:
    pass
  finally:
    proc.terminate()
  print(f"Stopped after {writes} belief writes.")
  sys.exit(0)


if __name__ == "__main__":
  main()
