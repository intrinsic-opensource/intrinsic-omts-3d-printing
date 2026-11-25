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

"""generate_arc_frames' maths against the retired scripted tool (knob_matrix).

The door-test layout: the printer at world (0.80, -0.0064, 0), yaw +90 deg; the
hinge frame at door.HINGE_IN_PRINTER in the printer frame (axes of the printer);
the grip point at door.KNOB_POS in the door frame. Opening the door by theta is
a rotation of -theta about the hinge's +z (door.point_in_printer).
"""

import math
from unittest import mock

import numpy as np
from absl.testing import absltest

from skills.motion import arc_math
from src.core import door

ATOL = 1e-12
PREGRASP_M = 0.06


def knob_matrix(
  root_t_printer: np.ndarray,
  theta_deg: float,
  back_m: float = 0.0,
  az_mode: str = "radial",
) -> np.ndarray:
  """The retired scripted tool's pose, kept here as the reference maths."""
  centre = (root_t_printer @ np.append(door.knob_in_printer(theta_deg), 1.0))[
    :3
  ]
  az = None
  if az_mode == "radial":
    az = math.degrees(math.atan2(centre[1], centre[0]))
  m = np.eye(4)
  m[:3, :3] = np.array(door.knob_tool_rotation_world(az))
  m[:3, 3] = centre + (door.GRIP_DEPTH_M - back_m) * m[:3, 2]
  return m


def printer_at(x: float, y: float, yaw_deg: float) -> np.ndarray:
  a = math.radians(yaw_deg)
  m = np.eye(4)
  m[:3, :3] = [
    [math.cos(a), -math.sin(a), 0],
    [math.sin(a), math.cos(a), 0],
    [0, 0, 1],
  ]
  m[:3, 3] = [x, y, 0]
  return m


ROOT_T_PRINTER = printer_at(0.80, -0.0064, 90.0)
PRINTER_T_HINGE = np.eye(4)
PRINTER_T_HINGE[:3, 3] = door.HINGE_IN_PRINTER
ROOT_T_PIVOT = ROOT_T_PRINTER @ PRINTER_T_HINGE
# The grip frame: door.KNOB_POS in the door (hinge) frame, door closed.
GRIP_START = (ROOT_T_PIVOT @ np.append(door.KNOB_POS, 1.0))[:3]
THETAS = list(range(0, 136, 3))  # 0 .. 135 deg, step 3


def door_arc(mode=arc_math.Mode.RADIAL, azimuth_deg=0.0, pitch_deg=0.0):
  """The skill's frames for opening the door 0 -> 135 deg in 3 deg steps."""
  return arc_math.arc_frames(
    ROOT_T_PIVOT,
    GRIP_START,
    -135.0,
    45,
    mode=mode,
    azimuth_deg=azimuth_deg,
    pitch_deg=pitch_deg,
    grip_depth_m=door.GRIP_DEPTH_M,
    approach_offset_m=PREGRASP_M,
  )


class DoorEquivalenceTest(absltest.TestCase):
  def assert_same_as_knob_matrix(self, frames, az_mode):
    by_name = {f.name: f for f in frames}

    def want(theta, back=0.0):
      return knob_matrix(ROOT_T_PRINTER, theta, back, az_mode)

    np.testing.assert_allclose(
      by_name["arc_grasp"].root_t_tool, want(0), atol=ATOL
    )
    np.testing.assert_allclose(
      by_name["arc_pregrasp"].root_t_tool, want(0, PREGRASP_M), atol=ATOL
    )
    for i, theta in enumerate(THETAS[1:]):
      frame = by_name[f"arc_wp_{i:02d}"]
      self.assertAlmostEqual(frame.angle_deg, -theta, places=9)
      np.testing.assert_allclose(
        frame.root_t_tool, want(theta), atol=ATOL, err_msg=f"theta {theta}"
      )
    np.testing.assert_allclose(
      by_name["arc_retreat"].root_t_tool, want(135, PREGRASP_M), atol=ATOL
    )

  def test_grip_point_follows_the_door(self):
    for theta in THETAS:
      got = arc_math.grip_point(ROOT_T_PIVOT, GRIP_START, -theta)
      want = (ROOT_T_PRINTER @ np.append(door.knob_in_printer(theta), 1.0))[:3]
      np.testing.assert_allclose(got, want, atol=ATOL, err_msg=f"{theta}")

  def test_radial_from_root_matches_knob_matrix(self):
    self.assert_same_as_knob_matrix(door_arc(), "radial")

  def test_every_theta_one_at_a_time(self):
    for theta in THETAS:
      g = arc_math.grip_point(ROOT_T_PIVOT, GRIP_START, -theta)
      got = arc_math.tool_pose(
        g,
        arc_math.Mode.RADIAL,
        0.0,
        0.0,
        door.GRIP_DEPTH_M,
        0.0,
        np.zeros(3),
      )
      np.testing.assert_allclose(
        got,
        knob_matrix(ROOT_T_PRINTER, theta),
        atol=ATOL,
        err_msg=f"theta {theta}",
      )

  def test_fixed_azimuth_matches_knob_matrix(self):
    for az in (door.KNOB_APPROACH_AZ_DEG, 40.0, -150.0):
      with mock.patch.object(door, "KNOB_APPROACH_AZ_DEG", az):
        frames = door_arc(arc_math.Mode.FIXED_AZIMUTH, azimuth_deg=az)
        self.assert_same_as_knob_matrix(frames, "fixed")

  def test_pitch_matches_knob_matrix(self):
    # the retired tool's --pitch set door.KNOB_APPROACH_PITCH_DEG for both
    # modes.
    for pitch in (20.0, -15.0, 60.0):
      with mock.patch.object(door, "KNOB_APPROACH_PITCH_DEG", pitch):
        self.assert_same_as_knob_matrix(door_arc(pitch_deg=pitch), "radial")
        self.assert_same_as_knob_matrix(
          door_arc(
            arc_math.Mode.FIXED_AZIMUTH,
            azimuth_deg=door.KNOB_APPROACH_AZ_DEG,
            pitch_deg=pitch,
          ),
          "fixed",
        )

  def test_rotation_matches_door_py(self):
    for az in np.linspace(-180.0, 180.0, 37):
      np.testing.assert_allclose(
        arc_math.tool_rotation(az, 0.0),
        np.array(door.knob_tool_rotation_world(az)),
        atol=ATOL,
      )


