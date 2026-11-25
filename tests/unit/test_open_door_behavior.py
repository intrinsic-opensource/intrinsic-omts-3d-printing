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

"""Unit tests for the door-opening tree, its config section and its runner."""

import contextlib
import dataclasses
import io
import math
import os
import pathlib
import tempfile
from typing import Any
from unittest import mock

import yaml
from absl.testing import absltest
from google.protobuf import text_format
from intrinsic.assets.build_defs import asset_pb2
from intrinsic.assets.proto import id_pb2
from intrinsic.executive.proto import behavior_call_pb2, behavior_tree_pb2
from intrinsic.icon.proto import joint_space_pb2
from intrinsic.math.proto import pose_pb2
from intrinsic.resources.proto import resource_handle_pb2
from intrinsic.skills.proto import equipment_pb2
from intrinsic.solutions import behavior_tree as bt
from intrinsic.solutions import execution, provided
from intrinsic.solutions.internal import resources as sbl_resources
from intrinsic.solutions.internal import skill_generation, skill_utils
from intrinsic.world.proto import (
  object_world_service_pb2,
  object_world_updates_pb2,
)
from intrinsic.world.python import object_world_resources

from src.behaviors import open_door
from src.core import door
from src.core.config import DoorConfig, RobotConfig, load_app_config
from src.hardware.gripper import GripperInterface
from src.hardware.robot import Robot
from src.utils.math_utils import create_transform_node_ref
from tools.printer import open_door_bt

_REBOT_CONFIG = "configs/rebot/app_config.yaml"
_CONTACT = [("gripper", "printer:crank_handle")]

# skill id -> (parameter message, result message or None, resource slots).
_REAL_SKILLS = {
  "ai.intrinsic.move_robot": (
    "intrinsic_proto.skills.MoveRobotParams",
    None,
    {
      "arm_part": ["Icon2PositionPart"],
      "motion_planner_service": [
        "intrinsic_proto.motion_planning.MotionPlannerService"
      ],
      "world_service": ["intrinsic_proto.world.ObjectWorldService"],
    },
  ),
  "ai.intrinsic.update_world": (
    "intrinsic_proto.skills.UpdateWorldParams",
    None,
    {},
  ),
  "ai.omts.detect_aruco_markers": (
    "omts.perception.DetectArucoMarkersParams",
    "omts.perception.DetectArucoMarkersResult",
    {"camera": ["CameraConfig"]},
  ),
  "ai.omts.generate_arc_frames": (
    "omts.motion.GenerateArcFramesParams",
    "omts.motion.GenerateArcFramesResult",
    {},
  ),
}
_RESOURCES = {
  "icon": ("Icon2PositionPart",),
  "motion_planner_service": (
    "intrinsic_proto.motion_planning.MotionPlannerService",
  ),
  "world_service": ("intrinsic_proto.world.ObjectWorldService",),
  "orbbec_camera": ("CameraConfig",),
}


def _fake_action(skill_id: str) -> mock.MagicMock:
  """A skill call bt.Task accepts, with a blackboard-like `result`."""
  action = mock.MagicMock(spec=bt.ActionBase)
  action.proto = behavior_call_pb2.BehaviorCall(skill_id=skill_id)
  action.result = mock.MagicMock(name=f"{skill_id}.result")
  return action


def _fake_solution() -> mock.MagicMock:
  """A solution whose skills return fake actions, recording the calls."""
  solution = mock.MagicMock()
  solution.world.list_object_names.return_value = ["gripper", "printer"]
  skills = {
    "ai.omts.detect_aruco_markers": (
      solution.skills.ai.omts.detect_aruco_markers
    ),
    "ai.omts.generate_arc_frames": solution.skills.ai.omts.generate_arc_frames,
    "ai.intrinsic.update_world": solution.skills.ai.intrinsic.update_world,
    "ai.intrinsic.move_robot": solution.skills.ai.intrinsic.move_robot,
    "ai.intrinsic.control_pinch_gripper": (
      solution.skills.ai.intrinsic.control_pinch_gripper
    ),
  }
  solution.actions = {skill_id: [] for skill_id in skills}

  def make(skill_id):
    def side_effect(*args, **kwargs):
      del args, kwargs
      action = _fake_action(skill_id)
      solution.actions[skill_id].append(action)
      return action

    return side_effect

  for skill_id, skill in skills.items():
    skill.side_effect = make(skill_id)
  return solution


