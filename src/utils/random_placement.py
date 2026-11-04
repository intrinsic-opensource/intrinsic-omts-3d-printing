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

"""Dynamic frame shifting for return infeed positioning."""

from typing import Any


def randomize_placement_frame(context: Any, params: Any) -> None:
  """Shifts the return frame to a random position within a bounding box centered at a fixed position.

  With a grasp frame, the grasp is placed at the shifted position and the
  return (pre-grasp) frame keeps its offset from it, rotated by the same yaw.

  Args:
      context: SBL BT PythonScript execution context providing `object_world`.
      params: Dynamic parameters protobuf containing shift configuration.
  """
  parent_object = params.parent_object
  frame_name = params.frame_name
  return_center_x = params.return_center_x
  return_center_y = params.return_center_y
  return_bounds_x = params.return_bounds_x
  return_bounds_y = params.return_bounds_y
  return_bounds_rz_degrees = params.return_bounds_rz_degrees
  grasp_frame_name = getattr(params, "grasp_frame_name", None)
  import math
  import random

  from intrinsic.math.python import data_types

  world = context.object_world
  parent_obj = getattr(world, parent_object, getattr(world, "root", None))
  frame_node = getattr(parent_obj, frame_name)

  # Get current transform to preserve Z and orientation
  parent_t_frame = world.get_transform(parent_obj, frame_node)
  pos = parent_t_frame.translation
  rot = parent_t_frame.rotation

  # Calculate random offsets within bounds
  half_bound_x = return_bounds_x / 2.0
  half_bound_y = return_bounds_y / 2.0

  shift_x = max(
    [random.uniform(-half_bound_x, half_bound_x) for _ in range(5)], key=abs
  )
  shift_y = max(
    [random.uniform(-half_bound_y, half_bound_y) for _ in range(5)], key=abs
  )

  # Apply random shift to the fixed center position
  new_x = return_center_x + shift_x
  new_y = return_center_y + shift_y
  new_z = float(pos[2])

  # Calculate random rotation around Z-axis
  half_bound_rz = return_bounds_rz_degrees / 2.0
  shift_rz_degrees = max(
    [random.uniform(-half_bound_rz, half_bound_rz) for _ in range(5)], key=abs
  )
  shift_rz_radians = math.radians(shift_rz_degrees)

  shift_rotation = data_types.Rotation3.from_euler_angles(
    rpy_radians=[0, 0, shift_rz_radians]
  )

  new_rot = shift_rotation * rot

  grasp_node = (
    getattr(parent_obj, grasp_frame_name, None)
    if grasp_frame_name and grasp_frame_name != frame_name
    else None
  )
  if grasp_node is None:
    new_pose = data_types.Pose3(new_rot, [new_x, new_y, new_z])
    world.update_transform(node_a=parent_obj, node_b=frame_node, a_t_b=new_pose)
    return

  # The grasp lands on the shifted position; the pre-grasp keeps its offset
  # from the grasp, turned by the same rotation, so a tilted approach stays
  # tilted (a vertical one is unchanged).
  parent_t_grasp = world.get_transform(parent_obj, grasp_node)
  grasp_pos = parent_t_grasp.translation
  offset = shift_rotation.rotate_point(
    [float(pos[i]) - float(grasp_pos[i]) for i in range(3)]
  )
  grasp_z = float(grasp_pos[2])
  pregrasp_pose = data_types.Pose3(
    new_rot,
    [
      new_x + float(offset[0]),
      new_y + float(offset[1]),
      grasp_z + float(offset[2]),
    ],
  )
  world.update_transform(
    node_a=parent_obj, node_b=frame_node, a_t_b=pregrasp_pose
  )
  grasp_pose = data_types.Pose3(new_rot, [new_x, new_y, grasp_z])
  world.update_transform(node_a=parent_obj, node_b=grasp_node, a_t_b=grasp_pose)
