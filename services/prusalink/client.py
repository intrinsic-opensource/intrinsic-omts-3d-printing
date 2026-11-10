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

import http.client
import json
import math
import urllib.error
import urllib.parse
import urllib.request

from services.prusalink import prusalink_pb2 as pb

MAX_RESPONSE_BYTES = 1024 * 1024


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
    self, url: str, username: str, password: str, timeout: float = 5.0
  ):
    parsed = urllib.parse.urlsplit(url)
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

  def request(self, method: str, path: str) -> dict | None:
    # A separate opener per request avoids sharing Digest nonce state across
    # concurrent HTTP/gRPC workers. Do not inherit workstation proxy settings.
    credentials = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    credentials.add_password(None, self.url, self.username, self.password)
    opener = urllib.request.build_opener(
      urllib.request.ProxyHandler({}),
      _NoRedirect(),
      urllib.request.HTTPDigestAuthHandler(credentials),
    )
    request = urllib.request.Request(
      self.url + path, method=method, headers={"Accept": "application/json"}
    )
    try:
      with opener.open(request, timeout=self.timeout) as response:
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
      raise ServiceError(502, "upstream_unavailable", "Cannot reach PrusaLink")
    except (ValueError, UnicodeDecodeError):
      raise ServiceError(
        502,
        "invalid_response",
        "Invalid response or unsupported PrusaLink authentication",
      )
    except (OSError, http.client.HTTPException):
      raise ServiceError(
        502, "upstream_unavailable", "PrusaLink connection failed"
      )

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
