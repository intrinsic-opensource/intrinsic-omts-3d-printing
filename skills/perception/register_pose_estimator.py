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

"""Skill: register a pose estimator for an installed scene-object asset.

Step C1 (research/CLUSTER_NATIVE_HANDOFF.md). The skill declares the services it uses as
`ResolvedDependency` fields of its parameters, as intrinsic-core's
`estimate_pose_multi_view` and `create_object` do, so it needs no equipment
manifest and no SDK allowlist entry. It reads the scene object of the installed
asset, has the cell's train service build and save the pose estimator, and
never touches the world.
"""

import logging
import math
import time

import grpc
from google.longrunning import operations_pb2
from intrinsic.assets.dependencies import utils as asset_utils
from intrinsic.assets.proto import (
  installed_assets_pb2,
  installed_assets_pb2_grpc,
  view_pb2,
)
from intrinsic.perception.proto.v1 import (
  pose_estimator_id_pb2,
  train_service_pb2,
  train_service_pb2_grpc,
)
from intrinsic.skills.proto import footprint_pb2
from intrinsic.skills.python import skill_interface

from skills.perception import register_pose_estimator_pb2 as pb
from skills.perception import train_requests

INVALID_INPUT = 2001
SERVICE_UNAVAILABLE = 2002
TRAINING_FAILED = 2003

_READER = "grpc://intrinsic_proto.assets.v1.InstalledAssetsReader"
_TRAIN = "grpc://intrinsic_proto.perception.v1.TrainService"
_POLL_SECONDS = 0.5


def _result(
  estimator, already_registered: bool
) -> pb.RegisterPoseEstimatorResult:
  return pb.RegisterPoseEstimatorResult(
    pose_estimator=estimator,
    already_registered=already_registered,
    pose_estimator_id=pose_estimator_id_pb2.PoseEstimatorId(
      package=estimator.package, id=estimator.name
    ),
  )


def _optional(params, field, default):
  return getattr(params, field) if params.HasField(field) else default


def _check_id(asset_id, name: str) -> None:
  if not asset_id.package or not asset_id.name:
    raise skill_interface.SkillError(
      INVALID_INPUT, f"{name} needs a package and a name"
    )


def _is_installed(reader, asset_id) -> bool:
  try:
    reader.GetInstalledAsset(
      installed_assets_pb2.GetInstalledAssetRequest(id=asset_id), timeout=30
    )
  except grpc.RpcError as exc:
    if exc.code() == grpc.StatusCode.NOT_FOUND:
      return False
    raise skill_interface.SkillError(
      SERVICE_UNAVAILABLE,
      f"Cannot look up {asset_id.package}.{asset_id.name}: {exc.code().name}",
    ) from exc
  return True


def _scene_object(reader, asset_id):
  try:
    asset = reader.GetInstalledAsset(
      installed_assets_pb2.GetInstalledAssetRequest(
        id=asset_id, view=view_pb2.AssetViewType.ASSET_VIEW_TYPE_FULL
      ),
      timeout=30,
    )
  except grpc.RpcError as exc:
    raise skill_interface.SkillError(
      SERVICE_UNAVAILABLE,
      f"Cannot read {asset_id.package}.{asset_id.name}: {exc.code().name}",
    ) from exc
  scene_object = (
    asset.deployment_data.scene_object.manifest.assets.scene_object_model
  )
  if not scene_object.entities:
    raise skill_interface.SkillError(
      INVALID_INPUT,
      f"{asset_id.package}.{asset_id.name} is not a scene-object asset",
    )
  return scene_object


class RegisterPoseEstimator(skill_interface.Skill):
  def get_footprint(self, request, context) -> footprint_pb2.Footprint:
    return footprint_pb2.Footprint(lock_the_universe=False)

  def preview(self, request, context):
    raise NotImplementedError(
      "Registering a pose estimator changes the cluster; preview cannot"
    )

  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.RegisterPoseEstimatorParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.RegisterPoseEstimatorResult:
    params = request.params
    _check_id(params.scene_object, "scene_object")
    _check_id(params.pose_estimator, "pose_estimator")
    confidence = _optional(params, "confidence_threshold", 0.25)
    timeout = _optional(params, "timeout_seconds", 120.0)
    if not math.isfinite(timeout) or not 0 < timeout <= 900:
      raise skill_interface.SkillError(
        INVALID_INPUT, "timeout_seconds must be in (0, 900]"
      )
    if not 0 < confidence <= 1:
      raise skill_interface.SkillError(
        INVALID_INPUT, "confidence_threshold must be in (0, 1]"
      )
    context.canceller.ready()
    try:
      reader_channel = asset_utils.connect(params.installed_assets, _READER)
      train_channel = asset_utils.connect(params.train_service, _TRAIN)
    except (asset_utils.MissingInterfaceError, asset_utils.NotGRPCError) as exc:
      raise skill_interface.SkillError(
        SERVICE_UNAVAILABLE, f"Missing dependency: {exc}"
      ) from exc
    with reader_channel, train_channel:
      reader = installed_assets_pb2_grpc.InstalledAssetsReaderStub(
        reader_channel
      )
      if _is_installed(reader, params.pose_estimator):
        logging.info(
          "Pose estimator %s.%s is already installed",
          params.pose_estimator.package,
          params.pose_estimator.name,
        )
        return _result(params.pose_estimator, True)
      scene_object = _scene_object(reader, params.scene_object)
      job = train_requests.training_request(
        scene_object,
        params.scene_object.name,
        params.pose_estimator,
        confidence,
        refinement_iters=_optional(params, "refinement_iters", 5),
        visibility_threshold=_optional(params, "visibility_threshold", 0.15),
        text_prompt=_optional(params, "text_prompt", "object on a table"),
      )
      stub = train_service_pb2_grpc.TrainServiceStub(train_channel)
      self._register(stub, job, params.pose_estimator, timeout, context)
    return _result(params.pose_estimator, False)

  def _register(self, stub, job, estimator, timeout, context) -> None:
    name = f"{estimator.package}.{estimator.name}"
    deadline = time.monotonic() + timeout
    try:
      op = stub.CreateTrainingJob(job, timeout=60)
    except grpc.RpcError as exc:
      raise skill_interface.SkillError(
        TRAINING_FAILED, f"CreateTrainingJob failed: {exc.details()}"
      ) from exc
    try:
      while not op.done:
        if time.monotonic() > deadline:
          raise skill_interface.SkillError(
            TRAINING_FAILED, f"Training {op.name} timed out"
          )
        if context.canceller.wait(_POLL_SECONDS):
          raise skill_interface.SkillCancelledError()
        op = stub.GetTrainingJob(
          operations_pb2.GetOperationRequest(name=op.name), timeout=30
        )
      if op.HasField("error"):
        raise skill_interface.SkillError(
          TRAINING_FAILED, f"Training failed: {op.error.message}"
        )
      try:
        stub.SaveTrainingJob(
          train_service_pb2.SaveTrainingJobRequest(
            name=op.name, asset_id=estimator
          ),
          timeout=60,
        )
      except grpc.RpcError as exc:
        raise skill_interface.SkillError(
          TRAINING_FAILED, f"Saving {name} failed: {exc.details()}"
        ) from exc
      logging.info("Registered pose estimator %s", name)
    finally:
      try:
        stub.DeleteTrainingJob(
          operations_pb2.DeleteOperationRequest(name=op.name), timeout=30
        )
      except grpc.RpcError:
        logging.warning("Could not delete training job %s", op.name)
