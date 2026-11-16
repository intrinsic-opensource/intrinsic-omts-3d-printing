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

"""Candidate `view` poses: the camera looking at the part on the bed.

Places the camera on a grid of azimuths, elevations and distances around the
part's centre on the bed, looking at it upright, and keeps poses where: the
tool is reachable (IK) with the joints at least --min_margin rad from their
limits; the arm and camera clear the printer by --min_clearance; the camera's
line of sight to the part misses the printer; and all four bed corners are in
the colour image and beyond the depth sensor's near limit. Prints the best
candidates (straight ahead first, then by joint margin) with the tool pose to
put in the `view` frame of configs/rebot/scene.updates.pbtxt, and checks the
committed `view` the same way.

  bazel run //research/tools:view_search
"""

import argparse
import itertools
import math

import numpy as np

from research.tools import cell, kin


def corners_visible(world_t_cam: np.ndarray, corners: np.ndarray) -> bool:
  c = (corners - world_t_cam[:3, 3]) @ world_t_cam[:3, :3]
  return bool(
    np.all(c[:, 2] > cell.DEPTH_NEAR)
    and np.all(np.abs(c[:, 0]) < cell.CAMERA_TAN_H * c[:, 2])
    and np.all(np.abs(c[:, 1]) < cell.CAMERA_TAN_V * c[:, 2])
  )


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--azimuth", type=float, nargs="+", default=[-15, 0, 15])
  parser.add_argument(
    "--elevation", type=float, nargs="+", default=[30, 40, 50, 60]
  )
  parser.add_argument(
    "--distance", type=float, nargs="+", default=[0.32, 0.36, 0.40, 0.44]
  )
  parser.add_argument("--min_margin", type=float, default=0.3)
  parser.add_argument("--min_clearance", type=float, default=0.02)
  parser.add_argument("--top", type=int, default=5)
  args = parser.parse_args()

  c = cell.Cell()
  target = cell.bed_centre() + [0, 0, cell.PART_HALF_HEIGHT]
  lo, hi = cell._heatbed_bounds()
  corners = np.array(
    [
      (c.printer @ [x, y, hi[2], 1])[:3]
      for x, y in itertools.product((lo[0], hi[0]), (lo[1], hi[1]))
    ]
  )
  cam_t_tool = np.linalg.inv(c.camera)
  rng = np.random.default_rng(21)

  def check(tool: np.ndarray):
    """(margin, clearance, q) if the view passes, else the reason it fails."""
    world_t_cam = tool @ c.camera
    if not corners_visible(world_t_cam, corners):
      return "bed corners out of view or too close"
    eye = world_t_cam[:3, 3]
    ray = np.array(
      [eye + s * (target - eye) for s in np.linspace(0.05, 0.95, 40)]
    )
    if c.nearest(ray)[0] < 0.005:
      return "line of sight blocked"
    found = c.best_ik(tool, 12, rng)
    if found is None:
      return "no IK"
    q, clear = found
    d = min(v[0] for k, v in clear.items() if k != "gripper")
    if d < args.min_clearance:
      return f"arm or camera {d * 100:.1f} cm from the printer"
    if kin.limit_margin(q) < args.min_margin:
      return f"joint margin {kin.limit_margin(q):.2f}"
    return kin.limit_margin(q), d, q

  views = []
  for az, el, dist in itertools.product(
    args.azimuth, args.elevation, args.distance
  ):
    a, e = math.radians(az), math.radians(el)
    look = np.array(
      [math.cos(a) * math.sin(e), -math.sin(a) * math.sin(e), -math.cos(e)]
    )
    eye = target - dist * look
    x = np.cross(look, [0, 0, 1])
    x /= np.linalg.norm(x)
    world_t_cam = np.eye(4)
    world_t_cam[:3, :3] = np.column_stack([x, np.cross(look, x), look])
    world_t_cam[:3, 3] = eye
    tool = world_t_cam @ cam_t_tool
    result = check(tool)
    if not isinstance(result, str):
      views.append((az, el, dist, eye, tool, *result))

  print(f"{len(views)} views pass")
  views.sort(key=lambda v: (v[0] != 0, -v[5]))
  for az, el, dist, eye, tool, margin, d, _ in views[: args.top]:
    print(
      f"  az {az:+.0f} el {el:.0f} d {dist:.2f}: camera "
      f"{np.round(eye, 3).tolist()}, margin {margin:.2f}, clear "
      f"{d * 100:.1f} cm | view position "
      f"{np.round(tool[:3, 3], 4).tolist()} orientation "
      f"{np.round(cell.quat(tool[:3, :3]), 6).tolist()}"
    )
  committed = check(cell.frame_pose("view"))
  if isinstance(committed, str):
    print(f"committed view fails: {committed}")
  else:
    eye = (cell.frame_pose("view") @ c.camera)[:3, 3]
    print(
      f"committed view passes: margin {committed[0]:.2f}, clear "
      f"{committed[1] * 100:.1f} cm, camera {np.linalg.norm(eye - target):.3f} m"
      " from the part"
    )


if __name__ == "__main__":
  main()
