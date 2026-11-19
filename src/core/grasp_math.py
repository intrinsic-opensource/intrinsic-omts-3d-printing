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

"""Grasp frames for a cuboid, from its pose: the math, without any world.

The "cuboid center" grasp: the gripper takes the part by its centre, aligned
with the part's long axis, optionally pitched so the approach leans away from
the robot, with a pre-grasp backed off along the approach.

This is the rule `src/utils/dynamic_frame_calculator.py` runs as a
`bt.PythonScript` inside the executive, made a plain function so the
`ai.omts.plan_cuboid_grasp` skill (`skills/grasp/`) and tests can call it.
`tests/unit/test_grasp_math.py` checks the two give the same frames; the script
cannot import this module (it ships as one source file), so keep them in step
until the script is retired. Must not import `intrinsic.*` (`CLAUDE.md`).

Quaternions are (x, y, z, w); positions are (x, y, z) in the parent frame.
"""

import dataclasses
import math

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


def quat_multiply(a: Quat, b: Quat) -> Quat:
  """Hamilton product of (x, y, z, w) quaternions."""
  ax, ay, az, aw = a
  bx, by, bz, bw = b
  return (
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  )


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
  """Rotates vector v by the (x, y, z, w) quaternion q."""
  rotated = quat_multiply(
    quat_multiply(q, (v[0], v[1], v[2], 0.0)), (-q[0], -q[1], -q[2], q[3])
  )
  return rotated[0], rotated[1], rotated[2]


@dataclasses.dataclass(frozen=True)
class CuboidGrasp:
  """The grasp and pre-grasp of a cuboid.

  Attributes:
      grasp_position: Where the tool goes, at the part's centre.
      pregrasp_position: The grasp backed off along the approach.
      orientation: The tool's orientation at both.
  """

  grasp_position: Vec3
  pregrasp_position: Vec3
  orientation: Quat


def cuboid_grasp(
  target_position: Vec3,
  target_orientation: Quat,
  approach_offset: float,
  tool_orientation: Quat | None = None,
  approach_tilt_degrees: float = 0.0,
  yaw_symmetry_degrees: float = 180.0,
) -> CuboidGrasp:
  """The grasp for a cuboid at the given pose, in the frame of that pose.

  The part's local X is its longest axis, local Z the medium one. The grasp is
  on the short side, aligned with the long axis in the XY plane (the medium
  axis, if the part is stood on its end).

  Args:
      target_position: The part's centre.
      target_orientation: The part's orientation.
      approach_offset: Distance of the pre-grasp back along the approach.
      tool_orientation: The tool's current orientation, if known. For a
        vertical grasp, of the four top-down candidates the one closest to it
        is taken, so the wrist turns as little as possible.
      approach_tilt_degrees: Pitch of the grasp about the jaw axis, so the
        approach leans away from the origin of the frame (the robot base) and
        the pre-grasp backs off along it. 0 is a vertical grasp. Of the
        candidates, the one whose tool X points most directly away from the
        origin is taken, whatever the tool's current orientation.
      yaw_symmetry_degrees: How far the part can turn about the vertical and
        look the same: 180 for a box, 90 for a square footprint, which lets a
        tilted grasp also take the other pair of faces.
  """
  ax = quat_rotate(target_orientation, (1.0, 0.0, 0.0))
  az = quat_rotate(target_orientation, (0.0, 0.0, 1.0))
  if abs(ax[2]) < 0.7:
    vx, vy = ax[0], ax[1]
  else:
    vx, vy = az[0], az[1]

  psi = math.atan2(vy, vx)
  half_psi = psi / 2.0
  c1: Quat = (math.cos(half_psi), math.sin(half_psi), 0.0, 0.0)
  c2: Quat = (-math.sin(half_psi), math.cos(half_psi), 0.0, 0.0)
  candidates: list[Quat] = [
    c1,
    (-c1[0], -c1[1], 0.0, 0.0),
    c2,
    (-c2[0], -c2[1], 0.0, 0.0),
  ]

  if tool_orientation is not None:
    grasp_ori = max(
      candidates,
      key=lambda c: sum(c[i] * tool_orientation[i] for i in range(4)),
    )
  else:
    grasp_ori = c1

  approach: Vec3 = (0.0, 0.0, -1.0)
  tilt = math.radians(approach_tilt_degrees)
  if tilt:
    radial = (target_position[0], target_position[1])
    tilt_candidates: list[Quat] = [c1, c2]
    if yaw_symmetry_degrees == 90.0:
      quarter: Quat = (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5))
      tilt_candidates += [
        quat_multiply(c1, quarter),
        quat_multiply(c2, quarter),
      ]
    grasp_ori = max(
      tilt_candidates,
      key=lambda c: (
        quat_rotate(c, (1.0, 0.0, 0.0))[0] * radial[0]
        + quat_rotate(c, (1.0, 0.0, 0.0))[1] * radial[1]
      ),
    )
    grasp_ori = quat_multiply(
      grasp_ori, (0.0, math.sin(tilt / 2.0), 0.0, math.cos(tilt / 2.0))
    )
    approach = quat_rotate(grasp_ori, (0.0, 0.0, 1.0))

  grasp_position = (
    float(target_position[0]),
    float(target_position[1]),
    float(target_position[2]),
  )
  pregrasp_position = (
    grasp_position[0] - approach_offset * approach[0],
    grasp_position[1] - approach_offset * approach[1],
    grasp_position[2] - approach_offset * approach[2],
  )
  return CuboidGrasp(grasp_position, pregrasp_position, grasp_ori)
