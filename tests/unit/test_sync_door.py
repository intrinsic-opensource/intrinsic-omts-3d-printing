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

"""Tests for the Gazebo door angle to belief joint conversion."""

import math

from absl.testing import absltest

from src.core import door
from tools.printer import sync_door


def _quat_z(yaw: float) -> dict:
  return {"x": 0.0, "y": 0.0, "z": math.sin(yaw / 2), "w": math.cos(yaw / 2)}


def _msg(door_yaw: float, crank_yaw: float) -> dict:
  return {
    "pose": [
      {"name": "door_link", "orientation": _quat_z(door_yaw)},
      {"name": "crank_handle", "orientation": _quat_z(crank_yaw)},
    ]
  }


class SyncDoorTest(absltest.TestCase):
  def test_open_door_angle(self):
    q, _ = sync_door.joints_from_poses(_msg(math.radians(-90), 0.0))
    self.assertAlmostEqual(door.q_to_theta(q), 90.0, places=4)

  def test_closed_door_is_clamped_not_an_error(self):
    # A door resting a hair past the hinge limit must not raise.
    q, _ = sync_door.joints_from_poses(_msg(3e-6, 0.0))
    self.assertAlmostEqual(q, door.Q_UPPER, places=4)

  def test_fully_open_door_past_the_limit_is_still_open(self):
    q, _ = sync_door.joints_from_poses(_msg(-math.pi - 1e-3, 0.0))
    self.assertAlmostEqual(door.q_to_theta(q), 180.0, places=4)

  def test_crank_angle_is_relative_to_the_door(self):
    _, pivot = sync_door.joints_from_poses(
      _msg(math.radians(-30), math.radians(-30) + 1.0)
    )
    self.assertAlmostEqual(pivot, 1.0, places=6)

  def test_missing_links_give_none(self):
    self.assertIsNone(sync_door.joints_from_poses({"pose": []}))


if __name__ == "__main__":
  absltest.main()
