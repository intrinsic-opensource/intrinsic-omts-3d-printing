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

"""Opens the printer door with one behavior tree of installed skills.

Only the pinch gripper adapter's short dwell after each gripper command is not a
skill (a PythonScript sleep).

The tree is src/behaviors/open_door.py's (look at the marker, locate the
printer, generate the arc frames with ai.omts.generate_arc_frames, grasp the D
handle, swing the door, longest plannable swing first, release and back off),
built from the `door` section of the cell config. This tool only builds it,
runs it (or dumps it) and prints the belief door angle it left. Simulation
only: it moves the arm. The door must be closed when it starts.

  bazel run //tools/printer:open_door_bt -- --address=localhost:17080
  bazel run //tools/printer:open_door_bt -- --dump=/tmp/open_door.textproto

--dump writes the tree as a text BehaviorTree proto and runs nothing; --no_run
builds the tree against the deployed skills and prints its outline.
"""

import argparse
import dataclasses
import math
import os
import pathlib
import sys
from collections.abc import Sequence
from typing import Any

from google.protobuf import text_format
from intrinsic.executive.proto import behavior_tree_pb2
from intrinsic.solutions import behavior_tree as bt
from intrinsic.solutions import deployments, execution

from src.behaviors.open_door import build_open_door_tree
from src.core.config import AppConfig, DoorConfig, load_app_config
from src.hardware.gripper import (
  DioGripper,
  GripperInterface,
  PinchGripper,
  RobotiqGripper,
)
from src.hardware.robot import Robot

TREE_NAME = "Open the printer door"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument("--config", default="configs/rebot/app_config.yaml")
  parser.add_argument(
    "--target_deg",
    type=float,
    default=None,
    help="Override door.target_deg (fallback angles beyond it are skipped).",
  )
  parser.add_argument(
    "--dump",
    default=None,
    metavar="PATH",
    help="Write the tree as a text BehaviorTree proto to PATH; do not run.",
  )
  parser.add_argument(
    "--no_run",
    action="store_true",
    help="Build the tree and print its outline; do not run.",
  )
  return parser.parse_args(argv)


def door_config(config: AppConfig, target_deg: float | None) -> DoorConfig:
  """The config's door section, with the target overridden if given."""
  if config.door is None:
    raise SystemExit(f"Cell '{config.cell_name}' has no 'door' section.")
  if target_deg is None:
    return config.door
  return dataclasses.replace(config.door, target_deg=target_deg)


def build_gripper(solution: Any, config: AppConfig) -> GripperInterface:
  """The gripper adapter for the cell, as omts_app builds it."""
  if config.gripper.type == "dio":
    return DioGripper(solution=solution, config=config.gripper)
  if config.gripper.type == "pinch":
    return PinchGripper(solution=solution, config=config.gripper)
  return RobotiqGripper(solution=solution, config=config.gripper)


def build_tree(
  solution: Any, config: AppConfig, door_cfg: DoorConfig
) -> bt.BehaviorTree:
  """The door-opening behavior tree for the connected solution."""
  root = build_open_door_tree(
    solution,
    Robot(solution=solution, config=config.robot),
    build_gripper(solution, config),
    door_cfg,
    tool_object_name=config.robot.tool_object_name,
    name=TREE_NAME,
  )
  return bt.BehaviorTree(name=TREE_NAME, root=root)


def resolve_output_path(path: str) -> pathlib.Path:
  """A relative path is relative to where `bazel run` was started."""
  out = pathlib.Path(path)
  if out.is_absolute():
    return out
  return pathlib.Path(os.environ.get("BUILD_WORKING_DIRECTORY", ".")) / out


def dump_tree(tree_proto: behavior_tree_pb2.BehaviorTree, path: str) -> str:
  """Writes the tree as a text proto; returns the path written."""
  out = resolve_output_path(path)
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(text_format.MessageToString(tree_proto), encoding="utf-8")
  return str(out)


def outline(
  node: behavior_tree_pb2.BehaviorTree.Node, depth: int = 0
) -> list[str]:
  """One line per node: its name and, for a skill, the skill id."""
  pad = "  " * depth
  kind = node.WhichOneof("node_type") or "?"
  line = f"{pad}{node.name or '(unnamed)'} [{kind}"
  if kind == "task" and node.task.HasField("call_behavior"):
    line += f" {node.task.call_behavior.skill_id}"
  lines = [line + "]"]
  if kind == "sequence":
    children = list(node.sequence.children)
  elif kind == "fallback":
    children = [t.node for t in node.fallback.tries] + list(
      node.fallback.children
    )
  else:
    children = []
  for child in children:
    lines += outline(child, depth + 1)
  return lines


def door_angle_deg(solution: Any, door_cfg: DoorConfig) -> float:
  """The belief door angle, degrees open."""
  printer = solution.world.get_kinematic_object(door_cfg.printer_object_name)
  names = list(printer.joint_entity_names)
  q = float(printer.joint_positions[names.index(door_cfg.hinge_joint_name)])
  return math.degrees(door_cfg.hinge_closed_q - q)


def main(argv: Sequence[str] | None = None) -> int:
  args = parse_args(argv)
  config = load_app_config(args.config)
  door_cfg = door_config(config, args.target_deg)
  solution = deployments.connect(address=args.address)
  tree = build_tree(solution, config, door_cfg)
  if args.dump is not None:
    print(f"Wrote {dump_tree(tree.proto, args.dump)}")
    return 0
  if args.no_run:
    print("\n".join(outline(tree.proto.root)))
    return 0
  print(
    f"Opening the door to {door_cfg.target_deg:g} deg (fallbacks"
    f" {list(door_cfg.fallback_deg)})..."
  )
  ok = True
  try:
    solution.executive.run(tree)
  except execution.ExecutionFailedError as e:
    ok = False
    print(f"[!] The tree failed: {e}")
  angle = door_angle_deg(solution, door_cfg)
  print(f"Belief door angle: {angle:.1f} deg (target {door_cfg.target_deg:g})")
  return 0 if ok else 1


if __name__ == "__main__":
  sys.exit(main())
