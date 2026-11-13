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

"""Bounded, uncached PrusaLink v1 requests using HTTP Digest authentication."""

import contextlib
import dataclasses
import http.client
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from services.prusalink import prusalink_pb2 as pb

MAX_RESPONSE_BYTES = 1024 * 1024
# A sliced job is G-code or bgcode. Sizes in the tens of MB are typical.
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
_DOWNLOAD_PATH = re.compile(r"/api/[A-Za-z0-9._~%/+@=,()\[\]-]{1,1000}")


@dataclasses.dataclass(frozen=True)
class JobFile:
  """The file the printer is printing, as `GET /api/v1/job` reports it."""

  job_id: int
  name: str
  download_path: str
  size: int | None
  # The file's modification time on the printer: tells a re-sent file, or a
  # job id reused after a printer reboot, from the job already read.
  m_timestamp: int | None = None


class ServiceError(Exception):
  def __init__(self, status: int, code: str, message: str):
    super().__init__(message)
    self.status = status
    self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self, req, fp, code, msg, headers, newurl):
    raise ServiceError(502, "upstream_redirect", "PrusaLink redirects rejected")


def number(value: object, name: str) -> float:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise ServiceError(502, "invalid_telemetry", f"Invalid {name}")
  try:
    result = float(value)
  except OverflowError:
    raise ServiceError(502, "invalid_telemetry", f"Invalid {name}")
  if not math.isfinite(result):
    raise ServiceError(502, "invalid_telemetry", f"Invalid {name}")
  return result


def integer(value: object, name: str) -> int:
  if (
    isinstance(value, bool)
    or not isinstance(value, int)
    or not 0 <= value <= 2**63 - 1
  ):
    raise ServiceError(502, "invalid_telemetry", f"Invalid {name}")
  return value


def state(value: object) -> int:
  if not isinstance(value, str) or value not in pb.PrinterState.keys()[1:]:
    raise ServiceError(502, "invalid_telemetry", "Invalid printer state")
  return pb.PrinterState.Value(value)


