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

"""Printer clearance of each arm body at given joint configurations.

Takes configurations in degrees, as the planner prints them in a collision
report ("Config: [...] in deg"), and prints the tool pose and, for each link,
the camera and the gripper, the nearest printer box and the distance to it.

  bazel run //research/tools:config_clearance -- \
    "[-0.0754,-90.5722,-61.8224,1.2505,-0.1169,-0.0670]"
"""

import argparse

import numpy as np

from research.tools import cell, kin


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument(
    "configs", nargs="+", help="joint angles in degrees, as [a,b,c,d,e,f]"
  )
  args = parser.parse_args()
  c = cell.Cell()
  for text in args.configs:
    q = np.radians([float(v) for v in text.strip("[]").split(",")])
    tool, _ = kin.fk(q)
    print(f"config {np.round(np.degrees(q), 2).tolist()} deg")
    print(f"  tool at {np.round(tool[:3, 3], 4).tolist()}")
    for name, (d, box) in c.clearance(q).items():
      print(f"  {name:8s} {d * 100:6.1f} cm to {box}")


if __name__ == "__main__":
  main()
