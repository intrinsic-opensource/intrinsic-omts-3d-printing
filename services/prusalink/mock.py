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

"""Deterministic loopback PrusaLink simulator with real Digest verification."""

import hashlib
import hmac
import http.server
import json
import re
import secrets
import threading
import urllib.request

from services.prusalink import client

MOCK_USERNAME = "maker"
MOCK_PASSWORD = "mock-only"


def send_json(
  handler: http.server.BaseHTTPRequestHandler, status: int, data: dict
):
  body = json.dumps(data, allow_nan=False).encode()
  handler.send_response(status)
  handler.send_header("Content-Type", "application/json")
  handler.send_header("Content-Length", str(len(body)))
  handler.end_headers()
  handler.wfile.write(body)


def read_json(handler: http.server.BaseHTTPRequestHandler) -> dict:
  if handler.headers.get("Transfer-Encoding"):
    raise client.ServiceError(400, "invalid_body", "Chunked bodies unsupported")
  try:
    length = int(handler.headers.get("Content-Length", "0"))
  except ValueError:
    raise client.ServiceError(400, "invalid_body", "Invalid Content-Length")
  if not 0 < length <= 8192:
    raise client.ServiceError(
      400, "invalid_body", "Expected JSON body <= 8192 bytes"
    )
  try:
    data = json.loads(handler.rfile.read(length))
  except TimeoutError:
    raise client.ServiceError(
      408, "request_timeout", "JSON body read timed out"
    )
  except (ValueError, UnicodeDecodeError):
    raise client.ServiceError(400, "invalid_body", "Invalid JSON body")
  if not isinstance(data, dict):
    raise client.ServiceError(400, "invalid_body", "Expected JSON object")
  return data


class MockPrinter:
  def __init__(self):
    self.lock = threading.Lock()
    self.printer_state = "PRINTING"
    self.bed_temperature: float | None = 60.0
    self.job_id: int | None = 42
    self.failure: int | None = None
    self.nonce = secrets.token_hex(16)

  def update(self, data: dict) -> dict:
    if set(data) - {"state", "temp_bed", "job_id", "failure"}:
      raise client.ServiceError(400, "invalid_mock_state", "Unknown mock field")
    try:
      if "state" in data:
        client.state(data["state"])
      if "temp_bed" in data and data["temp_bed"] is not None:
        client.number(data["temp_bed"], "temp_bed")
      if "job_id" in data and data["job_id"] is not None:
        client.integer(data["job_id"], "job_id")
      if "failure" in data and data["failure"] not in (
        None,
        401,
        404,
        409,
        500,
      ):
        raise client.ServiceError(
          400, "invalid_mock_state", "Invalid failure code"
        )
    except client.ServiceError as exc:
      raise client.ServiceError(400, "invalid_mock_state", str(exc))
    with self.lock:
      for key, attribute in (
        ("state", "printer_state"),
        ("temp_bed", "bed_temperature"),
        ("job_id", "job_id"),
        ("failure", "failure"),
      ):
        if key in data:
          setattr(self, attribute, data[key])
      return self._status()

  def _status(self) -> dict:
    printer = {"state": self.printer_state, "temp_nozzle": 25.0}
    if self.bed_temperature is not None:
      printer["temp_bed"] = self.bed_temperature
    result = {"printer": printer}
    if self.job_id is not None:
      result["job"] = {
        "id": self.job_id,
        "progress": 100.0 if self.printer_state == "FINISHED" else 42.0,
      }
    return result

  def authenticate(self, handler: http.server.BaseHTTPRequestHandler) -> bool:
    header = handler.headers.get("Authorization", "")
    if not header.startswith("Digest "):
      return False
    try:
      fields = urllib.request.parse_keqv_list(
        urllib.request.parse_http_list(header[7:])
      )
    except ValueError:
      handler.log_error("Malformed Digest authorization")
      return False
    if (
      fields.get("username") != MOCK_USERNAME
      or fields.get("realm") != "PrusaLink mock"
      or fields.get("nonce") != self.nonce
      or fields.get("uri") != handler.path
      or fields.get("qop") != "auth"
      or not re.fullmatch(r"[0-9a-fA-F]{8}", fields.get("nc", ""))
      or not fields.get("cnonce")
    ):
      return False

    def md5(text: str) -> str:
      return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()

    ha1 = md5(f"{MOCK_USERNAME}:PrusaLink mock:{MOCK_PASSWORD}")
    ha2 = md5(f"{handler.command}:{handler.path}")
    expected = md5(
      f"{ha1}:{self.nonce}:{fields['nc']}:{fields['cnonce']}:auth:{ha2}"
    )
    return hmac.compare_digest(expected, fields.get("response", ""))


