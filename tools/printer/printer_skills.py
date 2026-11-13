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

"""Run the printer skills through the executive, without robot motion.

Modes:
  read        one printer snapshot (ai.omts.read_printer_status)
  watch       the same, repeatedly
  wait        wait until the job is finished and cool (wait_for_printer_ready)
  model       one job-model snapshot (ai.omts.read_job_model)
  wait-model  wait until the STL of a job is built (wait_for_job_model)
  monitor     both read skills in one live screen, refreshed in place
"""

import argparse
import json
import logging
import math
import sys
import time

import grpc
from google.protobuf import json_format
from intrinsic.solutions import behavior_tree as bt
from intrinsic.solutions import deployments, execution

_MONITOR_COLORS = {
  "READY_TO_UNLOAD": "\x1b[1;32m",
  "MODEL_READY": "\x1b[1;32m",
  "WAITING_FOR_COOLING": "\x1b[1;33m",
  "DOWNLOADING": "\x1b[1;33m",
  "CONVERTING": "\x1b[1;33m",
  "WAITING_FOR_PRINT": "\x1b[1;34m",
  "PRINTER_BLOCKED": "\x1b[1;31m",
  "MODEL_FAILED": "\x1b[1;31m",
  "JOB_MISMATCH": "\x1b[1;31m",
}


def _skill(solution, mode: str):
  skills = solution.skills.ai.omts
  return {
    "read": skills.read_printer_status,
    "watch": skills.read_printer_status,
    "wait": skills.wait_for_printer_ready,
    "model": skills.read_job_model,
    "wait-model": skills.wait_for_job_model,
  }[mode]


def _kwargs(solution, args, mode: str) -> dict:
  kwargs = {
    "printer": solution.resources[args.printer],
    "_with_recommended_config": False,
  }
  if args.job_id is not None:
    kwargs["expected_job_id"] = args.job_id
  if mode == "wait-model" and args.after_job_id is not None:
    kwargs["after_job_id"] = args.after_job_id
  if mode in ("wait", "wait-model"):
    kwargs["timeout_seconds"] = args.timeout
    kwargs["poll_interval_seconds"] = args.interval
  return kwargs


def call(solution, mode: str, args, show_states: bool):
  """Runs one skill as an executive operation; returns its result proto."""
  executive = solution.executive
  # Never replace another application's active operation just to run a demo.
  if executive.has_operation and not executive.operation.done:
    raise RuntimeError(
      "Executive already has an active operation; stop it explicitly first"
    )
  action = _skill(solution, mode)(**_kwargs(solution, args, mode))
  tree = bt.BehaviorTree(
    name="Printer telemetry demo (no motion)",
    root=bt.Task(action=action, name=mode),
  )
  operation_name = None
  try:
    executive.run_async(tree, silence_outputs=True)
    operation_name = executive.operation.name
    last_state = None
    while True:
      operation = executive.operation
      if operation.name != operation_name:
        raise RuntimeError("The demo operation was replaced by another client")
      state = operation.metadata.State.Name(operation.metadata.operation_state)
      if show_states and state != last_state:
        print(json.dumps({"skill": mode, "execution_state": state}), flush=True)
        last_state = state
      if operation.done:
        if operation.proto.HasField("error"):
          raise RuntimeError(json_format.MessageToJson(operation.proto.error))
        break
      time.sleep(0.1)
    return operation.blackboard.get_value(action.result)
  except KeyboardInterrupt:
    if executive.has_operation:
      operation = executive.operation
      if operation.name == operation_name and not operation.done:
        executive.cancel()
    raise


def _json(result) -> str:
  return json_format.MessageToJson(
    result,
    preserving_proto_field_name=True,
    always_print_fields_with_no_presence=True,
  )


def _paint(name: str) -> str:
  return f"{_MONITOR_COLORS.get(name, chr(27) + '[1m')}{name}\x1b[0m"


