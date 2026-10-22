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

"""Tests for the reBot pick-and-place tree."""

from unittest import mock

from absl.testing import absltest
from intrinsic.solutions import behavior_tree as bt

from src.behaviors.rebot_pick_place import build_rebot_pick_place_tree
from src.core.infeed import GridInfeedStrategy
from src.core.tray import Tray
from src.hardware.gripper import GripperInterface
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
    self.robot.build_place_object_at_frame_task.side_effect = (
      lambda **kwargs: bt.Sequence(name=kwargs["name"], children=[])
    )
    self.robot.build_move_joint_task.side_effect = (
      lambda *args, **kwargs: bt.Sequence(name=kwargs["name"], children=[])
    )
    self.gripper = mock.MagicMock(spec=GripperInterface)
    self.gripper.build_open_task.side_effect = (
      lambda **kwargs: bt.Sequence(name=kwargs["name"], children=[])
    )
    self.gripper.build_close_task.side_effect = (
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
      gripper=self.gripper,
      infeed_strategy=self.infeed,
      tool_object_name="gripper",
    )

    cycle = tree.root.children[0]
    self.assertIsInstance(cycle, bt.Sequence)
    self.assertEqual(len(cycle.children), 2)
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

  def test_gripper_brackets_attach_and_detach(self):
    tree = build_rebot_pick_place_tree(
      robot=self.robot,
      gripper=self.gripper,
      infeed_strategy=self.infeed,
      tool_object_name="gripper",
    )

    self.assertEqual(self.gripper.build_open_task.call_count, 4)
    # Two grasps per cycle, plus closing the gripper before folding home.
    self.assertEqual(self.gripper.build_close_task.call_count, 3)
    self.robot.build_place_object_at_frame_task.assert_any_call(
      object_name="rebot_infeed_r0_c0",
      frame_name="part_b_rest",
      name="Snap printed part to rest pose at b",
    )
    a_to_b_transfer = tree.root.children[0].children[0]
    a_to_b = [child.name for child in a_to_b_transfer.children]
    self.assertEqual(
      a_to_b,
      [
        "Approach part at a",
        "Open gripper above a",
        "Position-only grasp approach at a",
        "Grasp printed part at a",
        "Attach printed part at a",
        "Retract with grasped part from a",
        "Transit with grasped part to b",
        "Position-only place approach at b",
        "Release printed part at b",
        "Detach printed part at b",
        "Snap printed part to rest pose at b",
        "Retract after placing at b",
      ],
    )

  def test_repeats_round_trip_for_requested_cycles(self):
    tree = build_rebot_pick_place_tree(
      robot=self.robot,
      gripper=self.gripper,
      infeed_strategy=self.infeed,
      tool_object_name="gripper",
      num_cycles=3,
    )

    loop = tree.root.children[0]
    self.assertIsInstance(loop, bt.Loop)
    self.assertEqual(loop.max_times, 3)

  def test_returns_home_with_gripper_closed_after_the_cycles(self):
    tree = build_rebot_pick_place_tree(
      robot=self.robot,
      gripper=self.gripper,
      infeed_strategy=self.infeed,
      tool_object_name="gripper",
      num_cycles=2,
    )

    self.assertEqual(len(tree.root.children), 2)
    return_home = tree.root.children[1]
    self.assertEqual(
      return_home.name, "Return to home (folded, gripper closed)"
    )
    self.assertEqual(
      [child.name for child in return_home.children],
      ["Close gripper before folding", "Fold to home"],
    )
    self.robot.build_move_joint_task.assert_called_once_with(
      "home", name="Fold to home"
    )


if __name__ == "__main__":
  absltest.main()
