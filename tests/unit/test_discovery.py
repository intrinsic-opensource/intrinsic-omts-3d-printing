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

"""Finding the mock printer, and refusing to mistake anything else for it."""

import http.server
import tempfile
import threading
from pathlib import Path

from absl.testing import absltest

from services.prusalink import discovery
from tools.mock_printer import mock_printer as mock


def _serve(handler=None, mock_printer=False):
  if mock_printer:
    httpd, _ = mock.make_mock_server(0, "127.0.0.1")
  else:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
  thread = threading.Thread(target=httpd.serve_forever, daemon=True)
  thread.start()
  return httpd, thread


class DiscoveryTest(absltest.TestCase):
  def serve(self, **kwargs):
    httpd, thread = _serve(**kwargs)
    self.addCleanup(httpd.server_close)
    self.addCleanup(thread.join)
    self.addCleanup(httpd.shutdown)
    return httpd.server_port

  def locator(self, port, hosts=("127.0.0.1",)):
    return discovery.MockLocator(port, list(hosts), retry_seconds=0)

  def test_finds_the_mock(self):
    port = self.serve(mock_printer=True)
    self.assertEqual(self.locator(port).current(), f"http://127.0.0.1:{port}")

  def test_nothing_listening(self):
    probe = http.server.ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = probe.server_port
    probe.server_close()
    self.assertIsNone(self.locator(port).current())

  def test_other_servers_are_not_the_mock(self):
    class Real(http.server.BaseHTTPRequestHandler):
      def do_GET(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Digest realm="Printer API"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    class Plain(http.server.BaseHTTPRequestHandler):
      def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    for handler in (Real, Plain):
      self.assertIsNone(self.locator(self.serve(handler=handler)).current())

  def test_forget_looks_again(self):
    port = self.serve(mock_printer=True)
    locator = self.locator(port)
    self.assertIsNotNone(locator.current())
    self.assertIsNotNone(locator.found)
    locator.forget()
    self.assertIsNone(locator.found)
    self.assertIsNotNone(locator.current())

  def test_retries_are_throttled(self):
    probe = http.server.ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = probe.server_port
    probe.server_close()
    locator = discovery.MockLocator(port, ["127.0.0.1"], retry_seconds=3600)
    self.assertIsNone(locator.current())
    self.assertIsNone(locator.current())  # inside the window: no probe

  def test_candidates_include_the_gateway(self):
    locator = discovery.MockLocator(1234, ["127.0.0.1", "10.0.0.1", "10.0.0.1"])
    self.assertEqual(
      locator.candidates(), ["http://127.0.0.1:1234", "http://10.0.0.1:1234"]
    )

  def test_default_gateway_parsing(self):
    with tempfile.TemporaryDirectory() as directory:
      table = Path(directory) / "route"
      table.write_text(
        "Iface\tDestination\tGateway\tFlags\n"
        "eth0\t00000000\t012A0A0A\t0003\n"
        "eth0\t002A0A0A\t00000000\t0001\n"
      )
      self.assertEqual(discovery.default_gateway(str(table)), "10.10.42.1")
      table.write_text("Iface\tDestination\tGateway\neth0\t002A0A0A\t00000000\n")
      self.assertIsNone(discovery.default_gateway(str(table)))
    self.assertIsNone(discovery.default_gateway("/nonexistent"))


if __name__ == "__main__":
  absltest.main()