class ArcMathTest(absltest.TestCase):
  def test_frame_names_and_angles(self):
    frames = arc_math.arc_frames(
      ROOT_T_PIVOT, GRIP_START, 90.0, 3, prefix="door"
    )
    self.assertEqual(
      [f.name for f in frames],
      [
        "door_pregrasp",
        "door_grasp",
        "door_wp_00",
        "door_wp_01",
        "door_wp_02",
        "door_retreat",
      ],
    )
    self.assertEqual(
      [f.angle_deg for f in frames], [0.0, 0.0, 30.0, 60.0, 90.0, 90.0]
    )

  def test_one_waypoint_is_the_final_angle(self):
    self.assertEqual(arc_math.waypoint_angles(-40.0, 1), [-40.0])

  def test_right_hand_about_the_pivot_z(self):
    pivot = np.eye(4)
    pivot[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # +z = root -y
    # (1, 0, 0) turned +90 deg about -y goes to (0, 0, 1).
    got = arc_math.grip_point(pivot, np.array([1.0, 0, 0]), 90.0)
    np.testing.assert_allclose(got, [0, 0, 1.0], atol=ATOL)
    up = np.eye(4)
    got = arc_math.grip_point(up, np.array([1.0, 0, 0]), 90.0)
    np.testing.assert_allclose(got, [0, 1.0, 0], atol=ATOL)

  def test_radial_origin_and_back_off(self):
    pivot = np.eye(4)
    origin = np.array([0.0, -1.0, 0.0])
    frames = arc_math.arc_frames(
      pivot,
      np.array([1.0, 0.0, 0.5]),
      90.0,
      1,
      grip_depth_m=0.01,
      approach_offset_m=0.1,
      radial_origin=origin,
    )
    pre, grasp, wp, retreat = (f.root_t_tool for f in frames)
    # Start grip (1, 0, 0.5) seen from (0, -1): azimuth 45 deg.
    z = grasp[:3, 2]
    np.testing.assert_allclose(
      z, [math.sqrt(0.5), math.sqrt(0.5), 0], atol=ATOL
    )
    np.testing.assert_allclose(grasp[:3, 3], [1, 0, 0.5] + 0.01 * z, atol=ATOL)
    np.testing.assert_allclose(pre[:3, 3], grasp[:3, 3] - 0.1 * z, atol=ATOL)
    # Final grip (0, 1, 0.5) seen from (0, -1): azimuth 90 deg.
    np.testing.assert_allclose(wp[:3, 2], [0, 1, 0], atol=ATOL)
    np.testing.assert_allclose(wp[:3, 3], [0, 1.01, 0.5], atol=ATOL)
    np.testing.assert_allclose(retreat[:3, 3], [0, 0.91, 0.5], atol=ATOL)

  def test_rotation_is_proper_with_a_level_y(self):
    for az, pitch in ((0.0, 0.0), (33.0, 45.0), (-120.0, -30.0), (179.0, 89.0)):
      r = arc_math.tool_rotation(az, pitch)
      np.testing.assert_allclose(r.T @ r, np.eye(3), atol=ATOL)
      self.assertAlmostEqual(np.linalg.det(r), 1.0, places=12)
      self.assertAlmostEqual(r[2, 1], 0.0, places=12)  # y is horizontal
      self.assertAlmostEqual(r[2, 2], -math.sin(math.radians(pitch)), places=12)

  def test_errors(self):
    with self.assertRaises(arc_math.GripOnAxisError):
      arc_math.arc_frames(ROOT_T_PIVOT, ROOT_T_PIVOT[:3, 3] + [0, 0, 0.2], 9, 3)
    with self.assertRaises(arc_math.UndefinedAzimuthError):
      arc_math.arc_frames(
        np.eye(4), np.array([1.0, 0, 0]), 90, 2, radial_origin=[1.0, 0, -1]
      )
    for n in (0, -1, arc_math.MAX_WAYPOINTS + 1):
      with self.assertRaises(ValueError):
        arc_math.arc_frames(ROOT_T_PIVOT, GRIP_START, 90, n)
    with self.assertRaises(ValueError):
      arc_math.arc_frames(ROOT_T_PIVOT, GRIP_START, 90, 3, pitch_deg=90.0)
    with self.assertRaises(ValueError):
      arc_math.arc_frames(ROOT_T_PIVOT, GRIP_START, math.nan, 3)


if __name__ == "__main__":
  absltest.main()
