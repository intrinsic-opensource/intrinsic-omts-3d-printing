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

"""Stateless read-only skills for fresh PrusaLink readiness observations."""

import logging
import math
import time
from contextlib import contextmanager

import grpc
from google.protobuf import empty_pb2
from intrinsic.skills.proto import footprint_pb2
from intrinsic.skills.python import skill_interface

from services.prusalink import prusalink_pb2 as service_pb
from services.prusalink import prusalink_pb2_grpc as service_rpc
from skills.printer import read_printer_status_pb2 as pb

CAPABILITY = "omts.prusalink.PrusaLinkService"
INVALID_INPUT = 1001
SERVICE_FAILURE = 1002
PRINT_FAILED = 1003
INVALID_OBSERVATION = 1004


def _positive(value: float, name: str, maximum: float) -> float:
  if not math.isfinite(value) or not 0 < value <= maximum:
    raise skill_interface.SkillError(
      INVALID_INPUT, f"{name} must be finite and in (0, {maximum}]"
    )
  return value


def _check_job(job_id: int | None, required: bool = False) -> None:
  if (required and job_id is None) or (job_id is not None and job_id < 0):
    raise skill_interface.SkillError(
      INVALID_INPUT, "A nonnegative expected_job_id is required"
    )


def readiness(
  status: service_pb.PrinterStatus, expected_job_id: int | None
) -> pb.PrinterReadiness:
  if (
    status.state not in service_pb.PrinterState.values()[1:]
    or not status.HasField("observed_at")
    or not 0
    <= time.time()
    - (status.observed_at.seconds + status.observed_at.nanos / 1e9)
    <= 10
    or (
      status.HasField("bed_temperature_c")
      and not math.isfinite(status.bed_temperature_c)
    )
  ):
    raise skill_interface.SkillError(
      INVALID_OBSERVATION, "Invalid or stale PrusaLink observation"
    )
  if not status.HasField("job_id"):
    decision = pb.PrinterReadiness.JOB_UNKNOWN
  elif expected_job_id is not None and status.job_id != expected_job_id:
    decision = pb.PrinterReadiness.JOB_MISMATCH
  elif status.state in (
    service_pb.ERROR,
    service_pb.STOPPED,
    service_pb.ATTENTION,
  ):
    decision = pb.PrinterReadiness.PRINTER_BLOCKED
  elif status.state != service_pb.FINISHED:
    decision = pb.PrinterReadiness.WAITING_FOR_PRINT
  elif not status.HasField("bed_temperature_c"):
    decision = pb.PrinterReadiness.TEMPERATURE_UNAVAILABLE
  elif status.bed_temperature_c >= 30:
    decision = pb.PrinterReadiness.WAITING_FOR_COOLING
  elif not status.print_finished or not status.ready_for_unload:
    raise skill_interface.SkillError(
      INVALID_OBSERVATION, "Inconsistent PrusaLink readiness observation"
    )
  else:
    decision = pb.PrinterReadiness.READY_TO_UNLOAD
  return pb.PrinterReadiness(
    printer_status=status,
    decision=decision,
    outcome=pb.PrinterReadiness.SNAPSHOT,
    ready_for_unload=decision == pb.PrinterReadiness.READY_TO_UNLOAD,
  )


def _cancel(context: skill_interface.ExecuteContext) -> None:
  if context.canceller.cancelled:
    raise skill_interface.SkillCancelledError()


@contextmanager
def _connection(context: skill_interface.ExecuteContext):
  handle = context.resource_handles.get("printer")
  if handle is None or not handle.connection_info.HasField("grpc"):
    raise skill_interface.SkillError(
      INVALID_INPUT, "Missing printer gRPC equipment"
    )
  connection = handle.connection_info.grpc
  if not connection.address or bool(connection.header) != bool(
    connection.server_instance
  ):
    raise skill_interface.SkillError(
      INVALID_INPUT, "Invalid printer connection metadata"
    )
  metadata = (
    ((connection.header, connection.server_instance),)
    if connection.header
    else ()
  )
  with grpc.insecure_channel(connection.address) as channel:
    yield service_rpc.PrusaLinkServiceStub(channel), metadata


