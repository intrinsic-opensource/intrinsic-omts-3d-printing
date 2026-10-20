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

"""Tests for the reBot simulation-only pick-and-place tree."""

from unittest import mock

from absl.testing import absltest
from intrinsic.solutions import behavior_tree as bt

from src.behaviors.rebot_pick_place import build_rebot_pick_place_tree
from src.core.infeed import GridInfeedStrategy
from src.core.tray import Tray
from src.hardware.robot import Robot


class RebotPickPlaceTest(absltest.TestCase):

  def setUp(self):
    super().setUp()
    self.robot = mock.MagicMock(spec=Robot)
    self.robot.build_move_cartesian_task.side_effect = (
      lambda **kwargs: bt.Sequence(name=kwargs["name"], children=[])
    )
    self.robot.build_attach_object_task.side_effect = (
      lambda **kwargs: bt.Sequence(name=kwargs["name"], children=[])
    )
    self.robot.build_detach_object_task.side_effect = (
      lambda **kwargs: bt.Sequence(name=kwargs["name"], children=[])
    )
    tray = Tray(
      name="rebot_infeed",
      rows=1,
      cols=1,
      pitch_x=0.0,
      pitch_y=0.0,
      origin_frame="root",
    )
    tray.populate_all_slots(part_cad_model="rebot_printed_part")
    self.infeed = GridInfeedStrategy(tray)

  def test_builds_two_position_only_transfers_per_cycle(self):
    tree = build_rebot_pick_place_tree(
      robot=self.robot,
      infeed_strategy=self.infeed,
      tool_object_name="gripper",
    )

    self.assertIsInstance(tree.root, bt.Sequence)
    self.assertEqual(len(tree.root.children), 2)
    self.assertEqual(self.robot.build_move_cartesian_task.call_count, 12)
    self.assertEqual(self.robot.build_attach_object_task.call_count, 2)
    self.assertEqual(self.robot.build_detach_object_task.call_count, 2)
    self.robot.build_move_to_contact_task.assert_not_called()
    self.robot.build_attach_object_task.assert_any_call(
      object_name="rebot_infeed_r0_c0",
      name="Attach printed part at a",
    )

    motion_calls = self.robot.build_move_cartesian_task.call_args_list
    self.assertEqual(
      motion_calls[1].kwargs["excluded_collision_pairs"],
      [
        ("gripper", "rebot_infeed_r0_c0"),
        ("rebot_infeed_r0_c0", "rebot_ground"),
      ],
    )
    self.assertEqual(
      motion_calls[3].kwargs["excluded_collision_pairs"],
      [("gripper", "rebot_infeed_r0_c0")],
    )
    self.assertNotIn(
      ("rebot_infeed_r0_c0", "rebot_ground"),
      motion_calls[3].kwargs["excluded_collision_pairs"],
    )

    motion_types = [call.kwargs["motion_type"] for call in motion_calls]
    self.assertEqual(motion_types.count("LINEAR"), 8)
    self.assertEqual(motion_types.count("ANY"), 4)

  def test_repeats_round_trip_for_requested_cycles(self):
    tree = build_rebot_pick_place_tree(
      robot=self.robot,
      infeed_strategy=self.infeed,
      tool_object_name="gripper",
      num_cycles=3,
    )

    self.assertIsInstance(tree.root, bt.Loop)
    self.assertEqual(tree.root.max_times, 3)


if __name__ == "__main__":
  absltest.main()