def _screen(printer, model, args, error: str = "") -> str:
  from services.prusalink import prusalink_pb2 as service_pb
  from skills.printer import job_model_pb2, read_printer_status_pb2

  p = printer.printer_status
  m = model.model
  lines = [
    "\x1b[1m SKILLS MONITOR\x1b[0m   "
    f"{args.address}   expected job: {args.job_id if args.job_id is not None else 'any'}",
    "─" * 72,
    " \x1b[1mai.omts.read_printer_status\x1b[0m",
    "   decision          "
    + _paint(read_printer_status_pb2.PrinterReadiness.Decision.Name(printer.decision)),
    f"   ready_for_unload  {printer.ready_for_unload}",
    f"   printer           {service_pb.PrinterState.Name(p.state)}  "
    f"job {p.job_id if p.HasField('job_id') else '-'}  "
    + (
      f"bed {p.bed_temperature_c:.1f} C"
      if p.HasField("bed_temperature_c")
      else "bed n/a"
    )
    + (
      f"  progress {p.progress_percent:.0f}%"
      if p.HasField("progress_percent")
      else ""
    ),
    "",
    " \x1b[1mai.omts.read_job_model\x1b[0m",
    "   decision          "
    + _paint(job_model_pb2.JobModelReadiness.Decision.Name(model.decision)),
    f"   model_ready       {model.model_ready}",
    f"   file              {m.file_name or '-'}  (job {m.job_id if m.HasField('job_id') else '-'}"
    f"{', reused' if m.reused else ''})",
    f"   stl               {m.stl_path or '-'}",
  ]
  if m.error:
    lines.append(f"   \x1b[1;31merror\x1b[0m             {m.error}")
  if m.poll_error:
    lines.append(f"   printer unreachable: {m.poll_error}")
  if error:
    lines.append(f"\n \x1b[1;31m{error}\x1b[0m")
  lines += ["─" * 72, f" {time.strftime('%H:%M:%S')}   Ctrl-C to stop"]
  return "\n".join(line + "\x1b[K" for line in lines)


def monitor(solution, args) -> None:
  sys.stdout.write("\x1b[?1049h\x1b[?25l")
  try:
    while True:
      try:
        printer = call(solution, "read", args, False)
        model = call(solution, "model", args, False)
        text = _screen(printer, model, args)
      except KeyboardInterrupt:
        raise
      except (RuntimeError, grpc.RpcError, execution.ExecutionFailedError) as exc:
        text = f"\x1b[1m SKILLS MONITOR\x1b[0m\n\n \x1b[1;31m{str(exc)[:300]}\x1b[0m\x1b[K"
      sys.stdout.write("\x1b[H" + text + "\x1b[J")
      sys.stdout.flush()
      time.sleep(args.interval)
  except KeyboardInterrupt:
    pass
  finally:
    sys.stdout.write("\x1b[?25h\x1b[?1049l")
    sys.stdout.flush()


def run(args: argparse.Namespace) -> None:
  if not math.isfinite(args.interval) or args.interval <= 0:
    raise ValueError("--interval must be positive and finite")
  if args.mode == "wait" and args.job_id is None:
    raise ValueError("--mode=wait needs --job-id")
  solution = deployments.connect(address=args.address)
  if args.printer not in dir(solution.resources):
    raise ValueError(f"Printer resource {args.printer!r} is not deployed")
  if args.mode == "monitor":
    monitor(solution, args)
    return
  count = 0
  while True:
    try:
      result = call(solution, args.mode, args, True)
      print(_json(result), flush=True)
    except KeyboardInterrupt:
      print(
        "Printer demo cancelled; service and robot deployment remain running.",
        flush=True,
      )
      return
    count += 1
    if args.mode != "watch" or (args.samples and count >= args.samples):
      return
    try:
      time.sleep(args.interval)
    except KeyboardInterrupt:
      return


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument("--printer", default="prusalink")
  parser.add_argument(
    "--mode",
    choices=("read", "watch", "wait", "model", "wait-model", "monitor"),
    default="read",
  )
  parser.add_argument(
    "--job-id",
    type=int,
    default=None,
    help="expected job id; without it the skills accept whatever job the "
    "printer has (required for --mode=wait)",
  )
  parser.add_argument(
    "--after-job-id",
    type=int,
    default=None,
    help="wait-model: only accept a job newer than this id",
  )
  parser.add_argument("--timeout", type=float, default=120)
  parser.add_argument("--interval", type=float, default=1)
  parser.add_argument(
    "--samples", type=int, default=0, help="Watch samples; 0 means until Ctrl-C"
  )
  args = parser.parse_args()
  if args.samples < 0:
    parser.error("--samples must be nonnegative")
  try:
    run(args)
  except (
    ValueError,
    KeyError,
    RuntimeError,
    grpc.RpcError,
    execution.ExecutionFailedError,
  ) as exc:
    logging.error("Printer skill demo failed: %s", exc)
    sys.exit(1)


if __name__ == "__main__":
  main()
