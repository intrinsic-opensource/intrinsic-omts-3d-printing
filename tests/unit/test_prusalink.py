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

"""PrusaLink contract, authenticated HTTP integration and gRPC parity tests."""

import http.server
import json
import math
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock as unittest_mock

import grpc
from absl.testing import absltest, parameterized
from google.protobuf import empty_pb2
from intrinsic.resources.proto import runtime_context_pb2

from services.prusalink import client, main, mock, server
from services.prusalink import prusalink_pb2 as pb
from services.prusalink import prusalink_pb2_grpc as rpc


class LifecycleTest(parameterized.TestCase):
  @parameterized.parameters(signal.SIGTERM, signal.SIGINT)
  def test_entrypoint_and_graceful_shutdown(self, stop_signal):
    binary = (
      Path(os.environ["TEST_SRCDIR"])
      / os.environ["TEST_WORKSPACE"]
      / "services/prusalink/prusalink_server"
    )
    with subprocess.Popen(
      [
        str(binary),
        "--mode=sim",
        "--http-port=0",
        "--grpc-port=0",
        "--mock-port=0",
      ],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.PIPE,
      text=True,
    ) as process:
      try:
        lines = queue.Queue()

        def read_logs():
          assert process.stderr is not None
          for line in process.stderr:
            lines.put(line)

        reader = threading.Thread(target=read_logs, daemon=True)
        reader.start()
        while True:
          line = lines.get(timeout=10)
          match = re.search(r"service HTTP 127.0.0.1:([0-9]+)", line)
          if match:
            break
          self.assertNotIn("startup failed", line)
        with urllib.request.urlopen(
          f"http://127.0.0.1:{match[1]}/healthz", timeout=2
        ) as response:
          self.assertEqual(json.load(response)["mode"], "sim")
        process.send_signal(stop_signal)
        self.assertEqual(process.wait(timeout=5), 0)
        reader.join(timeout=2)
        self.assertFalse(reader.is_alive())
      finally:
        if process.poll() is None:
          process.kill()
          process.wait(timeout=5)


