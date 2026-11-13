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

"""The service reads each new job's G-code from the printer and builds an STL."""

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock as unittest_mock

import grpc
from absl.testing import absltest
from google.protobuf import empty_pb2

from services.prusalink import client, jobwatch, server
from services.prusalink import prusalink_pb2 as pb
from services.prusalink import prusalink_pb2_grpc as rpc
from tools.mock_printer import mock_printer as mock

_DATA = Path(__file__).parent / "testdata"
_BGCODE = (_DATA / "prusaslicer_2_9_7_part.bgcode").read_bytes()
_GCODE = (_DATA / "prusaslicer_2_9_7_part.gcode").read_bytes()


class _Base(absltest.TestCase):
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
    self.storage = Path(tempfile.mkdtemp())
    self.addCleanup(lambda: __import__("shutil").rmtree(self.storage, True))
    self.watcher = self.new_watcher()

  def new_watcher(self):
    return jobwatch.JobWatcher(self.printer, self.storage, interval=0.05)

  def send(self, name, data, finish=True):
    """A new job on the printer; the previous one is finished first."""
    if finish:
      self.sim.update({"state": "IDLE"})
    self.sim.start_job(name, data)

  def downloads(self):
    # Each download is a 401 challenge and then the file: count the files.
    return sum(
      1
      for _, text in self.sim.events
      if text.startswith("GET /api/files") and text.endswith("-> 200")
    )


