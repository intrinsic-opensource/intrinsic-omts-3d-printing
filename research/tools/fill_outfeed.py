# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Fills the reBot cell's outfeed line, one part per spot, one operation each.

For each part, in order, on the running cell: puts it on the bed without moving
the other parts (`configure_cell --apply --keep_parked`, which also sets the
outfeed spots' frames and brings the simulation to the world), then runs
`omts_app`'s cycle for that part's spot. It stops at the first failure, because
a cycle that did not finish leaves its part on the bed or in the gripper and
the next one would be put on top of it. The layout and the number of spots are
cell_params.yaml's `outfeed` section.

configure_cell's offline checks take about 20 s, so they run here once, before
the first part, for each distinct part height, and not before every part: the
arm is idle only for the cluster calls between two cycles.

  bazel run //research/tools:fill_outfeed -- --reset
  bazel run //research/tools:fill_outfeed -- --outfeed_layout arc \
    --parts rebot_printed_part test_cuboid_40x40x40 test_benchy

To go on after a failure, once the part is back where it was (a reset with
`configure_cell --apply` parks everything), pass --first_spot with the parts
that are left.
"""

import argparse
import sys
import time
from pathlib import Path

from research.tools import cell, configure_cell
from src import main as omts_main
from src.core.config import load_app_config

# Parts that fill the line: at least MIN_PART_HEIGHT_M tall and found by the pose
# estimator on the bed (research/HANDOFF.md, sections 4a and 5e). The default
# part is first because it is on the bed after a reset.
DEFAULT_PARTS = (
  "rebot_printed_part",
  "test_cuboid_40x40x40",
  "test_benchy",
  "test_cuboid_80x20x40",
  "test_cylinder_30x60",
)
# The gripper body reaches the ground at the spot below this (a 22 mm part
# failed at A in simulation, section 4a).
MIN_PART_HEIGHT_M = 0.025


def _height(target: dict) -> float:
  """The part's height as it rests: its width when it lies."""
  size = target["size_m"]
  return size[0] if target.get("lying", False) else size[2]


def _check(parts, library, first_spot: int, count: int) -> list[str]:
  problems = []
  for part in parts:
    if part not in library:
      problems.append(f"{part} is not in targets.yaml: {sorted(library)}")
    elif _height(library[part]) < MIN_PART_HEIGHT_M:
      problems.append(
        f"{part} is {_height(library[part]) * 1000:.0f} mm tall, under "
        f"{MIN_PART_HEIGHT_M * 1000:.0f} mm: the gripper reaches the ground"
      )
  if len(set(parts)) != len(parts):
    problems.append("a part is listed twice")
  if first_spot < 0 or first_spot + len(parts) > count:
    problems.append(
      f"{len(parts)} part(s) from spot {first_spot} do not fit the line's "
      f"{count} spot(s)"
    )
  return problems


def _offline_checks(parts, library, layout: str, count: int, reset: bool):
  """configure_cell's offline checks, once for each distinct part height: the
  parts' and, after a reset, the default target's. Prints the failures and
  returns them."""
  params = cell.parameters()
  distance = params["printer_distance_m"]
  offset = tuple(params["camera_offset_m"])
  spots = configure_cell._outfeed_spots(
    configure_cell.outfeed_settings_for(params, layout, count)
  )
  names = list(parts) + ([params["target"]] if reset else [])
  heights = sorted({configure_cell.half_height_of(library[n]) for n in names})
  failed = []
  for half_height in heights:
    print(f"=== offline checks, part half height {half_height * 1000:.0f} mm")
    problems = configure_cell.check_cell(
      distance,
      offset,
      half_height,
      spots,
      params["outfeed"].get("transit_rotation_degrees"),
    )
    for problem in problems:
      print(f"  FAILS {problem}")
    failed += problems
  if not failed:
    print("  checks pass")
  return failed


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument(
    "--parts",
    nargs="+",
    default=list(DEFAULT_PARTS),
    help="the parts, in the order of the spots",
  )
  parser.add_argument("--first_spot", type=int, default=0)
  parser.add_argument(
    "--reset",
    action="store_true",
    help="first park every part and put the default part on the bed "
    "(clears the line)",
  )
  parser.add_argument("--outfeed_layout", choices=("line", "arc"), default=None)
  parser.add_argument("--outfeed_count", type=int, default=None)
  parser.add_argument("--out", type=Path, default=Path("/tmp/fill_outfeed"))
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument(
    "--force", action="store_true", help="skip the part and spot checks"
  )
  parser.add_argument(
    "--skip_checks",
    action="store_true",
    help="skip configure_cell's offline checks as well (about 20 s per part "
    "height)",
  )
  args = parser.parse_args(argv)

  settings = cell.parameters()["outfeed"]
  layout = args.outfeed_layout or settings["layout"]
  count = args.outfeed_count or int(settings["count"])
  problems = _check(args.parts, cell.targets(), args.first_spot, count)
  if problems and not args.force:
    for problem in problems:
      print(f"  FAILS {problem}")
    return 2

  if not args.skip_checks:
    failed = _offline_checks(
      args.parts, cell.targets(), layout, count, args.reset
    )
    if failed and not args.force:
      return 2

  common = [
    "--apply",
    "--skip_checks",
    "--address",
    args.address,
    "--outfeed_layout",
    layout,
    "--outfeed_count",
    str(count),
  ]
  index = 0
  try:
    if args.reset:
      print(f"=== reset: every part parked, {layout} x {count}")
      configure_cell.main(["--out", str(args.out / "reset")] + common)
    for index, part in enumerate(args.parts):
      spot = args.first_spot + index
      print(f"=== spot {spot}: {part}")
      out = args.out / f"spot_{spot}"
      started = time.monotonic()
      configure_cell.main(
        ["--out", str(out), "--keep_parked", "--target", part] + common
      )
      put_on_bed = time.monotonic()
      omts_main.run_machine_tending_pipeline(
        solution_address=args.address,
        config=load_app_config(out / "app_config.yaml"),
        num_cycles_override=1,
        outfeed_spot=spot,
      )
      print(
        f"=== spot {spot}: {part} done: {put_on_bed - started:.1f} s to put it "
        f"on the bed, {time.monotonic() - put_on_bed:.1f} s for the cycle"
      )
  except (Exception, SystemExit) as exc:
    left = args.parts[index:]
    print(
      f"STOPPED at spot {args.first_spot + index}: "
      f"{type(exc).__name__}: {exc}\n"
      "The part is on the bed or in the gripper. Reset with `configure_cell "
      "--apply` (this clears the line), or put it back, then go on with "
      f"--first_spot {args.first_spot + index} --parts {' '.join(left)}",
      file=sys.stderr,
    )
    return 1
  print(f"Filled {len(args.parts)} spot(s), {layout} layout")
  return 0


if __name__ == "__main__":
  sys.exit(main())
