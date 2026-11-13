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

"""Job model skills against a real service, watcher and mock printer."""

import tempfile
import threading
import time
from concurrent import futures
from pathlib import Path

from absl.testing import absltest
from intrinsic.resources.proto import resource_handle_pb2
from intrinsic.skills.python import skill_canceller, skill_interface
from intrinsic.skills.testing import skill_test_utils as stu

from services.prusalink import client, jobwatch, server
from skills.printer import job_model_pb2 as pb
from skills.printer import job_model_skills as skills
from tools.mock_printer import mock_printer as mock

_BGCODE = (
  Path(__file__).parent / "testdata/prusaslicer_2_9_7_part.bgcode"
).read_bytes()
Decision = pb.JobModelReadiness


class JobModelSkillsTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.httpd, self.sim = mock.make_mock_server(
      0, "127.0.0.1", initial_state="IDLE", initial_job_id=None, first_job_id=1
    )
    thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(self.httpd.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(self.httpd.shutdown)
    self.printer = client.PrusaLinkClient(
      f"http://127.0.0.1:{self.httpd.server_port}",
      mock.MOCK_USERNAME,
      mock.MOCK_PASSWORD,
      2.0,
    )
    self.gate = threading.Event()
    self.gate.set()
    storage = tempfile.mkdtemp()
    self.addCleanup(lambda: __import__("shutil").rmtree(storage, True))

    def gated_convert(*args, **kwargs):
      self.assertTrue(self.gate.wait(20))
      return jobwatch.gcode_to_stl.convert(*args, **kwargs)

    self.watcher = jobwatch.JobWatcher(
      self.printer, storage, convert=gated_convert
    )
    self.grpcd, port = server.make_grpc_server(
      self.printer, False, "127.0.0.1", 0, self.watcher
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
              address=f"127.0.0.1:{port}"
            )
          ),
        )
      },
    )

  def send(self, name="warrior.bgcode", data=_BGCODE):
    self.sim.update({"state": "IDLE"})
    self.sim.start_job(name, data)
    self.watcher.poll_once()

  def read(self, **kwargs):
    return skills.ReadJobModel().execute(
      stu.make_test_execute_request(pb.ReadJobModelParams(**kwargs)),
      self.context,
    )

  def wait(self, **kwargs):
    defaults = {"timeout_seconds": 0.3, "poll_interval_seconds": 0.01}
    defaults.update(kwargs)
    return skills.WaitForJobModel().execute(
      stu.make_test_execute_request(pb.WaitForJobModelParams(**defaults)),
      self.context,
    )

  def test_no_job_then_ready(self):
    result = self.read()
    self.assertEqual(result.decision, Decision.NO_JOB)
    self.assertFalse(result.model_ready)
    self.send()
    result = self.read()
    self.assertEqual(result.decision, Decision.MODEL_READY)
    self.assertTrue(result.model_ready)
    self.assertEqual(result.outcome, pb.JobModelReadiness.SNAPSHOT)
    self.assertEqual(result.model.job_id, 1)
    self.assertTrue(result.model.stl_path.endswith("compound.stl"))

  def test_converting_is_visible_and_is_not_ready(self):
    self.gate.clear()
    self.send_thread = threading.Thread(target=self.send)
    self.send_thread.start()
    self.addCleanup(self.send_thread.join)
    self.addCleanup(self.gate.set)
    deadline = time.monotonic() + 10
    while self.read().decision != Decision.CONVERTING:
      self.assertLess(time.monotonic(), deadline)
      time.sleep(0.02)
    self.assertFalse(self.read().model_ready)
    self.gate.set()
    self.send_thread.join()
    self.assertEqual(self.read().decision, Decision.MODEL_READY)

  def test_expected_job_is_that_jobs_model_even_after_a_newer_one(self):
    self.send()
    self.send("second.bgcode")
    self.assertEqual(self.read().model.job_id, 2)
    first = self.read(expected_job_id=1)
    self.assertEqual((first.decision, first.model.job_id), (Decision.MODEL_READY, 1))
    self.assertEqual(self.read(expected_job_id=9).decision, Decision.NO_JOB)

  def test_failed_conversion_is_reported_and_fails_the_wait(self):
    self.send("notes.gcode", b"not gcode\n")
    result = self.read()
    self.assertEqual(result.decision, Decision.MODEL_FAILED)
    self.assertIn("G-code", result.model.error)
    self.assertFalse(result.model_ready)
    with self.assertRaises(skill_interface.SkillError):
      self.wait()

  def test_wait_returns_when_the_model_is_built(self):
    with futures.ThreadPoolExecutor(max_workers=1) as pool:
      result = pool.submit(self.wait, timeout_seconds=15)
      time.sleep(0.1)
      self.assertFalse(result.done())
      self.send()
      observed = result.result(timeout=15)
    self.assertEqual(observed.outcome, pb.JobModelReadiness.READY)
    self.assertTrue(observed.model_ready)

  def test_wait_for_a_newer_job_ignores_the_old_model(self):
    self.send()
    result = self.wait(after_job_id=1, timeout_seconds=0.15)
    self.assertEqual(result.outcome, pb.JobModelReadiness.TIMED_OUT)
    self.assertEqual(result.decision, Decision.NO_JOB)
    self.send("second.bgcode")
    result = self.wait(after_job_id=1)
    self.assertEqual(
      (result.outcome, result.model.job_id),
      (pb.JobModelReadiness.READY, 2),
    )

  def test_wait_timeout_is_explicit_not_ready(self):
    result = self.wait(timeout_seconds=0.1)
    self.assertEqual(result.outcome, pb.JobModelReadiness.TIMED_OUT)
    self.assertFalse(result.model_ready)

  def test_wait_is_cancellable(self):
    with futures.ThreadPoolExecutor(max_workers=1) as pool:
      result = pool.submit(self.wait, timeout_seconds=30)
      self.canceller.wait_for_ready()
      self.canceller.cancel()
      with self.assertRaises(skill_interface.SkillCancelledError):
        result.result(timeout=5)

  def test_invalid_parameters(self):
    with self.assertRaises(skill_interface.SkillError):
      self.read(expected_job_id=-1)
    with self.assertRaises(skill_interface.SkillError):
      self.wait(timeout_seconds=0)


if __name__ == "__main__":
  absltest.main()
