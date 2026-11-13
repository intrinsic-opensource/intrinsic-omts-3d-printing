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

"""A disposable fake PrusaLink printer for testing. Standard library only.

    python3 mock_printer.py

starts a printer that speaks the PrusaLink HTTP API (Digest login, upload with
`Print-After-Upload`, status, job, download) on 0.0.0.0:18081 and shows a live
screen of what is happening to it. Send it a job like a slicer would:

    curl --digest -u maker:mock-only -X PUT -H 'Print-After-Upload: ?1' \\
      -T part.bgcode http://localhost:18081/api/v1/files/local/part.bgcode

It "prints" for --print-seconds, then reports FINISHED while the bed cools.
Keys on the live screen: f finish, c cool, i idle, p pause/resume, s stop,
e error, q quit. This file does not import anything from the rest of the
repository; delete the folder and nothing else is affected.
"""

import argparse
import collections
import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import select
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MOCK_USERNAME = "maker"
MOCK_PASSWORD = "mock-only"
REALM = "PrusaLink mock"
AMBIENT_C = 24.0
PRINT_BED_C = 60.0
STATES = (
  "IDLE",
  "BUSY",
  "PRINTING",
  "PAUSED",
  "FINISHED",
  "STOPPED",
  "ERROR",
  "ATTENTION",
  "READY",
)
RUNNING = ("PRINTING", "PAUSED")
JOB_FILE_NAME = re.compile(r"[A-Za-z0-9._ +()-]{1,120}\.(?:gcode|bgcode|gco)")
FILE_PATH = re.compile(r"/api/v1/files/(local|usb)/(.+)")
DOWNLOAD_PATH = re.compile(r"/api/files/(local|usb)/(.+)/raw")


class HttpError(Exception):
  def __init__(self, status: int, code: str, text: str):
    super().__init__(text)
    self.status, self.code, self.text = status, code, text


def send_json(handler, status: int, data: dict):
  body = json.dumps(data, allow_nan=False).encode()
  handler.send_response(status)
  handler.send_header("Content-Type", "application/json")
  handler.send_header("Content-Length", str(len(body)))
  handler.end_headers()
  handler.wfile.write(body)


def read_body(handler, limit: int = MAX_UPLOAD_BYTES) -> bytes:
  if handler.headers.get("Transfer-Encoding"):
    raise HttpError(400, "invalid_body", "Chunked bodies unsupported")
  try:
    length = int(handler.headers.get("Content-Length", ""))
  except ValueError:
    raise HttpError(400, "invalid_body", "Content-Length required")
  if not 0 < length <= limit:
    raise HttpError(400, "invalid_body", f"Expected 1..{limit} body bytes")
  return handler.rfile.read(length)


