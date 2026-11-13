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

"""HTTP and gRPC interfaces sharing the same PrusaLink client."""

import http.server
import json
import logging
import re
from concurrent import futures

import grpc
from google.protobuf import empty_pb2, json_format

from services.prusalink import client, jobwatch
from services.prusalink import prusalink_pb2 as pb
from services.prusalink import prusalink_pb2_grpc as rpc

_GRPC_ERRORS = {
  400: grpc.StatusCode.INVALID_ARGUMENT,
  403: grpc.StatusCode.PERMISSION_DENIED,
  404: grpc.StatusCode.NOT_FOUND,
  409: grpc.StatusCode.FAILED_PRECONDITION,
  502: grpc.StatusCode.UNAVAILABLE,
  504: grpc.StatusCode.DEADLINE_EXCEEDED,
}


def send_json(
  handler: http.server.BaseHTTPRequestHandler, status: int, data: dict
):
  body = json.dumps(data, allow_nan=False).encode()
  handler.send_response(status)
  handler.send_header("Content-Type", "application/json")
  handler.send_header("Content-Length", str(len(body)))
  handler.end_headers()
  handler.wfile.write(body)


def _need_watcher(watcher: jobwatch.JobWatcher | None) -> jobwatch.JobWatcher:
  if watcher is None:
    raise client.ServiceError(
      409, "job_pull_disabled", "The service does not pull jobs"
    )
  return watcher


class PrusaLinkServicer(rpc.PrusaLinkServiceServicer):
  def __init__(
    self,
    printer: client.PrusaLinkClient,
    commands_enabled: bool,
    watcher: jobwatch.JobWatcher | None = None,
  ):
    self.printer = printer
    self.commands_enabled = commands_enabled
    self.watcher = watcher

  def _invoke(self, context, operation):
    try:
      return operation()
    except client.ServiceError as exc:
      logging.warning("PrusaLink %s: %s", exc.code, exc)
      context.abort(_GRPC_ERRORS[exc.status], f"{exc.code}: {exc}")

  def GetStatus(self, request, context):
    return self._invoke(context, self.printer.get_status)

  def GetJob(self, request, context):
    return self._invoke(context, self.printer.get_job)

  def GetModelStatus(self, request, context):
    return self._invoke(
      context,
      lambda: _need_watcher(self.watcher).status(
        request.job_id if request.HasField("job_id") else None
      ),
    )

  def ListModels(self, request, context):
    return self._invoke(context, lambda: _need_watcher(self.watcher).list())

  def CommandJob(self, request, context):
    def command():
      self.printer.command_job(request, self.commands_enabled)
      return empty_pb2.Empty()

    return self._invoke(context, command)


def make_grpc_server(
  printer: client.PrusaLinkClient,
  enabled: bool,
  host: str,
  port: int,
  watcher: jobwatch.JobWatcher | None = None,
) -> tuple[grpc.Server, int]:
  server = grpc.server(
    futures.ThreadPoolExecutor(max_workers=4),
    options=(("grpc.so_reuseport", 0),),
  )
  rpc.add_PrusaLinkServiceServicer_to_server(
    PrusaLinkServicer(printer, enabled, watcher), server
  )
  bound = server.add_insecure_port(f"{host}:{port}")
  if not bound or (port and bound != port):
    raise RuntimeError("Could not bind gRPC listener")
  return server, bound


def make_http_server(
  printer: client.PrusaLinkClient,
  enabled: bool,
  host: str,
  port: int,
  path_prefix: str = "",
  watcher: jobwatch.JobWatcher | None = None,
  info=None,
) -> http.server.ThreadingHTTPServer:
  prefix = path_prefix.rstrip("/")

  class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
      super().setup()
      self.connection.settimeout(5)

    def handle_request(self):
      try:
        # Support both preserved and stripped ingress prefixes. Matching is
        # anchored so an unrelated URL cannot become an API endpoint.
        path = self.path
        if prefix and path.startswith(prefix + "/"):
          path = path[len(prefix) :]
        if self.command == "GET" and path == "/healthz":
          send_json(
            self,
            200,
            {
              "status": "ok",
              "job_commands_enabled": enabled,
              "job_pull_enabled": watcher is not None,
              **(info() if callable(info) else info or {}),
            },
          )
          return
        if self.command == "GET" and path == "/v1/model":
          self.send_proto(_need_watcher(watcher).status())
          return
        if self.command == "GET" and path == "/v1/jobs":
          self.send_proto(_need_watcher(watcher).list())
          return
        model = re.fullmatch(r"/v1/jobs/([0-9]{1,18})/model", path)
        if self.command == "GET" and model:
          self.send_proto(_need_watcher(watcher).status(int(model[1])))
          return
        model_file = re.fullmatch(
          r"/v1/jobs/([0-9]{1,18})/"
          r"(model\.stl|part\.stl|supports\.stl|by_type/[A-Za-z0-9_]+\.stl)",
          path,
        )
        if self.command == "GET" and model_file:
          file = _need_watcher(watcher).model_file(
            int(model_file[1]), model_file[2]
          )
          self.send_response(200)
          self.send_header("Content-Type", "model/stl")
          self.send_header("Content-Length", str(file.stat().st_size))
          self.end_headers()
          with open(file, "rb") as stream:
            while chunk := stream.read(1 << 16):
              self.wfile.write(chunk)
          return
        if self.command == "GET" and path in ("/v1/status", "/v1/job"):
          result = (
            printer.get_status() if path == "/v1/status" else printer.get_job()
          )
          self.send_proto(result)
          return
        match = re.fullmatch(
          r"/v1/jobs/([0-9]+)/(pause|resume|stop|continue)", path
        )
        if self.command == "POST" and match:
          if len(match[1]) > 19:
            raise client.ServiceError(
              400, "invalid_command", "job_id too large"
            )
          job_id = int(match[1])
          if job_id > 2**63 - 1:
            raise client.ServiceError(
              400, "invalid_command", "job_id too large"
            )
          printer.command_job(
            pb.JobCommand(
              job_id=job_id, action=pb.JobCommand.Action.Value(match[2].upper())
            ),
            enabled,
          )
          self.send_response(204)
          self.send_header("Content-Length", "0")
          self.end_headers()
          return
        raise client.ServiceError(404, "not_found", "Unknown route or method")
      except client.ServiceError as exc:
        self.log_error("%s: %s", exc.code, exc)
        send_json(
          self, exc.status, {"error": {"code": exc.code, "message": str(exc)}}
        )

    def send_proto(self, message):
      send_json(
        self,
        200,
        json_format.MessageToDict(
          message,
          preserving_proto_field_name=True,
          always_print_fields_with_no_presence=True,
        ),
      )

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request

  return http.server.ThreadingHTTPServer((host, port), Handler)
