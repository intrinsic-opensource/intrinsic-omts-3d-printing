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

"""Skill: the grasp and pre-grasp frames for an estimated cuboid.

Step C2 (research/CLUSTER_NATIVE_HANDOFF.md). The rule is
`src/core/grasp_math.py`, which replaces the `bt.PythonScript` of
`src/utils/dynamic_frame_calculator.py`: this skill reads the camera and tool
poses from the belief world, composes the estimate into the parent frame, moves
the part's world object there, checks the minimum height, and publishes the
frames. It changes the belief world only, and cannot be previewed: a preview
world is taken for the real one, and the frames are what a preview of the
following motions needs.
"""

import logging

from intrinsic.math.python import data_types
from intrinsic.math.python import proto_conversion as math_proto_conversion
from intrinsic.skills.proto import footprint_pb2
from intrinsic.skills.python import skill_interface

from skills.grasp import plan_cuboid_grasp_pb2 as pb
from src.core import grasp_math

INVALID_INPUT = 2101
MISSING_WORLD_ENTITY = 2102
TARGET_TOO_LOW = 2103


def _optional(params, field, default):
  return getattr(params, field) if params.HasField(field) else default


def _require(params, *names: str) -> None:
  missing = [name for name in names if not getattr(params, name)]
  if missing:
    raise skill_interface.SkillError(
      INVALID_INPUT, f"Missing parameter(s): {', '.join(missing)}"
    )


def _node(owner, name: str, what: str):
  """A child of a world or an object, by attribute as the script did; a clear
  error if it is not there."""
  try:
    return getattr(owner, name)
  except AttributeError as exc:
    raise skill_interface.SkillError(
      MISSING_WORLD_ENTITY, f"{what} '{name}' is not in the world"
    ) from exc


def _quat(pose: data_types.Pose3) -> grasp_math.Quat:
  q = pose.rotation.quaternion
  return (float(q.x), float(q.y), float(q.z), float(q.w))


def _pose(position, orientation) -> data_types.Pose3:
  return data_types.Pose3(
    data_types.Rotation3(data_types.Quaternion(list(orientation))),
    list(position),
  )


class PlanCuboidGrasp(skill_interface.Skill):
  def get_footprint(self, request, context) -> footprint_pb2.Footprint:
    # It moves a world object and frames, which `update_world` also reserves by
    # locking the world when it cannot name them (executive error 18201 if it
    # runs in a `bt.Parallel`).
    return footprint_pb2.Footprint(lock_the_universe=True)

  def preview(self, request, context):
    raise NotImplementedError(
      "plan_cuboid_grasp changes the belief world, which a preview cannot"
    )

  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.PlanCuboidGraspParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.PlanCuboidGraspResult:
    params = request.params
    _require(
      params,
      "camera_name",
      "parent_object",
      "pregrasp_frame_name",
      "grasp_frame_name",
      "tool_object_name",
      "tool_frame_name",
    )
    if not params.HasField("camera_t_target"):
      raise skill_interface.SkillError(
        INVALID_INPUT, "camera_t_target is unset"
      )
    tilt = _optional(params, "approach_tilt_degrees", 0.0)
    symmetry = _optional(params, "yaw_symmetry_degrees", 180.0)
    if not 0.0 <= tilt < 90.0:
      raise skill_interface.SkillError(
        INVALID_INPUT, "approach_tilt_degrees must be in [0, 90)"
      )
    if symmetry not in (90.0, 180.0):
      raise skill_interface.SkillError(
        INVALID_INPUT, "yaw_symmetry_degrees must be 90 or 180"
      )
    if params.approach_offset_z < 0.0:
      raise skill_interface.SkillError(
        INVALID_INPUT, "approach_offset_z must not be negative"
      )

    world = context.object_world
    parent = _node(world, params.parent_object, "Parent object")
    camera = _node(world, params.camera_name, "Camera object")
    sensor = getattr(camera, "sensor", camera)

    # The estimate is in the camera's frame; the world gives where that is.
    parent_t_camera = world.get_transform(parent, sensor)
    camera_t_target = math_proto_conversion.pose_from_proto(
      params.camera_t_target
    )
    parent_t_target = (
      parent_t_camera * camera_t_target
      if parent_t_camera is not None
      else camera_t_target
    )
    position = tuple(float(v) for v in parent_t_target.translation)
    if position[2] < params.min_safe_z:
      raise skill_interface.SkillError(
        TARGET_TOO_LOW,
        f"The part's height {position[2]:.4f} m is below the minimum safe "
        f"height {params.min_safe_z:.4f} m",
      )

    if params.target_scene_object_id:
      self._move_target(
        world, parent, params.target_scene_object_id, parent_t_target
      )

    result = pb.PlanCuboidGraspResult(
      parent_t_target=math_proto_conversion.pose_to_proto(parent_t_target)
    )
    if not _optional(params, "publish_grasp_frames", True):
      return result

    tool = getattr(
      getattr(world, params.tool_object_name, None),
      params.tool_frame_name,
      None,
    )
    parent_t_tool = (
      world.get_transform(parent, tool) if tool is not None else None
    )
    grasp = grasp_math.cuboid_grasp(
      position,
      _quat(parent_t_target),
      params.approach_offset_z,
      tool_orientation=_quat(parent_t_tool)
      if parent_t_tool is not None
      else None,
      approach_tilt_degrees=tilt,
      yaw_symmetry_degrees=symmetry,
    )
    for name, pose in (
      (
        params.pregrasp_frame_name,
        _pose(grasp.pregrasp_position, grasp.orientation),
      ),
      (params.grasp_frame_name, _pose(grasp.grasp_position, grasp.orientation)),
    ):
      self._publish_frame(world, parent, name, pose)
    result.parent_t_grasp.CopyFrom(
      math_proto_conversion.pose_to_proto(
        _pose(grasp.grasp_position, grasp.orientation)
      )
    )
    result.parent_t_pregrasp.CopyFrom(
      math_proto_conversion.pose_to_proto(
        _pose(grasp.pregrasp_position, grasp.orientation)
      )
    )
    logging.info(
      "Grasp for the part at %s: tilt %.0f deg, grasp %s",
      position,
      tilt,
      grasp.grasp_position,
    )
    return result

  @staticmethod
  def _move_target(world, parent, target_id: str, parent_t_target) -> None:
    """Moves the part's world object to its estimated pose. A missing object
    is skipped, as the script did: it is only a stand-in for the part."""
    target = getattr(world, target_id, None) or getattr(
      world, target_id.split(".")[-1], None
    )
    if target is None:
      logging.warning("No world object %s to move to the part", target_id)
      return
    world.update_transform(
      node_a=parent,
      node_b=target,
      a_t_b=parent_t_target,
      node_to_update=target,
    )

  @staticmethod
  def _publish_frame(world, parent, name: str, pose: data_types.Pose3) -> None:
    """Moves the frame if it exists under the parent, else creates it."""
    if name in parent.frame_names:
      world.update_transform(
        node_a=parent, node_b=parent.get_frame(name), a_t_b=pose
      )
    else:
      world.create_frame(frame_name=name, parent=parent, parent_t_frame=pose)
