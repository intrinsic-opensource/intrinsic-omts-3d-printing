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

"""configure_cell against a fake world with real transform math."""

import math
import types

from absl.testing import absltest
from intrinsic.math.proto import point_pb2
from intrinsic.math.python import data_types
from intrinsic.math.python import proto_conversion as conv
from intrinsic.skills.python import skill_interface

from skills.cell import configure_cell as skill
from skills.cell import configure_cell_pb2 as pb
from src.core import drop_off


def _pose(position, quaternion=(0.0, 0.0, 0.0, 1.0)) -> data_types.Pose3:
  # The world holds exact unit quaternions; the SDK refuses others.
  norm = math.sqrt(sum(c * c for c in quaternion))
  return data_types.Pose3(
    data_types.Rotation3(data_types.Quaternion([c / norm for c in quaternion])),
    list(position),
  )


def _yaw(degrees: float) -> tuple[float, float, float, float]:
  half = math.radians(degrees) / 2
  return (0.0, 0.0, math.sin(half), math.cos(half))


class _Node:
  def __init__(self, name, frame_names=(), **children):
    self.name = name
    self.frame_names = list(frame_names)
    for key, value in children.items():
      setattr(self, key, value)


def _ref_name(ref) -> str:
  by_name = ref.by_name
  if by_name.HasField("object"):
    return by_name.object.object_name
  return by_name.frame.frame_name


class _World:
  """Nodes with poses in the root; `get_transform` composes them. A batch of
  updates moves the nodes the way the world service would."""

  def __init__(self, a_frames_exist=True):
    self.root_t = {
      "root": _pose((0, 0, 0)),
      "printer": _pose((0.5895, -0.0064, 0.0), _yaw(90)),
      "flange": _pose((0.30, 0.05, 0.40), (1.0, 0.0, 0.0, 0.0)),
      "view": _pose((0.29, -0.024, 0.23), (0.866025, 0.0, 0.5, 0.0)),
    }
    self.root_t["orbbec_camera"] = self.root_t["flange"] * _pose(
      (0.07, -0.024, 0.076), _yaw(90)
    )
    self.root_t["tool_frame"] = self.root_t["flange"] * _pose((0, 0, 0.15))
    self.batches = []
    self.created = []
    a_frames = ["place_vise", "pre_place_vise", "machine_approach"]
    self._nodes = {
      "root": _Node(
        "root",
        frame_names=["view"] + (a_frames if a_frames_exist else []),
        view=_Node("view"),
      ),
      "printer": _Node("printer"),
      "orbbec_camera": _Node("orbbec_camera"),
      "rebot": _Node("rebot", flange=_Node("flange")),
      "gripper": _Node("gripper", tool_frame=_Node("tool_frame")),
    }

  def __getattr__(self, name):
    try:
      return self.__dict__["_nodes"][name]
    except KeyError as exc:
      raise AttributeError(name) from exc

  def get_transform(self, node_a, node_b):
    return self.root_t[node_a.name].inverse() * self.root_t[node_b.name]

  def batch_update(self, updates):
    self.batches.append(updates)
    for update in updates.updates:
      if update.HasField("create_frame"):
        request = update.create_frame
        parent = request.parent_object_with_filter.reference.by_name.object_name
        self.root_t[request.new_frame_name] = self.root_t[
          parent
        ] * conv.pose_from_proto(request.parent_t_new_frame)
        self.created.append(request.new_frame_name)
        continue
      request = update.update_transform
      node_a, node_b = _ref_name(request.node_a), _ref_name(request.node_b)
      self.root_t[node_b] = self.root_t[node_a] * conv.pose_from_proto(
        request.a_t_b
      )


def _run(world, **kwargs):
  params = pb.ConfigureCellParams(**kwargs)
  return skill.ConfigureCell().execute(
    types.SimpleNamespace(params=params),
    types.SimpleNamespace(object_world=world),
  )


def _code(world, **kwargs) -> int:
  try:
    _run(world, **kwargs)
  except skill_interface.SkillError as exc:
    return exc.status_code[1]
  raise AssertionError("expected a SkillError")


