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

"""Checks that the reBot cell works with a printer distance and camera offset.

Offline and approximate, like the other tools here (research/tools/README.md);
confirm the result in simulation.
"""

import itertools

import numpy as np

from research.tools import a_frames, cell, kin

# Minimum distance of the arm and camera from the printer, and from each other.
MIN_CLEARANCE = 0.01
MIN_JOINT_MARGIN = 0.05
# The gripper box covers the fingers and more, so at a grasp it reaches the bed
# and the base under it without touching (research/tools/README.md).
BED_BOXES = ("heatbed", "col_bottom_base")
BED_TOLERANCE = 0.015
# app_config's return_shift, and the part's own place at the bed's centre.
RETURN_DX = (-0.02, 0.0, 0.02)
RETURN_DY = (-0.01, 0.0, 0.01)
RETURN_YAW = (-5.0, 0.0, 5.0)


def committed_view_camera() -> np.ndarray:
  """Where the committed view puts the camera, with the committed configs."""
  cell.set_parameters()
  return cell.frame_pose("view") @ cell.tool_t_camera()


def view_for(world_t_cam_committed, printer_distance, camera_offset):
  """The view that sees the bed as the committed one does.

  It keeps the camera where the committed view has it, relative to the printer,
  whatever the mount, so the arm moves but the image does not change.
  """
  cell.set_parameters()
  dx = printer_distance - cell.world_t_printer()[0, 3]
  world_t_cam = world_t_cam_committed.copy()
  world_t_cam[0, 3] += dx
  cell.set_parameters(printer_distance, camera_offset)
  return world_t_cam @ np.linalg.inv(cell.tool_t_camera())


def _bed_corners(c: cell.Cell) -> np.ndarray:
  lo, hi = cell._heatbed_bounds()
  return np.array(
    [
      (c.printer @ [x, y, hi[2], 1])[:3]
      for x, y in itertools.product((lo[0], hi[0]), (lo[1], hi[1]))
    ]
  )


def _body_gap(a: np.ndarray, b: np.ndarray) -> float:
  d = a[:, None, :] - b[None, :, :]
  return float(np.sqrt((d * d).sum(axis=2)).min())


def check_mount(c: cell.Cell) -> list[str]:
  """Problems with the camera against the wrist and gripper, at any joint 5 or
  6 angle. Pose-independent, so it is checked once."""
  problems = []
  camera_in_tool = (
    cell.box_points(np.eye(4), *cell.CAMERA_BOX) @ c.camera[:3, :3].T
    + c.camera[:3, 3]
  )
  gripper = float(
    cell.box_sdf(camera_in_tool, np.eye(4), *cell.GRIPPER_BOX).min()
  )
  if gripper < MIN_CLEARANCE:
    problems.append(f"camera {gripper * 100:.1f} cm from the gripper")
  worst = (np.inf, "")
  for q5, q6 in itertools.product(
    np.linspace(kin.LOWER[4], kin.UPPER[4], 9),
    np.linspace(kin.LOWER[5], kin.UPPER[5], 13),
  ):
    q = np.array([0.0, -1.0, -1.0, 0.0, q5, q6])
    bodies = c.bodies(q)
    for link in ("link4", "link5", "link6"):
      gap = _body_gap(bodies["camera"], bodies[link][::40])
      if gap < worst[0]:
        worst = (gap, link)
  if worst[0] < MIN_CLEARANCE:
    problems.append(f"camera {worst[0] * 100:.1f} cm from {worst[1]}")
  return problems


def check_view(c: cell.Cell, view: np.ndarray, half_height: float, rng):
  """Problems with the view: it must see the bed and the part, and be reached."""
  problems = []
  world_t_cam = view @ c.camera
  corners = (_bed_corners(c) - world_t_cam[:3, 3]) @ world_t_cam[:3, :3]
  if not (
    np.all(corners[:, 2] > cell.DEPTH_NEAR)
    and np.all(np.abs(corners[:, 0]) < cell.CAMERA_TAN_H * corners[:, 2])
    and np.all(np.abs(corners[:, 1]) < cell.CAMERA_TAN_V * corners[:, 2])
  ):
    problems.append("view: bed corners out of view or too close")
  target = cell.bed_centre() + [0, 0, half_height]
  eye = world_t_cam[:3, 3]
  ray = np.array(
    [eye + s * (target - eye) for s in np.linspace(0.05, 0.95, 40)]
  )
  if c.nearest(ray)[0] < 0.005:
    problems.append("view: line of sight blocked by the printer")
  if float(cell.box_sdf(ray, view, *cell.GRIPPER_BOX).min()) < 0.0:
    problems.append("view: the gripper blocks the camera's line of sight")
  problems += _reach("view", c, view, rng)
  return problems


def _reach(name: str, c: cell.Cell, goal: np.ndarray, rng, seeds: int = 12):
  found = c.best_ik(goal, seeds, rng)
  if found is None:
    return [f"{name}: no IK"]
  q, clear = found
  problems = []
  d, body = min(
    (v[0], f"{k} to {v[1]}") for k, v in clear.items() if k != "gripper"
  )
  if d < MIN_CLEARANCE:
    problems.append(f"{name}: {body} {d * 100:.1f} cm")
  if kin.limit_margin(q) < MIN_JOINT_MARGIN:
    problems.append(f"{name}: joint margin {kin.limit_margin(q):.2f}")
  # The gripper may reach the bed at a grasp, but nothing else.
  bodies = c.bodies(q)
  for box, (centre, size) in c.boxes.items():
    g = float(cell.box_sdf(bodies["gripper"], c.printer, centre, size).min())
    if g < (-BED_TOLERANCE if box in BED_BOXES else 0.0):
      problems.append(f"{name}: gripper in {box} by {-g * 100:.1f} cm")
      break
  return problems


def check_grasps(c: cell.Cell, half_height: float, tilt, offset, rng):
  """Problems with the grasps and pre-grasps over the return area."""
  bed = cell.bed_centre()
  z = bed[2] + half_height
  problems = []
  for dx, dy, yaw in itertools.product(RETURN_DX, RETURN_DY, RETURN_YAW):
    grasp = cell.grasp_pose(bed[0] + dx, bed[1] + dy, z, tilt, yaw)
    pre = grasp.copy()
    pre[:3, 3] -= offset * grasp[:3, 2]
    where = f"({dx:+.2f},{dy:+.2f},{yaw:+.0f})"
    problems += _reach(f"grasp {where}", c, grasp, rng)
    problems += _reach(f"pre-grasp {where}", c, pre, rng)
    if problems:
      break
  return problems


def check_a(c: cell.Cell, half_height: float, tilt, radius, bearing, rng):
  """Problems at A, on the ground: reach, and the camera above the ground."""
  problems = []
  frames = a_frames.frames(tilt, radius, bearing, half_height=half_height)
  for name, goal in frames.items():
    sols = kin.ik(goal, 12, rng)
    if not sols:
      problems.append(f"{name}: no IK")
      continue
    camera = cell.box_points(goal @ c.camera, *cell.CAMERA_BOX)
    if camera[:, 2].min() < MIN_CLEARANCE:
      problems.append(f"{name}: camera {camera[:, 2].min() * 100:.1f} cm up")
  return problems