def make_mock_server(
  port: int = 0,
) -> tuple[http.server.ThreadingHTTPServer, MockPrinter]:
  printer = MockPrinter()

  class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
      super().setup()
      self.connection.settimeout(5)

    def handle_request(self):
      try:
        if not printer.authenticate(self):
          self.send_response(401)
          self.send_header(
            "WWW-Authenticate",
            f'Digest realm="PrusaLink mock", nonce="{printer.nonce}", '
            'algorithm=MD5, qop="auth"',
          )
          self.send_header("Content-Length", "0")
          self.end_headers()
          return
        if self.command == "POST" and self.path == "/mock/state":
          send_json(self, 200, printer.update(read_json(self)))
          return
        with printer.lock:
          if printer.failure:
            send_json(self, printer.failure, {"error": "Injected mock failure"})
            return
          if self.command == "GET" and self.path == "/api/v1/status":
            send_json(self, 200, printer._status())
            return
          if self.command == "GET" and self.path == "/api/v1/job":
            if printer.job_id is None or printer.printer_state in (
              "IDLE",
              "BUSY",
              "READY",
              "ATTENTION",
            ):
              self.no_content()
            else:
              send_json(
                self,
                200,
                {
                  "id": printer.job_id,
                  "state": printer.printer_state,
                  "progress": 100.0
                  if printer.printer_state == "FINISHED"
                  else 42.0,
                  "time_printing": 526,
                  "time_remaining": 0
                  if printer.printer_state == "FINISHED"
                  else 520,
                  "file": {
                    "name": "mock_part.gcode",
                    "display_name": "Mock part",
                  },
                },
              )
            return
          if self.command == "GET" and self.path == "/api/version":
            send_json(
              self,
              200,
              {"api": "1.0.0", "server": "mock", "text": "PrusaLink mock"},
            )
            return
          match = re.fullmatch(
            r"/api/v1/job/([0-9]+)(/pause|/resume|/continue)?", self.path
          )
          if not match or int(match[1]) != printer.job_id:
            raise client.ServiceError(
              404, "not_found", "Unknown mock job or route"
            )
          transitions = {
            ("PUT", "/pause"): ("PRINTING", "PAUSED"),
            ("PUT", "/resume"): ("PAUSED", "PRINTING"),
            ("PUT", "/continue"): ("PAUSED", "PRINTING"),
          }
          if self.command == "DELETE" and not match[2]:
            if printer.printer_state not in ("PRINTING", "PAUSED"):
              raise client.ServiceError(
                409, "conflict", "Job cannot be stopped"
              )
            printer.printer_state = "STOPPED"
          elif (self.command, match[2]) in transitions:
            before, after = transitions[(self.command, match[2])]
            if printer.printer_state != before:
              raise client.ServiceError(409, "conflict", "Invalid job state")
            printer.printer_state = after
          else:
            raise client.ServiceError(
              405, "method_not_allowed", "Unsupported method"
            )
          self.no_content()
      except client.ServiceError as exc:
        self.log_error("%s: %s", exc.code, exc)
        send_json(
          self, exc.status, {"error": {"code": exc.code, "message": str(exc)}}
        )

    def no_content(self):
      self.send_response(204)
      self.send_header("Content-Length", "0")
      self.end_headers()

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request

  return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler), printer