class MockPrinter:
  """The printer's state. Time-driven when print_seconds is set."""

  def __init__(
    self,
    username: str = MOCK_USERNAME,
    password: str = MOCK_PASSWORD,
    print_seconds: float = 0,
    cool_seconds: float = 0,
    clock=time.monotonic,
    initial_state: str = "PRINTING",
    initial_job_id: int | None = 42,
    first_job_id: int | None = None,
  ):
    self.lock = threading.RLock()
    self.username, self.password = username, password
    # 0 means manual: state changes only through update() or the keys.
    self.print_seconds, self.cool_seconds = print_seconds, cool_seconds
    self.clock = clock
    self.printer_state = initial_state
    self.bed_temperature: float | None = (
      PRINT_BED_C if initial_state == "PRINTING" else AMBIENT_C
    )
    self.job_id: int | None = initial_job_id
    self.first_job_id = first_job_id
    self.failure: int | None = None
    self.gcode: bytes | None = None
    self.gcode_name = "mock_part.gcode"
    self.gcode_key = "local/mock_part.gcode"
    self.files: dict[str, tuple[bytes, int]] = {}
    self.nonce = secrets.token_hex(16)
    self.started_at: float | None = None
    self.paused_at: float | None = None
    self.cool_from: tuple[float, float] | None = None
    self.events: collections.deque = collections.deque(maxlen=200)

  # -- state ---------------------------------------------------------------

  def log(self, text: str) -> None:
    self.events.append((time.strftime("%H:%M:%S"), text))

  def _set_state(self, state: str) -> None:
    if state != self.printer_state:
      self.log(f"state {self.printer_state} -> {state}")
      now = self.clock()
      if state == "PAUSED" and self.printer_state == "PRINTING":
        self.paused_at = now
      elif (
        state == "PRINTING"
        and self.printer_state == "PAUSED"
        and self.paused_at is not None
        and self.started_at is not None
      ):
        self.started_at += now - self.paused_at  # the pause does not count
        self.paused_at = None
    self.printer_state = state

  def _elapsed(self) -> float:
    if self.started_at is None:
      return 0.0
    end = self.paused_at if self.paused_at is not None else self.clock()
    return end - self.started_at

  def _advance(self) -> None:
    """Applies the passage of time (auto mode only)."""
    now = self.clock()
    if (
      self.print_seconds
      and self.printer_state == "PRINTING"
      and self.started_at is not None
      and now - self.started_at >= self.print_seconds
    ):
      self._set_state("FINISHED")
      self.cool_from = (now, self.bed_temperature or PRINT_BED_C)
    if self.cool_seconds and self.cool_from is not None:
      start, temp = self.cool_from
      fraction = min(1.0, (now - start) / self.cool_seconds)
      if self.printer_state in ("FINISHED", "IDLE", "READY", "STOPPED"):
        self.bed_temperature = round(
          temp - (temp - AMBIENT_C) * fraction, 1
        )

  def progress(self) -> float:
    if self.printer_state == "FINISHED":
      return 100.0
    if self.print_seconds and self.started_at is not None:
      if self.printer_state in RUNNING:
        return round(
          min(99.9, 100.0 * self._elapsed() / self.print_seconds), 1
        )
    return 42.0

  def update(self, data: dict) -> dict:
    """Manual override: the live keys and POST /mock/state use this."""
    if set(data) - {"state", "temp_bed", "job_id", "failure"}:
      raise HttpError(400, "invalid_mock_state", "Unknown mock field")
    if "state" in data and data["state"] not in STATES:
      raise HttpError(400, "invalid_mock_state", "Unknown printer state")
    for key in ("temp_bed", "job_id"):
      value = data.get(key)
      if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value != value
      ):
        raise HttpError(400, "invalid_mock_state", f"Invalid {key}")
    if data.get("failure") not in (None, 401, 404, 409, 500):
      raise HttpError(400, "invalid_mock_state", "Invalid failure code")
    with self.lock:
      self._advance()
      if "state" in data:
        self._set_state(data["state"])
        if data["state"] == "FINISHED" and "temp_bed" not in data:
          self.cool_from = (self.clock(), self.bed_temperature or PRINT_BED_C)
      if "temp_bed" in data:
        self.bed_temperature = data["temp_bed"]
        self.cool_from = None  # an explicit temperature stops the auto-cool
        self.log(f"bed set to {data['temp_bed']}")
      if "job_id" in data:
        self.job_id = data["job_id"]
      if "failure" in data:
        self.failure = data["failure"]
        self.log(f"failure injection: {data['failure']}")
      return self._status()

  # -- files and jobs ------------------------------------------------------

  @staticmethod
  def valid_path(path: str) -> bool:
    parts = path.split("/")
    return (
      all(part not in ("", ".", "..") for part in parts)
      and JOB_FILE_NAME.fullmatch(parts[-1]) is not None
      and all(re.fullmatch(r"[A-Za-z0-9._ +()-]{1,120}", p) for p in parts)
    )

  def store(
    self, storage: str, path: str, data: bytes, overwrite: bool, start: bool
  ) -> None:
    """PUT /api/v1/files/{storage}/{path}: 409 on existing file or busy."""
    if not self.valid_path(path):
      raise HttpError(
        400, "invalid_name", "Expected a .gcode, .bgcode or .gco file path"
      )
    key = f"{storage}/{path}"
    with self.lock:
      self._advance()
      if key in self.files and not overwrite:
        raise HttpError(409, "conflict", "File already exists")
      if start and self.printer_state in RUNNING:
        raise HttpError(409, "conflict", "A job is already running")
      self.files[key] = (data, int(time.time()))
      self.log(f"stored {key} ({len(data)} bytes)")
      if start:
        self._begin(key, data)

  def start_stored(self, storage: str, path: str) -> None:
    key = f"{storage}/{path}"
    with self.lock:
      self._advance()
      if key not in self.files:
        raise HttpError(404, "not_found", "No such file")
      if self.printer_state in RUNNING:
        raise HttpError(409, "conflict", "A job is already running")
      self._begin(key, self.files[key][0])

  def _begin(self, key: str, data: bytes) -> None:
    self.gcode, self.gcode_key = data, key
    self.gcode_name = key.split("/", 1)[1]
    if self.job_id is not None:
      self.job_id += 1
    else:
      self.job_id = self.first_job_id or 43
    self._set_state("PRINTING")
    self.bed_temperature = PRINT_BED_C
    self.cool_from = None
    self.paused_at = None
    self.started_at = self.clock()
    self.log(f"job {self.job_id} started: {self.gcode_name}")

  def start_job(self, name: str, data: bytes) -> dict:
    """Test shortcut: store (overwriting) and start, no 409 checks."""
    if not self.valid_path(name):
      raise HttpError(400, "invalid_name", "Expected a G-code file name")
    with self.lock:
      key = f"local/{name}"
      self.files[key] = (data, int(time.time()))
      self._begin(key, data)
      return self._status()

  def job_file(self) -> dict:
    name = self.gcode_name
    storage = self.gcode_key.split("/", 1)[0]
    short = name.rsplit("/", 1)[-1]
    file = {
      "name": short,
      "display_name": short,
      "path": f"/{storage}",
      "m_timestamp": self.files.get(self.gcode_key, (b"", int(time.time())))[
        1
      ],
    }
    if self.gcode is not None:
      file["size"] = len(self.gcode)
      file["refs"] = {
        "download": f"/api/files/{storage}/{urllib.parse.quote(name)}/raw"
      }
    return file

  def _status(self) -> dict:
    self._advance()
    printer = {"state": self.printer_state, "temp_nozzle": AMBIENT_C + 1}
    if self.bed_temperature is not None:
      printer["temp_bed"] = self.bed_temperature
    result = {"printer": printer}
    if self.job_id is not None:
      result["job"] = {"id": self.job_id, "progress": self.progress()}
    return result

  def job(self) -> dict | None:
    self._advance()
    if self.job_id is None or self.printer_state in (
      "IDLE",
      "BUSY",
      "READY",
      "ATTENTION",
    ):
      return None
    finished = self.printer_state == "FINISHED"
    elapsed = int(self._elapsed()) if self.started_at is not None else 526
    remaining = (
      0
      if finished
      else max(0, int(self.print_seconds - elapsed))
      if self.print_seconds
      else 520
    )
    return {
      "id": self.job_id,
      "state": self.printer_state,
      "progress": self.progress(),
      "time_printing": elapsed,
      "time_remaining": remaining,
      "file": self.job_file(),
    }

  # -- auth ----------------------------------------------------------------

  def authenticate(self, handler) -> bool:
    header = handler.headers.get("Authorization", "")
    if not header.startswith("Digest "):
      return False
    try:
      fields = urllib.request.parse_keqv_list(
        urllib.request.parse_http_list(header[7:])
      )
    except ValueError:
      return False
    if (
      fields.get("username") != self.username
      or fields.get("realm") != REALM
      or fields.get("nonce") != self.nonce
      or fields.get("uri") != handler.path
      or fields.get("qop") != "auth"
      or not re.fullmatch(r"[0-9a-fA-F]{8}", fields.get("nc", ""))
      or not fields.get("cnonce")
    ):
      return False

    def md5(text: str) -> str:
      return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()

    ha1 = md5(f"{self.username}:{REALM}:{self.password}")
    ha2 = md5(f"{handler.command}:{handler.path}")
    expected = md5(
      f"{ha1}:{self.nonce}:{fields['nc']}:{fields['cnonce']}:auth:{ha2}"
    )
    return hmac.compare_digest(expected, fields.get("response", ""))


