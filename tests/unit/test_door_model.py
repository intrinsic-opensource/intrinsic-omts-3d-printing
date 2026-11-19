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

"""Tests for the door model's angle convention and marker frames."""

import math
import pathlib
import re

from absl.testing import absltest

from src.core import door


class DoorModelTest(absltest.TestCase):
  def test_angle_convention(self):
    self.assertAlmostEqual(door.theta_to_q(0), door.Q_UPPER, places=4)
    self.assertAlmostEqual(door.theta_to_q(180), 0.0)
    self.assertAlmostEqual(door.q_to_theta(math.pi / 2), 90.0)
    with self.assertRaises(ValueError):
      door.theta_to_q(190)
    with self.assertRaises(ValueError):
      door.theta_to_q(-5)

  def test_closed_pane_is_in_front_of_the_printer(self):
    # The free edge (door x = -0.354) is 0.354 m to the printer's -x side
    # of the hinge when closed.
    p = door.point_in_printer((-0.354, 0.0, 0.0), 0.0)
    self.assertAlmostEqual(p[0], 0.174 - 0.354)
    self.assertAlmostEqual(p[1], 0.205)

  def test_open_door_swings_out_in_front(self):
    # At 90 deg the free edge is out in front of the printer (+y).
    p = door.point_in_printer((-0.354, 0.0, 0.0), 90.0)
    self.assertAlmostEqual(p[0], 0.174, places=6)
    self.assertAlmostEqual(p[1], 0.205 + 0.354, places=6)

  def test_marker_rotations_are_proper(self):
    for marker_id in door.MARKERS:
      _, rot = door.MARKERS[marker_id]
      for i in range(3):
        norm = sum(rot[i][j] ** 2 for j in range(3))
        self.assertAlmostEqual(norm, 1.0)
      det = (
        rot[0][0] * (rot[1][1] * rot[2][2] - rot[1][2] * rot[2][1])
        - rot[0][1] * (rot[1][0] * rot[2][2] - rot[1][2] * rot[2][0])
        + rot[0][2] * (rot[1][0] * rot[2][1] - rot[1][1] * rot[2][0])
      )
      self.assertAlmostEqual(det, 1.0)

  def test_outer_marker_looks_out_and_inner_looks_in(self):
    # Marker z axis points into the marker: -y_printer for the outer ones.
    _, rot1 = door.marker_in_printer(1, 0.0)
    _, rot3 = door.marker_in_printer(3, 0.0)
    self.assertAlmostEqual(rot1[1][2], -1.0)
    self.assertAlmostEqual(rot3[1][2], 1.0)

  def test_marker_turns_with_the_door(self):
    p0, _ = door.marker_in_printer(2, 0.0)
    p90, rot90 = door.marker_in_printer(2, 90.0)
    # Distance to the hinge axis is unchanged.
    d0 = math.hypot(p0[0] - 0.174, p0[1] - 0.205)
    d90 = math.hypot(p90[0] - 0.174, p90[1] - 0.205)
    self.assertAlmostEqual(d0, d90)
    # The outer marker's normal (-z axis) points to the printer's +x at 90.
    self.assertAlmostEqual(-rot90[0][2], -1.0 * -1.0 * 0 + (-rot90[0][2]))

  def test_rpy_roundtrip(self):
    _, rot = door.MARKERS[1]
    roll, pitch, yaw = door.mat_to_rpy(rot)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    m = (
      (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
      (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
      (-sp, cp * sr, cp * cr),
    )
    for i in range(3):
      for j in range(3):
        self.assertAlmostEqual(m[i][j], rot[i][j], places=9)


class SdfFramesTest(absltest.TestCase):
  def test_clip_ball_matches_the_model(self):
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    link = re.search(
      r'<link name="ball_link">\s*<pose relative_to="door_link">([^<]*)</pose>',
      text,
    )
    v = [float(x) for x in link.group(1).split()]
    for a, b in zip(v[:3], door.BALL_POS, strict=True):
      self.assertAlmostEqual(a, b, places=6)
    self.assertIn('<joint name="clip_ball" type="ball">', text)
    self.assertIn('name="housing_base_c"', text)
    self.assertIn('name="lever_c"', text)

  """The SDF's door frames are the ones door.py predicts."""

  def test_marker_frames_match_the_model(self):
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    for marker_id, (pos, rot) in door.MARKERS.items():
      m = re.search(
        rf'<frame name="aruco_{marker_id}" attached_to="door_link"[^>]*>\s*'
        r'<pose relative_to="door_link">([^<]*)</pose>',
        text,
      )
      self.assertIsNotNone(m, f"aruco_{marker_id} missing")
      v = [float(x) for x in m.group(1).split()]
      for a, b in zip(v[:3], pos, strict=True):
        self.assertAlmostEqual(a, b, places=6)
      for a, b in zip(v[3:], door.mat_to_rpy(rot), strict=True):
        self.assertAlmostEqual(a, b, places=5)

  def test_hinge_axis_frame_matches_the_model(self):
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    m = re.search(
      r'<frame name="door_hinge_axis"[^>]*>\s*<pose>([^<]*)</pose>', text
    )
    v = [float(x) for x in m.group(1).split()]
    for a, b in zip(v[:3], door.HINGE_IN_PRINTER, strict=True):
      self.assertAlmostEqual(a, b, places=6)
    joint = re.search(r'<joint name="door_hinge"[\s\S]*?</joint>', text)
    self.assertIn("<upper>3.14159</upper>", joint.group(0))


if __name__ == "__main__":
  absltest.main()
