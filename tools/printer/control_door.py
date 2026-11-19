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

"""Opens, closes or reads the printer door's hinge in a running solution.

Writes the door joint in the belief world. In simulation it then resets the
simulation so Gazebo picks the new position up, the same way
//tools/world:apply_scene_updates --reset_sim does: a reset clones the belief
world into Gazebo's sim_world, which the belief world update alone does not
change.
"""

import argparse
import sys
from collections.abc import Sequence

from intrinsic.solutions import deployments

PRINTER_OBJECT_NAME = "printer"

# Hinge angles, matching configs/rebot/printer_door_{open,closed}.updates.pbtxt.
DOOR_OPEN_ANGLE = 0.0
DOOR_CLOSED_ANGLE = 3.141596


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  """Parses command line arguments."""
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--address",
    type=str,
    default="localhost:17080",
    help="Solution gRPC address.",
  )
  parser.add_argument(
    "--action",
    choices=["open", "close", "set", "status"],
    default="open",
    help=(
      f"open: {DOOR_OPEN_ANGLE} rad. close: {DOOR_CLOSED_ANGLE} rad."
      " set: --angle. status: print the joint position only."
    ),
  )
  parser.add_argument(
    "--angle",
    type=float,
    default=1.57,
    help=(
      "Target angle in radians for --action=set (e.g. 1.57 is about halfway;"
      f" {DOOR_OPEN_ANGLE} is open, {DOOR_CLOSED_ANGLE} is closed)."
    ),
  )
  parser.add_argument(
    "--reset_sim",
    action=argparse.BooleanOptionalAction,
    default=True,
    help=(
      "In simulation, reset the simulation afterwards so Gazebo shows the new"
      " door position (default: True)."
    ),
  )
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  """Reads or sets the printer door joint."""
  args = parse_args(argv)
  print(f"Connecting to Intrinsic solution at {args.address}...")
  solution = deployments.connect(address=args.address)
  world = solution.world

  object_names = world.list_object_names()
  if PRINTER_OBJECT_NAME not in object_names:
    print(
      f"ERROR: '{PRINTER_OBJECT_NAME}' not found in the belief world."
      f" Available objects: {sorted(object_names)}"
    )
    sys.exit(1)

  printer = world.get_kinematic_object(PRINTER_OBJECT_NAME)
  print(f"Registered joints: {list(printer.joint_entity_names)}")
  print(f"Current positions: {list(printer.joint_positions)}")

  if args.action == "status":
    return

  if args.action == "open":
    target_angle = DOOR_OPEN_ANGLE
  elif args.action == "close":
    target_angle = DOOR_CLOSED_ANGLE
  else:
    target_angle = args.angle

  world.update_joint_positions(printer, [target_angle])
  print(f"[✓] Set belief world door position to {target_angle:.3f} rad.")

  if args.reset_sim and solution.is_simulated:
    if solution.simulator is None:
      print("[-] Warning: no simulator to reset; Gazebo is not updated.")
    else:
      print("[+] Resetting the simulation so Gazebo shows the new position...")
      solution.simulator.reset()
      print("[✓] Simulation reset.")

  printer = world.get_kinematic_object(PRINTER_OBJECT_NAME)
  print(f"Confirmed joint position: {list(printer.joint_positions)}")


if __name__ == "__main__":
  main()
