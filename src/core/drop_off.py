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

"""A's frames: where the cycle sets the part down on the ground.

The reBot cell has no machine, so the load and unload steps set the part down at
A, on the ground behind the robot, and pick it up again. A is three world frames
(`configs/rebot/scene.updates.pbtxt`): `place_vise` holds the part at its resting
height, `pre_place_vise` is 8 cm back along the approach and `machine_approach`
10 cm above that. They depend on the part's height, so a printed part of another
height needs them moved. This is `research/tools/a_frames.py`'s maths without
numpy (a test keeps them equal), so the `ai.omts.configure_cell` skill
(`skills/cell/`) can compute them. Nothing here imports `intrinsic.*`.
"""

import math

Vector = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]  # x, y, z, w
Pose = tuple[Vector, Quaternion]

PRE_PLACE_BACK = 0.08  # m, back along the approach from the part
APPROACH_UP = 0.10  # m, above the pre-place frame

_Matrix = tuple[Vector, Vector, Vector]


def _matmul(a: _Matrix, b: _Matrix) -> _Matrix:
  return tuple(
    tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
    for i in range(3)
  )  # type: ignore[return-value]


def _quaternion(r: _Matrix) -> Quaternion:
  """Quaternion (x, y, z, w) of a rotation matrix, with the sign convention
  of `research/tools/cell.py`."""
  w = math.sqrt(max(0.0, 1 + r[0][0] + r[1][1] + r[2][2])) / 2
  x = math.copysign(
    math.sqrt(max(0.0, 1 + r[0][0] - r[1][1] - r[2][2])) / 2, r[2][1] - r[1][2]
  )
  y = math.copysign(
    math.sqrt(max(0.0, 1 - r[0][0] + r[1][1] - r[2][2])) / 2, r[0][2] - r[2][0]
  )
  z = math.copysign(
    math.sqrt(max(0.0, 1 - r[0][0] - r[1][1] + r[2][2])) / 2, r[1][0] - r[0][1]
  )
  return (x, y, z, w)


def drop_off_frames(
  tilt_degrees: float,
  radius: float,
  bearing_degrees: float,
  half_height: float,
  depth: float = 0.0,
) -> dict[str, Pose]:
  """A's frames for a part whose centre rests `half_height` above the ground.

  The tool is pitched `tilt_degrees` from vertical about the jaw axis, leaning
  away from the robot (the grasp `cuboid_center` makes on the bed), so the part
  is set down flat. A is `radius` out from the robot base at `bearing_degrees`;
  `depth` is how far past its centre the part is gripped.

  Returns:
      `place_vise`, `pre_place_vise` and `machine_approach`, as (position,
      quaternion) in the world.
  """
  t = math.radians(tilt_degrees)
  b = math.radians(bearing_degrees)
  down: _Matrix = ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
  pitch: _Matrix = (
    (math.cos(t), 0.0, math.sin(t)),
    (0.0, 1.0, 0.0),
    (-math.sin(t), 0.0, math.cos(t)),
  )
  rot_z: _Matrix = (
    (math.cos(b), -math.sin(b), 0.0),
    (math.sin(b), math.cos(b), 0.0),
    (0.0, 0.0, 1.0),
  )
  rotation = _matmul(rot_z, _matmul(down, pitch))
  position = (
    radius * math.cos(b) + depth * math.cos(b),
    radius * math.sin(b) + depth * math.sin(b),
    half_height,
  )
  approach_axis = tuple(rotation[i][2] for i in range(3))
  pre = tuple(position[i] - PRE_PLACE_BACK * approach_axis[i] for i in range(3))
  above = (pre[0], pre[1], pre[2] + APPROACH_UP)
  orientation = _quaternion(rotation)
  return {
    "place_vise": (position, orientation),
    "pre_place_vise": (pre, orientation),  # type: ignore[dict-item]
    "machine_approach": (above, orientation),
  }
