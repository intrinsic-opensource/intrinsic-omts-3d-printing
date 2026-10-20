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

"""Simulation-only reBot pick-and-place behavior using world attachments."""

from intrinsic.solutions import behavior_tree as bt

from src.behaviors.motions import create_move_to_frame_task
from src.core.infeed import GridInfeedStrategy
from src.core.types import InfeedMode
from src.hardware.robot import Robot


def _build_transfer(
  robot: Robot,
  workpiece_name: str,
  tool_object_name: str,
  source: str,
  destination: str,
) -> bt.Node:
  collision_pair = (tool_object_name, workpiece_name)
  # The part rests on the ground, so its collision box touches the ground's.
  # Exclude that pair only on the segments at or leaving the ground.
  ground_contact_pairs = [
    collision_pair,
    (workpiece_name, "rebot_ground"),
  ]
  return bt.Sequence(
    name=f"Transfer printed part {source} to {destination}",
    children=[
      create_move_to_frame_task(
        robot=robot,
        frame_name=f"part_{source}_pregrasp",
        parent_object="root",
        motion_type="ANY",
        task_name=f"Approach part at {source}",
      ),
      create_move_to_frame_task(
        robot=robot,
        frame_name=f"part_{source}_grasp",
        parent_object="root",
        motion_type="LINEAR",
        excluded_collision_pairs=[collision_pair],
        task_name=f"Position-only grasp approach at {source}",
      ),
      robot.build_attach_object_task(
        object_name=workpiece_name,
        name=f"Attach printed part at {source}",
      ),
      create_move_to_frame_task(
        robot=robot,
        frame_name=f"part_{source}_pregrasp",
        parent_object="root",
        motion_type="LINEAR",
        excluded_collision_pairs=[collision_pair],
        task_name=f"Retract with attached part from {source}",
      ),
      create_move_to_frame_task(
        robot=robot,
        frame_name=f"part_{destination}_pregrasp",
        parent_object="root",
        motion_type="ANY",
        excluded_collision_pairs=[collision_pair],
        task_name=f"Transit with attached part to {destination}",
      ),
      create_move_to_frame_task(
        robot=robot,
        frame_name=f"part_{destination}_grasp",
        parent_object="root",
        motion_type="LINEAR",
        excluded_collision_pairs=[collision_pair],
        task_name=f"Position-only place approach at {destination}",
      ),
      robot.build_detach_object_task(
        object_name=workpiece_name,
        name=f"Detach printed part at {destination}",
      ),
      create_move_to_frame_task(
        robot=robot,
        frame_name=f"part_{destination}_pregrasp",
        parent_object="root",
        motion_type="LINEAR",
        excluded_collision_pairs=[collision_pair],
        task_name=f"Retract after placing at {destination}",
      ),
    ],
  )


def build_rebot_pick_place_tree(
  robot: Robot,
  infeed_strategy: GridInfeedStrategy,
  tool_object_name: str,
  num_cycles: int = 1,
) -> bt.BehaviorTree:
  """Builds a repeatable A-to-B-to-A transfer using simulated attachments.

  The gripper fingers are intentionally not actuated. Attaching the workpiece
  to the robot after a position-only approach stands in for grasping in sim.
  Each cycle transfers the same grid-infeed part from A to B and back to A.
  """
  if infeed_strategy.mode != InfeedMode.GRID:
    raise ValueError("The reBot demo requires the fixed-pose grid infeed.")

  workpiece = infeed_strategy.get_target_part()
  if workpiece is None:
    raise ValueError("The reBot demo grid has no workpiece to pick.")

  cycle = bt.Sequence(
    name="reBot pick-and-place round trip",
    children=[
      _build_transfer(
        robot,
        workpiece.id,
        tool_object_name,
        source="a",
        destination="b",
      ),
      _build_transfer(
        robot,
        workpiece.id,
        tool_object_name,
        source="b",
        destination="a",
      ),
    ],
  )

  if num_cycles == 1:
    root = cycle
  else:
    root = bt.Loop(
      max_times=num_cycles,
      do_child=cycle,
      name=(
        "Continuous reBot pick-and-place"
        if num_cycles <= 0
        else f"reBot pick-and-place loop ({num_cycles} cycles)"
      ),
    )

  return bt.BehaviorTree(name="reBot Simulation Pick and Place", root=root)
