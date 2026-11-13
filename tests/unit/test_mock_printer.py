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

"""The standalone mock printer behaves like the PrusaLink spec says."""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from absl.testing import absltest

from tools.mock_printer import mock_printer as mock

_BODY = (Path(__file__).parent / "testdata/prusaslicer_2_9_7_part.bgcode").read_bytes()


class _Base(absltest.TestCase):
  def make(self, **options):
    self.server, self.sim = mock.make_mock_server(0, "127.0.0.1", **options)
    thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(self.server.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(self.server.shutdown)
    self.base = f"http://127.0.0.1:{self.server.server_port}"
    manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(None, self.base, mock.MOCK_USERNAME, mock.MOCK_PASSWORD)
    self.opener = urllib.request.build_opener(
      urllib.request.HTTPDigestAuthHandler(manager)
    )

  def call(self, method, path, body=None, headers=None):
    request = urllib.request.Request(
      self.base + urllib.parse.quote(path, safe="/?=&"),
      data=body,
      method=method,
      headers=headers or {},
    )
    return self.opener.open(request, timeout=5)

  def put(self, name, body=_BODY, headers=None):
    return self.call(
      "PUT",
      "/api/v1/files/local/" + name,
      body,
      {"Print-After-Upload": "?1", **(headers or {})},
    )


class UploadTest(_Base):
  def setUp(self):
    super().setUp()
    self.make()
    self.sim.update({"state": "IDLE"})  # job 42 is "running" at the start

  def test_upload_starts_a_new_job_with_that_file(self):
    self.assertEqual(self.put("new job.gcode").status, 201)
    with self.call("GET", "/api/v1/job") as response:
      job = json.load(response)
    self.assertEqual((job["id"], job["state"]), (43, "PRINTING"))
    self.assertEqual(job["file"]["name"], "new job.gcode")
    self.assertEqual(job["file"]["path"], "/local")
    self.assertIn("m_timestamp", job["file"])
    ref = urllib.parse.unquote(job["file"]["refs"]["download"])
    with self.call("GET", ref) as response:
      self.assertEqual(response.read(), _BODY)

  def test_login_is_required(self):
    with self.assertRaises(urllib.error.HTTPError) as raised:
      urllib.request.urlopen(self.base + "/api/version", timeout=5)
    self.assertEqual(raised.exception.code, 401)
    self.assertIn(
      'realm="PrusaLink mock"', raised.exception.headers["WWW-Authenticate"]
    )

  def test_upload_while_printing_is_a_conflict(self):
    self.sim.update({"state": "PRINTING"})
    with self.assertRaises(urllib.error.HTTPError) as raised:
      self.put("a.gcode", b"G1 X1\n")
    self.assertEqual(raised.exception.code, 409)

  def test_existing_file_needs_overwrite(self):
    zero = {"Print-After-Upload": "?0"}
    self.put("a.gcode", b"G1 X1\n", zero).close()
    self.assertEqual(self.sim.job_id, 42)  # stored, not started
    with self.assertRaises(urllib.error.HTTPError) as raised:
      self.put("a.gcode", b"G1 X2\n", zero)
    self.assertEqual(raised.exception.code, 409)
    self.put("a.gcode", b"G1 X2\n", {**zero, "Overwrite": "?1"}).close()

  def test_stored_file_can_be_inspected_and_started(self):
    self.put("d/a.gcode", b"G1 X1\n", {"Print-After-Upload": "?0"}).close()
    with self.call("HEAD", "/api/v1/files/local/d/a.gcode") as response:
      self.assertEqual(response.headers["Currently-Printed"], "false")
    with self.call("GET", "/api/v1/files/local/d/a.gcode") as response:
      self.assertEqual(json.load(response)["type"], "PRINT_FILE")
    with self.call("POST", "/api/v1/files/local/d/a.gcode") as response:
      self.assertEqual(response.status, 204)
    with self.call("GET", "/api/v1/job") as response:
      job = json.load(response)
    self.assertEqual(job["file"]["refs"]["download"], "/api/files/local/d/a.gcode/raw")
    with self.assertRaises(urllib.error.HTTPError) as raised:
      self.call("POST", "/api/v1/files/local/d/a.gcode")
    self.assertEqual(raised.exception.code, 409)

  def test_unknown_file_404_and_bad_names_400(self):
    for method, path, code in (
      ("GET", "/api/v1/files/local/nope.gcode", 404),
      ("PUT", "/api/v1/files/local/evil.sh", 400),
      ("PUT", "/api/v1/files/local/../x.gcode", 400),
    ):
      with self.assertRaises(urllib.error.HTTPError) as raised:
        self.call(method, path, b"x" if method == "PUT" else None,
                  {"Print-After-Upload": "?1"})
      self.assertEqual(raised.exception.code, code)

  def test_spec_endpoints(self):
    with self.call("GET", "/api/version") as response:
      version = json.load(response)
    for field in ("api", "version", "printer", "text", "firmware"):
      self.assertIn(field, version)
    self.assertTrue(version["capabilities"]["upload-by-put"])
    with self.call("GET", "/api/v1/storage") as response:
      self.assertEqual(json.load(response)["storage_list"][0]["path"], "/local")
    with self.call("GET", "/api/v1/info") as response:
      self.assertIn("serial", json.load(response))

  def test_invalid_state_updates_are_refused(self):
    for data in (
      {"temp_bed": float("nan")},
      {"state": "UNKNOWN"},
      {"job_id": True},
      {"unexpected": 1},
      {"failure": 418},
    ):
      with self.assertRaises(mock.HttpError):
        self.sim.update(data)


class AutoSimulationTest(_Base):
  def setUp(self):
    super().setUp()
    self.now = [0.0]
    self.make(
      print_seconds=10,
      cool_seconds=20,
      clock=lambda: self.now[0],
      initial_state="IDLE",
      initial_job_id=None,
      first_job_id=1,
    )

  def status(self):
    with self.call("GET", "/api/v1/status") as response:
      return json.load(response)

  def test_job_prints_finishes_and_the_bed_cools(self):
    self.assertEqual(self.status()["printer"]["state"], "IDLE")
    self.put("a.gcode", b"G1 X1\n").close()
    self.assertEqual(self.status()["job"]["id"], 1)
    self.now[0] = 5
    status = self.status()
    self.assertEqual(status["printer"]["state"], "PRINTING")
    self.assertEqual(status["job"]["progress"], 50.0)
    self.now[0] = 10
    status = self.status()
    self.assertEqual(status["printer"]["state"], "FINISHED")
    self.assertEqual(status["printer"]["temp_bed"], 60.0)
    self.now[0] = 20  # halfway through cooling: 60 -> 24
    self.assertEqual(self.status()["printer"]["temp_bed"], 42.0)
    self.now[0] = 100
    self.assertEqual(self.status()["printer"]["temp_bed"], 24.0)

  def test_a_new_job_after_finishing_gets_the_next_id(self):
    self.put("a.gcode", b"G1 X1\n").close()
    self.now[0] = 11
    self.assertEqual(self.status()["printer"]["state"], "FINISHED")
    self.put("b.gcode", b"G1 X2\n").close()
    status = self.status()
    self.assertEqual(
      (status["printer"]["state"], status["job"]["id"], status["printer"]["temp_bed"]),
      ("PRINTING", 2, 60.0),
    )

  def test_explicit_temperature_stops_the_automatic_cooling(self):
    self.put("a.gcode", b"G1 X1\n").close()
    self.now[0] = 11
    self.sim.update({"temp_bed": 33.0})
    self.now[0] = 60
    self.assertEqual(self.status()["printer"]["temp_bed"], 33.0)

  def test_a_pause_does_not_count_as_printing_time(self):
    self.put("a.gcode", b"G1 X1\n").close()
    self.now[0] = 4
    self.sim.update({"state": "PAUSED"})
    self.now[0] = 50  # a long pause: still 40%, still not finished
    status = self.status()
    self.assertEqual(
      (status["printer"]["state"], status["job"]["progress"]), ("PAUSED", 40.0)
    )
    self.sim.update({"state": "PRINTING"})
    self.now[0] = 52  # 4 s before the pause + 2 s after
    self.assertEqual(self.status()["job"]["progress"], 60.0)
    self.now[0] = 56
    self.assertEqual(self.status()["printer"]["state"], "FINISHED")

  def test_keys(self):
    self.put("a.gcode", b"G1 X1\n").close()
    self.assertTrue(mock.handle_key(self.sim, "p"))
    self.assertEqual(self.sim.printer_state, "PAUSED")
    mock.handle_key(self.sim, "p")
    self.assertEqual(self.sim.printer_state, "PRINTING")
    mock.handle_key(self.sim, "f")
    self.assertEqual(self.sim.printer_state, "FINISHED")
    mock.handle_key(self.sim, "c")
    self.assertEqual(self.sim.bed_temperature, mock.AMBIENT_C)
    self.assertFalse(mock.handle_key(self.sim, "q"))

  def test_the_screen_renders(self):
    self.put("a.gcode", b"G1 X1\n").close()
    screen = mock.render(self.sim, self.server.server_port)
    self.assertIn("PRINTING", screen)
    self.assertIn("a.gcode", screen)


if __name__ == "__main__":
  absltest.main()