def make_mock_server(
  port: int = 0,
  host: str = "127.0.0.1",
  gcode_path: str | None = None,
  **options,
) -> tuple[http.server.ThreadingHTTPServer, MockPrinter]:
  printer = MockPrinter(**options)
  if gcode_path:
    with open(gcode_path, "rb") as stream:
      printer.gcode = stream.read()
    printer.gcode_name = os.path.basename(gcode_path)
    printer.gcode_key = f"local/{printer.gcode_name}"

  class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
      super().setup()
      self.connection.settimeout(10)

    def log_message(self, *args):  # Errors go to the events list instead.
      pass

    def log_request(self, code="-", size="-"):
      if self.path.startswith("/mock/"):
        return
      printer.log(f"{self.command} {self.path.split('?')[0]} -> {code}")

    def handle_request(self):
      try:
        if not printer.authenticate(self):
          # Read the body first so an upload sent with its first request
          # gets the 401, not a connection reset.
          try:
            length = int(self.headers.get("Content-Length", "0"))
          except ValueError:
            length = 0
          if 0 < length <= MAX_UPLOAD_BYTES:
            self.rfile.read(length)
          self.send_response(401)
          self.send_header(
            "WWW-Authenticate",
            f'Digest realm="{REALM}", nonce="{printer.nonce}", '
            'algorithm=MD5, qop="auth"',
          )
          self.send_header("Content-Length", "0")
          self.end_headers()
          return
        path = self.path.split("?")[0]
        if self.command == "POST" and path == "/mock/state":
          data = json.loads(read_body(self, 8192))
          if not isinstance(data, dict):
            raise HttpError(400, "invalid_body", "Expected JSON object")
          send_json(self, 200, printer.update(data))
          return
        target = FILE_PATH.fullmatch(path)
        if target:
          self.files_route(target[1], urllib.parse.unquote(target[2]))
          return
        with printer.lock:
          if printer.failure:
            send_json(self, printer.failure, {"title": "Injected failure"})
            return
          self.read_route(path)
      except HttpError as exc:
        send_json(
          self,
          exc.status,
          {"code": exc.code, "title": exc.code.replace("_", " "), "text": exc.text},
        )
      except (ValueError, UnicodeDecodeError):
        send_json(
          self, 400, {"code": "invalid_body", "title": "invalid body", "text": ""}
        )

    def files_route(self, storage: str, path: str):
      if self.command == "PUT":
        printer.store(
          storage,
          path,
          read_body(self),
          self.headers.get("Overwrite") == "?1",
          self.headers.get("Print-After-Upload") == "?1",
        )
        self.send_response(201)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return
      if self.command == "POST":
        printer.start_stored(storage, path)
        self.no_content()
        return
      with printer.lock:
        stored = printer.files.get(f"{storage}/{path}")
        if stored is None:
          raise HttpError(404, "not_found", "No such file")
        if self.command == "HEAD":
          self.send_response(200)
          self.send_header("Read-Only", "false")
          self.send_header(
            "Currently-Printed",
            str(
              printer.printer_state in RUNNING and printer.gcode_name == path
            ).lower(),
          )
          self.send_header("Content-Length", "0")
          self.end_headers()
          return
        if self.command == "GET":
          name = path.rsplit("/", 1)[-1]
          send_json(
            self,
            200,
            {
              "name": name,
              "display_name": name,
              "read_only": False,
              "size": len(stored[0]),
              "type": "PRINT_FILE",
              "m_timestamp": stored[1],
              "refs": {
                "download": "/api/files/%s/%s/raw"
                % (storage, urllib.parse.quote(path))
              },
            },
          )
          return
      raise HttpError(405, "method_not_allowed", "Unsupported method")

    def read_route(self, path: str):
      if self.command == "GET" and path == "/api/v1/status":
        send_json(self, 200, printer._status())
        return
      if self.command == "GET" and path == "/api/v1/job":
        job = printer.job()
        if job is None:
          self.no_content()
        else:
          send_json(self, 200, job)
        return
      download = DOWNLOAD_PATH.fullmatch(path)
      if self.command == "GET" and download:
        name = urllib.parse.unquote(download[2])
        stored = printer.files.get(f"{download[1]}/{name}")
        if stored is None and name == printer.gcode_name and printer.gcode:
          stored = (printer.gcode, 0)
        if stored is None:
          raise HttpError(404, "not_found", "No such file")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(stored[0])))
        self.end_headers()
        self.wfile.write(stored[0])
        return
      if self.command == "GET" and path == "/api/version":
        send_json(
          self,
          200,
          {
            "api": "1.0.0",
            "version": "0.7.0",
            "printer": "mock",
            "text": "PrusaLink mock",
            "firmware": "0.0.0-mock",
            "sdk": "0.7.0",
            "capabilities": {"upload-by-put": True},
          },
        )
        return
      if self.command == "GET" and path == "/api/v1/info":
        send_json(
          self,
          200,
          {
            "name": "mock-printer",
            "nozzle_diameter": 0.4,
            "serial": "MOCK0000",
            "hostname": socket.gethostname(),
          },
        )
        return
      if self.command == "GET" and path == "/api/v1/storage":
        send_json(
          self,
          200,
          {
            "storage_list": [
              {
                "name": "PrusaLink gcodes",
                "type": "LOCAL",
                "path": "/local",
                "available": True,
                "read_only": False,
                "print_files": sum(len(d) for d, _ in printer.files.values()),
              }
            ]
          },
        )
        return
      match = re.fullmatch(
        r"/api/v1/job/([0-9]+)(/pause|/resume|/continue)?", path
      )
      if not match or int(match[1]) != printer.job_id:
        raise HttpError(404, "not_found", "Unknown mock job or route")
      transitions = {
        ("PUT", "/pause"): ("PRINTING", "PAUSED"),
        ("PUT", "/resume"): ("PAUSED", "PRINTING"),
        ("PUT", "/continue"): ("PAUSED", "PRINTING"),
      }
      if self.command == "DELETE" and not match[2]:
        if printer.printer_state not in RUNNING:
          raise HttpError(409, "conflict", "Job cannot be stopped")
        printer._set_state("STOPPED")
      elif (self.command, match[2]) in transitions:
        before, after = transitions[(self.command, match[2])]
        if printer.printer_state != before:
          raise HttpError(409, "conflict", "Invalid job state")
        printer._set_state(after)
      else:
        raise HttpError(405, "method_not_allowed", "Unsupported method")
      self.no_content()

    def no_content(self):
      self.send_response(204)
      self.send_header("Content-Length", "0")
      self.end_headers()

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = handle_request

  return http.server.ThreadingHTTPServer((host, port), Handler), printer


