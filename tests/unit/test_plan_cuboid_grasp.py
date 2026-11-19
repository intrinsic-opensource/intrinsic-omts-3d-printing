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

"""plan_cuboid_grasp against a fake world."""

import types

from absl.testing import absltest
from intrinsic.math.python import data_types
from intrinsic.math.python import proto_conversion as conv
from intrinsic.skills.python import skill_interface

from skills.grasp import plan_cuboid_grasp as skill
from skills.grasp import plan_cuboid_grasp_pb2 as pb


def _pose(position, orientation=(0.0, 0.0, 0.0, 1.0)) -> data_types.Pose3:
  return data_types.Pose3(
    data_types.Rotation3(data_types.Quaternion(list(orientation))),
    list(position),
  )


class _Node:
  """An object or frame: a name, and for an object its frames."""

  def __init__(self, name, frames=(), **children):
    self.name = name
    self.frame_names = list(frames)
    for key, value in children.items():
      setattr(self, key, value)

  def get_frame(self, name):
    return _Node(name)


class _World:
  """The few calls the skill makes. `poses` maps a node name to its pose in the
  parent, which `get_transform` returns."""

  def __init__(self, poses, **objects):
    self._objects = objects
    self.poses = poses
    self.created = []
    self.updated = []

  def __getattr__(self, name):
    try:
      return self.__dict__["_objects"][name]
    except KeyError as exc:
      raise AttributeError(name) from exc

  def get_transform(self, node_a, node_b):
    del node_a
    return self.poses.get(node_b.name)

  def update_transform(self, **kwargs):
    self.updated.append(kwargs)

  def create_frame(self, **kwargs):
    self.created.append(kwargs)


def _world(camera_offset=(0.1, 0.2, 1.5), root_frames=(), tool=None):
  root = _Node("root", frames=root_frames)
  camera = _Node("orbbec_camera", sensor=_Node("sensor"))
  gripper = _Node("gripper", tool_frame=_Node("tool_frame"))
  part = _Node("rebot_printed_part")
  poses = {"sensor": _pose(camera_offset)}
  if tool is not None:
    poses["tool_frame"] = tool
  return _World(
    poses,
    root=root,
    orbbec_camera=camera,
    gripper=gripper,
    rebot_printed_part=part,
  )


def _params(**overrides) -> pb.PlanCuboidGraspParams:
  values = dict(
    camera_t_target=conv.pose_to_proto(_pose((0.0, 0.0, 0.0))),
    camera_name="orbbec_camera",
    parent_object="root",
    pregrasp_frame_name="pre_grasp",
    grasp_frame_name="grasp",
    tool_object_name="gripper",
    tool_frame_name="tool_frame",
    target_scene_object_id="ai.intrinsic.rebot_printed_part",
    approach_offset_z=0.08,
    min_safe_z=0.0,
  )
  values.update(overrides)
  return pb.PlanCuboidGraspParams(**values)


def _run(world, params):
  context = types.SimpleNamespace(object_world=world)
  request = types.SimpleNamespace(params=params)
  return skill.PlanCuboidGrasp().execute(request, context)


def _error_code(world, params) -> int:
  try:
    _run(world, params)
  except skill_interface.SkillError as exc:
    return exc.status_code[1]
  raise AssertionError("expected a SkillError")


