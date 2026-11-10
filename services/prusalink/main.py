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

"""Intrinsic RuntimeContext entrypoint, with explicit local simulation mode."""

import argparse
import logging
import os
import signal
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

from google.protobuf import any_pb2, message
from intrinsic.resources.proto import runtime_context_pb2

from services.prusalink import client, mock, server
from services.prusalink import prusalink_pb2 as pb


def load_runtime(
  path: str, mode: str
) -> tuple[pb.PrusaLinkConfig, int, int, str]:
  context = runtime_context_pb2.RuntimeContext.FromString(
    Path(path).read_bytes()
  )
  config = pb.PrusaLinkConfig()
  if not context.config.Unpack(config):
    raise ValueError(
      "RuntimeContext config is not omts.prusalink.PrusaLinkConfig"
    )
  expected = (
    runtime_context_pb2.RuntimeContext.PHYSICS_SIM
    if mode == "sim"
    else runtime_context_pb2.RuntimeContext.REALITY
  )
  if context.level != expected:
    raise ValueError("RuntimeContext level disagrees with --mode")
  if not 1 <= context.port <= 65535 or not 1 <= context.http_port <= 65535:
    raise ValueError("RuntimeContext must allocate valid gRPC and HTTP ports")
  return config, context.port, context.http_port, context.http_path_prefix


def run(args: argparse.Namespace) -> None:
  if args.runtime_context:
    if args.write_config or args.printer_url or args.enable_job_commands:
      raise ValueError(
        "RuntimeContext cannot be combined with local config flags"
      )
    config, grpc_port, http_port, prefix = load_runtime(
      args.runtime_context, args.mode
    )
    host = "0.0.0.0"
  else:
    config = pb.PrusaLinkConfig(
      printer_url=args.printer_url,
      username=args.username,
      password_env=args.password_env,
      timeout_seconds=args.timeout,
      enable_job_commands=args.enable_job_commands,
    )
    grpc_port, http_port, prefix, host = (
      args.grpc_port,
      args.http_port,
      "",
      args.host,
    )
  if args.write_config:
    envelope = any_pb2.Any()
    envelope.Pack(config)
    Path(args.write_config).write_bytes(envelope.SerializeToString())
    logging.info("Wrote binary service configuration to %s", args.write_config)
    return
  stop = threading.Event()
  for signum in (signal.SIGTERM, signal.SIGINT):
    signal.signal(signum, lambda signum, frame: stop.set())
  with ExitStack() as cleanup:
    simulator = None
    if args.mode == "sim":
      if config.printer_url:
        raise ValueError("Simulation cannot target an external printer_url")
      mock_server, simulator = mock.make_mock_server(args.mock_port)
      cleanup.callback(mock_server.server_close)
      mock_thread = threading.Thread(
        target=mock_server.serve_forever, daemon=True
      )
      mock_thread.start()
      cleanup.callback(mock_thread.join)
      cleanup.callback(mock_server.shutdown)
      url = f"http://127.0.0.1:{mock_server.server_port}"
      username, password = mock.MOCK_USERNAME, mock.MOCK_PASSWORD
      logging.info("Separate mock PrusaLink HTTP listener at %s", url)
    else:
      url, username = config.printer_url, config.username
      password = os.environ.get(config.password_env, "")
    printer = client.PrusaLinkClient(
      url, username, password, config.timeout_seconds
    )
    httpd = server.make_http_server(
      printer, config.enable_job_commands, host, http_port, prefix, simulator
    )
    cleanup.callback(httpd.server_close)
    grpcd, bound = server.make_grpc_server(
      printer, config.enable_job_commands, host, grpc_port
    )
    grpcd.start()
    cleanup.callback(lambda: grpcd.stop(grace=2).wait())
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    cleanup.callback(http_thread.join)
    cleanup.callback(httpd.shutdown)
    logging.info(
      "PrusaLink service HTTP %s:%s; gRPC %s:%s",
      host,
      httpd.server_port,
      host,
      bound,
    )
    stop.wait()


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--mode", choices=("sim", "real"), default="sim")
  parser.add_argument(
    "--runtime-context",
    default=os.environ.get("INTRINSIC_RUNTIME_CONFIG"),
    help="Required in Intrinsic; defaults to /etc/intrinsic/runtime_config.pb when deployed",
  )
  parser.add_argument("--host", default="127.0.0.1")
  parser.add_argument("--http-port", type=int, default=18080)
  parser.add_argument("--grpc-port", type=int, default=18082)
  parser.add_argument("--mock-port", type=int, default=18081)
  parser.add_argument("--printer-url", default="")
  parser.add_argument("--username", default="")
  parser.add_argument("--password-env", default="PRUSALINK_PASSWORD")
  parser.add_argument("--timeout", type=float, default=5.0)
  parser.add_argument("--enable-job-commands", action="store_true")
  parser.add_argument(
    "--write-config", help="Write binary google.protobuf.Any and exit"
  )
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
  args = parser.parse_args()
  try:
    run(args)
  except (ValueError, OSError, RuntimeError, message.DecodeError) as exc:
    logging.error("PrusaLink startup failed: %s", exc)
    sys.exit(1)
  sys.exit(0)


if __name__ == "__main__":
  main()