def _named_node(*args, **kwargs) -> bt.Node:
  del args
  return bt.Sequence(name=kwargs.get("name", "mock"), children=[])


def _mock_robot() -> mock.MagicMock:
  robot = mock.MagicMock(spec=Robot)
  for builder in (
    robot.build_move_joint_task,
    robot.build_move_cartesian_task,
    robot.build_move_blended_cartesian_task,
    robot.build_move_relative_cartesian_task,
  ):
    builder.side_effect = _named_node
  return robot


def _mock_gripper() -> mock.MagicMock:
  gripper = mock.MagicMock(spec=GripperInterface)
  gripper.build_open_task.side_effect = _named_node
  gripper.build_close_task.side_effect = _named_node
  return gripper


def _skill_ids(node: behavior_tree_pb2.BehaviorTree.Node) -> list[str]:
  """Skill ids of all task nodes under `node`, depth first."""
  ids = []
  if node.HasField("task") and node.task.HasField("call_behavior"):
    ids.append(node.task.call_behavior.skill_id)
  children = list(node.sequence.children) + [
    t.node for t in node.fallback.tries
  ]
  for child in children:
    ids += _skill_ids(child)
  return ids


class OpenDoorTreeTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.door_cfg = load_app_config(_REBOT_CONFIG).door
    self.solution = _fake_solution()
    self.robot = _mock_robot()
    self.gripper = _mock_gripper()

  def _build(self, door_cfg: DoorConfig | None = None) -> bt.Sequence:
    return open_door.build_open_door_tree(
      self.solution,
      self.robot,
      self.gripper,
      door_cfg or self.door_cfg,
    )

  def test_top_level_steps_in_order(self):
    root = self._build()
    self.assertIsInstance(root, bt.Sequence)
    self.assertEqual(root.name, "Open the printer door")
    self.assertEqual(
      [child.name for child in root.children],
      [
        "Door: look at the marker",
        "Door: locate the printer",
        "Door: generate the arc frames (135 deg, 45 waypoints)",
        "Door: open the gripper",
        "Door: move to the pre-grasp (ANY)",
        "Door: move to the grasp (LINEAR)",
        "Door: close on the handle",
        "Door: swing",
        "Door: release the handle",
        "Door: retreat 6.0 cm (-Z tool)",
      ],
    )
    self.assertIsInstance(root.children[7], bt.Fallback)

  def test_look_moves_to_the_configured_joints(self):
    self._build()
    call = self.robot.build_move_joint_task.call_args
    target = call.args[0]
    self.assertIsInstance(target, joint_space_pb2.JointVec)
    self.assertSequenceAlmostEqual(
      list(target.joints), [-0.8678, -0.5884, -0.8892, 0.3008, -0.8676, -1.5708]
    )
    self.assertEqual(call.kwargs["excluded_collision_pairs"], _CONTACT)

  def test_locate_writes_the_detected_pose_through_the_blackboard(self):
    root = self._build()
    locate = root.children[1]
    self.assertEqual(
      [child.name for child in locate.children],
      [
        "Door: detect the printer's marker",
        "Door: write the measured printer pose",
      ],
    )
    detect_skill = self.solution.skills.ai.omts.detect_aruco_markers
    kwargs = detect_skill.call_args.kwargs
    self.assertIs(kwargs["camera"], self.solution.resources["orbbec_camera"])
    self.assertEqual(kwargs["rgb_sensor"], "rgb")
    self.assertEqual(kwargs["marker_ids"], [1])
    self.assertAlmostEqual(kwargs["marker_size_m"], 0.080)
    (pose,) = kwargs["printer_t_marker"]
    self.assertIsInstance(pose, pose_pb2.Pose)
    self.assertAlmostEqual(pose.position.y, 0.2125)
    self.assertAlmostEqual(pose.orientation.y, math.sqrt(0.5))

    detect = self.solution.actions["ai.omts.detect_aruco_markers"][0]
    world_ns = self.solution.skills.ai.intrinsic.update_world.intrinsic_proto
    request = world_ns.world.UpdateTransformRequest.call_args.kwargs
    printer = create_transform_node_ref("printer")
    self.assertEqual(request["node_a"], create_transform_node_ref("root"))
    self.assertEqual(request["node_b"], printer)
    self.assertEqual(request["node_to_update"], printer)
    self.assertIs(request["a_t_b"], detect.result.root_t_printer)

  def test_detect_false_omits_the_locate_step(self):
    root = self._build(dataclasses.replace(self.door_cfg, detect=False))
    names = [child.name for child in root.children]
    self.assertNotIn("Door: locate the printer", names)
    self.assertLen(names, 9)
    self.solution.skills.ai.omts.detect_aruco_markers.assert_not_called()

  def test_arc_frames_come_from_generate_arc_frames(self):
    self._build()
    arc_skill = self.solution.skills.ai.omts.generate_arc_frames
    arc_skill.assert_called_once()
    kwargs = arc_skill.call_args.kwargs
    self.assertEqual(
      kwargs["pivot_frame"],
      create_transform_node_ref("printer", "door_hinge_axis"),
    )
    self.assertEqual(
      kwargs["grip_frame"], create_transform_node_ref("printer", "handle_grip")
    )
    self.assertEqual(
      kwargs["radial_origin_frame"], create_transform_node_ref("root")
    )
    # Opening by theta is -theta about the hinge's +z.
    self.assertEqual(kwargs["total_angle_deg"], -135.0)
    self.assertEqual(kwargs["num_waypoints"], 45)
    self.assertEqual(kwargs["grip_depth_m"], 0.015)
    self.assertEqual(kwargs["approach_offset_m"], 0.06)
    self.assertEqual(kwargs["frame_prefix"], "door_arc")
    orientation_cls = arc_skill.omts.motion.ToolOrientation
    orientation_cls.assert_called_once_with(
      mode=orientation_cls.Mode.RADIAL, azimuth_deg=0.0, pitch_deg=0.0
    )
    self.assertIs(kwargs["orientation"], orientation_cls.return_value)

  def test_grasp_approaches_the_generated_frames(self):
    self._build()
    calls = self.robot.build_move_cartesian_task.call_args_list
    self.assertEqual(
      [
        (
          c.kwargs["target_frame_name"],
          c.kwargs["target_object_name"],
          c.kwargs["motion_type"],
          c.kwargs["excluded_collision_pairs"],
        )
        for c in calls
      ],
      [
        ("door_arc_pregrasp", "root", "ANY", _CONTACT),
        ("door_arc_grasp", "root", "LINEAR", _CONTACT),
      ],
    )
    self.assertEqual(
      [c.kwargs["name"] for c in self.gripper.build_close_task.call_args_list],
      ["Door: close on the handle"],
    )

  def test_swing_alternatives_longest_first_each_setting_the_belief_door(
    self,
  ):
    root = self._build()
    fallback = root.children[7]
    tries = [t.node for t in fallback.tries]
    self.assertEqual(
      [node.name for node in tries],
      [
        "Door: swing to 135 deg",
        "Door: swing to 114 deg",
        "Door: swing to 90 deg",
        "Door: swing to 60 deg",
        "Door: no swing plannable",
      ],
    )
    blended = self.robot.build_move_blended_cartesian_task.call_args_list
    self.assertEqual([len(c.args[0]) for c in blended], [45, 38, 30, 20])
    for call in blended:
      frames = call.args[0]
      self.assertEqual(frames[0], ("root", "door_arc_wp_00"))
      self.assertEqual(
        frames[-1], ("root", f"door_arc_wp_{len(frames) - 1:02d}")
      )
      self.assertEqual(call.kwargs["motion_type"], "JOINT")
      self.assertEqual(call.kwargs["joint_tightness_rad"], 0.05)
      self.assertEqual(call.kwargs["excluded_collision_pairs"], _CONTACT)

    for node in tries[:4]:
      self.assertLen(node.children, 2)
      # the belief write is best effort: a Fallback ending in a no-op success,
      # so its failure cannot trigger the next alternative's swing
      record = node.children[1]
      self.assertIsInstance(record, bt.Fallback)
      self.assertIsInstance(record.tries[0].node, bt.Task)
      self.assertIsInstance(record.tries[1].node, bt.Sequence)
      self.assertEmpty(record.tries[1].node.children)
    updates = [
      c.kwargs["update"]
      for c in self.solution.skills.ai.intrinsic.update_world.call_args_list
      if isinstance(
        c.kwargs["update"], object_world_updates_pb2.ObjectWorldUpdate
      )
    ]
    self.assertLen(updates, 4)
    for update, angle in zip(updates, (135.0, 114.0, 90.0, 60.0), strict=True):
      joint = update.update_object_joint
      self.assertEqual(joint.object.by_name.object_name, "printer")
      self.assertEqual(joint.joint_name, "door_hinge")
      self.assertAlmostEqual(
        joint.joint_position, 3.14159 - math.radians(angle), places=9
      )

  def test_no_swing_releases_backs_off_and_fails(self):
    root = self._build()
    give_up = root.children[7].tries[-1].node
    self.assertEqual(
      [child.name for child in give_up.children],
      [
        "Door: release the handle (no swing)",
        "Door: back off the handle (no swing)",
        "Door: not opened",
      ],
    )
    self.assertIsInstance(give_up.children[2], bt.Fail)

  def test_retreats_back_along_the_tool_after_release(self):
    self._build()
    retreats = self.robot.build_move_relative_cartesian_task.call_args_list
    self.assertLen(retreats, 2)  # the no-swing branch and the main path
    for call in retreats:
      self.assertEqual(call.kwargs["translation"], (0.0, 0.0, -0.06))
      self.assertEqual(call.kwargs["motion_type"], "LINEAR")
      self.assertEqual(call.kwargs["excluded_collision_pairs"], _CONTACT)
    self.assertEqual(
      [c.kwargs["name"] for c in self.gripper.build_open_task.call_args_list],
      [
        "Door: open the gripper",
        "Door: release the handle (no swing)",
        "Door: release the handle",
      ],
    )

  def test_tree_proto_names_only_installed_skills(self):
    tree = bt.BehaviorTree(name="door", root=self._build())
    ids = _skill_ids(tree.proto.root)
    self.assertEqual(
      ids,
      [
        "ai.omts.detect_aruco_markers",
        "ai.intrinsic.update_world",
        "ai.omts.generate_arc_frames",
        "ai.intrinsic.update_world",
        "ai.intrinsic.update_world",
        "ai.intrinsic.update_world",
        "ai.intrinsic.update_world",
      ],
    )


class SwingAlternativesTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.door_cfg = load_app_config(_REBOT_CONFIG).door

  def _alternatives(self, **changes) -> list[tuple[int, float]]:
    cfg = dataclasses.replace(self.door_cfg, **changes)
    return [
      (a.num_waypoints, a.angle_deg) for a in open_door.swing_alternatives(cfg)
    ]

  def test_fallbacks_snap_to_the_full_arcs_waypoints(self):
    self.assertEqual(
      self._alternatives(),
      [(45, 135.0), (38, 114.0), (30, 90.0), (20, 60.0)],
    )

  def test_a_lower_target_skips_fallbacks_at_or_beyond_it(self):
    self.assertEqual(
      self._alternatives(target_deg=90.0), [(45, 90.0), (30, 60.0)]
    )

  def test_repeats_are_dropped_and_the_first_waypoint_is_the_minimum(self):
    self.assertEqual(
      self._alternatives(fallback_deg=(134.9, 1.0, 60.0, 60.5)),
      [(45, 135.0), (20, 60.0), (1, 3.0)],
    )

  def test_hinge_position_from_angle(self):
    self.assertAlmostEqual(
      open_door.hinge_position(self.door_cfg, 0.0), 3.14159
    )
    self.assertAlmostEqual(
      open_door.hinge_position(self.door_cfg, 90.0), 3.14159 - math.pi / 2
    )
    self.assertEqual(open_door.hinge_position(self.door_cfg, 180.0), 0.0)

  def test_frame_names_match_the_skill_contract(self):
    self.assertEqual(open_door.pregrasp_frame_name("arc"), "arc_pregrasp")
    self.assertEqual(open_door.grasp_frame_name("arc"), "arc_grasp")
    self.assertEqual(open_door.waypoint_frame_name("arc", 7), "arc_wp_07")


