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
import logging
import re
from concurrent import futures

import grpc
from google.protobuf import empty_pb2, json_format

from services.prusalink import client, mock
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


class PrusaLinkServicer(rpc.PrusaLinkServiceServicer):
  def __init__(self, printer: client.PrusaLinkClient, commands_enabled: bool):
    self.printer = printer
    self.commands_enabled = commands_enabled

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

  def CommandJob(self, request, context):
    def command():
      self.printer.command_job(request, self.commands_enabled)
      return empty_pb2.Empty()

    return self._invoke(context, command)


def make_grpc_server(
  printer: client.PrusaLinkClient, enabled: bool, host: str, port: int
) -> tuple[grpc.Server, int]:
  server = grpc.server(
    futures.ThreadPoolExecutor(max_workers=4),
    options=(("grpc.so_reuseport", 0),),
  )
  rpc.add_PrusaLinkServiceServicer_to_server(
    PrusaLinkServicer(printer, enabled), server
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
  simulator: mock.MockPrinter | None = None,
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
          mock.send_json(
            self,
            200,
            {
              "status": "ok",
              "mode": "sim" if simulator is not None else "real",
              "job_commands_enabled": enabled,
            },
          )
          return
        if self.command == "POST" and path == "/simulation/state":
          if simulator is None:
            raise client.ServiceError(
              404, "not_found", "Simulation controls unavailable"
            )
          mock.send_json(self, 200, simulator.update(mock.read_json(self)))
          return
        if self.command == "GET" and path in ("/v1/status", "/v1/job"):
          result = (
            printer.get_status() if path == "/v1/status" else printer.get_job()
          )
          mock.send_json(
            self,
            200,
            json_format.MessageToDict(
              result,
              preserving_proto_field_name=True,
              always_print_fields_with_no_presence=True,
            ),
          )
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
        mock.send_json(
          self, exc.status, {"error": {"code": exc.code, "message": str(exc)}}
        )

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request

  return http.server.ThreadingHTTPServer((host, port), Handler)
