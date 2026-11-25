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

"""Tool frames that swing a grip point along a circular arc (numpy only).

The maths of ai.omts.generate_arc_frames, kept free of Intrinsic imports so it
can be tested on its own. All poses are 4x4 matrices in the root frame.

The grip point at angle phi (degrees, right-hand about the pivot's +z) is
G(phi) = P + Rot(axis, phi) (G0 - P). The tool's z axis is the approach
direction; the tool sits at G + (grip_depth_m - back_off) * z. The rotation is
that of src/core/door.py knob_tool_rotation_world, and RADIAL mode is the
azimuth rule of tools/printer/open_door.py knob_matrix.
"""

import dataclasses
import enum
import math

import numpy as np

# Below this, a length counts as zero (meters).
EPS_M = 1e-6
MAX_WAYPOINTS = 100


class Mode(enum.IntEnum):
  """Values match omts.motion.ToolOrientation.Mode."""

  RADIAL = 0
  FIXED_AZIMUTH = 1


class GripOnAxisError(ValueError):
  """The grip point lies on the pivot axis, so the arc has no radius."""


class UndefinedAzimuthError(ValueError):
  """RADIAL: the grip point is straight above or below the radial origin."""


@dataclasses.dataclass(frozen=True)
class ArcFrame:
  name: str
  angle_deg: float
  root_t_tool: np.ndarray  # 4x4


def tool_rotation(az_deg: float, pitch_deg: float) -> np.ndarray:
  """Tool rotation (columns x, y, z = approach) in the root frame.

  z = (cos p cos az, cos p sin az, -sin p), y = normalise(z x up) =
  normalise((z1, -z0, 0)) and x = y x z: the tool's y axis stays horizontal and
  a positive pitch points the tool down.
  """
  if not -90.0 < pitch_deg < 90.0:
    raise ValueError(f"pitch_deg {pitch_deg} is not in (-90, 90)")
  az = math.radians(az_deg)
  pitch = math.radians(pitch_deg)
  z = np.array(
    [
      math.cos(pitch) * math.cos(az),
      math.cos(pitch) * math.sin(az),
      -math.sin(pitch),
    ]
  )
  y = np.array([z[1], -z[0], 0.0])
  y /= math.hypot(y[0], y[1])
  x = np.cross(y, z)
  return np.column_stack([x, y, z])


def axis_rotation(axis: np.ndarray, angle_deg: float) -> np.ndarray:
  """Right-hand rotation by angle_deg about axis (Rodrigues)."""
  k = np.asarray(axis, dtype=np.float64)
  k = k / np.linalg.norm(k)
  a = math.radians(angle_deg)
  cross = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
  return np.eye(3) + math.sin(a) * cross + (1.0 - math.cos(a)) * (cross @ cross)


def grip_point(
  root_t_pivot: np.ndarray, grip_start: np.ndarray, angle_deg: float
) -> np.ndarray:
  """The grip point after turning by angle_deg about the pivot's +z."""
  p = root_t_pivot[:3, 3]
  r = axis_rotation(root_t_pivot[:3, 2], angle_deg)
  return p + r @ (np.asarray(grip_start, dtype=np.float64) - p)


def arc_radius(root_t_pivot: np.ndarray, grip_start: np.ndarray) -> float:
  """Distance of the grip point from the pivot axis, meters."""
  k = root_t_pivot[:3, 2] / np.linalg.norm(root_t_pivot[:3, 2])
  d = np.asarray(grip_start, dtype=np.float64) - root_t_pivot[:3, 3]
  return float(np.linalg.norm(d - (d @ k) * k))


