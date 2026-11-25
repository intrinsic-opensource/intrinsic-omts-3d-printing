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


"""Behavior Tree subtree releasing the picked part on the outfeed line."""

import dataclasses

from intrinsic.solutions import behavior_tree as bt

from src.behaviors.load_machine import build_load_machine_subtree
from src.behaviors.motions import (
  create_move_through_frames_task,
  create_move_to_frame_task,
)
from src.core.config import AppConfig
from src.hardware.gripper import GripperInterface
from src.hardware.robot import Robot


def build_release_to_outfeed_subtree(
  robot: Robot,
  gripper: GripperInterface,
  config: AppConfig,
  spot_index: int = 0,
) -> bt.Node:
  """Builds the subtree carrying the picked part to an outfeed spot.

  Sequence:
  1. Set the part down at the spot and release it. This is the machine load
     subtree on the spot's frames (blended transit through `transit_frame` and the
     outfeed's own transit frame, approach, press onto the support, open, detach,
     blended exit).
  2. Move back to `view_frame`, ready for the next pick, through the outfeed's
     transit frame if it has one.

  Args:
      robot: Robot controller adapter.
      gripper: End-effector gripper adapter.
      config: Validated application configuration with an `outfeed` section.
      spot_index: Which spot of the line to release at.

  Returns:
      Behavior tree sequence releasing the part and returning to `view`.
  """
  if config.outfeed is None:
    raise ValueError("The outfeed subtree needs an 'outfeed' config section")
  spot = config.outfeed.spots[spot_index]
  transit = config.outfeed.transit_frame
  spot_frames = dataclasses.replace(
    config.frames,
    machine_approach_frame=spot.approach_frame,
    preplace_vise_frame=spot.preplace_frame,
    place_vise_frame=spot.place_frame,
  )
  # The load subtree excludes the printer from collision checking when the cell
  # has an enclosure, so the arm can reach into a machine. The outfeed is outside
  # the printer, next to it: the planner must check the printer against the
  # gripper and the held part, or it plans through the printer's corner.
  outside = dataclasses.replace(config.robot, enclosure_object_name=None)
  release = build_load_machine_subtree(
    robot=robot,
    gripper=gripper,
    machine=None,
    config=dataclasses.replace(
      config, frames=spot_frames, machine=None, robot=outside
    ),
    extra_entry_frames=[transit] if transit else [],
  )
  # Back to view the way it came: through the transit frame, out of the
  # printer's corner.
  back = [transit, config.frames.view_frame] if transit else None
  to_view = (
    create_move_through_frames_task(
      robot=robot,
      frame_names=back,
      parent_object=config.frames.parent_object,
      config=config,
      motion_type="ANY",
      task_name=f"Return to {config.frames.view_frame} via {transit}",
    )
    if back
    else create_move_to_frame_task(
      robot=robot,
      frame_name=config.frames.view_frame,
      parent_object=config.frames.parent_object,
      config=config,
      task_name=f"Return to {config.frames.view_frame}",
    )
  )
  return bt.Sequence(
    name=f"Release at Outfeed Spot {spot_index}", children=[release, to_view]
  )
