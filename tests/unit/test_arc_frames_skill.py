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

"""The generate_arc_frames skill against a fake object world service.

The skill talks to a real ObjectWorldClient whose gRPC stub is a small
in-memory world: named objects and frames with root-frame poses.
"""

import math

import grpc
import numpy as np
from absl.testing import absltest
from intrinsic.math.python import data_types, proto_conversion
from intrinsic.skills.python import skill_interface
from intrinsic.skills.testing import skill_test_utils as stu
from intrinsic.world.proto import object_world_refs_pb2 as refs
from intrinsic.world.proto import object_world_service_pb2 as service
from intrinsic.world.python import object_world_client

from skills.motion import arc_frames_skill, arc_math
from skills.motion import generate_arc_frames_pb2 as pb

ATOL = 1e-9


class FakeRpcError(grpc.RpcError):
  def __init__(self, code: grpc.StatusCode, details: str):
    super().__init__(details)
    self._code = code
    self._details = details

  def code(self):
    return self._code

  def details(self):
    return self._details


def _pose_proto(m: np.ndarray):
  return proto_conversion.pose_to_proto(data_types.Pose3.from_matrix4x4(m))


def _matrix(pose_proto) -> np.ndarray:
  return proto_conversion.pose_from_proto(pose_proto).matrix4x4()


def translation(x, y, z) -> np.ndarray:
  m = np.eye(4)
  m[:3, 3] = [x, y, z]
  return m


class FakeWorldStub:
  """GetTransform, GetObject (root) and UpdateWorldResources, in memory."""

  def __init__(self):
    self.objects: dict[str, np.ndarray] = {"root": np.eye(4)}
    # (object name, frame name) -> root_t_frame
    self.frames: dict[tuple[str, str], np.ndarray] = {}
    self.update_requests = []
    self.fail_writes_with = None
    self.fail_reads_with = None

  def _lookup(self, ref: refs.TransformNodeReference) -> np.ndarray:
    if self.fail_reads_with is not None:
      raise FakeRpcError(self.fail_reads_with, "world service is broken")
    if ref.HasField("id"):
      if ref.id in self.objects:
        return self.objects[ref.id]
    elif ref.by_name.HasField("object"):
      name = ref.by_name.object.object_name
      if name in self.objects:
        return self.objects[name]
    else:
      key = (ref.by_name.frame.object_name, ref.by_name.frame.frame_name)
      if key in self.frames:
        return self.frames[key]
    raise FakeRpcError(grpc.StatusCode.NOT_FOUND, f"no node {ref}")

  def GetTransform(self, request):  # pylint: disable=invalid-name
    a = self._lookup(request.node_a)
    b = self._lookup(request.node_b)
    return service.GetTransformResponse(a_t_b=_pose_proto(np.linalg.inv(a) @ b))

  def GetObject(self, request):  # pylint: disable=invalid-name
    assert request.object.id == "root", request
    obj = service.Object(id="root", name="root", type=service.ROOT)
    for owner, name in self.frames:
      if owner == "root":
        obj.frames.add(name=name, id=f"id_{name}")
    return obj

  def UpdateWorldResources(self, request):  # pylint: disable=invalid-name
    self.update_requests.append(request)
    if self.fail_writes_with is not None:
      raise FakeRpcError(self.fail_writes_with, "write refused")
    for update in request.world_updates.updates:
      kind = update.WhichOneof("update")
      if kind == "create_frame":
        create = update.create_frame
        assert create.parent_object_with_filter.reference.id == "root"
        key = ("root", create.new_frame_name)
        assert key not in self.frames, f"{key} exists"
        self.frames[key] = _matrix(create.parent_t_new_frame)
      elif kind == "update_transform":
        req = update.update_transform
        assert req.node_a.id == "root"
        assert req.node_to_update == req.node_b
        frame = req.node_b.by_name.frame
        key = (frame.object_name, frame.frame_name)
        assert key in self.frames, f"{key} missing"
        self.frames[key] = _matrix(req.a_t_b)
      else:
        raise AssertionError(f"unexpected update {kind}")
    return service.UpdateWorldResourcesResponse()


def frame_ref(object_name: str, frame_name: str):
  return refs.TransformNodeReference(
    by_name=refs.TransformNodeReferenceByName(
      frame=refs.FrameReferenceByName(
        object_name=object_name, frame_name=frame_name
      )
    )
  )


def object_ref(name: str):
  return refs.TransformNodeReference(
    by_name=refs.TransformNodeReferenceByName(
      object=refs.ObjectReferenceByName(object_name=name)
    )
  )


