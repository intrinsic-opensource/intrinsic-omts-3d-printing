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

"""The printer door's geometry and hinge angle (math only).

theta is the door angle: 0 closed, 180 deg fully open. The SDF joint is
q = pi - theta (closed = pi, open = 0); that convention lives only here.
Door-frame points are in door_link's frame at q = pi (door closed): x = 0 at
the hinge, x < 0 toward the free edge, y out of the printer's front, z up.
Printer-frame points are in the printer's base_link frame.
"""

import math

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]

# door_link's origin (the hinge axis, +Z) in the printer's base_link frame.
HINGE_IN_PRINTER: Vec = (0.174, 0.205, 0.279)
# Hinge joint limits, radians.
Q_LOWER = 0.0
Q_UPPER = 3.14159
# The crank (models/printer/3d_printer.sdf): an arm fixed to the door's handle
# carries a bearing block 70 mm in front of the pane; the crank handle (a rod
# with a flat tab) turns freely about its own vertical axis on the joint
# crank_pivot. The door hinge is the fixed axis: the arm swings the pivot on a
# circle about it, and because the handle turns, the gripper holding the tab
# never has to twist. Pivot centre, door frame (the top of the handle):
CRANK_PIVOT_POS: Vec = (-0.347, 0.070, 0.2145)
# The gripper holds the tab, 55 mm above the pivot. The arm keeps the open
# fingers (+-50 mm across the tab) clear of the printer's frame, which matters:
# the simulator welds a gripper to the first free (floating) body it touches,
# and the printer's base is one.
TAB_ABOVE_PIVOT_M = 0.055
KNOB_POS: Vec = (
  CRANK_PIVOT_POS[0],
  CRANK_PIVOT_POS[1],
  CRANK_PIVOT_POS[2] + TAB_ABOVE_PIVOT_M,
)
# Tool orientation for open_door's --az_mode=fixed: level, azimuth in the world
# frame, the fingers closing horizontally across the tab. The default radial
# mode points the tool from the robot's base at the grip point instead (the
# crank turns, so the wrist need not), which reaches about 120 deg.
KNOB_APPROACH_AZ_DEG = -19.7
KNOB_APPROACH_PITCH_DEG = 0.0
# Faces of the pane in the door frame (outer faces the robot).
OUTER_FACE_Y = 0.0075
# ArUco marker side (black square), meters: one big marker.
MARKER_SIZE_M = 0.080

# Marker frames in the door frame: origin on the face, OpenCV convention
# (x right and y down in the image, z into the marker) seen from the viewer.
_OUTER_ROT: Mat = ((-1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, -1.0, 0.0))
# id -> (position in the door frame, rotation, columns = marker axes). One
# marker, big, top-left seen from the robot, clear of the hinge knuckles and the
# pane's top edge (a 107 mm tile with its quiet zone). It identifies the printer
# and gives the printer's pose as a whole.
MARKERS: dict[int, tuple[Vec, Mat]] = {
  1: ((-0.090, OUTER_FACE_Y, 0.180), _OUTER_ROT),
}


# Tool-tip (tool_frame) pose that wraps the handle, in the door frame: the
# fingertips at the handle centre, 0.15 m above the printer base, approaching
# into the pane (-y) pitched 30 deg down. Roll 0: the fingers close along the
# door's x axis, across the blade's thickness (roll 270 closes them vertically,
# along the blade, which only hooks it). Legacy grasp (--grip=handle). The tool
# +z axis is the approach direction.
WRAP_GRASP_POS: Vec = (-0.3465, 0.0145, 0.15 - HINGE_IN_PRINTER[2])
_S3 = math.sqrt(3.0) / 2.0
WRAP_GRASP_ROT: Mat = ((0.0, -1.0, 0.0), (-0.5, 0.0, -_S3), (_S3, 0.0, -0.5))