class WatcherTest(_Base):
  def test_nothing_to_do_without_a_job(self):
    self.watcher.poll_once()
    self.assertEqual(self.watcher.status().state, pb.NO_JOB)
    self.assertEqual(len(self.watcher.list().models), 0)

  def test_a_new_job_becomes_a_model(self):
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    model = self.watcher.status()
    self.assertEqual(model.state, pb.MODEL_READY)
    self.assertEqual((model.job_id, model.file_name), (1, "warrior.bgcode"))
    self.assertGreater(model.layers, 100)
    self.assertEqual(len(model.sha256), 64)
    self.assertEqual(model.http_path, "/v1/jobs/1/model.stl")
    stl = Path(model.stl_path)
    self.assertEqual(stl.name, "compound.stl")
    self.assertTrue(stl.is_file() and stl.stat().st_size > 1000)
    self.assertTrue((stl.parent / "by_type").is_dir())
    self.assertEqual(
      json.loads((stl.parent / "job.json").read_text())["job_id"], 1
    )
    self.assertEqual((stl.parent / "job.bgcode").read_bytes(), _BGCODE)

  def test_the_same_job_is_read_only_once(self):
    self.send("warrior.bgcode", _BGCODE)
    for _ in range(4):
      self.watcher.poll_once()
    self.assertEqual(len(self.watcher.list().models), 1)
    self.assertEqual(self.downloads(), 1)

  def test_the_same_model_sent_again_is_a_new_job_with_a_reused_model(self):
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    first = self.watcher.status()
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    second = self.watcher.status()
    self.assertEqual((first.job_id, second.job_id), (1, 2))
    self.assertEqual(second.state, pb.MODEL_READY)
    self.assertTrue(second.reused and not first.reused)
    self.assertEqual(first.sha256, second.sha256)
    self.assertNotEqual(first.stl_path, second.stl_path)
    self.assertEqual(
      Path(first.stl_path).read_bytes(), Path(second.stl_path).read_bytes()
    )
    self.assertEqual(self.downloads(), 2)  # read again, converted once
    self.assertEqual(len(self.watcher.list().models), 2)

  def test_a_job_id_reused_after_a_printer_restart_is_read_again(self):
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    # The printer restarted: ids start over, and the file has a new time.
    self.sim.job_id = None
    self.sim.first_job_id = 1
    self.send("warrior.bgcode", _BGCODE)
    key = "local/warrior.bgcode"
    self.sim.files[key] = (_BGCODE, self.sim.files[key][1] + 100)
    self.watcher.poll_once()
    models = self.watcher.list().models
    self.assertEqual([m.job_id for m in models], [1, 1])
    self.assertEqual(self.watcher.status().state, pb.MODEL_READY)
    self.assertTrue(self.watcher.status().reused)
    self.assertNotEqual(models[0].stl_path, models[1].stl_path)

  def test_different_content_is_converted_again(self):
    self.send("a.bgcode", _BGCODE)
    self.watcher.poll_once()
    self.send("b.gcode", _GCODE)
    self.watcher.poll_once()
    model = self.watcher.status()
    self.assertEqual((model.state, model.reused), (pb.MODEL_READY, False))

  def test_not_gcode_fails_with_a_reason(self):
    self.send("notes.gcode", b"hello, this is not G-code at all\n")
    self.watcher.poll_once()
    model = self.watcher.status()
    self.assertEqual(model.state, pb.MODEL_FAILED)
    self.assertIn("G-code", model.error)
    self.assertEqual(model.stl_path, "")
    self.watcher.poll_once()  # a permanent failure is not retried
    self.assertEqual(self.downloads(), 1)

  def test_binary_garbage_fails_cleanly(self):
    self.send("junk.bgcode", b"GCDE" + bytes(range(256)) * 4)
    self.watcher.poll_once()
    self.assertEqual(self.watcher.status().state, pb.MODEL_FAILED)

  def test_too_large_fails(self):
    watcher = jobwatch.JobWatcher(
      self.printer, self.storage, max_bytes=1000
    )
    self.send("warrior.bgcode", _BGCODE)
    watcher.poll_once()
    model = watcher.status()
    self.assertEqual(model.state, pb.MODEL_FAILED)
    self.assertIn("file_too_large", model.error)

  def test_a_dropped_connection_is_retried(self):
    self.send("warrior.bgcode", _BGCODE)
    real = self.printer.download
    calls = []

    def flaky(*args, **kwargs):
      calls.append(1)
      if len(calls) == 1:
        raise client.ServiceError(502, "upstream_unavailable", "gone")
      return real(*args, **kwargs)

    with unittest_mock.patch.object(self.printer, "download", flaky):
      self.watcher.poll_once()
      self.assertEqual(self.watcher.status().state, pb.MODEL_FAILED)
      self.watcher.poll_once()
    self.assertEqual(self.watcher.status().state, pb.MODEL_READY)
    self.assertEqual(len(self.watcher.list().models), 1)

  def test_a_missing_printer_is_reported_not_raised(self):
    gone = client.PrusaLinkClient("http://127.0.0.1:1", "u", "p", 0.2)
    watcher = jobwatch.JobWatcher(gone, self.storage)
    watcher.poll_once()
    self.assertEqual(watcher.status().state, pb.NO_JOB)
    self.assertIn("upstream_unavailable", watcher.status().poll_error)

  def test_a_restart_does_not_read_old_jobs_again(self):
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    restarted = self.new_watcher()
    self.assertEqual(restarted.status().state, pb.MODEL_READY)
    with unittest_mock.patch.object(
      self.printer, "download", side_effect=AssertionError("read twice")
    ):
      restarted.poll_once()

  def test_background_thread_picks_up_a_job(self):
    self.watcher.start()
    self.addCleanup(self.watcher.stop)
    self.send("warrior.bgcode", _BGCODE)
    deadline = time.monotonic() + 20
    while self.watcher.status().state != pb.MODEL_READY:
      self.assertLess(time.monotonic(), deadline, self.watcher.status())
      time.sleep(0.05)


