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

  def test_there_is_one_big_marker_that_looks_out(self):
    self.assertEqual(list(door.MARKERS), [1])
    self.assertGreaterEqual(door.MARKER_SIZE_M, 0.08)
    # Marker z axis points into the marker: -y_printer for the outer face.
    _, rot1 = door.marker_in_printer(1, 0.0)
    self.assertAlmostEqual(rot1[1][2], -1.0)

  def test_marker_turns_with_the_door(self):
    p0, _ = door.marker_in_printer(1, 0.0)
    p90, _ = door.marker_in_printer(1, 90.0)
    # Distance to the hinge axis is unchanged.
    d0 = math.hypot(p0[0] - 0.174, p0[1] - 0.205)
    d90 = math.hypot(p90[0] - 0.174, p90[1] - 0.205)
    self.assertAlmostEqual(d0, d90)

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
  def test_crank_matches_the_model(self):
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    link = re.search(
      r'<link name="crank_handle">\s*<pose relative_to="door_link">([^<]*)</pose>',
      text,
    )
    v = [float(x) for x in link.group(1).split()]
    for a, b in zip(v[:3], door.CRANK_PIVOT_POS, strict=True):
      self.assertAlmostEqual(a, b, places=6)
    # the handle turns on a vertical revolute joint, a child of the door
    joint = re.search(r'<joint name="crank_pivot"[\s\S]*?</joint>', text).group(
      0
    )
    self.assertIn('type="revolute"', joint)
    self.assertIn("<parent>door_link</parent>", joint)
    self.assertIn("<child>crank_handle</child>", joint)
    self.assertIn("<xyz>0 0 1</xyz>", joint)
    self.assertNotIn("ball_link", text)
    self.assertNotIn("clip_ball", text)

  def test_d_handle_matches_the_model(self):
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    # the bar is the only collision on the turning link, at the right size
    link = re.search(r'<link name="crank_handle">[\s\S]*?</link>', text).group(
      0
    )
    self.assertEqual(link.count("<collision "), 1)
    bar = re.search(
      r'<collision name="bar_c">[\s\S]*?</collision>', link
    ).group(0)
    size = [
      float(v)
      for v in re.search(r"<box><size>([^<]*)</size>", bar).group(1).split()
    ]
    # a rectangular prism with a longer face, turned toward the robot
    self.assertAlmostEqual(size[0], door.HANDLE_BAR_LONG_M)
    self.assertAlmostEqual(size[1], door.HANDLE_BAR_THIN_M)
    self.assertAlmostEqual(size[2], door.HANDLE_BAR_LENGTH_M)
    self.assertGreater(size[0], size[1])
    yaw = float(re.search(r"<pose>[^<]*?([-\d.]+)</pose>", bar).group(1))
    self.assertAlmostEqual(yaw, door.HANDLE_BAR_YAW_RAD)
    # the arms sit above and below the bar, inside the door mesh (top 0.248)
    zs = sorted(
      float(
        re.search(rf'<visual name="{n}_v"><pose>([^<]*)</pose>', text)
        .group(1)
        .split()[2]
      )
      for n in ("handle_arm_top", "handle_arm_bottom")
    )
    self.assertAlmostEqual(zs[0], door.HANDLE_GRIP_Z - door.HANDLE_ARM_DZ_M, 6)
    self.assertAlmostEqual(zs[1], door.HANDLE_GRIP_Z + door.HANDLE_ARM_DZ_M, 6)
    self.assertLess(zs[1] + 0.008, 0.248)
    # the open gripper's body fits between the arms with margin
    self.assertGreaterEqual(
      door.HANDLE_BAR_LENGTH_M / 2 + door.HANDLE_GAP_M,
      door.GRIPPER_HALF_HEIGHT_M + 0.009,
    )

  def test_d_handle_is_beyond_the_free_edge_and_coloured(self):
    self.assertAlmostEqual(
      door.CRANK_PIVOT_POS[0], door.PANE_EDGE_X - door.HANDLE_STANDOFF_M
    )
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    fixed = set(
      re.findall(
        r'<visual name="handle_[a-z_]+_v">[\s\S]*?<ambient>([^<]*)</ambient>',
        text,
      )
    )
    bar = re.search(
      r'<visual name="bar_v">[\s\S]*?<ambient>([^<]*)</ambient>', text
    ).group(1)
    # the arms, corners and mounts share one colour; the turning bar differs
    self.assertEqual(len(fixed), 1)
    self.assertNotIn(bar, fixed)
    for old in ("crank_arm", "crank_block", "col_handle_rod", "tab_v"):
      self.assertNotIn(old, text)

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

  def test_handle_grip_frame_is_the_bar_centre(self):
    text = pathlib.Path("models/printer/3d_printer.sdf").read_text()
    m = re.search(
      r'<frame name="handle_grip" attached_to="door_link"[^>]*>\s*'
      r'<pose relative_to="door_link">([^<]*)</pose>',
      text,
    )
    self.assertIsNotNone(m)
    v = [float(x) for x in m.group(1).split()]
    for a, b in zip(v[:3], door.KNOB_POS, strict=True):
      self.assertAlmostEqual(a, b, places=6)

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
