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

"""Finds which printer distances and camera offsets the reBot cell can use.

One parameter at a time, the others at their committed values, for the default
part and the other targets' heights. Offline; confirm the edges in simulation.

  bazel run //research/tools:cell_limits
"""

import argparse

import numpy as np

from research.tools import cell, cell_checks

A_RADIUS, A_BEARING = 0.55, 130.0


def problems(committed_camera, distance, offset, half_height, tilt, approach):
  view = cell_checks.view_for(committed_camera, distance, offset)
  c = cell.Cell(samples=800)
  rng = np.random.default_rng(7)
  return (
    cell_checks.check_mount(c)
    + cell_checks.check_view(c, view, half_height, rng)
    + cell_checks.check_grasps(c, half_height, tilt, approach, rng)
    + cell_checks.check_a(c, half_height, tilt, A_RADIUS, A_BEARING, rng)
  )


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument(
    "--half_height", type=float, default=cell.PART_HALF_HEIGHT
  )
  parser.add_argument("--printer_step", type=float, default=0.01)
  parser.add_argument(
    "--printer_range", type=float, nargs=2, default=(0.45, 0.80)
  )
  parser.add_argument("--camera_step", type=float, default=0.01)
  parser.add_argument("--camera_range", type=float, default=0.10)
  parser.add_argument("--only", choices=("printer", "camera"), default=None)
  args = parser.parse_args()

  params = cell.parameters()
  distance0 = params["printer_distance_m"]
  offset0 = list(params["camera_offset_m"])
  committed = cell_checks.committed_view_camera()
  tilt = cell.app_setting("approach_tilt_degrees")
  approach = cell.app_setting("approach_offset_z")

  def run(label, distance, offset):
    found = problems(
      committed, distance, offset, args.half_height, tilt, approach
    )
    print(f"{label}: {'ok' if not found else '; '.join(found[:3])}", flush=True)

  if args.only != "camera":
    print(f"printer distance (committed {distance0})")
    for d in np.arange(
      args.printer_range[0], args.printer_range[1] + 1e-6, args.printer_step
    ):
      run(f"  {d:.3f}", float(d), offset0)
  if args.only != "printer":
    for axis, name in enumerate("xyz"):
      print(f"camera {name} (committed {offset0[axis]})")
      for delta in np.arange(
        -args.camera_range, args.camera_range + 1e-6, args.camera_step
      ):
        offset = list(offset0)
        offset[axis] += float(delta)
        run(f"  {offset[axis]:+.3f}", distance0, offset)


if __name__ == "__main__":
  main()
