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

"""PrusaLink service: printer telemetry, and a model of each print job.

The printer is the one given by --printer-url (or the solution's config). With
none given, the service looks for the disposable mock printer
(tools/mock_printer) on this machine and says which route it took.
"""

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

from services.prusalink import client, discovery, jobwatch, server
from services.prusalink import prusalink_pb2 as pb

MOCK_USERNAME = "maker"
MOCK_PASSWORD = "mock-only"
DEFAULT_STORAGE = "/tmp/prusalink"


def load_runtime(path: str) -> tuple[pb.PrusaLinkConfig, int, int, str]:
  context = runtime_context_pb2.RuntimeContext.FromString(
    Path(path).read_bytes()
  )
  config = pb.PrusaLinkConfig()
  if not context.config.Unpack(config):
    raise ValueError(
      "RuntimeContext config is not omts.prusalink.PrusaLinkConfig"
    )
  if not 1 <= context.port <= 65535 or not 1 <= context.http_port <= 65535:
    raise ValueError("RuntimeContext must allocate valid gRPC and HTTP ports")
  return config, context.port, context.http_port, context.http_path_prefix


def connect(
  config: pb.PrusaLinkConfig, mock_port: int, mock_hosts: list[str] | None
) -> tuple[client.PrusaLinkClient, dict]:
  """The client for the configured printer, or for the mock; and its route."""
  password = config.password or os.environ.get(config.password_env, "")
  timeout = config.timeout_seconds or 5.0
  if config.printer_url:
    if not config.username or not password:
      raise ValueError(
        "printer_url needs a username and a password "
        f"(--password, or ${config.password_env or 'PRUSALINK_PASSWORD'})"
      )
    logging.info(
      "ROUTE: printer %s as user %r (explicitly configured)",
      config.printer_url,
      config.username,
    )
    return (
      client.PrusaLinkClient(
        config.printer_url, config.username, password, timeout
      ),
      {"route": "configured", "printer_url": config.printer_url},
    )
  locator = discovery.MockLocator(mock_port, mock_hosts)
  logging.info(
    "ROUTE: no printer configured; looking for the mock printer at %s",
    ", ".join(locator.candidates()),
  )
  printer = client.PrusaLinkClient(
    "",
    config.username or MOCK_USERNAME,
    password or MOCK_PASSWORD,
    timeout,
    locator=locator,
  )
  return printer, {"route": "mock", "printer_url": None}


def run(args: argparse.Namespace) -> None:
  if args.runtime_context:
    if args.write_config or args.printer_url or args.enable_job_commands:
      raise ValueError(
        "RuntimeContext cannot be combined with local config flags"
      )
    config, grpc_port, http_port, prefix = load_runtime(args.runtime_context)
    host = "0.0.0.0"
  else:
    config = pb.PrusaLinkConfig(
      printer_url=args.printer_url,
      username=args.username,
      password=args.password,
      password_env=args.password_env,
      timeout_seconds=args.timeout,
      enable_job_commands=args.enable_job_commands,
      disable_job_pull=args.no_job_pull,
      storage_dir=args.storage_dir,
      poll_interval_seconds=args.poll_interval,
      max_download_bytes=int(args.max_download_mb * 1024 * 1024),
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
    printer, route = connect(config, args.mock_port, args.mock_host)
    watcher = None
    if not config.disable_job_pull:
      storage = Path(config.storage_dir or DEFAULT_STORAGE)
      watcher = jobwatch.JobWatcher(
        printer,
        storage,
        config.poll_interval_seconds or 2.0,
        config.max_download_bytes or client.MAX_DOWNLOAD_BYTES,
      )
      watcher.start()
      cleanup.callback(watcher.stop)
      logging.info("Pulling each new job's G-code into %s", watcher.root)
    else:
      logging.info("Job pull disabled: telemetry only")

    def info() -> dict:
      url = printer.url if printer.locator is None else printer.locator.found
      return {
        **route,
        "printer_url": url,
        "storage_dir": str(watcher.root) if watcher else None,
      }

    httpd = server.make_http_server(
      printer,
      config.enable_job_commands,
      host,
      http_port,
      prefix,
      watcher,
      info,
    )
    cleanup.callback(httpd.server_close)
    grpcd, bound = server.make_grpc_server(
      printer, config.enable_job_commands, host, grpc_port, watcher
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
  parser.add_argument(
    "--runtime-context",
    default=os.environ.get("INTRINSIC_RUNTIME_CONFIG"),
    help="Required in Intrinsic; defaults to /etc/intrinsic/runtime_config.pb when deployed",
  )
  parser.add_argument("--host", default="127.0.0.1")
  parser.add_argument("--http-port", type=int, default=18080)
  parser.add_argument("--grpc-port", type=int, default=18082)
  parser.add_argument(
    "--printer-url",
    default="",
    help="the printer's origin, e.g. http://192.168.1.50; empty: look for "
    "the mock printer",
  )
  parser.add_argument("--username", default="")
  parser.add_argument("--password", default="", help="or use --password-env")
  parser.add_argument("--password-env", default="PRUSALINK_PASSWORD")
  parser.add_argument("--timeout", type=float, default=5.0)
  parser.add_argument(
    "--mock-port",
    type=int,
    default=discovery.DEFAULT_MOCK_PORT,
    help="port of the mock printer to look for",
  )
  parser.add_argument(
    "--mock-host",
    action="append",
    help="host to look for the mock on (repeatable); default: loopback, the "
    "default gateway, host.docker.internal",
  )
  parser.add_argument("--storage-dir", default="")
  parser.add_argument("--poll-interval", type=float, default=2.0)
  parser.add_argument("--max-download-mb", type=float, default=256)
  parser.add_argument(
    "--no-job-pull",
    action="store_true",
    help="telemetry only: do not download jobs or build models",
  )
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
