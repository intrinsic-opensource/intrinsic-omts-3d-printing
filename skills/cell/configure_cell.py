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

"""Skill: configure the live cell: the printer, the camera mount, the view, A.

Step C4 (research/CLUSTER_NATIVE_HANDOFF.md). The geometry of
`research/tools/configure_cell.py`, read from the live world instead of the
checkout: the camera's pose relative to the printer at `view` is kept when the
printer moves (the camera follows it by the same distance) and when the mount
changes (the arm's pose for `view` is solved again). It changes the belief
world only, in one `UpdateWorldResources` call, and cannot be previewed.

The target and the parked objects are reparented to the parent and placed, in
the same update; the bed is where the printer is after the call.

A's frames (`drop_off`) come from `src/core/drop_off.py`, plain geometry that a
test keeps equal to `research/tools/a_frames.py`.

The checks of `research/tools/cell_checks.py` (reach, clearance) are design-time
analysis and stay a host tool: run them first.
"""

import logging
import math

from intrinsic.math.python import data_types
from intrinsic.math.python import proto_conversion as math_proto_conversion
from intrinsic.skills.proto import footprint_pb2
from intrinsic.skills.python import skill_interface
from intrinsic.world.proto import (
  object_world_refs_pb2,
  object_world_updates_pb2,
)

from skills.cell import configure_cell_pb2 as pb
from src.core import drop_off

INVALID_INPUT = 2201
MISSING_WORLD_ENTITY = 2202

# Bounds that catch a value in the wrong unit (millimetres for metres).
_MAX_PRINTER_DISTANCE_M = 3.0
_MAX_CAMERA_OFFSET_M = 0.5
_MAX_DROP_OFF_RADIUS_M = 2.0
_MAX_PART_HALF_HEIGHT_M = 0.25
_MAX_GRASP_DEPTH_M = 0.1
_MAX_BED_OFFSET_M = 0.5
_MAX_PARKING_DISTANCE_M = 3.0
# A part on its side: model z along the world x axis, a quarter turn about y.
_LYING = (0.0, math.sqrt(0.5), 0.0, math.sqrt(0.5))
_UPRIGHT = (0.0, 0.0, 0.0, 1.0)


def _optional(params, field, default):
  return getattr(params, field) if params.HasField(field) else default


def _node(owner, name: str, what: str):
  try:
    return getattr(owner, name)
  except AttributeError as exc:
    raise skill_interface.SkillError(
      MISSING_WORLD_ENTITY, f"{what} '{name}' is not in the world"
    ) from exc


def _frame_of(obj, name: str, what: str):
  """A frame of an object, by attribute."""
  try:
    return getattr(obj, name)
  except AttributeError as exc:
    raise skill_interface.SkillError(
      MISSING_WORLD_ENTITY, f"{what} '{name}' is not in the world"
    ) from exc


def _object_ref(name: str):
  return object_world_refs_pb2.TransformNodeReference(
    by_name=object_world_refs_pb2.TransformNodeReferenceByName(
      object=object_world_refs_pb2.ObjectReferenceByName(object_name=name)
    )
  )


def _frame_ref(object_name: str, frame_name: str):
  return object_world_refs_pb2.TransformNodeReference(
    by_name=object_world_refs_pb2.TransformNodeReferenceByName(
      frame=object_world_refs_pb2.FrameReferenceByName(
        object_name=object_name, frame_name=frame_name
      )
    )
  )


def _create_frame(parent_name: str, frame_name: str, parent_t_frame):
  return object_world_updates_pb2.ObjectWorldUpdate(
    create_frame=object_world_updates_pb2.CreateFrameRequest(
      new_frame_name=frame_name,
      parent_t_new_frame=math_proto_conversion.pose_to_proto(parent_t_frame),
      parent_object_with_filter=object_world_refs_pb2.ObjectReferenceWithEntityFilter(
        reference=object_world_refs_pb2.ObjectReference(
          by_name=object_world_refs_pb2.ObjectReferenceByName(
            object_name=parent_name
          )
        )
      ),
    )
  )


