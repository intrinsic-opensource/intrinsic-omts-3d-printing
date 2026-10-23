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


"""Picks an object using planner-generated grasp frames and returns it home.

No geometry is computed here by hand:
  * Grasp/pre-grasp come from the grasp planner (moveit_plan_grasp_and_move
    writes root/grasp and root/pre_grasp).
  * The place pose is the object's pose in init_world (its original pose),
    composed with the planned object->grasp transform via SDK Pose3 math.
  * Collision-free trajectories are planned by the move_robot skill.

  open -> pre-grasp -> grasp (linear) -> close -> attach -> pre-grasp (linear)
  -> pre-place -> place (linear) -> open -> detach -> pre-place (linear)
"""

import argparse
from collections.abc import Sequence

from intrinsic.math.python import data_types
from intrinsic.solutions import behavior_tree as bt
from intrinsic.solutions import deployments
from intrinsic.solutions import worlds

from src.core.config import load_app_config
from src.hardware.gripper import RobotiqGripper
from src.hardware.robot import Robot


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  """Parses command line arguments."""
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument("--config", default="configs/omts/app_config.yaml")
  parser.add_argument("--object", default="raw_stock_2x3x5")
  parser.add_argument("--grasp_frame", default="grasp")
  parser.add_argument("--pregrasp_frame", default="pre_grasp")
  parser.add_argument(
    "--plan_only",
    action="store_true",
    help="Only create the place frames; do not move the robot.",
  )
  return parser.parse_args(argv)


def _set_frame(world, name: str, pose: data_types.Pose3) -> None:
  """Creates or moves a frame on root."""
  if name in world.root.frame_names:
    world.update_transform(world.root, getattr(world.root, name), pose)
  else:
    world.create_frame(name, world.root, pose)


def main(argv: Sequence[str] | None = None) -> None:
  """Builds the place frames and runs the pick-and-place behavior tree."""
  args = parse_args(argv)
  config = load_app_config(args.config)
  solution = deployments.connect(address=args.address)
  world = solution.world
  init_world = worlds.ObjectWorld.connect(
    worlds.EditWorldId.INITIAL, solution.grpc_channel
  )

  obj = world.get_object(args.object)
  grasp = getattr(world.root, args.grasp_frame)
  pre_grasp = getattr(world.root, args.pregrasp_frame)
  obj_t_grasp = world.get_transform(obj, grasp)
  obj_t_pregrasp = world.get_transform(obj, pre_grasp)
  root_t_home = init_world.get_transform(
    init_world.root, init_world.get_object(args.object)
  )
  _set_frame(world, "pp_place", root_t_home * obj_t_grasp)
  _set_frame(world, "pp_pre_place", root_t_home * obj_t_pregrasp)
  for name in (args.pregrasp_frame, args.grasp_frame, "pp_pre_place", "pp_place"):
    print(f"root/{name}: {world.get_transform(world.root, getattr(world.root, name))}")
  if args.plan_only:
    return

  robot = Robot(solution=solution, config=config.robot)
  gripper = RobotiqGripper(solution=solution, config=config.gripper)
  held = [(config.robot.tool_object_name, args.object)]
  carry = held + [(args.object, "printer"), (args.object, "enclosure")]

  def move(frame, motion, excluded=None):
    return robot.build_move_cartesian_task(
      target_frame_name=frame,
      target_object_name="root",
      motion_type=motion,
      excluded_collision_pairs=excluded,
    )

  tree = bt.BehaviorTree(
    name="Pick and return home",
    root=bt.Sequence(
      name="pick_and_place",
      children=[
        gripper.build_open_task(),
        move(args.pregrasp_frame, "ANY"),
        move(args.grasp_frame, "LINEAR", held),
        gripper.build_close_task(),
        robot.build_attach_object_task(object_name=args.object),
        move(args.pregrasp_frame, "LINEAR", carry),
        move("pp_pre_place", "ANY", carry),
        move("pp_place", "LINEAR", carry),
        gripper.build_open_task(),
        robot.build_detach_object_task(object_name=args.object),
        move("pp_pre_place", "LINEAR", held),
      ],
    ),
  )
  solution.executive.run(tree)
  print("[✓] Pick and place finished.")


if __name__ == "__main__":
  main()
