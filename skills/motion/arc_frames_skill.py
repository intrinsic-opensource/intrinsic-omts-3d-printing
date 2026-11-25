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

"""Skill: write the tool frames for swinging a grip point along an arc.

Stateless. It reads the pivot, grip and radial-origin poses from the world,
computes the frames (skills/motion/arc_math.py) and writes them as children of
the root object in one world update. It never moves a robot; move_robot
targets the frames afterwards.
"""

import re

import grpc
import numpy as np
from intrinsic.math.python import data_types, proto_conversion
from intrinsic.skills.proto import footprint_pb2
from intrinsic.skills.python import skill_interface
from intrinsic.world.proto import (
  object_world_refs_pb2,
  object_world_updates_pb2,
)

from skills.motion import arc_math
from skills.motion import generate_arc_frames_pb2 as pb

INVALID_PARAMS = 2101
MISSING_REFERENCE = 2102
NOT_FOUND = 2103
GRIP_ON_AXIS = 2104
UNDEFINED_AZIMUTH = 2105
WORLD_FAILED = 2106

ROOT = "root"
DEFAULT_PREFIX = "arc"
_PREFIX_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_NOT_FOUND_CODES = (grpc.StatusCode.NOT_FOUND, grpc.StatusCode.INVALID_ARGUMENT)


def _error(code: int, message: str) -> skill_interface.SkillError:
  return skill_interface.SkillError(code, message)


def _root_node() -> object_world_refs_pb2.TransformNodeReference:
  return object_world_refs_pb2.TransformNodeReference(id=ROOT)


def _is_set(ref: object_world_refs_pb2.TransformNodeReference) -> bool:
  return ref.WhichOneof("transform_node_reference") is not None


def _grpc_code(exc: grpc.RpcError):
  code = getattr(exc, "code", None)
  return code() if callable(code) else None


def _grpc_text(exc: grpc.RpcError) -> str:
  details = getattr(exc, "details", None)
  return (details() if callable(details) else None) or str(exc)


def validate(params: pb.GenerateArcFramesParams) -> str:
  """Checks the parameters; returns the frame name prefix."""
  for field in ("pivot_frame", "grip_frame"):
    if not params.HasField(field) or not _is_set(getattr(params, field)):
      raise _error(MISSING_REFERENCE, f"{field} is required")
  n = params.num_waypoints
  if not 1 <= n <= arc_math.MAX_WAYPOINTS:
    raise _error(
      INVALID_PARAMS,
      f"num_waypoints is {n}; it must be in 1..{arc_math.MAX_WAYPOINTS}",
    )
  orientation = params.orientation
  values = {
    "total_angle_deg": params.total_angle_deg,
    "orientation.azimuth_deg": orientation.azimuth_deg,
    "orientation.pitch_deg": orientation.pitch_deg,
    "grip_depth_m": params.grip_depth_m,
    "approach_offset_m": params.approach_offset_m,
  }
  for name, value in values.items():
    if not np.isfinite(value):
      raise _error(INVALID_PARAMS, f"{name} is {value}; it must be finite")
  if abs(params.total_angle_deg) > 360.0:
    raise _error(
      INVALID_PARAMS,
      f"total_angle_deg is {params.total_angle_deg}; |angle| must be <= 360",
    )
  if not -90.0 < orientation.pitch_deg < 90.0:
    raise _error(
      INVALID_PARAMS,
      f"orientation.pitch_deg is {orientation.pitch_deg}; it must be in "
      "(-90, 90)",
    )
  if orientation.mode not in (m.value for m in arc_math.Mode):
    raise _error(INVALID_PARAMS, f"unknown orientation.mode {orientation.mode}")
  prefix = params.frame_prefix or DEFAULT_PREFIX
  if not _PREFIX_RE.fullmatch(prefix):
    raise _error(
      INVALID_PARAMS,
      f"frame_prefix {prefix!r}: use letters, digits and '_', starting with "
      "a letter",
    )
  return prefix


def _root_t(world, field: str, ref) -> np.ndarray:
  """The 4x4 pose of a referenced node in the root frame."""
  try:
    return world.get_transform(node_a=_root_node(), node_b=ref).matrix4x4()
  except grpc.RpcError as exc:
    if _grpc_code(exc) in _NOT_FOUND_CODES:
      raise _error(
        NOT_FOUND, f"{field} ({_describe(ref)}) is not in the world"
      ) from exc
    raise _error(
      WORLD_FAILED, f"reading {field} from the world: {_grpc_text(exc)}"
    ) from exc


def _describe(ref: object_world_refs_pb2.TransformNodeReference) -> str:
  if ref.HasField("by_name"):
    by_name = ref.by_name
    if by_name.HasField("frame"):
      return f"frame {by_name.frame.object_name}.{by_name.frame.frame_name}"
    return f"object {by_name.object.object_name}"
  return f"id {ref.id}"