def _camera_at_view(world, view_name="view"):
  """Where the view puts the camera, in the root."""
  tool_t_camera = world.get_transform(
    world._nodes["gripper"].tool_frame, world._nodes["orbbec_camera"]
  )
  return world.root_t[view_name] * tool_t_camera


class ConfigureCellTest(absltest.TestCase):
  def test_the_printer_moves_along_x_only(self):
    world = _World()
    before = world.root_t["printer"]
    result = _run(world, printer_distance_m=0.62, follow_view=False)
    after = world.root_t["printer"]
    self.assertAlmostEqual(float(after.translation[0]), 0.62)
    self.assertAlmostEqual(
      float(after.translation[1]), float(before.translation[1])
    )
    self.assertAlmostEqual(
      float(after.translation[2]), float(before.translation[2])
    )
    self.assertEqual(after.rotation.quaternion, before.rotation.quaternion)
    self.assertSequenceAlmostEqual(
      list(conv.pose_from_proto(result.parent_t_printer).translation),
      list(after.translation),
    )
    self.assertFalse(result.HasField("parent_t_view"))

  def test_the_view_follows_the_printer(self):
    world = _World()
    camera_before = _camera_at_view(world)
    dx = 0.62 - 0.5895
    _run(world, printer_distance_m=0.62)
    camera_after = _camera_at_view(world)
    # The camera sees the printer as before: it moved with it.
    self.assertSequenceAlmostEqual(
      list(camera_after.translation),
      [
        float(camera_before.translation[0]) + dx,
        float(camera_before.translation[1]),
        float(camera_before.translation[2]),
      ],
    )
    self.assertAlmostEqual(
      abs(
        float(
          (
            camera_after.rotation.quaternion.x
            * camera_before.rotation.quaternion.x
          )
          + (
            camera_after.rotation.quaternion.y
            * camera_before.rotation.quaternion.y
          )
          + (
            camera_after.rotation.quaternion.z
            * camera_before.rotation.quaternion.z
          )
          + (
            camera_after.rotation.quaternion.w
            * camera_before.rotation.quaternion.w
          )
        )
      ),
      1.0,
    )

  def test_a_new_mount_keeps_the_camera_where_it_was_at_the_view(self):
    world = _World()
    camera_before = _camera_at_view(world)
    old_view = world.root_t["view"]
    _run(world, camera_offset_m=point_pb2.Point(x=0.09, y=-0.03, z=0.10))
    # The camera is on the flange at the new offset, in the flange frame.
    flange_t_camera = world.get_transform(
      world._nodes["rebot"].flange, world._nodes["orbbec_camera"]
    )
    self.assertSequenceAlmostEqual(
      list(flange_t_camera.translation), [0.09, -0.03, 0.10]
    )
    # The view moved, because the tool is not where the camera is.
    self.assertNotEqual(
      list(world.root_t["view"].translation), list(old_view.translation)
    )
    camera_after = _camera_at_view(world)
    self.assertSequenceAlmostEqual(
      list(camera_after.translation), list(camera_before.translation)
    )

  def test_both_together_in_one_update(self):
    world = _World()
    camera_before = _camera_at_view(world)
    _run(
      world,
      printer_distance_m=0.60,
      camera_offset_m=point_pb2.Point(x=0.08, y=-0.02, z=0.09),
    )
    self.assertLen(world.batches, 1)
    self.assertLen(world.batches[0].updates, 3)
    camera_after = _camera_at_view(world)
    self.assertSequenceAlmostEqual(
      list(camera_after.translation),
      [
        float(camera_before.translation[0]) + (0.60 - 0.5895),
        float(camera_before.translation[1]),
        float(camera_before.translation[2]),
      ],
    )

  def test_an_empty_call_changes_nothing(self):
    world = _World()
    result = _run(world)
    self.assertEmpty(world.batches)
    self.assertFalse(result.HasField("parent_t_view"))

  def test_the_view_stays_if_asked(self):
    world = _World()
    view = world.root_t["view"]
    _run(world, printer_distance_m=0.62, follow_view=False)
    self.assertEqual(world.root_t["view"], view)
    self.assertLen(world.batches[0].updates, 1)

  def test_bad_values_are_refused_before_anything_changes(self):
    world = _World()
    for kwargs in (
      dict(printer_distance_m=0.0),
      dict(printer_distance_m=590.0),
      dict(camera_offset_m=point_pb2.Point(x=70.0, y=0.0, z=0.0)),
      dict(view_frame=""),
    ):
      self.assertEqual(_code(world, **kwargs), skill.INVALID_INPUT)
    self.assertEmpty(world.batches)

  def test_a_missing_object_is_an_error(self):
    world = _World()
    for kwargs in (
      dict(printer_distance_m=0.6, printer_object="nope"),
      dict(printer_distance_m=0.6, flange_frame="nope"),
      dict(printer_distance_m=0.6, view_frame="nope"),
    ):
      self.assertEqual(_code(world, **kwargs), skill.MISSING_WORLD_ENTITY)
    self.assertEmpty(world.batches)

  def _drop_off(self, **overrides):
    values = dict(
      approach_tilt_degrees=75.0,
      radius_m=0.55,
      bearing_degrees=130.0,
      part_half_height_m=0.015,
    )
    values.update(overrides)
    return pb.DropOff(**values)

  def test_a_frames_are_moved_to_the_new_part_height(self):
    world = _World()
    _run(world, drop_off=self._drop_off(part_half_height_m=0.024))
    self.assertEmpty(world.created)
    expected = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.024)
    for name in ("place_vise", "pre_place_vise", "machine_approach"):
      position, _ = expected[name]
      self.assertSequenceAlmostEqual(
        list(world.root_t[name].translation), list(position)
      )
    # Nothing else was in the call, so nothing else moved.
    self.assertLen(world.batches[0].updates, 3)
    self.assertNotIn(
      "printer",
      [
        u.update_transform.node_b.by_name.object.object_name
        for u in world.batches[0].updates
      ],
    )

  def test_missing_a_frames_are_created(self):
    world = _World(a_frames_exist=False)
    result = _run(world, drop_off=self._drop_off())
    self.assertCountEqual(
      world.created, ["place_vise", "pre_place_vise", "machine_approach"]
    )
    expected, _ = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.015)[
      "place_vise"
    ]
    self.assertSequenceAlmostEqual(
      list(conv.pose_from_proto(result.parent_t_place).translation),
      list(expected),
    )

  def test_a_frames_and_the_printer_go_in_one_update(self):
    world = _World()
    _run(
      world,
      printer_distance_m=0.60,
      drop_off=self._drop_off(),
    )
    self.assertLen(world.batches, 1)
    # printer, view, and A's three frames.
    self.assertLen(world.batches[0].updates, 5)

  def test_a_frames_follow_the_requested_names_and_depth(self):
    world = _World(a_frames_exist=False)
    _run(
      world,
      drop_off=self._drop_off(
        grasp_depth_m=0.01,
        place_frame="a_place",
        pre_place_frame="a_pre",
        approach_frame="a_above",
      ),
    )
    self.assertCountEqual(world.created, ["a_place", "a_pre", "a_above"])
    expected, _ = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.015, 0.01)[
      "place_vise"
    ]
    self.assertSequenceAlmostEqual(
      list(world.root_t["a_place"].translation), list(expected)
    )

  def test_bad_a_frame_values_are_refused_before_anything_changes(self):
    world = _World()
    for overrides in (
      dict(approach_tilt_degrees=90.0),
      dict(radius_m=0.0),
      dict(radius_m=55.0),
      dict(part_half_height_m=0.0),
      dict(part_half_height_m=1.5),
      dict(grasp_depth_m=0.5),
      dict(place_frame="x", pre_place_frame="x"),
      dict(approach_frame=""),
    ):
      self.assertEqual(
        _code(
          world, printer_distance_m=0.6, drop_off=self._drop_off(**overrides)
        ),
        skill.INVALID_INPUT,
        overrides,
      )
    self.assertEmpty(world.batches)

  def test_footprint_locks_the_world_and_preview_is_refused(self):
    self.assertTrue(
      skill.ConfigureCell().get_footprint(None, None).lock_the_universe
    )
    with self.assertRaises(NotImplementedError):
      skill.ConfigureCell().preview(None, None)


if __name__ == "__main__":
  absltest.main()
