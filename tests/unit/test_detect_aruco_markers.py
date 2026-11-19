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

"""Tests for the detect_aruco_markers skill's maths on synthetic images."""

import math

import numpy as np
from absl.testing import absltest
from intrinsic.math.python import data_types, proto_conversion
from intrinsic.skills.python import skill_interface

from skills.perception import aruco_pose, aruco_skills
from skills.perception import detect_aruco_markers_pb2 as pb
from src.core import door

W, H = 1280, 800
K = np.array([[597.0, 0, 640.0], [0, 593.0, 400.0], [0, 0, 1.0]])
SIZE = door.MARKER_SIZE_M


def printer_t_marker(marker_id: int) -> np.ndarray:
  pos, rot = door.marker_in_printer(marker_id, 0.0)
  m = np.eye(4)
  m[:3, :3] = np.array(rot)
  m[:3, 3] = pos
  return m


def pose(matrix):
  return proto_conversion.pose_to_proto(data_types.Pose3.from_matrix4x4(matrix))


def scene(root_t_printer: np.ndarray, root_t_camera: np.ndarray):
  """A synthetic image of markers 1 and 2 on the closed door."""
  img = None
  for marker_id in (1, 2):
    root_t_marker = root_t_printer @ printer_t_marker(marker_id)
    cam_t_marker = np.linalg.inv(root_t_camera) @ root_t_marker
    one = aruco_pose.render_marker(
      (W, H), K, cam_t_marker[:3, :3], cam_t_marker[:3, 3], marker_id, SIZE
    )
    img = one if img is None else np.minimum(img, one)
  return img


def look_at(eye, target):
  """camera_T: z toward target, x right, y down (z-up world)."""
  z = np.array(target, float) - eye
  z /= np.linalg.norm(z)
  x = np.cross(z, [0, 0, 1.0])
  x /= np.linalg.norm(x)
  y = np.cross(z, x)
  m = np.eye(4)
  m[:3, :3] = np.stack([x, y, z], axis=1)
  m[:3, 3] = eye
  return m


def printer_at(x, y, yaw_deg):
  a = math.radians(yaw_deg)
  m = np.eye(4)
  m[:3, :3] = [
    [math.cos(a), -math.sin(a), 0],
    [math.sin(a), math.cos(a), 0],
    [0, 0, 1],
  ]
  m[:3, 3] = [x, y, 0]
  return m


class DetectSkillTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.root_t_printer = printer_at(0.675, 0.0, 90.0)
    # 0.36 m in front of the point between markers 1 and 2, looking at it.
    centers = [
      (self.root_t_printer @ printer_t_marker(i))[:3, 3] for i in (1, 2)
    ]
    target = (centers[0] + centers[1]) / 2
    self.root_t_camera = look_at(target + [-0.36, 0.02, 0.03], target)
    self.image = scene(self.root_t_printer, self.root_t_camera)

  def params(self, ids=(1, 2), with_printer=True):
    p = pb.DetectArucoMarkersParams(
      marker_ids=list(ids), marker_size_m=SIZE, rgb_sensor="rgb"
    )
    if with_printer:
      p.printer_t_marker.extend([pose(printer_t_marker(i)) for i in ids])
    return p

  def test_printer_pose_from_two_markers(self):
    result = aruco_skills.detect(
      self.image, K, self.root_t_camera, self.params()
    )
    got = proto_conversion.pose_from_proto(result.root_t_printer).matrix4x4()
    self.assertLess(
      np.linalg.norm(got[:3, 3] - self.root_t_printer[:3, 3]), 0.003
    )
    yaw = math.atan2(got[1, 0], got[0, 0])
    self.assertAlmostEqual(math.degrees(yaw), 90.0, delta=1.0)
    self.assertLess(result.joint_reprojection_px, 1.0)
    self.assertLen(result.markers, 2)

  def test_missing_marker_raises(self):
    with self.assertRaises(skill_interface.SkillError) as cm:
      aruco_skills.detect(
        self.image, K, self.root_t_camera, self.params(ids=(1, 3))
      )
    self.assertIn(str(aruco_skills.NOT_FOUND), str(cm.exception))

  def test_viewing_rule_failure_raises(self):
    p = self.params()
    p.min_side_px = 5000.0
    with self.assertRaises(skill_interface.SkillError) as cm:
      aruco_skills.detect(self.image, K, self.root_t_camera, p)
    self.assertIn(str(aruco_skills.VIEWING_RULE), str(cm.exception))

  def test_bad_parameters_raise(self):
    p = self.params()
    p.marker_size_m = 0.0
    with self.assertRaises(skill_interface.SkillError):
      aruco_skills.detect(self.image, K, self.root_t_camera, p)
    p = self.params()
    del p.printer_t_marker[1:]
    with self.assertRaises(skill_interface.SkillError):
      aruco_skills.detect(self.image, K, self.root_t_camera, p)

  def test_without_printer_poses_no_printer_pose(self):
    result = aruco_skills.detect(
      self.image, K, self.root_t_camera, self.params(with_printer=False)
    )
    self.assertFalse(result.HasField("root_t_printer"))


if __name__ == "__main__":
  absltest.main()