def compute_frames(
  world, params: pb.GenerateArcFramesParams
) -> list[arc_math.ArcFrame]:
  """Validates the parameters, reads the world, returns the arc's frames."""
  prefix = validate(params)
  root_t_pivot = _root_t(world, "pivot_frame", params.pivot_frame)
  grip_start = _root_t(world, "grip_frame", params.grip_frame)[:3, 3]
  origin = np.zeros(3)
  mode = arc_math.Mode(params.orientation.mode)
  if mode == arc_math.Mode.RADIAL and _is_set(params.radial_origin_frame):
    origin = _root_t(world, "radial_origin_frame", params.radial_origin_frame)[
      :3, 3
    ]
  try:
    return arc_math.arc_frames(
      root_t_pivot,
      grip_start,
      params.total_angle_deg,
      params.num_waypoints,
      mode=mode,
      azimuth_deg=params.orientation.azimuth_deg,
      pitch_deg=params.orientation.pitch_deg,
      grip_depth_m=params.grip_depth_m,
      approach_offset_m=params.approach_offset_m,
      radial_origin=origin,
      prefix=prefix,
    )
  except arc_math.GripOnAxisError as exc:
    radius = arc_math.arc_radius(root_t_pivot, grip_start)
    raise _error(
      GRIP_ON_AXIS,
      f"grip_frame is {radius * 1000:.3f} mm from the pivot axis: no arc",
    ) from exc
  except arc_math.UndefinedAzimuthError as exc:
    raise _error(
      UNDEFINED_AZIMUTH,
      f"RADIAL: {exc}; use FIXED_AZIMUTH or another radial_origin_frame",
    ) from exc
  except ValueError as exc:
    raise _error(INVALID_PARAMS, str(exc)) from exc


def _existing_root_frames(world) -> set[str]:
  try:
    root = world.get_object(object_world_refs_pb2.ObjectReference(id=ROOT))
  except grpc.RpcError as exc:
    raise _error(
      WORLD_FAILED, f"reading the root object: {_grpc_text(exc)}"
    ) from exc
  return set(root.frame_names)


def world_updates(
  frames: list[arc_math.ArcFrame], existing: set[str]
) -> object_world_updates_pb2.ObjectWorldUpdates:
  """Creates each frame under the root object, or moves it if it exists."""
  updates = object_world_updates_pb2.ObjectWorldUpdates()
  for frame in frames:
    pose = proto_conversion.pose_to_proto(
      data_types.Pose3.from_matrix4x4(frame.root_t_tool)
    )
    update = updates.updates.add()
    if frame.name in existing:
      node = object_world_refs_pb2.TransformNodeReference(
        by_name=object_world_refs_pb2.TransformNodeReferenceByName(
          frame=object_world_refs_pb2.FrameReferenceByName(
            object_name=ROOT, frame_name=frame.name
          )
        )
      )
      update.update_transform.node_a.CopyFrom(_root_node())
      update.update_transform.node_b.CopyFrom(node)
      update.update_transform.node_to_update.CopyFrom(node)
      update.update_transform.a_t_b.CopyFrom(pose)
    else:
      create = update.create_frame
      create.parent_object_with_filter.reference.id = ROOT
      create.new_frame_name = frame.name
      create.parent_t_new_frame.CopyFrom(pose)
  return updates


def plan(
  world, params: pb.GenerateArcFramesParams
) -> tuple[
  pb.GenerateArcFramesResult, object_world_updates_pb2.ObjectWorldUpdates
]:
  """The skill's result and the world update that writes its frames."""
  frames = compute_frames(world, params)
  updates = world_updates(frames, _existing_root_frames(world))
  result = pb.GenerateArcFramesResult(
    frame_names=[f.name for f in frames],
    final_angle_deg=params.total_angle_deg,
  )
  return result, updates


class GenerateArcFrames(skill_interface.Skill):
  """Writes pregrasp, grasp, waypoint and retreat frames along an arc."""

  @classmethod
  def required_equipment(cls) -> dict[str, str]:
    return {}

  def get_footprint(self, request, context) -> footprint_pb2.Footprint:
    # It writes frames other skills may be planning against.
    return footprint_pb2.Footprint(lock_the_universe=True)

  def preview(
    self,
    request: skill_interface.PreviewRequest[pb.GenerateArcFramesParams],
    context: skill_interface.PreviewContext,
  ) -> pb.GenerateArcFramesResult:
    result, updates = plan(context.object_world, request.params)
    for update in updates.updates:
      context.record_world_update(update=update, elapsed=0, duration=0)
    return result

  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.GenerateArcFramesParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.GenerateArcFramesResult:
    world = context.object_world
    result, updates = plan(world, request.params)
    try:
      world.batch_update(updates)
    except grpc.RpcError as exc:
      raise _error(
        WORLD_FAILED, f"writing the arc frames: {_grpc_text(exc)}"
      ) from exc
    return result
