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

"""The training job that registers a pose estimator for a scene object.

The job intrinsic-core's `register_using_ioc_train_service` builds, with the
settings of the reBot cell. Imports no skill runtime, so tools can use it too.
"""

from intrinsic.assets.proto import id_pb2
from intrinsic.perception.proto.v1 import (
  pose_estimation_config_pb2,
  pose_range_pb2,
  target_pb2,
  train_service_pb2,
)
from intrinsic_perception.intrinsic.perception.service.ioc_train_service.proto import (
  ioc_pose_estimator_params_pb2,
)

# The estimator version intrinsic-core's registration tool gives.
ESTIMATOR_VERSION = "0.0.1"


def training_request(
  scene_object,
  part_name: str,
  pose_estimator: id_pb2.Id,
  confidence_threshold: float,
  refinement_iters: int = 5,
  visibility_threshold: float = 0.15,
  text_prompt: str = "object on a table",
  min_distance: float = 0.5,
  max_distance: float = 1.5,
) -> train_service_pb2.CreateTrainingJobRequest:
  config = pose_estimation_config_pb2.PoseEstimationConfig()
  config.targets.append(
    target_pb2.Target(
      id=part_name,
      scene_object=scene_object,
      pose_range=pose_range_pb2.PoseRange(
        min_distance=min_distance, max_distance=max_distance
      ),
    )
  )
  config.inference_params.Pack(
    ioc_pose_estimator_params_pb2.IocPoseEstimatorParams(
      refinement_iters=refinement_iters,
      confidence_threshold=confidence_threshold,
      visibility_threshold=visibility_threshold,
      text_prompt=text_prompt,
    )
  )
  return train_service_pb2.CreateTrainingJobRequest(
    pose_estimation_config=config,
    pose_estimator_type=train_service_pb2.POSE_ESTIMATOR_TYPE_UNSPECIFIED,
    asset_metadata=train_service_pb2.AssetMetadata(
      asset_name=pose_estimator.name,
      id_version=id_pb2.IdVersion(id=pose_estimator, version=ESTIMATOR_VERSION),
    ),
  )
