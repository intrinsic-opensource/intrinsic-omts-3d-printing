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

"""Run actual printer skills through the executive, without robot motion."""

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


def run(args: argparse.Namespace) -> None:
  if not math.isfinite(args.interval) or args.interval <= 0:
    raise ValueError("--interval must be positive and finite")
  solution = deployments.connect(address=args.address)
  if args.printer not in dir(solution.resources):
    raise ValueError(f"Printer resource {args.printer!r} is not deployed")
  executive = solution.executive
  count = 0
  while True:
    # Never replace another application's active operation just to run a demo.
    if executive.has_operation and not executive.operation.done:
      raise RuntimeError(
        "Executive already has an active operation; stop it explicitly first"
      )
    skill_class = (
      solution.skills.ai.omts.wait_for_printer_ready
      if args.mode == "wait"
      else solution.skills.ai.omts.read_printer_status
    )
    kwargs = {
      "printer": solution.resources[args.printer],
      "expected_job_id": args.job_id,
      "_with_recommended_config": False,
    }
    if args.mode == "wait":
      kwargs["timeout_seconds"] = args.timeout
      kwargs["poll_interval_seconds"] = args.interval
    action = skill_class(**kwargs)
    tree = bt.BehaviorTree(
      name="Printer telemetry demo (no motion)",
      root=bt.Task(action=action, name=args.mode),
    )
    operation_name = None
    try:
      executive.run_async(tree, silence_outputs=True)
      operation_name = executive.operation.name
      last_state = None
      while True:
        operation = executive.operation
        if operation.name != operation_name:
          raise RuntimeError(
            "The demo operation was replaced by another client"
          )
        state = operation.metadata.State.Name(
          operation.metadata.operation_state
        )
        if state != last_state:
          print(
            json.dumps({"skill": args.mode, "execution_state": state}),
            flush=True,
          )
          last_state = state
        if operation.done:
          if operation.proto.HasField("error"):
            raise RuntimeError(json_format.MessageToJson(operation.proto.error))
          break
        time.sleep(0.25)
      result = operation.blackboard.get_value(action.result)
      print(
        json_format.MessageToJson(
          result,
          preserving_proto_field_name=True,
          always_print_fields_with_no_presence=True,
        ),
        flush=True,
      )
    except KeyboardInterrupt:
      if executive.has_operation:
        operation = executive.operation
        if operation.name == operation_name and not operation.done:
          executive.cancel()
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
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument("--printer", default="prusalink")
  parser.add_argument(
    "--mode", choices=("read", "watch", "wait"), default="read"
  )
  parser.add_argument("--job-id", type=int, default=42)
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