class PlanCuboidGraspTest(absltest.TestCase):
  def test_the_estimate_is_composed_with_the_camera_pose(self):
    world = _world(camera_offset=(0.1, 0.2, 1.5))
    result = _run(
      world,
      _params(camera_t_target=conv.pose_to_proto(_pose((0.0, 0.0, -1.0)))),
    )
    target = conv.pose_from_proto(result.parent_t_target)
    self.assertSequenceAlmostEqual(list(target.translation), [0.1, 0.2, 0.5])
    # The part's object is moved there, in the parent's frame.
    (update,) = [
      u for u in world.updated if u["node_b"].name == "rebot_printed_part"
    ]
    self.assertEqual(update["node_a"].name, "root")
    self.assertEqual(update["node_to_update"].name, "rebot_printed_part")

  def test_vertical_grasp_creates_both_frames(self):
    world = _world()
    result = _run(world, _params())
    frames = {c["frame_name"]: c["parent_t_frame"] for c in world.created}
    self.assertCountEqual(frames, ["pre_grasp", "grasp"])
    grasp = frames["grasp"].translation
    pregrasp = frames["pre_grasp"].translation
    self.assertSequenceAlmostEqual(list(grasp), [0.1, 0.2, 1.5])
    # Backed off straight up by the approach offset.
    self.assertAlmostEqual(float(pregrasp[2]), 1.58)
    self.assertSequenceAlmostEqual(list(pregrasp)[:2], [0.1, 0.2])
    self.assertSequenceAlmostEqual(
      list(conv.pose_from_proto(result.parent_t_grasp).translation), list(grasp)
    )

  def test_existing_frames_are_moved_not_created(self):
    world = _world(root_frames=["pre_grasp", "grasp"])
    _run(world, _params())
    self.assertEmpty(world.created)
    moved = {u["node_b"].name for u in world.updated}
    self.assertContainsSubset({"pre_grasp", "grasp"}, moved)

  def test_a_tilted_grasp_backs_off_along_the_approach(self):
    world = _world(camera_offset=(0.5, 0.0, 0.1))
    result = _run(
      world, _params(approach_tilt_degrees=75.0, approach_offset_z=0.06)
    )
    grasp = conv.pose_from_proto(result.parent_t_grasp).translation
    pregrasp = conv.pose_from_proto(result.parent_t_pregrasp).translation
    self.assertLess(float(pregrasp[0]), float(grasp[0]))
    self.assertGreater(float(pregrasp[2]), float(grasp[2]))

  def test_the_tools_orientation_picks_the_wrist_turn(self):
    # A part at identity has four top-down candidates a quarter turn apart; the
    # one nearest the tool's current orientation is taken.
    def grasp_rotation(tool_orientation):
      world = _world(tool=_pose((0.2, 0.0, 0.3), tool_orientation))
      result = _run(world, _params())
      return conv.pose_from_proto(result.parent_t_grasp).rotation.quaternion

    near_x = grasp_rotation((1.0, 0.0, 0.0, 0.0))
    near_y = grasp_rotation((0.0, 1.0, 0.0, 0.0))
    self.assertNotAlmostEqual(abs(near_x.x), abs(near_y.x))
    self.assertAlmostEqual(abs(near_x.x), 1.0)
    self.assertAlmostEqual(abs(near_y.y), 1.0)

  def test_publish_off_still_moves_the_part_and_checks_the_height(self):
    world = _world()
    result = _run(world, _params(publish_grasp_frames=False))
    self.assertEmpty(world.created)
    self.assertFalse(result.HasField("parent_t_grasp"))
    self.assertNotEmpty(world.updated)
    self.assertEqual(
      _error_code(
        _world(), _params(publish_grasp_frames=False, min_safe_z=9.0)
      ),
      skill.TARGET_TOO_LOW,
    )

  def test_a_part_below_the_minimum_height_writes_nothing(self):
    world = _world()
    self.assertEqual(
      _error_code(world, _params(min_safe_z=2.0)), skill.TARGET_TOO_LOW
    )
    self.assertEmpty(world.created)
    self.assertEmpty(world.updated)

  def test_a_missing_target_object_is_skipped(self):
    world = _world()
    del world._objects["rebot_printed_part"]
    _run(world, _params())
    self.assertCountEqual(
      [c["frame_name"] for c in world.created], ["pre_grasp", "grasp"]
    )

  def test_bad_parameters_are_refused(self):
    world = _world()
    self.assertEqual(
      _error_code(world, _params(approach_tilt_degrees=90.0)),
      skill.INVALID_INPUT,
    )
    self.assertEqual(
      _error_code(world, _params(yaw_symmetry_degrees=45.0)),
      skill.INVALID_INPUT,
    )
    self.assertEqual(
      _error_code(world, _params(approach_offset_z=-0.1)), skill.INVALID_INPUT
    )
    self.assertEqual(
      _error_code(world, _params(grasp_frame_name="")), skill.INVALID_INPUT
    )
    unset = _params()
    unset.ClearField("camera_t_target")
    self.assertEqual(_error_code(world, unset), skill.INVALID_INPUT)
    self.assertEmpty(world.created)

  def test_a_missing_camera_or_parent_is_an_error(self):
    self.assertEqual(
      _error_code(_world(), _params(camera_name="nope")),
      skill.MISSING_WORLD_ENTITY,
    )
    self.assertEqual(
      _error_code(_world(), _params(parent_object="nope")),
      skill.MISSING_WORLD_ENTITY,
    )

  def test_the_footprint_locks_the_world_and_preview_is_refused(self):
    footprint = skill.PlanCuboidGrasp().get_footprint(None, None)
    self.assertTrue(footprint.lock_the_universe)
    with self.assertRaises(NotImplementedError):
      skill.PlanCuboidGrasp().preview(None, None)


if __name__ == "__main__":
  absltest.main()