# -- live screen ---------------------------------------------------------

_COLORS = {
  "PRINTING": "\x1b[1;34m",
  "PAUSED": "\x1b[1;33m",
  "FINISHED": "\x1b[1;32m",
  "STOPPED": "\x1b[1;31m",
  "ERROR": "\x1b[1;31m",
  "ATTENTION": "\x1b[1;33m",
}
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"


def _bar(fraction: float, width: int = 30) -> str:
  filled = int(round(max(0.0, min(1.0, fraction)) * width))
  return "█" * filled + "░" * (width - filled)


def lan_addresses() -> list[str]:
  found = []
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
      probe.connect(("10.255.255.255", 1))  # no packet is sent
      found.append(probe.getsockname()[0])
  except OSError:
    pass
  return found


def render(printer: MockPrinter, port: int) -> str:
  width = max(60, min(shutil.get_terminal_size().columns, 100))
  with printer.lock:
    status = printer._status()
    job = printer.job()
    state = printer.printer_state
    bed = printer.bed_temperature
    files = list(printer.files)
    events = list(printer.events)[-8:]
    failure = printer.failure
  color = _COLORS.get(state, "\x1b[1m")
  out = []
  out.append("\x1b[1m MOCK PRUSALINK PRINTER\x1b[0m   (test double, not a printer)")
  out.append("─" * width)
  addresses = ", ".join(f"http://{a}:{port}" for a in lan_addresses())
  out.append(f" listening   http://localhost:{port}   {addresses}")
  out.append(
    f" login       {printer.username} / {printer.password}   (HTTP Digest)"
  )
  out.append("")
  out.append(f" state       {color}{state:<10}{_RESET}")
  progress = status.get("job", {}).get("progress", 0.0)
  out.append(f" progress    {_bar(progress / 100)} {progress:5.1f}%")
  if bed is None:
    out.append(" bed         unavailable")
  else:
    out.append(
      f" bed         {_bar((bed - AMBIENT_C) / (PRINT_BED_C - AMBIENT_C))}"
      f" {bed:5.1f} °C"
      + (
        "   <- ready to unload (<30)"
        if state == "FINISHED" and bed < 30
        else ""
      )
    )
  if job:
    f = job["file"]
    out.append(
      f" job         id {job['id']}   {f['name']}   "
      f"{f.get('size', 0) / 1024:.0f} KiB"
    )
    out.append(
      f" time        printing {job['time_printing']}s   "
      f"remaining {job['time_remaining']}s"
    )
  else:
    out.append(" job         none")
  out.append(f" stored      {len(files)} file(s): {', '.join(files[-3:])}")
  if failure:
    out.append(f" \x1b[1;31mFAILURE INJECTED: every request answers {failure}{_RESET}")
  out.append("")
  out.append(f" {_DIM}recent requests and events{_RESET}")
  for stamp, text in events:
    out.append(f"  {_DIM}{stamp}{_RESET}  {text[: width - 14]}")
  out.append("")
  out.append("─" * width)
  out.append(
    " keys:  f finish   c cool bed   i idle   p pause/resume   s stop   "
    "e error   q quit"
  )
  return "\n".join(line + "\x1b[K" for line in out)


