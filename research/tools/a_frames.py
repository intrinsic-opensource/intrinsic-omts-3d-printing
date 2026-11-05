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

"""Frames for A, the drop-off on the ground, and their reach.

A's frames in configs/rebot/scene.updates.pbtxt hold the part on the ground at
a distance (radius) and bearing from the robot base, with the tool tilted like
the grasp on the bed, leaning away from the robot, so the part is set down
flat: place_vise at the part's resting height, pre_place_vise 8 cm back along
the approach, and machine_approach 10 cm above that. For each radius and
bearing, prints the three frames and the joints' margin from their limits
(rad) at each, and the lowest arm link origin. The tilt defaults to
grasp.approach_tilt_degrees in configs/rebot/app_config.yaml.

  bazel run //research/tools:a_frames -- --radius 0.50 0.55 --bearing 130
"""

import argparse
import math

import numpy as np

from research.tools import cell, kin

PRE_PLACE_BACK = 0.08
APPROACH_UP = 0.10


def frames(
  tilt: float,
  radius: float,
  bearing: float,
  half_height: float = cell.PART_HALF_HEIGHT,
  depth: float = 0.0,
):
  """A's frames for a part whose centre rests half_height above the ground,
  gripped `depth` past its centre horizontally (grasp.grasp_depth_meters)."""
  b = math.radians(bearing)
  grasp = cell.grasp_pose(
    radius * math.cos(b), radius * math.sin(b), half_height, tilt
  )
  grasp[:3, :3] = cell.rot_z(b) @ grasp[:3, :3]
  grasp[:3, 3] += depth * np.array([math.cos(b), math.sin(b), 0.0])
  pre = grasp.copy()
  pre[:3, 3] -= PRE_PLACE_BACK * grasp[:3, 2]
  approach = pre.copy()
  approach[2, 3] += APPROACH_UP
  return {
    "place_vise": grasp,
    "pre_place_vise": pre,
    "machine_approach": approach,
  }


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--tilt", type=float, default=None)
  parser.add_argument("--radius", type=float, nargs="+", default=[0.55])
  parser.add_argument("--bearing", type=float, nargs="+", default=[130.0])
  parser.add_argument("--depth", type=float, default=None)
  parser.add_argument("--seeds", type=int, default=30)
  args = parser.parse_args()
  tilt = args.tilt or cell.app_setting("approach_tilt_degrees")
  depth = args.depth
  if depth is None:
    try:
      depth = cell.app_setting("grasp_depth_meters")
    except KeyError:
      depth = 0.0
  rng = np.random.default_rng(5)
  for radius in args.radius:
    for bearing in args.bearing:
      print(f"tilt {tilt:.0f}, radius {radius}, bearing {bearing}")
      for name, goal in frames(tilt, radius, bearing, depth=depth).items():
        sols = kin.ik(goal, args.seeds, rng)
        if sols:
          q = max(sols, key=kin.limit_margin)
          _, links = kin.fk(q)
          reach = (
            f"margin {kin.limit_margin(q):.2f}, lowest link origin "
            f"z {min(f[2, 3] for f in links[1:]):.3f}"
          )
        else:
          reach = "no IK"
        p = np.round(goal[:3, 3], 4).tolist()
        r = np.round(cell.quat(goal[:3, :3]), 6).tolist()
        print(f"  {name:16s} position {p} orientation {r}: {reach}")


if __name__ == "__main__":
  main()