def _observe(stub, metadata, timeout, context, expected_job_id):
  _cancel(context)
  try:
    status = stub.GetStatus(
      empty_pb2.Empty(), metadata=metadata, timeout=timeout
    )
  except grpc.RpcError as exc:
    _cancel(context)
    logging.error("PrusaLink GetStatus failed: %s", exc.code())
    raise skill_interface.SkillError(
      SERVICE_FAILURE, f"PrusaLink GetStatus failed: {exc.code().name}"
    ) from exc
  _cancel(context)
  return readiness(status, expected_job_id)


class _PrinterSkill(skill_interface.Skill):
  @classmethod
  def required_equipment(cls) -> dict[str, str]:
    return {"printer": CAPABILITY}

  def get_footprint(self, request, context) -> footprint_pb2.Footprint:
    # The runtime adds the manifest's READ lease using the bound resource name.
    return footprint_pb2.Footprint(lock_the_universe=False)

  def preview(self, request, context):
    raise NotImplementedError(
      "Printer skills need live telemetry; preview cannot assert readiness"
    )


class ReadPrinterStatus(_PrinterSkill):
  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.ReadPrinterStatusParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.PrinterReadiness:
    params = request.params
    expected = (
      params.expected_job_id if params.HasField("expected_job_id") else None
    )
    _check_job(expected)
    timeout = _positive(
      params.rpc_timeout_seconds
      if params.HasField("rpc_timeout_seconds")
      else 5,
      "rpc_timeout_seconds",
      10,
    )
    context.canceller.ready()
    with _connection(context) as (stub, metadata):
      return _observe(stub, metadata, timeout, context, expected)


class WaitForPrinterReady(_PrinterSkill):
  def execute(
    self,
    request: skill_interface.ExecuteRequest[pb.WaitForPrinterReadyParams],
    context: skill_interface.ExecuteContext,
  ) -> pb.PrinterReadiness:
    params = request.params
    expected = (
      params.expected_job_id if params.HasField("expected_job_id") else None
    )
    _check_job(expected, required=True)
    timeout = _positive(
      params.timeout_seconds if params.HasField("timeout_seconds") else 120,
      "timeout_seconds",
      3600,
    )
    poll = _positive(
      params.poll_interval_seconds
      if params.HasField("poll_interval_seconds")
      else 1,
      "poll_interval_seconds",
      60,
    )
    rpc_timeout = _positive(
      params.rpc_timeout_seconds
      if params.HasField("rpc_timeout_seconds")
      else 5,
      "rpc_timeout_seconds",
      10,
    )
    context.canceller.ready()
    deadline = time.monotonic() + timeout
    previous_decision = None
    result = None
    with _connection(context) as (stub, metadata):
      while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
          if result is None:
            raise skill_interface.SkillError(
              SERVICE_FAILURE, "No observation before deadline"
            )
          result.outcome = pb.PrinterReadiness.TIMED_OUT
          return result
        result = _observe(
          stub, metadata, min(rpc_timeout, remaining), context, expected
        )
        if result.decision != previous_decision:
          logging.info(
            "Printer job %s: %s",
            expected,
            pb.PrinterReadiness.Decision.Name(result.decision),
          )
          previous_decision = result.decision
        if result.decision in (
          pb.PrinterReadiness.JOB_MISMATCH,
          pb.PrinterReadiness.JOB_UNKNOWN,
          pb.PrinterReadiness.PRINTER_BLOCKED,
        ):
          raise skill_interface.SkillError(
            PRINT_FAILED,
            f"Cannot wait for job {expected}: {pb.PrinterReadiness.Decision.Name(result.decision)}",
          )
        if result.ready_for_unload:
          result.outcome = pb.PrinterReadiness.READY
          return result
        remaining = deadline - time.monotonic()
        if remaining <= 0 or poll >= remaining:
          if remaining > 0 and context.canceller.wait(remaining):
            raise skill_interface.SkillCancelledError()
          result.outcome = pb.PrinterReadiness.TIMED_OUT
          return result
        if context.canceller.wait(poll):
          raise skill_interface.SkillCancelledError()
