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

"""Skill: find ArUco markers with a camera and return their poses.

Stateless and read-only: it captures one frame and never moves a robot or
writes the world. The pose maths is in skills/perception/aruco_pose.py.
"""

import logging
import math

import numpy as np
from intrinsic.math.python import data_types, proto_conversion
from intrinsic.perception.client.v1.python.camera import cameras
from intrinsic.skills.proto import footprint_pb2
from intrinsic.skills.python import skill_interface

from skills.perception import aruco_pose
from skills.perception import detect_aruco_markers_pb2 as pb

INVALID_INPUT = 2001
CAPTURE_FAILED = 2002
NOT_FOUND = 2003
VIEWING_RULE = 2004


def _rule(params: pb.DetectArucoMarkersParams) -> aruco_pose.ViewingRule:
  d = aruco_pose.ViewingRule()
  return aruco_pose.ViewingRule(
    max_incidence_deg=params.max_incidence_deg or d.max_incidence_deg,
    min_side_px=params.min_side_px or d.min_side_px,
    max_reprojection_px=params.max_reprojection_px or d.max_reprojection_px,
    min_ippe_ratio=params.min_ippe_ratio or d.min_ippe_ratio,
  )


def _matrix(pose_proto) -> np.ndarray:
  return proto_conversion.pose_from_proto(pose_proto).matrix4x4()


def _pose_proto(matrix: np.ndarray):
  return proto_conversion.pose_to_proto(data_types.Pose3.from_matrix4x4(matrix))


def _upright(matrix: np.ndarray) -> np.ndarray:
  """Keeps position and yaw; roll and pitch are zeroed."""
  yaw = math.atan2(matrix[1, 0], matrix[0, 0])
  c, s = math.cos(yaw), math.sin(yaw)
  out = np.eye(4)
  out[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
  out[:3, 3] = matrix[:3, 3]
  return out


def detect(
  image: np.ndarray,
  k: np.ndarray,
  root_t_camera: np.ndarray,
  params: pb.DetectArucoMarkersParams,
) -> pb.DetectArucoMarkersResult:
  """The skill's maths, on one image (also used by the tests)."""
  ids = list(params.marker_ids)
  if not ids or len(set(ids)) != len(ids):
    raise skill_interface.SkillError(INVALID_INPUT, "marker_ids is required")
  if not math.isfinite(params.marker_size_m) or params.marker_size_m <= 0:
    raise skill_interface.SkillError(INVALID_INPUT, "marker_size_m <= 0")
  if params.printer_t_marker and len(params.printer_t_marker) != len(ids):
    raise skill_interface.SkillError(
      INVALID_INPUT, "printer_t_marker needs one pose per marker id"
    )
  gray = image if image.ndim == 2 else image.mean(axis=2).astype(np.uint8)
  corners = aruco_pose.detect_corners(gray)
  rule = _rule(params)
  result = pb.DetectArucoMarkersResult()
  for marker_id in ids:
    if marker_id not in corners:
      raise skill_interface.SkillError(
        NOT_FOUND, f"marker {marker_id} not found (saw {sorted(corners)})"
      )
    det = aruco_pose.solve_marker(
      marker_id, corners[marker_id], params.marker_size_m, k
    )
    why = aruco_pose.check_viewing_rule(det, rule)
    if why:
      raise skill_interface.SkillError(
        VIEWING_RULE, f"marker {marker_id}: {why}"
      )
    camera_t_marker = np.eye(4)
    camera_t_marker[:3, :3] = det.rotation
    camera_t_marker[:3, 3] = det.translation
    result.markers.append(
      pb.MarkerPose(
        id=marker_id,
        root_t_marker=_pose_proto(root_t_camera @ camera_t_marker),
        camera_t_marker=_pose_proto(camera_t_marker),
        reprojection_px=det.reprojection_px,
        side_px=det.side_px,
        ippe_ratio=det.ippe_ratio,
        incidence_deg=det.incidence_deg,
      )
    )
  if params.printer_t_marker:
    printer_t_marker = {
      i: _matrix(p) for i, p in zip(ids, params.printer_t_marker, strict=True)
    }
    if len(ids) == 1:
      m = result.markers[0]
      root_t_printer = _matrix(m.root_t_marker) @ np.linalg.inv(
        printer_t_marker[ids[0]]
      )
      result.joint_reprojection_px = m.reprojection_px
    else:
      obj = {}
      local = aruco_pose.marker_object_points(params.marker_size_m)
      for i, t in printer_t_marker.items():
        obj[i] = (t[:3, :3] @ local.T).T + t[:3, 3]
      rot, tr, rms = aruco_pose.solve_joint(
        {i: corners[i] for i in ids}, obj, k
      )
      camera_t_printer = np.eye(4)
      camera_t_printer[:3, :3] = rot
      camera_t_printer[:3, 3] = tr
      root_t_printer = root_t_camera @ camera_t_printer
      result.joint_reprojection_px = rms
    result.root_t_printer.CopyFrom(_pose_proto(_upright(root_t_printer)))
  return result


class DetectArucoMarkers(skill_interface.Skill):
  @classmethod
  def required_equipment(cls):
    return {"camera": cameras.make_camera_resource_selector()}

  def get_footprint(self, request, context) -> footprint_pb2.Footprint:
    return footprint_pb2.Footprint(lock_the_universe=False)

  def preview(self, request, context):
    raise NotImplementedError("Detecting markers needs a live camera image")

  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.DetectArucoMarkersParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.DetectArucoMarkersResult:
    params = request.params
    sensor = params.rgb_sensor or "rgb"
    try:
      camera = cameras.Camera.create(context, "camera")
      capture = camera.capture()
      image = capture.sensor_images[sensor]
      k = np.asarray(image.intrinsic_matrix, dtype=np.float64)
      pose = camera.world_t_sensor(sensor)
      array = np.asarray(image.array)
    except Exception as exc:  # pylint: disable=broad-exception-caught
      logging.error("capture failed: %s", exc)
      raise skill_interface.SkillError(
        CAPTURE_FAILED, f"capture of {sensor!r} failed: {exc}"
      ) from exc
    if pose is None:
      raise skill_interface.SkillError(
        CAPTURE_FAILED, f"no world pose for sensor {sensor!r}"
      )
    return detect(array, k, pose.matrix4x4(), params)
