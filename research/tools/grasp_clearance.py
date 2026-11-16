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

"""Reach and printer clearance of the tilted grasp over the bed.

For each grasp tilt, and part positions around the bed centre (offsets along
x and y, turned by a yaw), solves IK for the pre-grasp and the grasp, keeps
the solution whose arm and camera are furthest from the printer, and prints:
the closest arm or camera body and its distance, the joints' margin from
their limits, and the gripper's distance (at the grasp the gripper box
reaching the bed is expected). Defaults come from
configs/rebot/app_config.yaml and the printer's pose in configs/rebot/.

  bazel run //research/tools:grasp_clearance -- --tilt 60 75
"""

import argparse
import itertools

import numpy as np

from research.tools import cell


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--tilt", type=float, nargs="+", default=None)
  parser.add_argument("--approach_offset", type=float, default=None)
  parser.add_argument("--dx", type=float, nargs="+", default=[-0.02, 0, 0.02])
  parser.add_argument("--dy", type=float, nargs="+", default=[0.0])
  parser.add_argument("--yaw", type=float, nargs="+", default=[0.0])
  parser.add_argument("--seeds", type=int, default=20)
  args = parser.parse_args()
  tilts = args.tilt or [cell.app_setting("approach_tilt_degrees")]
  offset = args.approach_offset or cell.app_setting("approach_offset_z")

  c = cell.Cell()
  bed = cell.bed_centre()
  part_z = bed[2] + cell.PART_HALF_HEIGHT
  rng = np.random.default_rng(3)
  print(
    f"bed centre {np.round(bed, 4).tolist()}, part centre z {part_z:.4f}, "
    f"pre-grasp {offset} m back along the approach"
  )
  print("distances in cm; m = joint margin (rad); g = gripper")
  for tilt, dy, yaw in itertools.product(tilts, args.dy, args.yaw):
    row = []
    for dx in args.dx:
      grasp = cell.grasp_pose(bed[0] + dx, bed[1] + dy, part_z, tilt, yaw)
      pre = grasp.copy()
      pre[:3, 3] -= offset * grasp[:3, 2]
      cells = []
      for goal in (pre, grasp):
        found = c.best_ik(goal, args.seeds, rng)
        if found is None:
          cells.append("no IK")
          continue
        q, clear = found
        d, body = min(
          (v[0], f"{k}:{v[1]}") for k, v in clear.items() if k != "gripper"
        )
        cells.append(
          f"{d * 100:5.1f} {body} m{cell.kin.limit_margin(q):.2f} "
          f"g{clear['gripper'][0] * 100:.1f}"
        )
      row.append(f"dx {dx:+.2f}: pre {cells[0]} / grasp {cells[1]}")
    print(f"tilt {tilt:.0f} dy {dy:+.2f} yaw {yaw:+.0f}")
    for line in row:
      print("  " + line)


if __name__ == "__main__":
  main()