def tool_pose(
  grip: np.ndarray,
  mode: Mode,
  azimuth_deg: float,
  pitch_deg: float,
  grip_depth_m: float,
  back_m: float,
  radial_origin: np.ndarray,
) -> np.ndarray:
  """Root-frame 4x4 of the tool holding the grip point `grip`.

  RADIAL: the approach azimuth is that of the grip point seen from
  radial_origin; FIXED_AZIMUTH: azimuth_deg. back_m backs the tool off along
  its approach axis.
  """
  grip = np.asarray(grip, dtype=np.float64)
  if mode == Mode.RADIAL:
    dx = grip[0] - radial_origin[0]
    dy = grip[1] - radial_origin[1]
    if math.hypot(dx, dy) < EPS_M:
      raise UndefinedAzimuthError(
        "the grip point is straight above or below the radial origin"
      )
    az = math.degrees(math.atan2(dy, dx))
  else:
    az = azimuth_deg
  m = np.eye(4)
  m[:3, :3] = tool_rotation(az, pitch_deg)
  m[:3, 3] = grip + (grip_depth_m - back_m) * m[:3, 2]
  return m


def waypoint_angles(total_angle_deg: float, num_waypoints: int) -> list[float]:
  """Waypoint i (0-based) is at total * (i + 1) / N."""
  n = num_waypoints
  return [total_angle_deg * (i + 1) / n for i in range(n)]


def frame_names(prefix: str, num_waypoints: int) -> list[str]:
  """pregrasp, grasp, wp_00 .. wp_(N-1), retreat."""
  return (
    [f"{prefix}_pregrasp", f"{prefix}_grasp"]
    + [f"{prefix}_wp_{i:02d}" for i in range(num_waypoints)]
    + [f"{prefix}_retreat"]
  )


def arc_frames(
  root_t_pivot: np.ndarray,
  grip_start: np.ndarray,
  total_angle_deg: float,
  num_waypoints: int,
  *,
  mode: Mode = Mode.RADIAL,
  azimuth_deg: float = 0.0,
  pitch_deg: float = 0.0,
  grip_depth_m: float = 0.0,
  approach_offset_m: float = 0.0,
  radial_origin: np.ndarray | None = None,
  prefix: str = "arc",
) -> list[ArcFrame]:
  """All frames of the arc, in the order of frame_names().

  Raises:
    ValueError: num_waypoints is outside 1..MAX_WAYPOINTS, a value is not
      finite, or the pitch is not in (-90, 90).
    GripOnAxisError: the grip point lies on the pivot axis.
    UndefinedAzimuthError: RADIAL, and a grip point is straight above or below
      radial_origin.
  """
  if not 1 <= num_waypoints <= MAX_WAYPOINTS:
    raise ValueError(f"num_waypoints {num_waypoints} not in 1..{MAX_WAYPOINTS}")
  values = (
    total_angle_deg,
    azimuth_deg,
    pitch_deg,
    grip_depth_m,
    approach_offset_m,
  )
  if not all(math.isfinite(v) for v in values):
    raise ValueError("angles and distances must be finite")
  root_t_pivot = np.asarray(root_t_pivot, dtype=np.float64)
  grip_start = np.asarray(grip_start, dtype=np.float64)
  origin = (
    np.zeros(3)
    if radial_origin is None
    else np.asarray(radial_origin, dtype=np.float64)
  )
  if arc_radius(root_t_pivot, grip_start) < EPS_M:
    raise GripOnAxisError("the grip point lies on the pivot axis")

  def pose(angle: float, back: float) -> np.ndarray:
    g = grip_point(root_t_pivot, grip_start, angle)
    return tool_pose(
      g, mode, azimuth_deg, pitch_deg, grip_depth_m, back, origin
    )

  angles = (
    [0.0, 0.0]
    + waypoint_angles(total_angle_deg, num_waypoints)
    + [total_angle_deg]
  )
  backs = [approach_offset_m, 0.0] + [0.0] * num_waypoints + [approach_offset_m]
  names = frame_names(prefix, num_waypoints)
  return [
    ArcFrame(name=n, angle_deg=a, root_t_tool=pose(a, b))
    for n, a, b in zip(names, angles, backs, strict=True)
  ]