class PrusaLinkTest(parameterized.TestCase):
  def setUp(self):
    super().setUp()
    self.mock_server, self.simulator = mock.make_mock_server()
    self.start_http(self.mock_server)
    self.printer = client.PrusaLinkClient(
      f"http://127.0.0.1:{self.mock_server.server_port}",
      mock.MOCK_USERNAME,
      mock.MOCK_PASSWORD,
      0.2,
    )
    self.httpd = server.make_http_server(
      self.printer,
      True,
      "127.0.0.1",
      0,
      "/ext/services/prusalink",
      self.simulator,
    )
    self.start_http(self.httpd)
    self.url = f"http://127.0.0.1:{self.httpd.server_port}"
    self.grpcd, port = server.make_grpc_server(
      self.printer, True, "127.0.0.1", 0
    )
    self.grpcd.start()
    self.addCleanup(lambda: self.grpcd.stop(0).wait())
    self.channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    self.addCleanup(self.channel.close)
    self.stub = rpc.PrusaLinkServiceStub(self.channel)

  def start_http(self, httpd):
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(httpd.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(httpd.shutdown)

  def request(self, path, data=None):
    request = urllib.request.Request(
      self.url + path,
      data=json.dumps(data).encode() if data is not None else None,
      headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
      return response.status, json.loads(
        response.read()
      ) if response.status != 204 else None

  @parameterized.parameters(
    ("FINISHED", 29.999, True),
    ("FINISHED", 30.0, False),
    ("FINISHED", 30.001, False),
    ("FINISHED", None, False),
    ("PRINTING", 25, False),
    ("PAUSED", 25, False),
    ("IDLE", 25, False),
    ("STOPPED", 25, False),
    ("ERROR", 25, False),
    ("ATTENTION", 25, False),
  )
  def test_unload_threshold_http_and_grpc(self, state, temperature, ready):
    self.request("/simulation/state", {"state": state, "temp_bed": temperature})
    _, http_result = self.request("/ext/services/prusalink/v1/status")
    result = self.stub.GetStatus(empty_pb2.Empty(), timeout=2)
    self.assertEqual(http_result["ready_for_unload"], ready)
    self.assertEqual(result.ready_for_unload, ready)
    self.assertEqual(result.print_finished, state == "FINISHED")
    self.assertEqual(
      result.HasField("bed_temperature_c"), temperature is not None
    )
    self.assertGreater(result.observed_at.seconds, 0)

  def test_digest_authentication_is_required(self):
    with self.assertRaises(urllib.error.HTTPError) as cm:
      urllib.request.urlopen(self.printer.url + "/api/v1/status", timeout=2)
    self.assertEqual(cm.exception.code, 401)
    cm.exception.close()
    wrong = client.PrusaLinkClient(self.printer.url, "maker", "wrong", 0.2)
    with self.assertRaises(client.ServiceError) as cm:
      wrong.get_status()
    self.assertEqual(cm.exception.code, "upstream_authentication")
    self.assertEqual(self.printer.get_status().state, pb.PRINTING)

  def test_pause_resume_continue_stop_and_conflict(self):
    for action, expected in (
      ("pause", pb.PAUSED),
      ("resume", pb.PRINTING),
      ("pause", pb.PAUSED),
      ("continue", pb.PRINTING),
      ("stop", pb.STOPPED),
    ):
      self.assertEqual(self.request(f"/v1/jobs/42/{action}", {})[0], 204)
      self.assertEqual(self.printer.get_status().state, expected)
    with self.assertRaises(urllib.error.HTTPError) as cm:
      self.request("/v1/jobs/42/resume", {})
    self.assertEqual(cm.exception.code, 409)
    cm.exception.close()
    with self.assertRaises(grpc.RpcError) as cm:
      self.stub.CommandJob(
        pb.JobCommand(job_id=42, action=pb.JobCommand.RESUME)
      )
    self.assertEqual(cm.exception.code(), grpc.StatusCode.FAILED_PRECONDITION)

  def test_grpc_command_and_job(self):
    self.stub.CommandJob(pb.JobCommand(job_id=42, action=pb.JobCommand.PAUSE))
    self.assertEqual(self.stub.GetJob(empty_pb2.Empty()).state, pb.PAUSED)
    self.assertEqual(self.request("/v1/job")[1]["id"], "42")
    self.simulator.update({"job_id": None, "state": "IDLE"})
    self.assertFalse(self.stub.GetJob(empty_pb2.Empty()).has_job)
    self.assertEqual(self.request("/v1/job")[1]["has_job"], False)

  def test_commands_are_opt_in_and_mock_controls_are_sim_only(self):
    httpd = server.make_http_server(self.printer, False, "127.0.0.1", 0)
    self.start_http(httpd)
    self.url = f"http://127.0.0.1:{httpd.server_port}"
    for path, status in (
      ("/v1/jobs/42/pause", 403),
      ("/simulation/state", 404),
    ):
      with self.assertRaises(urllib.error.HTTPError) as cm:
        self.request(path, {})
      self.assertEqual(cm.exception.code, status)
      cm.exception.close()
    self.assertEqual(self.printer.get_status().state, pb.PRINTING)

  @parameterized.parameters((401, 502), (404, 404), (409, 409), (500, 502))
  def test_upstream_errors_not_success(self, upstream, expected):
    self.simulator.update({"failure": upstream})
    with self.assertRaises(urllib.error.HTTPError) as cm:
      self.request("/v1/status")
    self.assertEqual(cm.exception.code, expected)
    self.assertIn("error", json.loads(cm.exception.read()))
    cm.exception.close()
    self.simulator.update({"failure": None})
    self.assertEqual(self.request("/v1/status")[0], 200)

  def test_invalid_http_inputs(self):
    for path, body, expected in (
      ("/simulation/state", {"temp_bed": math.nan}, 400),
      ("/simulation/state", {"state": "UNKNOWN"}, 400),
      ("/simulation/state", {"job_id": True}, 400),
      ("/simulation/state", {"unexpected": 1}, 400),
      ("/v1/jobs/99999999999999999999/pause", {}, 400),
      ("/v1/jobs/99/pause", {}, 404),
      ("/not-a-route", None, 404),
    ):
      with self.assertRaises(urllib.error.HTTPError) as cm:
        self.request(path, body)
      self.assertEqual(cm.exception.code, expected)
      cm.exception.close()

  @parameterized.parameters(
    ({},),
    ({"printer": {}},),
    ({"printer": {"state": "UNKNOWN"}},),
    ({"printer": {"state": "FINISHED", "temp_bed": True}},),
    ({"printer": {"state": "FINISHED", "temp_bed": math.nan}},),
    ({"printer": {"state": "FINISHED", "temp_bed": "25"}},),
    ({"printer": {"state": "FINISHED"}, "job": None},),
    ({"printer": {"state": "PRINTING"}, "job": {"id": -1}},),
    ({"printer": {"state": "FINISHED", "temp_bed": 10**1000}},),
  )
  def test_invalid_telemetry_is_rejected(self, payload):
    with unittest_mock.patch.object(
      self.printer, "request", return_value=payload
    ):
      with self.assertRaises(client.ServiceError) as cm:
        self.printer.get_status()
      self.assertEqual(cm.exception.status, 502)

  @parameterized.parameters(
    ("broken", "application/json", 502),
    ("[]", "application/json", 502),
    ("{}", "text/html", 502),
    ("{}", "application/json", 504),
  )
  def test_invalid_network_response_and_timeout(
    self, body, content_type, expected
  ):
    class Handler(http.server.BaseHTTPRequestHandler):
      def do_GET(handler):
        if expected == 504:
          threading.Event().wait(0.4)
          return
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.end_headers()
        handler.wfile.write(body.encode())

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    self.start_http(httpd)
    printer = client.PrusaLinkClient(
      f"http://127.0.0.1:{httpd.server_port}", "u", "p", 0.05
    )
    with self.assertRaises(client.ServiceError) as cm:
      printer.get_status()
    self.assertEqual(cm.exception.status, expected)

  def test_runtime_context_requires_correct_config_mode_and_ports(self):
    context = runtime_context_pb2.RuntimeContext(
      port=30000,
      http_port=30001,
      http_path_prefix="/ext/services/prusalink",
      level=runtime_context_pb2.RuntimeContext.PHYSICS_SIM,
    )
    context.config.Pack(pb.PrusaLinkConfig(timeout_seconds=5))
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "context.pb"
      path.write_bytes(context.SerializeToString())
      config, grpc_port, http_port, prefix = main.load_runtime(str(path), "sim")
      self.assertEqual(config.timeout_seconds, 5)
      self.assertEqual(
        (grpc_port, http_port, prefix),
        (30000, 30001, "/ext/services/prusalink"),
      )
      with self.assertRaises(ValueError):
        main.load_runtime(str(path), "real")
      context.http_port = 0
      path.write_bytes(context.SerializeToString())
      with self.assertRaises(ValueError):
        main.load_runtime(str(path), "sim")
      context.http_port = 30001
      context.config.Pack(empty_pb2.Empty())
      path.write_bytes(context.SerializeToString())
      with self.assertRaises(ValueError):
        main.load_runtime(str(path), "sim")

  @parameterized.parameters(
    "ftp://printer",
    "http://user:pass@printer",
    "http://printer/api",
    "http://printer?query=1",
    "",
  )
  def test_invalid_configuration(self, url):
    with self.assertRaises(ValueError):
      client.PrusaLinkClient(url, "u", "p")


if __name__ == "__main__":
  absltest.main()
