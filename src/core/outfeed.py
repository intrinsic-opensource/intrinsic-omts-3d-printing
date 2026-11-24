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


"""The outfeed line's spots: where finished parts are set down, in two layouts.

Each spot is a place on the ground to the robot's right with A's three frames
(`src/core/drop_off.py`). `LINE` puts the spots along a straight line with the
tool at one fixed yaw, so every part is set down axis aligned. `ARC` puts them on
a circle around the robot's base at one radius, stepped by a bearing angle, with
the tool leaning along each spot's bearing: every part has the same distance from
the robot and the same orientation relative to it. Nothing here imports
`intrinsic.*`.
"""

import dataclasses
import math

from src.core import drop_off

# The line's tool yaw: leaning along -y, away from a robot facing +x whose right
# is -y.
LINE_YAW_DEGREES = -90.0


@dataclasses.dataclass(frozen=True)
class Spot:
  """A spot on the ground, in the world frame.

  Attributes:
      x: Position along the world x axis, in metres.
      y: Position along the world y axis, in metres.
      yaw_degrees: The direction the tool leans, or `None` for along the spot's
        bearing from the robot's base.
  """

  x: float
  y: float
  yaw_degrees: float | None = None


def line_spots(
  count: int,
  y: float,
  start_x: float,
  spacing: float,
  yaw_degrees: float = LINE_YAW_DEGREES,
) -> list[Spot]:
  """`count` spots along x at `y`, `spacing` apart from `start_x`, all at one
  yaw."""
  return [Spot(start_x + k * spacing, y, yaw_degrees) for k in range(count)]


def arc_spots(
  count: int, radius: float, start_bearing_degrees: float, step_degrees: float
) -> list[Spot]:
  """`count` spots on a circle of `radius` around the robot's base, from
  `start_bearing_degrees`, `step_degrees` apart, each leaning along its bearing."""
  spots = []
  for k in range(count):
    bearing = math.radians(start_bearing_degrees + k * step_degrees)
    spots.append(Spot(radius * math.cos(bearing), radius * math.sin(bearing)))
  return spots


def frame_names(prefix: str, index: int) -> tuple[str, str, str]:
  """The names of spot `index`'s place, pre-place and approach frames."""
  return (
    f"{prefix}_{index}_place",
    f"{prefix}_{index}_preplace",
    f"{prefix}_{index}_approach",
  )


def spot_frames(
  spot: Spot,
  tilt_degrees: float,
  half_height: float,
  depth: float = 0.0,
) -> tuple[drop_off.Pose, drop_off.Pose, drop_off.Pose]:
  """The spot's place, pre-place and approach frames, as (position, quaternion)
  in the world, for a part whose centre rests `half_height` above the ground."""
  frames = drop_off.drop_off_frames(
    tilt_degrees,
    math.hypot(spot.x, spot.y),
    math.degrees(math.atan2(spot.y, spot.x)),
    half_height,
    depth,
    spot.yaw_degrees,
  )
  return (
    frames["place_vise"],
    frames["pre_place_vise"],
    frames["machine_approach"],
  )