def _reparent(object_name: str, parent_name: str):
  """Makes the object a child of the parent, so it is not carried by whatever it
  was attached to."""
  return object_world_updates_pb2.ObjectWorldUpdate(
    reparent_object=object_world_updates_pb2.ReparentObjectRequest(
      object=object_world_refs_pb2.ObjectReference(
        by_name=object_world_refs_pb2.ObjectReferenceByName(
          object_name=object_name
        )
      ),
      parent_object=object_world_refs_pb2.ObjectReferenceWithEntityFilter(
        reference=object_world_refs_pb2.ObjectReference(
          by_name=object_world_refs_pb2.ObjectReferenceByName(
            object_name=parent_name
          )
        ),
        entity_filter=object_world_refs_pb2.ObjectEntityFilter(
          include_base_entity=True
        ),
      ),
    )
  )


def _unit_pose(position, quaternion) -> data_types.Pose3:
  """A pose from a computed quaternion, which the SDK takes only if it is a
  unit one to within rounding."""
  norm = sum(c * c for c in quaternion) ** 0.5
  return data_types.Pose3(
    data_types.Rotation3(data_types.Quaternion([c / norm for c in quaternion])),
    [float(v) for v in position],
  )


def _update(node_a, node_b, a_t_b: data_types.Pose3):
  """Sets the pose of node_b (a child of node_a) in node_a."""
  return object_world_updates_pb2.ObjectWorldUpdate(
    update_transform=object_world_updates_pb2.UpdateTransformRequest(
      node_a=node_a,
      node_b=node_b,
      node_to_update=node_b,
      a_t_b=math_proto_conversion.pose_to_proto(a_t_b),
    )
  )


def _shifted(
  pose: data_types.Pose3, dx=0.0, dy=0.0, dz=0.0
) -> data_types.Pose3:
  t = pose.translation
  return data_types.Pose3(
    pose.rotation, [float(t[0]) + dx, float(t[1]) + dy, float(t[2]) + dz]
  )


def _with_position(pose: data_types.Pose3, position) -> data_types.Pose3:
  return data_types.Pose3(pose.rotation, [float(v) for v in position])