class PrusaLinkClient:
  def __init__(
    self,
    url: str,
    username: str,
    password: str,
    timeout: float = 5.0,
    locator=None,
  ):
    """`locator` (an object with `current()` and `forget()`) finds the URL.

    Used when no printer is configured: the printer is then looked up on
    every request until found, and forgotten again if it stops answering.
    """
    self.locator = locator
    if not url and locator is None:
      raise ValueError("printer_url is required without a locator")
    parsed = urllib.parse.urlsplit(url or "http://locator.invalid")
    if (
      parsed.scheme not in ("http", "https")
      or not parsed.hostname
      or parsed.username is not None
      or parsed.password is not None
      or parsed.path not in ("", "/")
      or parsed.query
      or parsed.fragment
      or parsed.port == 0
    ):
      raise ValueError(
        "printer_url must be an HTTP(S) origin without credentials"
      )
    if not username or not password:
      raise ValueError("PrusaLink Digest username and password are required")
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
      raise ValueError("timeout_seconds must be in (0, 60]")
    self.url = url.rstrip("/")
    self.username = username
    self.password = password
    self.timeout = timeout

  def _target(self) -> str:
    if self.locator is None:
      return self.url
    url = self.locator.current()
    if not url:
      raise ServiceError(
        502,
        "printer_not_found",
        "No printer configured and no mock printer found",
      )
    self.url = url
    return url

  def _opener(self) -> urllib.request.OpenerDirector:
    # A separate opener per request avoids sharing Digest nonce state across
    # concurrent HTTP/gRPC workers. Do not inherit workstation proxy settings.
    credentials = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    credentials.add_password(None, self.url, self.username, self.password)
    return urllib.request.build_opener(
      urllib.request.ProxyHandler({}),
      _NoRedirect(),
      urllib.request.HTTPDigestAuthHandler(credentials),
    )

  @contextlib.contextmanager
  def _upstream_errors(self):
    try:
      yield
    except urllib.error.HTTPError as exc:
      exc.close()
      if exc.code in (404, 409):
        raise ServiceError(
          exc.code, "upstream_error", f"PrusaLink HTTP {exc.code}"
        )
      if exc.code == 401:
        raise ServiceError(
          502, "upstream_authentication", "PrusaLink rejected credentials"
        )
      raise ServiceError(502, "upstream_error", f"PrusaLink HTTP {exc.code}")
    except TimeoutError:
      raise ServiceError(504, "upstream_timeout", "PrusaLink request timed out")
    except urllib.error.URLError as exc:
      if isinstance(exc.reason, TimeoutError):
        raise ServiceError(
          504, "upstream_timeout", "PrusaLink request timed out"
        )
      self._forget()
      raise ServiceError(502, "upstream_unavailable", "Cannot reach PrusaLink")
    except (ValueError, UnicodeDecodeError):
      raise ServiceError(
        502,
        "invalid_response",
        "Invalid response or unsupported PrusaLink authentication",
      )
    except (OSError, http.client.HTTPException):
      self._forget()
      raise ServiceError(
        502, "upstream_unavailable", "PrusaLink connection failed"
      )

  def _forget(self) -> None:
    if self.locator is not None:
      self.locator.forget()

  def request(self, method: str, path: str) -> dict | None:
    request = urllib.request.Request(
      self._target() + path,
      method=method,
      headers={"Accept": "application/json"},
    )
    with self._upstream_errors():
      with self._opener().open(request, timeout=self.timeout) as response:
        if method != "GET":
          if response.status != 204:
            raise ServiceError(502, "invalid_response", "Expected HTTP 204")
          return None
        if response.status == 204 and path == "/api/v1/job":
          return None
        if response.status != 200:
          raise ServiceError(502, "invalid_response", "Expected HTTP 200")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
          raise ServiceError(
            502, "invalid_response", "PrusaLink response too large"
          )
        if response.headers.get_content_type() != "application/json":
          raise ServiceError(
            502, "invalid_response", "Expected JSON from PrusaLink"
          )
        result = json.loads(body)
        if not isinstance(result, dict):
          raise ServiceError(502, "invalid_response", "Expected a JSON object")
        return result

  def get_job_file(self) -> JobFile | None:
    """The running job's file and where to download it, or None.

    PrusaLink lists it as `file.refs.download` in `GET /api/v1/job`. The
    reference must be a plain `/api/...` path on the printer: anything that
    could point elsewhere (a host, `..`, a query) is refused.
    """
    data = self.request("GET", "/api/v1/job")
    if data is None:
      return None
    file = data.get("file")
    refs = file.get("refs") if isinstance(file, dict) else None
    ref = refs.get("download") if isinstance(refs, dict) else None
    if not isinstance(file, dict) or ref is None:
      raise ServiceError(
        404, "no_download_reference", "The job has no downloadable file"
      )
    if (
      not isinstance(ref, str)
      or not _DOWNLOAD_PATH.fullmatch(ref)
      or ".." in ref.split("/")
    ):
      raise ServiceError(502, "invalid_response", "Invalid download reference")
    name = file.get("display_name") or file.get("name")
    if not isinstance(name, str) or not 0 < len(name) <= 255:
      raise ServiceError(502, "invalid_response", "Invalid job file name")
    size = file.get("size")
    return JobFile(
      job_id=integer(data.get("id"), "job.id"),
      name=name,
      download_path=ref,
      size=None if size is None else integer(size, "file.size"),
      m_timestamp=(
        file["m_timestamp"]
        if isinstance(file.get("m_timestamp"), int)
        and not isinstance(file.get("m_timestamp"), bool)
        else None
      ),
    )

  def download(
    self, path: str, destination: Path, max_bytes: int = MAX_DOWNLOAD_BYTES
  ) -> int:
    """Streams a file from the printer to `destination`; returns its size.

    Bounded by `max_bytes`; written to a temporary name and renamed, so a
    partial download never looks like a finished one.
    """
    if not _DOWNLOAD_PATH.fullmatch(path) or ".." in path.split("/"):
      raise ServiceError(400, "invalid_path", "Invalid download path")
    request = urllib.request.Request(
      self._target() + path, method="GET", headers={"Accept": "*/*"}
    )
    partial = destination.with_name(destination.name + ".part")
    try:
      with self._upstream_errors():
        with self._opener().open(request, timeout=self.timeout) as response:
          if response.status != 200:
            raise ServiceError(502, "invalid_response", "Expected HTTP 200")
          declared = response.headers.get("Content-Length")
          if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ServiceError(502, "file_too_large", "File exceeds limit")
          total = 0
          with open(partial, "wb") as out:
            while chunk := response.read(64 * 1024):
              total += len(chunk)
              if total > max_bytes:
                raise ServiceError(502, "file_too_large", "File exceeds limit")
              out.write(chunk)
      os.replace(partial, destination)
      return total
    finally:
      partial.unlink(missing_ok=True)

  def get_status(self) -> pb.PrinterStatus:
    data = self.request("GET", "/api/v1/status")
    if data is None or not isinstance(data.get("printer"), dict):
      raise ServiceError(502, "invalid_telemetry", "Missing printer telemetry")
    printer = data["printer"]
    result = pb.PrinterStatus(state=state(printer.get("state")))
    for source, target in (
      ("temp_bed", "bed_temperature_c"),
      ("temp_nozzle", "nozzle_temperature_c"),
    ):
      if source in printer:
        setattr(result, target, number(printer[source], source))
    if "job" in data:
      if not isinstance(data["job"], dict):
        raise ServiceError(502, "invalid_telemetry", "Invalid job telemetry")
      job = data["job"]
      if "id" in job:
        result.job_id = integer(job["id"], "job.id")
      if "progress" in job:
        result.progress_percent = number(job["progress"], "job.progress")
    result.print_finished = result.state == pb.FINISHED
    result.ready_for_unload = (
      result.print_finished
      and result.HasField("bed_temperature_c")
      and result.bed_temperature_c < 30.0
    )
    result.observed_at.GetCurrentTime()
    return result

  def get_job(self) -> pb.Job:
    data = self.request("GET", "/api/v1/job")
    if data is None:
      return pb.Job(has_job=False)
    result = pb.Job(
      has_job=True,
      id=integer(data.get("id"), "job.id"),
      state=state(data.get("state")),
      progress_percent=number(data.get("progress"), "job.progress"),
      time_printing_seconds=integer(data.get("time_printing"), "time_printing"),
    )
    if "time_remaining" in data:
      result.time_remaining_seconds = integer(
        data["time_remaining"], "time_remaining"
      )
    return result

  def command_job(self, command: pb.JobCommand, enabled: bool) -> None:
    if not enabled:
      raise ServiceError(403, "commands_disabled", "Job commands are disabled")
    if command.job_id < 0:
      raise ServiceError(400, "invalid_command", "job_id must be nonnegative")
    routes = {
      pb.JobCommand.PAUSE: ("PUT", "/pause"),
      pb.JobCommand.RESUME: ("PUT", "/resume"),
      pb.JobCommand.STOP: ("DELETE", ""),
      pb.JobCommand.CONTINUE: ("PUT", "/continue"),
    }
    if command.action not in routes:
      raise ServiceError(400, "invalid_command", "Unknown job command")
    method, suffix = routes[command.action]
    self.request(method, f"/api/v1/job/{command.job_id}{suffix}")