def _quaternion_matrix(q) -> list[list[float]]:
  x, y, z, w = q
  return [
    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
  ]


class DoorConfigTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.raw = yaml.safe_load(
      pathlib.Path(_REBOT_CONFIG).read_text(encoding="utf-8")
    )

  def _load(self, raw) -> object:
    with tempfile.TemporaryDirectory() as tmp:
      path = pathlib.Path(tmp) / "app_config.yaml"
      path.write_text(yaml.safe_dump(raw), encoding="utf-8")
      return load_app_config(path)

  def test_rebot_door_section(self):
    cfg = load_app_config(_REBOT_CONFIG).door
    self.assertIsInstance(cfg, DoorConfig)
    self.assertEqual(cfg.printer_object_name, "printer")
    self.assertEqual(cfg.hinge_frame_name, "door_hinge_axis")
    self.assertEqual(cfg.grip_frame_name, "handle_grip")
    self.assertEqual(cfg.radial_origin_object_name, "root")
    self.assertEqual(cfg.hinge_joint_name, "door_hinge")
    self.assertEqual(
      cfg.look_joints, (-0.8678, -0.5884, -0.8892, 0.3008, -0.8676, -1.5708)
    )
    self.assertEqual(cfg.target_deg, 135.0)
    self.assertEqual(cfg.fallback_deg, (115.0, 90.0, 60.0))
    self.assertEqual(cfg.num_waypoints, 45)
    self.assertTrue(cfg.detect)
    self.assertEqual(cfg.orientation_mode, "RADIAL")
    self.assertEqual(cfg.handle_entity_name, "crank_handle")

  def test_cells_without_a_door_section_have_none(self):
    for cell in ("omts", "lab_bb_01"):
      with self.subTest(cell=cell):
        self.assertIsNone(
          load_app_config(f"configs/{cell}/app_config.yaml").door
        )

  def test_rebot_values_match_the_door_model(self):
    cfg = load_app_config(_REBOT_CONFIG).door
    self.assertEqual(cfg.marker_size_m, door.MARKER_SIZE_M)
    self.assertEqual(cfg.grip_depth_m, door.GRIP_DEPTH_M)
    self.assertAlmostEqual(cfg.hinge_closed_q, door.Q_UPPER)
    self.assertEqual(
      sorted(m.id for m in cfg.markers), sorted(door.MARKERS.keys())
    )
    for marker in cfg.markers:
      position, rotation = door.marker_in_printer(marker.id, 0.0)
      self.assertSequenceAlmostEqual(marker.position, position, delta=1e-9)
      got = _quaternion_matrix(marker.quaternion)
      for row_got, row_want in zip(got, rotation, strict=True):
        self.assertSequenceAlmostEqual(row_got, row_want, delta=1e-9)

  def test_missing_door_field_fails_loudly(self):
    del self.raw["door"]["target_deg"]
    with self.assertRaisesRegex(KeyError, r"target_deg.*'door'"):
      self._load(self.raw)

  def test_missing_marker_field_fails_loudly(self):
    del self.raw["door"]["markers"][0]["quaternion"]
    with self.assertRaisesRegex(KeyError, r"door\.markers\[0\]"):
      self._load(self.raw)

  def test_optional_fields_take_their_defaults(self):
    for key in (
      "detect",
      "handle_entity_name",
      "orientation_mode",
      "pitch_deg",
      "joint_tightness_rad",
      "frame_prefix",
    ):
      self.raw["door"].pop(key, None)
    cfg = self._load(self.raw).door
    self.assertTrue(cfg.detect)
    self.assertEqual(cfg.handle_entity_name, "crank_handle")
    self.assertEqual(cfg.orientation_mode, "RADIAL")
    self.assertEqual(cfg.azimuth_deg, 0.0)
    self.assertEqual(cfg.joint_tightness_rad, 0.05)
    self.assertEqual(cfg.frame_prefix, "arc")

  def test_null_door_section_is_none(self):
    self.raw["door"] = None
    self.assertIsNone(self._load(self.raw).door)

  def test_invalid_values_are_rejected(self):
    cfg = load_app_config(_REBOT_CONFIG).door
    for changes in (
      {"num_waypoints": 0},
      {"num_waypoints": 101},
      {"target_deg": 0.0},
      {"target_deg": 181.0},
      {"fallback_deg": (0.0,)},
      {"orientation_mode": "SIDEWAYS"},
      {"pitch_deg": 90.0},
      {"frame_prefix": "1arc"},
      {"frame_prefix": "arc-1"},
      {"approach_offset_m": 0.0},
      {"markers": ()},
      {"markers": cfg.markers * 2},
      {"look_joints": ()},
    ):
      with self.subTest(changes=changes):
        with self.assertRaises(ValueError):
          dataclasses.replace(cfg, **changes)
    # Without detection, no marker is needed.
    dataclasses.replace(cfg, detect=False, markers=())

  def test_is_immutable(self):
    cfg = load_app_config(_REBOT_CONFIG).door
    with self.assertRaises(dataclasses.FrozenInstanceError):
      cfg.target_deg = 90.0  # type: ignore[misc]