class ConfigureCell(skill_interface.Skill):
  def get_footprint(self, request, context) -> footprint_pb2.Footprint:
    return footprint_pb2.Footprint(lock_the_universe=True)

  def preview(self, request, context):
    raise NotImplementedError(
      "configure_cell changes the belief world, which a preview cannot"
    )

  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.ConfigureCellParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.ConfigureCellResult:
    params = request.params
    parent_name = _optional(params, "parent_object", "root")
    printer_name = _optional(params, "printer_object", "printer")
    camera_name = _optional(params, "camera_object", "orbbec_camera")
    robot_name = _optional(params, "robot_object", "rebot")
    flange_name = _optional(params, "flange_frame", "flange")
    tool_name = _optional(params, "tool_object", "gripper")
    tool_frame_name = _optional(params, "tool_frame", "tool_frame")
    view_name = _optional(params, "view_frame", "view")
    follow_view = _optional(params, "follow_view", True)
    for label, value in (
      ("parent_object", parent_name),
      ("printer_object", printer_name),
      ("camera_object", camera_name),
      ("robot_object", robot_name),
      ("flange_frame", flange_name),
      ("tool_object", tool_name),
      ("tool_frame", tool_frame_name),
      ("view_frame", view_name),
    ):
      if not value:
        raise skill_interface.SkillError(INVALID_INPUT, f"{label} is empty")

    new_distance = (
      params.printer_distance_m
      if params.HasField("printer_distance_m")
      else None
    )
    if (
      new_distance is not None
      and not 0.0 < new_distance <= _MAX_PRINTER_DISTANCE_M
    ):
      raise skill_interface.SkillError(
        INVALID_INPUT,
        f"printer_distance_m {new_distance} is outside (0, "
        f"{_MAX_PRINTER_DISTANCE_M}] m",
      )
    new_offset = None
    if params.HasField("camera_offset_m"):
      offset = params.camera_offset_m
      new_offset = (offset.x, offset.y, offset.z)
      if any(abs(v) > _MAX_CAMERA_OFFSET_M for v in new_offset):
        raise skill_interface.SkillError(
          INVALID_INPUT,
          f"camera_offset_m {new_offset} has a component over "
          f"{_MAX_CAMERA_OFFSET_M} m",
        )

    drop = params.drop_off if params.HasField("drop_off") else None
    if drop is not None:
      self._check_drop_off(drop)
    target = params.target if params.HasField("target") else None
    self._check_placements(target, params.parked)

    world = context.object_world
    parent = _node(world, parent_name, "Parent object")
    printer = _node(world, printer_name, "Printer object")
    camera = _node(world, camera_name, "Camera object")
    robot = _node(world, robot_name, "Robot object")
    flange = _frame_of(robot, flange_name, "Flange frame")
    tool = _frame_of(
      _node(world, tool_name, "Tool object"), tool_frame_name, "Tool frame"
    )

    parent_t_printer = world.get_transform(parent, printer)
    flange_t_camera = world.get_transform(flange, camera)
    new_flange_t_camera = (
      _with_position(flange_t_camera, new_offset)
      if new_offset is not None
      else flange_t_camera
    )
    new_parent_t_printer = (
      _with_position(
        parent_t_printer,
        [
          new_distance,
          parent_t_printer.translation[1],
          parent_t_printer.translation[2],
        ],
      )
      if new_distance is not None
      else parent_t_printer
    )

    updates = []
    if new_distance is not None:
      updates.append(
        _update(
          _object_ref(parent_name),
          _object_ref(printer_name),
          new_parent_t_printer,
        )
      )
    if new_offset is not None:
      updates.append(
        _update(
          _frame_ref(robot_name, flange_name),
          _object_ref(camera_name),
          new_flange_t_camera,
        )
      )

    result = pb.ConfigureCellResult(
      parent_t_printer=math_proto_conversion.pose_to_proto(
        new_parent_t_printer
      ),
      parent_t_camera=math_proto_conversion.pose_to_proto(
        world.get_transform(parent, camera)
      ),
    )
    if follow_view and (new_distance is not None or new_offset is not None):
      view = _frame_of(parent, view_name, "View frame")
      parent_t_view = world.get_transform(parent, view)
      tool_t_camera = world.get_transform(tool, camera)
      tool_t_flange = world.get_transform(tool, flange)
      # Where the view puts the camera now, moved with the printer, and the
      # view that puts the camera there with the new mount.
      parent_t_camera_at_view = parent_t_view * tool_t_camera
      dx = float(new_parent_t_printer.translation[0]) - float(
        parent_t_printer.translation[0]
      )
      new_tool_t_camera = tool_t_flange * new_flange_t_camera
      new_parent_t_view = _shifted(parent_t_camera_at_view, dx=dx) * (
        new_tool_t_camera.inverse()
      )
      updates.append(
        _update(
          _object_ref(parent_name),
          _frame_ref(parent_name, view_name),
          new_parent_t_view,
        )
      )
      result.parent_t_view.CopyFrom(
        math_proto_conversion.pose_to_proto(new_parent_t_view)
      )

    if drop is not None:
      self._drop_off_updates(parent, parent_name, drop, updates, result)
    if target is not None or params.parked:
      for name in [target.object_name] if target is not None else []:
        _node(world, name, "Part object")
      for parked in params.parked:
        _node(world, parked.object_name, "Parked object")
    if target is not None:
      # The bed is where the printer is after this call.
      bed = new_parent_t_printer * _unit_pose(
        (
          target.bed_top_in_printer_m.x,
          target.bed_top_in_printer_m.y,
          target.bed_top_in_printer_m.z,
        ),
        _UPRIGHT,
      )
      position = bed.translation
      part = _unit_pose(
        (
          float(position[0]),
          float(position[1]),
          float(position[2]) + target.part_half_height_m,
        ),
        _LYING if _optional(target, "lying", False) else _UPRIGHT,
      )
      updates.append(_reparent(target.object_name, parent_name))
      updates.append(
        _update(_object_ref(parent_name), _object_ref(target.object_name), part)
      )
      result.parent_t_part.CopyFrom(math_proto_conversion.pose_to_proto(part))
    for parked in params.parked:
      updates.append(_reparent(parked.object_name, parent_name))
      updates.append(
        _update(
          _object_ref(parent_name),
          _object_ref(parked.object_name),
          _unit_pose(
            (parked.position_m.x, parked.position_m.y, parked.position_m.z),
            _UPRIGHT,
          ),
        )
      )

    if updates:
      world.batch_update(
        object_world_updates_pb2.ObjectWorldUpdates(updates=updates)
      )
      # The camera's pose in the parent follows the printer move or the mount.
      result.parent_t_camera.CopyFrom(
        math_proto_conversion.pose_to_proto(world.get_transform(parent, camera))
      )
    logging.info(
      "Configured the cell: printer distance %s, camera offset %s, view %s",
      new_distance,
      new_offset,
      "moved" if result.HasField("parent_t_view") else "kept",
    )
    return result

  @staticmethod
  def _check_placements(target, parked) -> None:
    names = [p.object_name for p in parked]
    if target is not None:
      names.append(target.object_name)
      if not 0.0 < target.part_half_height_m <= _MAX_PART_HALF_HEIGHT_M:
        raise skill_interface.SkillError(
          INVALID_INPUT,
          f"target.part_half_height_m {target.part_half_height_m} is outside "
          f"(0, {_MAX_PART_HALF_HEIGHT_M}] m (half the part's height)",
        )
      bed = target.bed_top_in_printer_m
      if not target.HasField("bed_top_in_printer_m") or any(
        not math.isfinite(v) or abs(v) > _MAX_BED_OFFSET_M
        for v in (bed.x, bed.y, bed.z)
      ):
        raise skill_interface.SkillError(
          INVALID_INPUT,
          "target.bed_top_in_printer_m must be set, with each component "
          f"within {_MAX_BED_OFFSET_M} m (the heatbed's top centre in the "
          "printer's frame)",
        )
    for p in parked:
      pos = p.position_m
      if any(
        not math.isfinite(v) or abs(v) > _MAX_PARKING_DISTANCE_M
        for v in (pos.x, pos.y, pos.z)
      ):
        raise skill_interface.SkillError(
          INVALID_INPUT,
          f"parked '{p.object_name}' has a position over "
          f"{_MAX_PARKING_DISTANCE_M} m",
        )
    if not all(names) or len(set(names)) != len(names):
      raise skill_interface.SkillError(
        INVALID_INPUT,
        "target and parked objects need different, non-empty names",
      )

  @staticmethod
  def _check_drop_off(drop) -> None:
    if not 0.0 <= drop.approach_tilt_degrees < 90.0:
      raise skill_interface.SkillError(
        INVALID_INPUT, "drop_off.approach_tilt_degrees must be in [0, 90)"
      )
    if not 0.0 < drop.radius_m <= _MAX_DROP_OFF_RADIUS_M:
      raise skill_interface.SkillError(
        INVALID_INPUT,
        f"drop_off.radius_m {drop.radius_m} is outside (0, "
        f"{_MAX_DROP_OFF_RADIUS_M}] m",
      )
    if not math.isfinite(drop.bearing_degrees):
      raise skill_interface.SkillError(
        INVALID_INPUT, "drop_off.bearing_degrees must be a number"
      )
    if not 0.0 < drop.part_half_height_m <= _MAX_PART_HALF_HEIGHT_M:
      raise skill_interface.SkillError(
        INVALID_INPUT,
        f"drop_off.part_half_height_m {drop.part_half_height_m} is outside "
        f"(0, {_MAX_PART_HALF_HEIGHT_M}] m (half the part's height)",
      )
    depth = _optional(drop, "grasp_depth_m", 0.0)
    if abs(depth) > _MAX_GRASP_DEPTH_M:
      raise skill_interface.SkillError(
        INVALID_INPUT,
        f"drop_off.grasp_depth_m {depth} is over {_MAX_GRASP_DEPTH_M} m",
      )
    names = _drop_off_names(drop)
    if not all(names) or len(set(names)) != 3:
      raise skill_interface.SkillError(
        INVALID_INPUT, "drop_off needs three different, non-empty frame names"
      )

  @staticmethod
  def _drop_off_updates(parent, parent_name, drop, updates, result) -> None:
    """Moves A's frames, or creates those that are missing, in the same batch
    as the rest."""
    frames = drop_off.drop_off_frames(
      drop.approach_tilt_degrees,
      drop.radius_m,
      drop.bearing_degrees,
      drop.part_half_height_m,
      _optional(drop, "grasp_depth_m", 0.0),
    )
    place, pre_place, approach = _drop_off_names(drop)
    for key, name, field in (
      ("place_vise", place, result.parent_t_place),
      ("pre_place_vise", pre_place, result.parent_t_pre_place),
      ("machine_approach", approach, result.parent_t_approach),
    ):
      pose = _unit_pose(*frames[key])
      if name in parent.frame_names:
        updates.append(
          _update(_object_ref(parent_name), _frame_ref(parent_name, name), pose)
        )
      else:
        updates.append(_create_frame(parent_name, name, pose))
      field.CopyFrom(math_proto_conversion.pose_to_proto(pose))


def _drop_off_names(drop) -> tuple[str, str, str]:
  return (
    _optional(drop, "place_frame", "place_vise"),
    _optional(drop, "pre_place_frame", "pre_place_vise"),
    _optional(drop, "approach_frame", "machine_approach"),
  )
