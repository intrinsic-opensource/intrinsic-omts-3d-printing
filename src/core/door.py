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
# The D handle (models/printer/3d_printer.sdf): two arms in the door's plane run
# from the pane's free edge out to rounded corners HANDLE_STANDOFF_M beyond it;
# the straight vertical bar between the corners (the link crank_handle) turns
# freely about its own axis on the joint crank_pivot. The door hinge is the
# fixed axis: the arms swing the bar on a circle about it, and because the bar
# turns, the gripper holding it never has to twist. Being beyond the free edge,
# the bar is never behind the pane, whatever the door angle.
PANE_EDGE_X = -0.354  # the pane's free edge, door frame
HANDLE_STANDOFF_M = 0.10  # bar axis beyond the free edge
HANDLE_PLANE_Y = 0.016  # the D's plane, in front of the pane's outer face
HANDLE_GRIP_Z = 0.175  # bar centre height; the top arm stays inside the mesh
HANDLE_BAR_LENGTH_M = 0.100  # free bar length between the corners
# The bar is a rectangular prism: the long face points at the robot at the
# closed door (yaw about the bar axis, door frame, for the door-test layout:
# approach azimuth -27 deg in the world), so the fingers close flat across the
# thin side.
HANDLE_BAR_LONG_M = 0.040
HANDLE_BAR_THIN_M = 0.016
HANDLE_BAR_YAW_RAD = 1.095
HANDLE_ARM_RADIUS_M = 0.006
HANDLE_GAP_M = 0.002  # bar end to corner sphere
CORNER_RADIUS_M = 0.008
# Arm height above and below the bar centre.
HANDLE_ARM_DZ_M = HANDLE_BAR_LENGTH_M / 2 + HANDLE_GAP_M + CORNER_RADIUS_M
# The open gripper body is +-40.7 mm tall, so the arms must clear it.
GRIPPER_HALF_HEIGHT_M = 0.0407
# The bar axis (centre of the pivot), door frame.
CRANK_PIVOT_POS: Vec = (
  PANE_EDGE_X - HANDLE_STANDOFF_M,
  HANDLE_PLANE_Y,
  HANDLE_GRIP_Z,
)
# The grip point is the bar centre. The tool goes GRIP_DEPTH_M past it so the
# bar sits on the fingers' flat pads, not on their tips.
KNOB_POS: Vec = CRANK_PIVOT_POS
GRIP_DEPTH_M = 0.015
# Tool orientation for open_door's --az_mode=fixed: level, azimuth in the world
# frame, the fingers closing horizontally across the bar. The default radial
# mode points the tool from the robot's base at the grip point instead (the
# bar turns, so the wrist need not).
KNOB_APPROACH_AZ_DEG = -28.2
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