class ServiceInterfaceTest(_Base):
  def setUp(self):
    super().setUp()
    self.http = server.make_http_server(
      self.printer, False, "127.0.0.1", 0, "/p", self.watcher, {"route": "mock"}
    )
    thread = threading.Thread(target=self.http.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(self.http.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(self.http.shutdown)
    self.grpcd, port = server.make_grpc_server(
      self.printer, False, "127.0.0.1", 0, self.watcher
    )
    self.grpcd.start()
    self.addCleanup(lambda: self.grpcd.stop(0).wait())
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    self.addCleanup(channel.close)
    self.stub = rpc.PrusaLinkServiceStub(channel)
    self.url = f"http://127.0.0.1:{self.http.server_port}"

  def get(self, path):
    with urllib.request.urlopen(self.url + path, timeout=5) as response:
      return response.status, response.headers, response.read()

  def error(self, path):
    with self.assertRaises(urllib.error.HTTPError) as raised:
      self.get(path)
    raised.exception.close()
    return raised.exception.code

  def test_http_model_routes(self):
    self.assertEqual(json.loads(self.get("/v1/model")[2])["state"], "NO_JOB")
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    model = json.loads(self.get("/p/v1/model")[2])
    self.assertEqual(
      (model["state"], model["job_id"], model["http_path"]),
      ("MODEL_READY", "1", "/v1/jobs/1/model.stl"),
    )
    self.assertEqual(json.loads(self.get("/v1/jobs/1/model")[2])["job_id"], "1")
    self.assertEqual(len(json.loads(self.get("/v1/jobs")[2])["models"]), 1)
    status, headers, body = self.get("/v1/jobs/1/model.stl")
    self.assertEqual(headers["Content-Type"], "model/stl")
    self.assertEqual(body, Path(self.watcher.status().stl_path).read_bytes())
    self.assertEqual(self.get("/v1/jobs/1/by_type/perimeter.stl")[0], 200)
    self.assertEqual(self.get("/v1/jobs/1/part.stl")[0], 200)
    self.assertEqual(self.get("/v1/jobs/1/supports.stl")[0], 200)
    info = json.loads(self.get("/healthz")[2])
    self.assertEqual((info["route"], info["job_pull_enabled"]), ("mock", True))

  def test_http_errors(self):
    self.assertEqual(self.error("/v1/jobs/9/model"), 404)
    self.assertEqual(self.error("/v1/jobs/9/model.stl"), 404)
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    self.assertEqual(self.error("/v1/jobs/1/by_type/nope.stl"), 404)
    self.assertEqual(self.error("/v1/jobs/1/by_type/../job.json"), 404)
    self.assertEqual(self.error("/v1/jobs/1/job.bgcode"), 404)

  def test_http_without_a_watcher_is_a_conflict(self):
    http = server.make_http_server(self.printer, False, "127.0.0.1", 0)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(http.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(http.shutdown)
    self.url = f"http://127.0.0.1:{http.server_port}"
    self.assertEqual(self.error("/v1/model"), 409)
    self.assertFalse(
      json.loads(self.get("/healthz")[2])["job_pull_enabled"]
    )

  def test_grpc_model_status(self):
    self.assertEqual(
      self.stub.GetModelStatus(pb.ModelRequest()).state, pb.NO_JOB
    )
    self.send("warrior.bgcode", _BGCODE)
    self.watcher.poll_once()
    self.send("two.bgcode", _BGCODE)
    self.watcher.poll_once()
    latest = self.stub.GetModelStatus(pb.ModelRequest())
    self.assertEqual((latest.job_id, latest.state), (2, pb.MODEL_READY))
    first = self.stub.GetModelStatus(pb.ModelRequest(job_id=1))
    self.assertEqual(first.file_name, "warrior.bgcode")
    self.assertEqual(len(self.stub.ListModels(empty_pb2.Empty()).models), 2)
    with self.assertRaises(grpc.RpcError) as raised:
      self.stub.GetModelStatus(pb.ModelRequest(job_id=99))
    self.assertEqual(raised.exception.code(), grpc.StatusCode.NOT_FOUND)


if __name__ == "__main__":
  absltest.main()
