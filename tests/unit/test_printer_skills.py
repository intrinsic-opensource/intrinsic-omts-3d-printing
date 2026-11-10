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

"""Skill behavior against real local mock HTTP and PrusaLink gRPC listeners."""

import threading
import time
from concurrent import futures

from absl.testing import absltest, parameterized
from intrinsic.resources.proto import resource_handle_pb2
from intrinsic.skills.python import skill_canceller, skill_interface
from intrinsic.skills.testing import skill_test_utils as stu

from services.prusalink import client, mock, server
from services.prusalink import prusalink_pb2 as service_pb
from skills.printer import printer_skills as skills
from skills.printer import read_printer_status_pb2 as pb


class PrinterSkillsTest(parameterized.TestCase):
  def setUp(self):
    super().setUp()
    self.httpd, self.printer = mock.make_mock_server()
    thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(self.httpd.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(self.httpd.shutdown)
    self.grpcd, port = server.make_grpc_server(
      client.PrusaLinkClient(
        f"http://127.0.0.1:{self.httpd.server_port}",
        mock.MOCK_USERNAME,
        mock.MOCK_PASSWORD,
      ),
      True,
      "127.0.0.1",
      0,
    )
    self.grpcd.start()
    self.addCleanup(lambda: self.grpcd.stop(0).wait())
    self.canceller = skill_canceller.SkillCancellationManager(ready_timeout=2)
    self.context = stu.make_test_execute_context(
      canceller=self.canceller,
      resource_handles={
        "printer": resource_handle_pb2.ResourceHandle(
          name="prusalink",
          connection_info=resource_handle_pb2.ResourceConnectionInfo(
            grpc=resource_handle_pb2.ResourceGrpcConnectionInfo(
              address=f"127.0.0.1:{port}",
            )
          ),
        )
      },
    )

  def read(self, **kwargs):
    return skills.ReadPrinterStatus().execute(
      stu.make_test_execute_request(pb.ReadPrinterStatusParams(**kwargs)),
      self.context,
    )

  def wait(self, **kwargs):
    defaults = {
      "expected_job_id": 42,
      "timeout_seconds": 0.3,
      "poll_interval_seconds": 0.01,
    }
    defaults.update(kwargs)
    return skills.WaitForPrinterReady().execute(
      stu.make_test_execute_request(pb.WaitForPrinterReadyParams(**defaults)),
      self.context,
    )

  @parameterized.parameters(
    ("PRINTING", 60, pb.PrinterReadiness.WAITING_FOR_PRINT),
    ("PAUSED", 25, pb.PrinterReadiness.WAITING_FOR_PRINT),
    ("FINISHED", 30, pb.PrinterReadiness.WAITING_FOR_COOLING),
    ("FINISHED", 30.001, pb.PrinterReadiness.WAITING_FOR_COOLING),
    ("FINISHED", 29.999, pb.PrinterReadiness.READY_TO_UNLOAD),
    ("FINISHED", None, pb.PrinterReadiness.TEMPERATURE_UNAVAILABLE),
    ("STOPPED", 25, pb.PrinterReadiness.PRINTER_BLOCKED),
    ("ERROR", 25, pb.PrinterReadiness.PRINTER_BLOCKED),
    ("ATTENTION", 25, pb.PrinterReadiness.PRINTER_BLOCKED),
  )
  def test_snapshot_outputs(self, state, temperature, decision):
    self.printer.update({"state": state, "temp_bed": temperature})
    result = self.read(expected_job_id=42)
    self.assertEqual(result.decision, decision)
    self.assertEqual(result.outcome, pb.PrinterReadiness.SNAPSHOT)
    self.assertEqual(
      result.ready_for_unload, decision == pb.PrinterReadiness.READY_TO_UNLOAD
    )

  def test_no_latched_readiness_across_calls(self):
    self.printer.update({"state": "FINISHED", "temp_bed": 29})
    self.assertTrue(self.read().ready_for_unload)
    self.printer.update({"state": "PRINTING", "temp_bed": 60})
    self.assertFalse(self.read().ready_for_unload)

  def test_missing_and_changed_job_cannot_pass(self):
    self.printer.update({"state": "FINISHED", "temp_bed": 29, "job_id": None})
    self.assertEqual(self.read().decision, pb.PrinterReadiness.JOB_UNKNOWN)
    with self.assertRaises(skill_interface.SkillError):
      self.wait()
    self.printer.update({"job_id": 43})
    self.assertEqual(
      self.read(expected_job_id=42).decision, pb.PrinterReadiness.JOB_MISMATCH
    )
    with self.assertRaises(skill_interface.SkillError):
      self.wait()

  def test_wait_completes_only_after_finish_and_cool(self):
    with futures.ThreadPoolExecutor(max_workers=1) as pool:
      result = pool.submit(self.wait, timeout_seconds=2)
      time.sleep(0.08)
      self.assertFalse(result.done())
      self.printer.update({"state": "FINISHED", "temp_bed": 30})
      time.sleep(0.08)
      self.assertFalse(result.done())
      self.printer.update({"temp_bed": 29})
      observed = result.result(timeout=2)
    self.assertEqual(observed.outcome, pb.PrinterReadiness.READY)
    self.assertTrue(observed.ready_for_unload)

  def test_wait_timeout_is_explicit_not_ready(self):
    result = self.wait(timeout_seconds=0.1)
    self.assertEqual(result.outcome, pb.PrinterReadiness.TIMED_OUT)
    self.assertFalse(result.ready_for_unload)

  def test_wait_is_cancellable(self):
    with futures.ThreadPoolExecutor(max_workers=1) as pool:
      result = pool.submit(self.wait, timeout_seconds=2)
      self.canceller.wait_for_ready()
      self.canceller.cancel()
      with self.assertRaises(skill_interface.SkillCancelledError):
        result.result(timeout=1)

  @parameterized.parameters("STOPPED", "ERROR", "ATTENTION")
  def test_wait_fails_on_printer_fault(self, state):
    self.printer.update({"state": state})
    with self.assertRaises(skill_interface.SkillError):
      self.wait()

  def test_upstream_fault_is_skill_error_not_old_result(self):
    self.printer.update({"state": "FINISHED", "temp_bed": 29})
    self.assertTrue(self.read().ready_for_unload)
    self.printer.update({"failure": 500})
    with self.assertRaises(skill_interface.SkillError):
      self.read()
    with self.assertRaises(skill_interface.SkillError):
      self.wait()

  @parameterized.parameters(
    ({"timeout_seconds": 0},),
    ({"timeout_seconds": float("nan")},),
    ({"poll_interval_seconds": 0},),
    ({"rpc_timeout_seconds": -1},),
    ({"expected_job_id": -1},),
  )
  def test_invalid_wait_parameters(self, params):
    with self.assertRaises(skill_interface.SkillError):
      self.wait(**params)

  def test_wait_requires_job_id(self):
    with self.assertRaises(skill_interface.SkillError):
      skills.WaitForPrinterReady().execute(
        stu.make_test_execute_request(pb.WaitForPrinterReadyParams()),
        self.context,
      )

  def test_equipment_required(self):
    context = stu.make_test_execute_context()
    with self.assertRaises(skill_interface.SkillError):
      skills.ReadPrinterStatus().execute(
        stu.make_test_execute_request(pb.ReadPrinterStatusParams()), context
      )

  def test_read_only_footprint_and_preview(self):
    for skill in (skills.ReadPrinterStatus(), skills.WaitForPrinterReady()):
      footprint = skill.get_footprint(None, None)
      self.assertFalse(footprint.lock_the_universe)
      self.assertEmpty(footprint.resource_reservation)
      self.assertEqual(
        skill.required_equipment(), {"printer": skills.CAPABILITY}
      )
      with self.assertRaises(NotImplementedError):
        skill.preview(None, None)

  @parameterized.parameters(-60, 60)
  def test_stale_and_future_observation_rejected(self, offset):
    status = service_pb.PrinterStatus(state=service_pb.FINISHED)
    status.observed_at.FromSeconds(int(time.time()) + offset)
    with self.assertRaises(skill_interface.SkillError):
      skills.readiness(status, 42)

  @parameterized.parameters(
    {"state": service_pb.PRINTER_STATE_UNSPECIFIED},
    {"state": 999},
    {"bed_temperature_c": float("nan")},
    {"bed_temperature_c": float("inf")},
    {"ready_for_unload": False},
    {"print_finished": False},
  )
  def test_invalid_or_inconsistent_observation_rejected(self, **changes):
    status = service_pb.PrinterStatus(
      state=service_pb.FINISHED,
      job_id=42,
      bed_temperature_c=29,
      ready_for_unload=True,
      print_finished=True,
    )
    status.observed_at.GetCurrentTime()
    for field, value in changes.items():
      setattr(status, field, value)
    with self.assertRaises(skill_interface.SkillError):
      skills.readiness(status, 42)

  @parameterized.parameters(
    ({"rpc_timeout_seconds": 0},),
    ({"rpc_timeout_seconds": 11},),
    ({"rpc_timeout_seconds": float("inf")},),
    ({"expected_job_id": -1},),
  )
  def test_invalid_read_parameters(self, params):
    with self.assertRaises(skill_interface.SkillError):
      self.read(**params)

  def test_missing_temperature_never_completes_wait(self):
    self.printer.update({"state": "FINISHED", "temp_bed": None})
    result = self.wait(timeout_seconds=0.1)
    self.assertEqual(result.outcome, pb.PrinterReadiness.TIMED_OUT)
    self.assertEqual(
      result.decision, pb.PrinterReadiness.TEMPERATURE_UNAVAILABLE
    )
    self.assertFalse(result.ready_for_unload)


if __name__ == "__main__":
  absltest.main()