class _SkillTestBase(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.stub = FakeWorldStub()
    # A hinge (pivot) frame on a "printer" object, 0.3 m from a grip frame.
    self.stub.objects["printer"] = translation(0.8, 0.0, 0.0)
    self.stub.frames[("printer", "hinge")] = translation(0.8, 0.2, 0.3)
    self.stub.frames[("printer", "grip")] = translation(0.5, 0.2, 0.3)
    self.stub.objects["robot"] = translation(0.0, -0.1, 0.0)
    self.world = object_world_client.ObjectWorldClient(
      world_id="world", stub=self.stub
    )
    self.skill = arc_frames_skill.GenerateArcFrames()

  def params(self, **kwargs) -> pb.GenerateArcFramesParams:
    p = pb.GenerateArcFramesParams(
      pivot_frame=frame_ref("printer", "hinge"),
      grip_frame=frame_ref("printer", "grip"),
      total_angle_deg=-90.0,
      num_waypoints=3,
      grip_depth_m=0.015,
      approach_offset_m=0.06,
    )
    for key, value in kwargs.items():
      if key == "orientation":
        p.orientation.CopyFrom(value)
      elif isinstance(value, refs.TransformNodeReference):
        getattr(p, key).CopyFrom(value)
      else:
        setattr(p, key, value)
    return p

  def execute(self, params):
    return self.skill.execute(
      stu.make_test_execute_request(params),
      stu.make_test_execute_context(object_world=self.world),
    )

  def expected(self, params, origin=(0.0, 0.0, 0.0)):
    o = params.orientation
    return arc_math.arc_frames(
      self.stub.frames[("printer", "hinge")],
      self.stub.frames[("printer", "grip")][:3, 3],
      params.total_angle_deg,
      params.num_waypoints,
      mode=arc_math.Mode(o.mode),
      azimuth_deg=o.azimuth_deg,
      pitch_deg=o.pitch_deg,
      grip_depth_m=params.grip_depth_m,
      approach_offset_m=params.approach_offset_m,
      radial_origin=np.array(origin),
      prefix=params.frame_prefix or "arc",
    )

  def assert_frames_written(self, params, origin=(0.0, 0.0, 0.0)):
    for frame in self.expected(params, origin):
      np.testing.assert_allclose(
        self.stub.frames[("root", frame.name)],
        frame.root_t_tool,
        atol=ATOL,
        err_msg=frame.name,
      )


class ArcFramesSkillTest(_SkillTestBase):
  def test_creates_frames_with_exact_names(self):
    params = self.params()
    result = self.execute(params)
    names = [
      "arc_pregrasp",
      "arc_grasp",
      "arc_wp_00",
      "arc_wp_01",
      "arc_wp_02",
      "arc_retreat",
    ]
    self.assertEqual(list(result.frame_names), names)
    self.assertEqual(result.final_angle_deg, -90.0)
    self.assertEqual(
      sorted(k[1] for k in self.stub.frames if k[0] == "root"), sorted(names)
    )
    self.assertLen(self.stub.update_requests, 1)  # one atomic write
    kinds = {
      u.WhichOneof("update")
      for u in self.stub.update_requests[0].world_updates.updates
    }
    self.assertEqual(kinds, {"create_frame"})
    self.assert_frames_written(params)
    # -90 deg about the hinge's +z takes the grip from (0.5, 0.2) to (0.8, 0.5).
    last = self.stub.frames[("root", "arc_wp_02")]
    np.testing.assert_allclose(
      last[:3, 3] - 0.015 * last[:3, 2], [0.8, 0.5, 0.3], atol=ATOL
    )

  def test_rerun_updates_existing_frames(self):
    self.execute(self.params())
    self.stub.update_requests.clear()
    params = self.params(total_angle_deg=-45.0, approach_offset_m=0.1)
    result = self.execute(params)
    self.assertEqual(result.final_angle_deg, -45.0)
    kinds = {
      u.WhichOneof("update")
      for u in self.stub.update_requests[0].world_updates.updates
    }
    self.assertEqual(kinds, {"update_transform"})
    self.assert_frames_written(params)

  def test_partial_rerun_creates_only_new_frames(self):
    self.execute(self.params(num_waypoints=1))
    self.stub.update_requests.clear()
    params = self.params(num_waypoints=2)
    self.execute(params)
    by_frame = {}
    for u in self.stub.update_requests[0].world_updates.updates:
      if u.HasField("create_frame"):
        by_frame[u.create_frame.new_frame_name] = "create"
      else:
        by_frame[u.update_transform.node_b.by_name.frame.frame_name] = "update"
    self.assertEqual(by_frame.pop("arc_wp_01"), "create")
    self.assertEqual(set(by_frame.values()), {"update"})
    self.assert_frames_written(params)

  def test_prefix_and_radial_origin_object(self):
    params = self.params(
      frame_prefix="door", radial_origin_frame=object_ref("robot")
    )
    result = self.execute(params)
    self.assertEqual(result.frame_names[0], "door_pregrasp")
    self.assertEqual(result.frame_names[-1], "door_retreat")
    self.assert_frames_written(params, origin=(0.0, -0.1, 0.0))
    # Seen from the robot at (0, -0.1), the start grip (0.5, 0.2) is at
    # atan2(0.3, 0.5).
    z = self.stub.frames[("root", "door_grasp")][:3, 2]
    self.assertAlmostEqual(
      math.atan2(z[1], z[0]), math.atan2(0.3, 0.5), places=9
    )

  def test_fixed_azimuth_with_pitch(self):
    orientation = pb.ToolOrientation(
      mode=pb.ToolOrientation.FIXED_AZIMUTH, azimuth_deg=-30.0, pitch_deg=10.0
    )
    # In FIXED_AZIMUTH the radial origin is not read (it need not exist).
    params = self.params(
      orientation=orientation, radial_origin_frame=object_ref("nowhere")
    )
    self.execute(params)
    self.assert_frames_written(params)
    for name in ("arc_grasp", "arc_wp_02"):
      z = self.stub.frames[("root", name)][:3, 2]
      self.assertAlmostEqual(math.degrees(math.atan2(z[1], z[0])), -30.0)
      self.assertAlmostEqual(z[2], -math.sin(math.radians(10.0)))

  def test_preview_records_updates_without_writing(self):
    context = stu.make_test_preview_context(object_world=self.world)
    recorded = []
    context.record_world_update = lambda update, elapsed, duration: (
      recorded.append(update)
    )
    result = self.skill.preview(
      stu.make_test_preview_request(self.params()), context
    )
    self.assertLen(result.frame_names, 6)
    self.assertLen(recorded, 6)
    self.assertEqual(recorded[1].create_frame.new_frame_name, "arc_grasp")
    self.assertEmpty(self.stub.update_requests)

  def test_footprint_locks_the_universe(self):
    footprint = self.skill.get_footprint(
      stu.make_test_get_footprint_request(self.params()),
      stu.make_test_get_footprint_context(),
    )
    self.assertTrue(footprint.lock_the_universe)
    self.assertEqual(
      arc_frames_skill.GenerateArcFrames.required_equipment(), {}
    )


class ArcFramesSkillErrorTest(_SkillTestBase):
  def assert_code(self, code, params):
    with self.assertRaises(skill_interface.SkillError) as cm:
      self.execute(params)
    self.assertEqual(cm.exception.status_code[1], code, str(cm.exception))
    return cm.exception

  def test_missing_references(self):
    p = self.params()
    p.ClearField("pivot_frame")
    self.assert_code(arc_frames_skill.MISSING_REFERENCE, p)
    p = self.params()
    p.ClearField("grip_frame")
    self.assert_code(arc_frames_skill.MISSING_REFERENCE, p)
    p = self.params(grip_frame=refs.TransformNodeReference())  # empty oneof
    self.assert_code(arc_frames_skill.MISSING_REFERENCE, p)

  def test_invalid_values(self):
    bad = [
      {"num_waypoints": 0},
      {"num_waypoints": -3},
      {"num_waypoints": arc_math.MAX_WAYPOINTS + 1},
      {"total_angle_deg": math.nan},
      {"total_angle_deg": 361.0},
      {"grip_depth_m": math.inf},
      {"orientation": pb.ToolOrientation(pitch_deg=90.0)},
      {"orientation": pb.ToolOrientation(pitch_deg=-95.0)},
      {"orientation": pb.ToolOrientation(mode=7)},
      {"frame_prefix": "1arc"},
      {"frame_prefix": "door arc"},
      {"frame_prefix": "door.arc"},
    ]
    for kwargs in bad:
      with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
        self.assert_code(arc_frames_skill.INVALID_PARAMS, self.params(**kwargs))
    self.assertEmpty(self.stub.update_requests)

  def test_frame_not_found(self):
    for field in ("pivot_frame", "grip_frame", "radial_origin_frame"):
      with self.subTest(field):
        p = self.params(**{field: frame_ref("printer", "missing")})
        err = self.assert_code(arc_frames_skill.NOT_FOUND, p)
        self.assertIn(field, str(err))
    p = self.params(pivot_frame=object_ref("missing_object"))
    self.assert_code(arc_frames_skill.NOT_FOUND, p)

  def test_grip_on_the_pivot_axis(self):
    self.stub.frames[("printer", "grip")] = translation(0.8, 0.2, 0.9)
    self.assert_code(arc_frames_skill.GRIP_ON_AXIS, self.params())
    # Same point as the pivot.
    self.stub.frames[("printer", "grip")] = translation(0.8, 0.2, 0.3)
    self.assert_code(arc_frames_skill.GRIP_ON_AXIS, self.params())
    self.assertEmpty(self.stub.update_requests)

  def test_radial_azimuth_undefined(self):
    # The robot straight below the grip point at the end of the arc.
    self.stub.objects["robot"] = translation(0.8, 0.5, 0.0)
    p = self.params(radial_origin_frame=object_ref("robot"))
    self.assert_code(arc_frames_skill.UNDEFINED_AZIMUTH, p)

  def test_world_failures(self):
    self.stub.fail_writes_with = grpc.StatusCode.INTERNAL
    self.assert_code(arc_frames_skill.WORLD_FAILED, self.params())
    self.stub.fail_writes_with = None
    self.stub.fail_reads_with = grpc.StatusCode.INTERNAL
    self.assert_code(arc_frames_skill.WORLD_FAILED, self.params())


if __name__ == "__main__":
  absltest.main()
