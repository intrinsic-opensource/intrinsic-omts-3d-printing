# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""register_pose_estimator against fake installed-assets and train services."""

from concurrent import futures

import grpc
from absl.testing import absltest
from google.longrunning import operations_pb2
from google.protobuf import empty_pb2
from intrinsic.assets.proto import id_pb2, installed_assets_pb2
from intrinsic.assets.proto import installed_assets_pb2_grpc as assets_grpc
from intrinsic.assets.proto.v1 import resolved_dependency_pb2
from intrinsic.perception.proto.v1 import train_service_pb2
from intrinsic.perception.proto.v1 import train_service_pb2_grpc as train_grpc
from intrinsic.skills.python import skill_canceller, skill_interface
from intrinsic.skills.testing import skill_test_utils as stu

from skills.perception import register_pose_estimator as skill
from skills.perception import register_pose_estimator_pb2 as pb

_READER = "grpc://intrinsic_proto.assets.v1.InstalledAssetsReader"
_TRAIN = "grpc://intrinsic_proto.perception.v1.TrainService"


class _Reader(assets_grpc.InstalledAssetsReaderServicer):
  def __init__(self, entities=1):
    self.entities = entities
    self.requested = []
    self.installed = set()

  def GetInstalledAsset(self, request, context):
    self.requested.append(request)
    if request.id.name in self.installed:
      return installed_assets_pb2.InstalledAsset()
    if request.id.name.endswith("_est"):
      context.abort(grpc.StatusCode.NOT_FOUND, "no such asset")
    asset = installed_assets_pb2.InstalledAsset()
    so = asset.deployment_data.scene_object.manifest.assets.scene_object_model
    for i in range(self.entities):
      so.entities.add().name = f"link{i}"
    return asset


class _Train(train_grpc.TrainServiceServicer):
  def __init__(self):
    self.jobs = []
    self.saved = []
    self.deleted = []
    self.error = None
    self.save_code = None

  def CreateTrainingJob(self, request, context):
    self.jobs.append(request)
    return operations_pb2.Operation(name="operations/ioc-train-test")

  def GetTrainingJob(self, request, context):
    op = operations_pb2.Operation(name=request.name, done=True)
    if self.error:
      op.error.message = self.error
    return op

  def SaveTrainingJob(self, request, context):
    if self.save_code:
      context.abort(self.save_code, "exists")
    self.saved.append(request)
    return train_service_pb2.SaveTrainingJobResponse()

  def DeleteTrainingJob(self, request, context):
    self.deleted.append(request.name)
    return empty_pb2.Empty()


def _dependency(iface: str, port: int | None):
  dep = resolved_dependency_pb2.ResolvedDependency(name="x")
  if port is not None:
    dep.interfaces[iface].grpc.connection.address = f"127.0.0.1:{port}"
  return dep


class RegisterPoseEstimatorTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.reader = _Reader()
    self.train = _Train()
    self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    assets_grpc.add_InstalledAssetsReaderServicer_to_server(
      self.reader, self.server
    )
    train_grpc.add_TrainServiceServicer_to_server(self.train, self.server)
    self.port = self.server.add_insecure_port("127.0.0.1:0")
    self.server.start()
    self.addCleanup(lambda: self.server.stop(0).wait())
    self.context = stu.make_test_execute_context(
      canceller=skill_canceller.SkillCancellationManager(ready_timeout=2)
    )

  def run_skill(self, reader_port=0, train_port=0, **kwargs):
    defaults = dict(
      installed_assets=_dependency(_READER, reader_port or self.port),
      train_service=_dependency(_TRAIN, train_port or self.port),
      scene_object=id_pb2.Id(package="ai.intrinsic", name="benchy"),
      pose_estimator=id_pb2.Id(package="ai.intrinsic", name="benchy_est"),
    )
    defaults.update(kwargs)
    return skill.RegisterPoseEstimator().execute(
      stu.make_test_execute_request(pb.RegisterPoseEstimatorParams(**defaults)),
      self.context,
    )

  def assert_error(self, code, **kwargs):
    with self.assertRaises(skill_interface.SkillError) as raised:
      self.run_skill(**kwargs)
    self.assertIn(f":{code}", str(raised.exception))

  def test_registers_the_estimator_for_the_installed_asset(self):
    result = self.run_skill(confidence_threshold=0.3, text_prompt="a part")
    self.assertEqual(result.pose_estimator.name, "benchy_est")
    self.assertFalse(result.already_registered)
    self.assertEqual(result.pose_estimator_id.id, "benchy_est")
    self.assertEqual(result.pose_estimator_id.package, "ai.intrinsic")
    self.assertEqual(
      [r.id.name for r in self.reader.requested], ["benchy_est", "benchy"]
    )
    (job,) = self.train.jobs
    self.assertEqual(job.asset_metadata.asset_name, "benchy_est")
    target = job.pose_estimation_config.targets[0]
    self.assertEqual(target.id, "benchy")
    self.assertTrue(target.scene_object.entities)
    (saved,) = self.train.saved
    self.assertEqual(saved.asset_id.name, "benchy_est")
    self.assertEqual(self.train.deleted, ["operations/ioc-train-test"])

  def test_an_installed_estimator_is_left_alone(self):
    self.reader.installed.add("benchy_est")
    result = self.run_skill()
    self.assertTrue(result.already_registered)
    self.assertEqual(result.pose_estimator_id.id, "benchy_est")
    self.assertEqual(result.pose_estimator.name, "benchy_est")
    self.assertEmpty(self.train.jobs)
    self.assertEmpty(self.train.saved)

  def test_defaults_match_the_cells_registration(self):
    self.run_skill()
    params = train_service_pb2.CreateTrainingJobRequest()
    params.CopyFrom(self.train.jobs[0])
    text = str(params.pose_estimation_config.inference_params)
    self.assertIn("object on a table", text)

  def test_invalid_parameters_fail_before_any_call(self):
    for kwargs in (
      {"scene_object": id_pb2.Id()},
      {"pose_estimator": id_pb2.Id(package="ai.intrinsic")},
      {"timeout_seconds": 0.0},
      {"timeout_seconds": 1000.0},
      {"confidence_threshold": 1.5},
    ):
      self.assert_error(skill.INVALID_INPUT, **kwargs)
    self.assertEmpty(self.reader.requested)
    self.assertEmpty(self.train.jobs)

  def test_missing_dependency_interface_fails(self):
    self.assert_error(
      skill.SERVICE_UNAVAILABLE,
      installed_assets=resolved_dependency_pb2.ResolvedDependency(),
    )
    self.assertEmpty(self.train.jobs)

  def test_a_non_scene_object_asset_fails(self):
    self.reader.entities = 0
    self.assert_error(skill.INVALID_INPUT)
    self.assertEmpty(self.train.jobs)

  def test_training_failure_is_reported_and_cleaned_up(self):
    self.train.error = "boom"
    self.assert_error(skill.TRAINING_FAILED)
    self.assertEmpty(self.train.saved)
    self.assertEqual(self.train.deleted, ["operations/ioc-train-test"])

  def test_an_existing_estimator_fails_without_hiding_it(self):
    self.train.save_code = grpc.StatusCode.ALREADY_EXISTS
    self.assert_error(skill.TRAINING_FAILED)
    self.assertEqual(self.train.deleted, ["operations/ioc-train-test"])


if __name__ == "__main__":
  absltest.main()