def knob_tool_rotation_world(az_deg: float | None = None) -> Mat:
  """Tool rotation (columns x, y, z = approach) in the world frame.

  The approach is level, at azimuth az_deg (default: KNOB_APPROACH_AZ_DEG).
  """
  az = math.radians(KNOB_APPROACH_AZ_DEG if az_deg is None else az_deg)
  pitch = math.radians(KNOB_APPROACH_PITCH_DEG)
  z = (
    math.cos(pitch) * math.cos(az),
    math.cos(pitch) * math.sin(az),
    -math.sin(pitch),
  )
  y = (z[1], -z[0], 0.0)  # z cross up, normalised
  n = math.hypot(y[0], y[1])
  y = (y[0] / n, y[1] / n, 0.0)
  x = (
    y[1] * z[2] - y[2] * z[1],
    y[2] * z[0] - y[0] * z[2],
    y[0] * z[1] - y[1] * z[0],
  )
  return tuple((x[i], y[i], z[i]) for i in range(3))


def knob_in_printer(theta_deg: float) -> Vec:
  """The lever's grip point in the printer frame at door angle theta."""
  return point_in_printer(KNOB_POS, theta_deg)


def theta_to_q(theta_deg: float) -> float:
  """Hinge joint position (rad) for a door angle (deg)."""
  q = math.pi - math.radians(theta_deg)
  if q < Q_LOWER - 1e-9 or q > Q_UPPER + 1e-4:
    raise ValueError(f"theta {theta_deg} deg is outside 0..180")
  return min(max(q, Q_LOWER), Q_UPPER)


def q_to_theta(q: float) -> float:
  """Door angle (deg) for a hinge joint position (rad)."""
  return math.degrees(math.pi - q)


def rot_z(angle: float) -> Mat:
  c, s = math.cos(angle), math.sin(angle)
  return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _mat_vec(m: Mat, v: Vec) -> Vec:
  return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def _mat_mat(a: Mat, b: Mat) -> Mat:
  return tuple(
    tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
    for i in range(3)
  )


def point_in_printer(p_door: Vec, theta_deg: float) -> Vec:
  """A door-frame point in the printer frame at door angle theta.

  door_link turns by -theta about the hinge axis (yaw = q - pi).
  """
  r = _mat_vec(rot_z(-math.radians(theta_deg)), p_door)
  return tuple(r[i] + HINGE_IN_PRINTER[i] for i in range(3))


def frame_in_printer(
  p_door: Vec, rot_door: Mat, theta_deg: float
) -> tuple[Vec, Mat]:
  """A door-frame pose in the printer frame at door angle theta."""
  r = rot_z(-math.radians(theta_deg))
  return point_in_printer(p_door, theta_deg), _mat_mat(r, rot_door)


def marker_in_printer(marker_id: int, theta_deg: float) -> tuple[Vec, Mat]:
  """Marker pose (OpenCV axes) in the printer frame at door angle theta."""
  p, rot = MARKERS[marker_id]
  return frame_in_printer(p, rot, theta_deg)


def wrap_grasp_in_printer(
  theta_deg: float, back_m: float = 0.0, height_m: float | None = None
):
  """The wrap grasp (tool_frame) in the printer frame at door angle theta.

  back_m backs the tool off along its approach axis (a pre-grasp pose);
  height_m is the tip height above the printer base (default 0.15).
  """
  z = WRAP_GRASP_POS[2] if height_m is None else height_m - HINGE_IN_PRINTER[2]
  base = (WRAP_GRASP_POS[0], WRAP_GRASP_POS[1], z)
  pos = tuple(base[i] - back_m * WRAP_GRASP_ROT[i][2] for i in range(3))
  return frame_in_printer(pos, WRAP_GRASP_ROT, theta_deg)


def mat_to_rpy(m: Mat) -> Vec:
  """SDF roll, pitch, yaw (x-y-z extrinsic) of a rotation matrix."""
  pitch = math.asin(-max(-1.0, min(1.0, m[2][0])))
  if abs(m[2][0]) < 1 - 1e-9:
    roll = math.atan2(m[2][1], m[2][2])
    yaw = math.atan2(m[1][0], m[0][0])
  else:
    roll = math.atan2(-m[1][2], m[1][1])
    yaw = 0.0
  return roll, pitch, yaw
