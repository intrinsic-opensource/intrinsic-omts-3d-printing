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

"""Unit tests for src/core/grasp_math.py, against the script it was taken from."""

import math
import random
from typing import Any
from unittest import mock

from absl.testing import absltest
from intrinsic.math.python import data_types

from src.core import grasp_math
from src.utils.dynamic_frame_calculator import (
  calculate_and_update_dynamic_frames,
)


def _unit(q: tuple[float, ...]) -> grasp_math.Quat:
  norm = math.sqrt(sum(c * c for c in q))
  return (q[0] / norm, q[1] / norm, q[2] / norm, q[3] / norm)


def _script_frames(
  position, orientation, tool_orientation, offset, tilt, symmetry
) -> dict[str, Any]:
  """What the PythonScript writes, for a part already in the parent frame."""
  world = mock.MagicMock()
  world.root = mock.MagicMock()
  world.root.list_frames.return_value = []
  tool_pose = (
    data_types.Pose3(
      data_types.Rotation3(data_types.Quaternion(list(tool_orientation))),
      [0.2, 0.0, 0.3],
    )
    if tool_orientation is not None
    else None
  )
  world.get_transform.side_effect = lambda a, b: (
    tool_pose if b is world.gripper.tool_frame else None
  )
  context = mock.MagicMock()
  context.object_world = world
  params = mock.MagicMock()
  for key, value in {
    "parent_object": "root",
    "camera_name": "orbbec_camera",
    "pos_x": position[0],
    "pos_y": position[1],
    "pos_z": position[2],
    "ori_x": orientation[0],
    "ori_y": orientation[1],
    "ori_z": orientation[2],
    "ori_w": orientation[3],
    "approach_offset_z": offset,
    "pregrasp_frame_name": "pre_grasp",
    "grasp_frame_name": "grasp",
    "target_scene_object_id": "",
    "min_safe_z": -10.0,
    "tool_object_name": "gripper",
    "tool_frame_name": "tool_frame",
    "approach_tilt_degrees": tilt,
    "yaw_symmetry_degrees": symmetry,
  }.items():
    setattr(params, key, value)
  calculate_and_update_dynamic_frames(context, params)
  return {
    call.kwargs["frame_name"]: call.kwargs["parent_t_frame"]
    for call in world.create_frame.call_args_list
  }


def _same_rotation(a, b) -> bool:
  """Quaternions agree up to sign."""
  dot = sum(x * y for x, y in zip(a, b, strict=True))
  return abs(abs(dot) - 1.0) < 1e-9


class CuboidGraspTest(absltest.TestCase):
  def test_matches_the_script_on_random_poses(self):
    rng = random.Random(7)
    for _ in range(300):
      position = (
        rng.uniform(0.2, 0.8),
        rng.uniform(-0.4, 0.4),
        rng.uniform(0.0, 0.3),
      )
      orientation = _unit([rng.gauss(0, 1) for _ in range(4)])
      tool = rng.choice([None, _unit([rng.gauss(0, 1) for _ in range(4)])])
      tilt = rng.choice([0.0, 35.0, 60.0, 75.0])
      symmetry = rng.choice([180.0, 90.0])
      offset = rng.choice([0.04, 0.06, 0.08])

      frames = _script_frames(
        position, orientation, tool, offset, tilt, symmetry
      )
      got = grasp_math.cuboid_grasp(
        position,
        orientation,
        offset,
        tool_orientation=tool,
        approach_tilt_degrees=tilt,
        yaw_symmetry_degrees=symmetry,
      )
      context = (
        f"{position} {orientation} tool={tool} tilt={tilt} sym={symmetry}"
      )
      for name, expected in (
        ("grasp", got.grasp_position),
        ("pre_grasp", got.pregrasp_position),
      ):
        pose = frames[name]
        for want, have in zip(expected, pose.translation, strict=True):
          self.assertAlmostEqual(want, float(have), places=9, msg=context)
        q = pose.rotation.quaternion
        self.assertTrue(
          _same_rotation(got.orientation, (q.x, q.y, q.z, q.w)), msg=context
        )

  def test_vertical_grasp_backs_off_straight_up(self):
    got = grasp_math.cuboid_grasp((0.5, 0.0, 0.1), (0.0, 0.0, 0.0, 1.0), 0.08)
    self.assertEqual(got.grasp_position, (0.5, 0.0, 0.1))
    self.assertAlmostEqual(got.pregrasp_position[2], 0.18)
    self.assertAlmostEqual(got.pregrasp_position[0], 0.5)

  def test_tilted_approach_leans_outward_so_the_pregrasp_is_nearer_the_base(
    self,
  ):
    got = grasp_math.cuboid_grasp(
      (0.5, 0.0, 0.1), (0.0, 0.0, 0.0, 1.0), 0.06, approach_tilt_degrees=75.0
    )
    # The tool moves outward and down onto the part, so it starts nearer the
    # base and higher, a pre-grasp distance back along the approach.
    self.assertLess(got.pregrasp_position[0], 0.5)
    self.assertGreater(got.pregrasp_position[2], 0.1)
    self.assertAlmostEqual(
      math.dist(got.grasp_position, got.pregrasp_position), 0.06
    )

  def test_square_footprint_has_more_candidates_than_a_box(self):
    # A part turned a quarter turn: a box and a square pick different faces.
    quarter = (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5))
    box = grasp_math.cuboid_grasp(
      (0.5, 0.1, 0.1), quarter, 0.06, approach_tilt_degrees=60.0
    )
    square = grasp_math.cuboid_grasp(
      (0.5, 0.1, 0.1),
      quarter,
      0.06,
      approach_tilt_degrees=60.0,
      yaw_symmetry_degrees=90.0,
    )
    self.assertFalse(_same_rotation(box.orientation, square.orientation))


if __name__ == "__main__":
  absltest.main()