def handle_key(printer: MockPrinter, key: str) -> bool:
  """Applies a key press. Returns False to quit."""
  try:
    if key == "q":
      return False
    if key == "f":
      printer.update({"state": "FINISHED"})
    elif key == "c":
      printer.update({"temp_bed": AMBIENT_C})
    elif key == "i":
      printer.update({"state": "IDLE"})
    elif key == "s":
      printer.update({"state": "STOPPED"})
    elif key == "e":
      printer.update({"state": "ERROR"})
    elif key == "p":
      with printer.lock:
        current = printer.printer_state
      printer.update(
        {"state": "PAUSED" if current == "PRINTING" else "PRINTING"}
      )
  except HttpError:
    pass
  return True


def run_ui(printer: MockPrinter, port: int, stop: threading.Event) -> None:
  interactive = sys.stdin.isatty() and sys.stdout.isatty()
  if not interactive:
    last = None
    while not stop.wait(1.0):
      line = (
        f"{printer.printer_state} job={printer.job_id} "
        f"bed={printer.bed_temperature}"
      )
      if line != last:
        print(time.strftime("%H:%M:%S"), line, flush=True)
        last = line
    return
  import termios
  import tty

  fd = sys.stdin.fileno()
  saved = termios.tcgetattr(fd)
  sys.stdout.write("\x1b[?1049h\x1b[?25l")  # alternate screen, hide cursor
  try:
    tty.setcbreak(fd)
    while not stop.is_set():
      sys.stdout.write("\x1b[H" + render(printer, port) + "\x1b[J")
      sys.stdout.flush()
      ready, _, _ = select.select([sys.stdin], [], [], 0.5)
      if ready and not handle_key(printer, sys.stdin.read(1).lower()):
        stop.set()
  finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    sys.stdout.write("\x1b[?25h\x1b[?1049l")
    sys.stdout.flush()


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
  parser.add_argument("--host", default="0.0.0.0")
  parser.add_argument("--port", type=int, default=18081)
  parser.add_argument("--username", default=MOCK_USERNAME)
  parser.add_argument("--password", default=MOCK_PASSWORD)
  parser.add_argument(
    "--print-seconds",
    type=float,
    default=60,
    help="how long a job 'prints' before FINISHED; 0 = change state by key",
  )
  parser.add_argument(
    "--cool-seconds",
    type=float,
    default=60,
    help="how long the bed takes to cool from 60 to 24 °C after FINISHED",
  )
  parser.add_argument(
    "--gcode", help="a file the starting job (id 42) offers for download"
  )
  args = parser.parse_args()
  httpd, printer = make_mock_server(
    args.port,
    args.host,
    args.gcode,
    username=args.username,
    password=args.password,
    print_seconds=args.print_seconds,
    cool_seconds=args.cool_seconds,
    initial_state="IDLE",
    initial_job_id=None,
    first_job_id=1,
  )
  stop = threading.Event()
  threading.Thread(target=httpd.serve_forever, daemon=True).start()
  printer.log(f"listening on {args.host}:{httpd.server_port}")
  try:
    run_ui(printer, httpd.server_port, stop)
  except KeyboardInterrupt:
    pass
  finally:
    httpd.shutdown()
    httpd.server_close()


if __name__ == "__main__":
  main()
