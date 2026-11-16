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

"""reBot B601-RS forward and numeric inverse kinematics.

Joint origins, axes and limits are copied from
models/rebot_b601_rs/rebot_b601_rs.sdf. The tool frame is the gripper's
`tool_frame`: the flange plus 0.16621 m along its z axis. The base is at the
world origin, as in configs/rebot/.
"""

import math

import numpy as np
from scipy.optimize import least_squares

# Per joint: origin xyz and rpy in the parent link frame, and the joint axis.
JOINTS = [
  ((-0.00034283, -0.00098683, 0.075), (0, 0, 0), (0, 0, 1)),
  ((0.020343, 0.027237, 0.07), (-1.5708, 0, 0), (0, 0, -1)),
  ((-0.236, 0, 0), (0, 0, 0), (0, 0, 1)),
  ((0.228, -0.072746, 0.0045), (0, 0, 0), (0, 0, 1)),
  ((0.087, -0.048, -0.03075), (-1.5708, 0, 0), (0, 0, 1)),
  ((0.0365, 0, 0.048), (0, 1.5708, 0), (0, 0, 1)),
]
LOWER = np.array([-2.8, -3.14, -3.14, -1.79, -1.57, -3.14])
UPPER = np.array([2.8, 0, 0, 1.69, 1.57, 3.14])
TOOL_Z = 0.16621


def rpy(r: float, p: float, y: float) -> np.ndarray:
  cr, sr = math.cos(r), math.sin(r)
  cp, sp = math.cos(p), math.sin(p)
  cy, sy = math.cos(y), math.sin(y)
  return np.array(
    [
      [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
      [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
      [-sp, cp * sr, cp * cr],
    ]
  )


def axis_angle(axis, angle: float) -> np.ndarray:
  a = np.array(axis, float)
  k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
  return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * k @ k


def fk(q) -> tuple[np.ndarray, list[np.ndarray]]:
  """Returns the tool pose and the six link frames (link1..link6) at q."""
  t = np.eye(4)
  frames = []
  for (xyz, r, axis), qi in zip(JOINTS, q, strict=True):
    origin = np.eye(4)
    origin[:3, :3] = rpy(*r)
    origin[:3, 3] = xyz
    motion = np.eye(4)
    motion[:3, :3] = axis_angle(axis, qi)
    t = t @ origin @ motion
    frames.append(t.copy())
  tool = t.copy()
  tool[:3, 3] = t[:3, 3] + TOOL_Z * t[:3, 2]
  return tool, frames


def ik(goal: np.ndarray, seeds: int = 20, rng=None) -> list[np.ndarray]:
  """Joint solutions within the limits that reach the 4x4 tool pose `goal`."""
  rng = rng or np.random.default_rng(0)

  def residual(q):
    t, _ = fk(q)
    err = t[:3, 3] - goal[:3, 3]
    return np.concatenate([err * 10, (t[:3, :3] - goal[:3, :3]).ravel()])

  solutions = []
  for _ in range(seeds):
    fit = least_squares(
      residual, rng.uniform(LOWER, UPPER), bounds=(LOWER, UPPER)
    )
    if np.linalg.norm(fit.fun) < 1e-4:
      solutions.append(fit.x)
  return solutions


def limit_margin(q) -> float:
  """Smallest distance (rad) from any joint to its limit."""
  return float(min(np.min(q - LOWER), np.min(UPPER - q)))
