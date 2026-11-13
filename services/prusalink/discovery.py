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

"""Finds the disposable mock printer (tools/mock_printer) when no printer is
configured.

The mock listens on the machine that runs the test. The service may run in a
container on that same machine (a local Intrinsic cluster), where the mock is
not on `127.0.0.1` but on the container's default gateway, so both are tried.
A candidate counts as the mock only if its unauthenticated reply is a Digest
challenge for the realm "PrusaLink mock", so a real printer, or any other
web server, is never taken for it.
"""

import logging
import threading
import time
import urllib.error
import urllib.request

MOCK_REALM = 'realm="PrusaLink mock"'
DEFAULT_MOCK_PORT = 18081


def default_gateway(route_table: str = "/proc/net/route") -> str | None:
  """The IPv4 default gateway; inside a pod or container, the host."""
  try:
    with open(route_table) as table:
      next(table)
      for line in table:
        fields = line.split()
        if len(fields) > 2 and fields[1] == "00000000" and fields[2]:
          raw = bytes.fromhex(fields[2])[::-1]
          return ".".join(str(b) for b in raw)
  except (OSError, ValueError, StopIteration):
    pass
  return None


def is_mock(url: str, timeout: float) -> bool:
  opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
  try:
    opener.open(url + "/api/version", timeout=timeout).close()
  except urllib.error.HTTPError as exc:
    exc.close()
    return exc.code == 401 and MOCK_REALM in exc.headers.get(
      "WWW-Authenticate", ""
    )
  except (OSError, ValueError):
    return False
  return False


class MockLocator:
  def __init__(
    self,
    port: int = DEFAULT_MOCK_PORT,
    hosts: list[str] | None = None,
    retry_seconds: float = 3.0,
    probe_timeout: float = 1.0,
  ):
    self.port = port
    self.retry_seconds = retry_seconds
    self.probe_timeout = probe_timeout
    self._hosts = hosts
    self._lock = threading.Lock()
    self._url: str | None = None
    self._next_try = 0.0
    self._warned = False

  @property
  def found(self) -> str | None:
    """The mock's URL if it was found, without probing."""
    return self._url

  def candidates(self) -> list[str]:
    hosts = self._hosts or [
      "127.0.0.1",
      default_gateway(),
      "host.docker.internal",
      "host.containers.internal",
    ]
    seen, urls = set(), []
    for host in hosts:
      if host and host not in seen:
        seen.add(host)
        urls.append(f"http://{host}:{self.port}")
    return urls

  def current(self) -> str | None:
    with self._lock:
      if self._url:
        return self._url
      now = time.monotonic()
      if now < self._next_try:
        return None
      self._next_try = now + self.retry_seconds
      candidates = self.candidates()
      for url in candidates:
        if is_mock(url, self.probe_timeout):
          self._url = url
          self._warned = False
          logging.info("ROUTE: mock printer found at %s", url)
          return url
      if not self._warned:
        logging.warning(
          "ROUTE: no printer configured and no mock printer found at %s; "
          "still looking (start tools/mock_printer or pass --printer-url)",
          ", ".join(candidates),
        )
        self._warned = True
      return None

  def forget(self) -> None:
    with self._lock:
      if self._url:
        logging.warning("ROUTE: mock printer at %s stopped answering", self._url)
      self._url = None
      self._next_try = 0.0
