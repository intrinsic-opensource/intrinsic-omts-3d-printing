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

"""Tests for the ArUco pose maths on synthetic images."""

import math

import numpy as np
from absl.testing import absltest

from skills.perception import aruco_pose

W, H = 1280, 800
K = np.array([[597.0, 0, 640.0], [0, 593.0, 400.0], [0, 0, 1.0]])
SIZE = 0.05


def look_at_marker(incidence_deg: float, dist: float, yaw_axis="y"):
  """camera_R_marker, camera_t_marker for a marker tilted by incidence.

  The marker's normal (its z axis points away from the camera) is turned by
  incidence about the vertical image axis.
  """
  a = math.radians(incidence_deg)
  ry = np.array(
    [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]
  )
  return ry, np.array([0.0, 0.0, dist])


class DetectTest(absltest.TestCase):
  def _pose(self, incidence, dist=0.28, marker_id=1):
    rot, t = look_at_marker(incidence, dist)
    img = aruco_pose.render_marker((W, H), K, rot, t, marker_id, SIZE)
    corners = aruco_pose.detect_corners(img)
    self.assertIn(marker_id, corners)
    det = aruco_pose.solve_marker(marker_id, corners[marker_id], SIZE, K)
    return rot, t, det

  def test_pose_within_4_mm_up_to_58_degrees(self):
    for inc in (20, 40, 58):
      rot, t, det = self._pose(inc)
      self.assertLess(np.linalg.norm(det.translation - t), 0.004, inc)
      cos = np.clip((np.trace(rot.T @ det.rotation) - 1) / 2, -1, 1)
      self.assertLess(math.degrees(math.acos(cos)), 3.0, inc)
      self.assertAlmostEqual(det.incidence_deg, inc, delta=3.0)

  def test_side_in_pixels(self):
    _, _, det = self._pose(0, dist=0.28)
    # fx 597 * 0.05 / 0.28 = 107 px
    self.assertAlmostEqual(det.side_px, 597 * SIZE / 0.28, delta=3)

  def test_viewing_rule_rejects_each_cause(self):
    rule = aruco_pose.ViewingRule()
    _, _, near = self._pose(30)
    self.assertIsNone(aruco_pose.check_viewing_rule(near, rule))
    _, _, far = self._pose(30, dist=0.8)  # 37 px
    self.assertIn("side", aruco_pose.check_viewing_rule(far, rule))
    _, _, steep = self._pose(70)
    self.assertIn("incidence", aruco_pose.check_viewing_rule(steep, rule))

  def test_face_on_is_flagged_ambiguous(self):
    # Face-on the two IPPE solutions have nearly the same error; an oblique
    # view tells them apart. The rule's ratio must separate the two.
    ratios = {inc: self._pose(inc)[2].ippe_ratio for inc in (0, 20, 40)}
    self.assertLess(ratios[0], ratios[40])

  def test_missing_marker_is_not_detected(self):
    img = np.full((H, W), 128, np.uint8)
    self.assertEqual(aruco_pose.detect_corners(img), {})

  def test_two_ids_are_told_apart(self):
    rot, t = look_at_marker(20, 0.3)
    img = aruco_pose.render_marker((W, H), K, rot, t, 1, SIZE)
    rot2, t2 = look_at_marker(20, 0.3)
    t2 = t2 + np.array([0.08, 0, 0])
    img2 = aruco_pose.render_marker((W, H), K, rot2, t2, 2, SIZE, 128)
    both = np.minimum(img, img2)
    self.assertCountEqual(aruco_pose.detect_corners(both), [1, 2])


class JointTest(absltest.TestCase):
  def test_two_coplanar_markers_give_one_pose_face_on(self):
    # Two markers 23 cm apart on a plane facing the camera: single-marker
    # yaw is poorly conditioned face-on, the joint solve is not.
    centers = {1: np.array([-0.115, 0, 0]), 2: np.array([0.115, 0, 0])}
    plane_t = np.array([0.0, 0.0, 0.30])
    rot = np.eye(3)
    corners, obj = {}, {}
    for mid, c in centers.items():
      img = aruco_pose.render_marker((W, H), K, rot, plane_t + c, mid, SIZE)
      det = aruco_pose.detect_corners(img)[mid]
      corners[mid] = det
      obj[mid] = aruco_pose.marker_object_points(SIZE) + c
    r, t, rms = aruco_pose.solve_joint(corners, obj, K)
    self.assertLess(np.linalg.norm(t - plane_t), 0.002)
    cos = np.clip((np.trace(r) - 1) / 2, -1, 1)
    self.assertLess(math.degrees(math.acos(cos)), 1.0)
    self.assertLess(rms, 1.0)

  def test_one_marker_is_not_enough(self):
    c = {1: np.zeros((4, 2))}
    with self.assertRaises(ValueError):
      aruco_pose.solve_joint(c, {1: np.zeros((4, 3))}, K)


if __name__ == "__main__":
  absltest.main()