class _FakePrinter:
  joint_entity_names = ["door_hinge", "crank_pivot"]

  def __init__(self, angle_deg: float) -> None:
    self.joint_positions = [3.14159 - math.radians(angle_deg), 0.3]


class OpenDoorRunnerTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.solution = _fake_solution()
    self.solution.world.get_kinematic_object.return_value = _FakePrinter(114.0)
    patcher = mock.patch.object(
      open_door_bt.deployments, "connect", return_value=self.solution
    )
    self.connect = patcher.start()
    self.addCleanup(patcher.stop)

  def _main(self, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
      code = open_door_bt.main(list(argv))
    return code, out.getvalue()

  def test_defaults(self):
    args = open_door_bt.parse_args([])
    self.assertEqual(args.address, "localhost:17080")
    self.assertEqual(args.config, _REBOT_CONFIG)
    self.assertIsNone(args.target_deg)
    self.assertIsNone(args.dump)
    self.assertFalse(args.no_run)

  def test_door_config_overrides_the_target_and_needs_a_door_section(self):
    config = load_app_config(_REBOT_CONFIG)
    self.assertEqual(open_door_bt.door_config(config, 90.0).target_deg, 90.0)
    self.assertIs(open_door_bt.door_config(config, None), config.door)
    with self.assertRaises(SystemExit):
      open_door_bt.door_config(
        load_app_config("configs/omts/app_config.yaml"), None
      )

  def test_dump_writes_the_tree_as_text_proto_without_running(self):
    with tempfile.TemporaryDirectory() as tmp:
      path = os.path.join(tmp, "out", "door.textproto")
      code, out = self._main("--dump", path, "--address", "host:1")
      self.assertEqual(code, 0)
      self.assertIn(path, out)
      tree = text_format.Parse(
        pathlib.Path(path).read_text(encoding="utf-8"),
        behavior_tree_pb2.BehaviorTree(),
      )
    self.connect.assert_called_once_with(address="host:1")
    self.solution.executive.run.assert_not_called()
    self.assertEqual(tree.name, "Open the printer door")
    ids = _skill_ids(tree.root)
    self.assertEqual(ids[0], "ai.intrinsic.move_robot")
    self.assertEqual(
      set(ids),
      {
        "ai.intrinsic.move_robot",
        "ai.omts.detect_aruco_markers",
        "ai.intrinsic.update_world",
        "ai.omts.generate_arc_frames",
        "ai.intrinsic.control_pinch_gripper",
      },
    )

  def test_relative_dump_paths_are_relative_to_the_bazel_run_directory(self):
    with mock.patch.dict(os.environ, {"BUILD_WORKING_DIRECTORY": "/work"}):
      self.assertEqual(
        open_door_bt.resolve_output_path("a/b.textproto"),
        pathlib.Path("/work/a/b.textproto"),
      )
      self.assertEqual(
        open_door_bt.resolve_output_path("/abs.textproto"),
        pathlib.Path("/abs.textproto"),
      )

  def test_no_run_prints_the_outline(self):
    code, out = self._main("--no_run")
    self.assertEqual(code, 0)
    self.solution.executive.run.assert_not_called()
    self.assertIn("Door: swing [fallback]", out)
    self.assertIn("[task ai.omts.generate_arc_frames]", out)

  def test_run_executes_one_tree_and_reports_the_belief_door(self):
    code, out = self._main("--target_deg", "120")
    self.assertEqual(code, 0)
    self.solution.executive.run.assert_called_once()
    (tree,) = self.solution.executive.run.call_args.args
    self.assertIsInstance(tree, bt.BehaviorTree)
    arc = self.solution.skills.ai.omts.generate_arc_frames.call_args.kwargs
    self.assertEqual(arc["total_angle_deg"], -120.0)
    self.solution.world.get_kinematic_object.assert_called_with("printer")
    self.assertIn("Belief door angle: 114.0 deg (target 120)", out)

  def test_a_failed_run_still_reports_the_door_and_exits_non_zero(self):
    self.solution.executive.run.side_effect = execution.ExecutionFailedError(
      "no swing"
    )
    code, out = self._main()
    self.assertEqual(code, 1)
    self.assertIn("The tree failed", out)
    self.assertIn("Belief door angle: 114.0 deg", out)


def _asset_infos() -> dict[str, asset_pb2.AssetInfo]:
  """The skills' AssetInfo protos (:open_door_skill_asset_infos), by id."""
  root = os.environ.get("TEST_SRCDIR") or "."
  infos = {}
  for dirpath, _, filenames in os.walk(root, followlinks=True):
    for name in filenames:
      if name.endswith(".asset_info.binpb"):
        with open(os.path.join(dirpath, name), "rb") as f:
          info = asset_pb2.AssetInfo.FromString(f.read())
        infos[f"{info.id.package}.{info.id.name}"] = info
  return infos


class _SkillNamespace:
  """solution.skills: ai.<package>.<skill> attribute access."""

  def __init__(self, classes: dict[str, Any]) -> None:
    self.ai = mock.NonCallableMock(spec=["intrinsic", "omts"])
    self.ai.intrinsic = mock.NonCallableMock(spec=[])
    self.ai.omts = mock.NonCallableMock(spec=[])
    # Robot keeps a handle on it; the door tree never calls it.
    self.ai.intrinsic.move_to_contact = mock.NonCallableMock(spec=[])
    for skill_id, cls in classes.items():
      _, package, name = skill_id.split(".")
      setattr(getattr(self.ai, package), name, cls)


class _RealSkillSolution:
  """A solution offline: real generated skill classes, fake world/resources."""

  def __init__(self, infos: dict[str, asset_pb2.AssetInfo]) -> None:
    handles = {}
    for name, capabilities in _RESOURCES.items():
      handle = resource_handle_pb2.ResourceHandle(name=name)
      for capability in capabilities:
        handle.resource_data[capability].SetInParent()
      handles[name] = provided.ResourceHandle(handle)
    self.resources = handles
    self.world = mock.NonCallableMock()
    self.world.list_object_names.return_value = ["rebot", "gripper", "printer"]
    self.world.rebot = object_world_resources.KinematicObject(
      object_world_service_pb2.Object(
        id="rebot_id",
        name="rebot",
        name_is_global_alias=True,
        type=object_world_service_pb2.ObjectType.KINEMATIC_OBJECT,
        object_component=object_world_service_pb2.ObjectComponent(),
        kinematic_object_component=(
          object_world_service_pb2.KinematicObjectComponent()
        ),
      ),
      stub=None,
    )
    classes = {}
    self.skill_infos = {}
    for skill_id, (params, result, slots) in _REAL_SKILLS.items():
      info = infos[skill_id]
      skill_info = skill_generation.SkillInfoImpl(
        id_version=id_pb2.IdVersion(
          id=id_pb2.Id(package=info.id.package, name=info.id.name),
          version="0.0.1",
        ),
        description=skill_id,
        parameter_message_full_name=params,
        return_value_message_full_name=result,
        file_descriptor_set=info.file_descriptor_set,
        default_params=None,
        recommended_config=None,
        resource_selectors={
          slot: equipment_pb2.ResourceSelector(capability_names=caps)
          for slot, caps in slots.items()
        },
        proto_comments={},
        skill_type=provided.SkillType.REGULAR_SKILL,
        type_url_area=skill_utils.INTRINSIC_TYPE_URL_AREA_ASSETS,
      )
      compatible = {}
      for slot, caps in slots.items():
        param = (
          slot + skill_utils.RESOURCE_SLOT_DECONFLICT_SUFFIX
          if slot in skill_info.field_names
          else slot
        )
        compatible[param] = sbl_resources.ResourceListImpl(
          [h for h in handles.values() if set(caps) <= set(h.types)]
        )
      classes[skill_id] = skill_generation.gen_skill_class(
        skill_info, compatible
      )
      self.skill_infos[skill_id] = skill_info
    self.skills = _SkillNamespace(classes)


class OpenDoorTreeWithRealSkillsTest(absltest.TestCase):
  """The tree against the skills' real parameter schemas (no cluster)."""

  @classmethod
  def setUpClass(cls):
    super().setUpClass()
    cls.solution = _RealSkillSolution(_asset_infos())
    cls.door_cfg = load_app_config(_REBOT_CONFIG).door
    robot = Robot(
      solution=cls.solution,
      config=RobotConfig(
        arm_part_name="rebot",
        tool_object_name="gripper",
        tool_frame_name="tool_frame",
      ),
    )
    cls.tree = bt.BehaviorTree(
      name="door",
      root=open_door.build_open_door_tree(
        cls.solution, robot, _mock_gripper(), cls.door_cfg
      ),
    )
    cls.tree.validate_id_uniqueness()
    cls.calls = [
      node.task.call_behavior
      for node in _all_nodes(cls.tree.proto.root)
      if node.HasField("task") and node.task.HasField("call_behavior")
    ]

  def _params(self, call: behavior_call_pb2.BehaviorCall):
    params = self.solution.skill_infos[call.skill_id].create_param_message()
    self.assertTrue(call.parameters.Unpack(params))
    return params

  def test_every_call_is_a_deployed_skill_with_valid_parameters(self):
    self.assertEqual(
      {call.skill_id for call in self.calls}, set(_REAL_SKILLS.keys())
    )
    for call in self.calls:
      fields = (
        self.solution.skill_infos[call.skill_id]
        .parameter_descriptor()
        .fields_by_name
      )
      self._params(call)
      for assignment in call.assignments:
        self.assertIn(
          assignment.parameter_path.split("[")[0].split(".")[0], fields
        )

  def test_look_is_a_joint_move_to_the_configured_joints(self):
    look = self._params(self.calls[0])
    (segment,) = look.motion_segments
    self.assertSequenceAlmostEqual(
      list(segment.joint_position.joints), list(self.door_cfg.look_joints)
    )

  def test_printer_pose_comes_from_the_detection_on_the_blackboard(self):
    detect, write = self.calls[1], self.calls[2]
    self.assertEqual(detect.skill_id, "ai.omts.detect_aruco_markers")
    params = self._params(detect)
    self.assertEqual(list(params.marker_ids), [1])
    self.assertAlmostEqual(params.printer_t_marker[0].position.z, 0.459)
    self.assertEqual(write.skill_id, "ai.intrinsic.update_world")
    update = self._params(write).update.update_transform
    self.assertEqual(update.node_b.by_name.object.object_name, "printer")
    (assignment,) = write.assignments
    self.assertEqual(assignment.parameter_path, "update.update_transform.a_t_b")
    self.assertIn(detect.return_value_name, assignment.cel_expression)
    self.assertIn("root_t_printer", assignment.cel_expression)

  def test_arc_frames_parameters(self):
    (call,) = [c for c in self.calls if c.skill_id.endswith("arc_frames")]
    params = self._params(call)
    self.assertEqual(
      params.pivot_frame.by_name.frame.frame_name, "door_hinge_axis"
    )
    self.assertEqual(params.grip_frame.by_name.frame.frame_name, "handle_grip")
    self.assertEqual(
      params.radial_origin_frame.by_name.object.object_name, "root"
    )
    self.assertEqual(params.total_angle_deg, -135.0)
    self.assertEqual(params.num_waypoints, 45)
    self.assertEqual(params.orientation.mode, 0)  # RADIAL
    self.assertEqual(params.frame_prefix, "door_arc")

  def test_swings_and_belief_door_updates(self):
    moves = [c for c in self.calls if c.skill_id == "ai.intrinsic.move_robot"]
    # look, pre-grasp, grasp, 4 swings, 2 back-offs (no swing, main path).
    self.assertLen(moves, 9)
    swings = [self._params(c) for c in moves[3:7]]
    self.assertEqual([len(p.motion_segments) for p in swings], [45, 38, 30, 20])
    for swing in swings:
      last = swing.motion_segments[-1]
      self.assertEqual(
        last.cartesian_pose.target_frame.by_name.frame.frame_name,
        f"door_arc_wp_{len(swing.motion_segments) - 1:02d}",
      )
      self.assertGreater(
        swing.curve_parameters.joint_blending.desired_tightness_rad, 0.0
      )
    joints = [
      self._params(c).update.update_object_joint
      for c in self.calls
      if c.skill_id == "ai.intrinsic.update_world"
      and self._params(c).update.HasField("update_object_joint")
    ]
    self.assertEqual([j.joint_name for j in joints], ["door_hinge"] * 4)
    for joint, angle in zip(joints, (135, 114, 90, 60), strict=True):
      self.assertAlmostEqual(
        joint.joint_position, 3.14159 - math.radians(angle), places=9
      )


def _all_nodes(
  node: behavior_tree_pb2.BehaviorTree.Node,
) -> list[behavior_tree_pb2.BehaviorTree.Node]:
  nodes = [node]
  for child in list(node.sequence.children) + [
    t.node for t in node.fallback.tries
  ]:
    nodes += _all_nodes(child)
  return nodes


if __name__ == "__main__":
  absltest.main()
