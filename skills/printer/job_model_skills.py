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

"""Read-only skills: has the printer service built the model of a print job?

The service pulls each new job's G-code from the printer and converts it to an
STL. These skills only look at that state, so a behavior tree can start the
next process once `MODEL_READY`. They never move a robot.
"""

import logging
import time

import grpc
from intrinsic.skills.python import skill_interface

from services.prusalink import prusalink_pb2 as service_pb
from skills.printer import job_model_pb2 as pb
from skills.printer import printer_skills as common

MODEL_FAILED_CODE = 1003
INVALID_OBSERVATION = common.INVALID_OBSERVATION
_DECISIONS = {
  service_pb.NO_JOB: pb.JobModelReadiness.NO_JOB,
  service_pb.DOWNLOADING: pb.JobModelReadiness.DOWNLOADING,
  service_pb.CONVERTING: pb.JobModelReadiness.CONVERTING,
  service_pb.MODEL_READY: pb.JobModelReadiness.MODEL_READY,
  service_pb.MODEL_FAILED: pb.JobModelReadiness.MODEL_FAILED,
}


def readiness(
  model: service_pb.ModelStatus, after_job_id: int | None = None
) -> pb.JobModelReadiness:
  if (
    model.state not in _DECISIONS
    or not model.HasField("observed_at")
    or not 0
    <= time.time() - (model.observed_at.seconds + model.observed_at.nanos / 1e9)
    <= 10
  ):
    raise skill_interface.SkillError(
      INVALID_OBSERVATION, "Invalid or stale job model observation"
    )
  decision = _DECISIONS[model.state]
  if model.HasField("job_id") and (
    after_job_id is not None and model.job_id <= after_job_id
  ):
    decision = pb.JobModelReadiness.NO_JOB  # Not newer than what was asked.
  return pb.JobModelReadiness(
    model=model,
    decision=decision,
    outcome=pb.JobModelReadiness.SNAPSHOT,
    model_ready=decision == pb.JobModelReadiness.MODEL_READY,
  )


def _observe(stub, metadata, timeout, context, expected, after):
  common.cancel(context)
  request = service_pb.ModelRequest()
  if expected is not None:
    request.job_id = expected
  try:
    model = stub.GetModelStatus(request, metadata=metadata, timeout=timeout)
  except grpc.RpcError as exc:
    common.cancel(context)
    if expected is not None and exc.code() == grpc.StatusCode.NOT_FOUND:
      # The service has not seen that job yet.
      model = service_pb.ModelStatus(state=service_pb.NO_JOB)
      model.observed_at.GetCurrentTime()
    else:
      logging.error("PrusaLink GetModelStatus failed: %s", exc.code())
      raise skill_interface.SkillError(
        common.SERVICE_FAILURE,
        f"PrusaLink GetModelStatus failed: {exc.code().name}",
      ) from exc
  common.cancel(context)
  return readiness(model, after)


def _optional(params, field):
  return getattr(params, field) if params.HasField(field) else None


def _or(value, default):
  """The default only when the parameter is absent (0 is invalid, not unset)."""
  return default if value is None else value


class _ModelSkill(common.PrinterSkill):
  def preview(self, request, context):
    raise NotImplementedError(
      "Job model skills need the live service; preview cannot assert it"
    )


class ReadJobModel(_ModelSkill):
  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.ReadJobModelParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.JobModelReadiness:
    params = request.params
    expected = _optional(params, "expected_job_id")
    common.check_job(expected)
    timeout = common.positive(
      _or(_optional(params, "rpc_timeout_seconds"), 5), "rpc_timeout_seconds", 10
    )
    context.canceller.ready()
    with common.connection(context) as (stub, metadata):
      return _observe(stub, metadata, timeout, context, expected, None)


class WaitForJobModel(_ModelSkill):
  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.WaitForJobModelParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.JobModelReadiness:
    params = request.params
    expected = _optional(params, "expected_job_id")
    after = _optional(params, "after_job_id")
    common.check_job(expected)
    common.check_job(after)
    timeout = common.positive(
      _or(_optional(params, "timeout_seconds"), 120), "timeout_seconds", 3600
    )
    poll = common.positive(
      _or(_optional(params, "poll_interval_seconds"), 1),
      "poll_interval_seconds",
      60,
    )
    rpc_timeout = common.positive(
      _or(_optional(params, "rpc_timeout_seconds"), 5), "rpc_timeout_seconds", 10
    )
    context.canceller.ready()
    deadline = time.monotonic() + timeout
    previous = None
    result = None
    with common.connection(context) as (stub, metadata):
      while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
          if result is None:
            raise skill_interface.SkillError(
              common.SERVICE_FAILURE, "No observation before deadline"
            )
          result.outcome = pb.JobModelReadiness.TIMED_OUT
          return result
        result = _observe(
          stub,
          metadata,
          min(rpc_timeout, remaining),
          context,
          expected,
          after,
        )
        if result.decision != previous:
          logging.info(
            "Job model: %s", pb.JobModelReadiness.Decision.Name(result.decision)
          )
          previous = result.decision
        if result.decision == pb.JobModelReadiness.MODEL_FAILED:
          raise skill_interface.SkillError(
            MODEL_FAILED_CODE, f"Job model failed: {result.model.error}"
          )
        if result.model_ready:
          result.outcome = pb.JobModelReadiness.READY
          return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
          result.outcome = pb.JobModelReadiness.TIMED_OUT
          return result
        if context.canceller.wait(min(poll, remaining)):
          raise skill_interface.SkillCancelledError()
