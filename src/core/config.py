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

"""Cell configuration dataclasses and strict YAML loader for OMTS workcells."""

import dataclasses
import pathlib
from typing import Any, TypeVar

import yaml

from src.core.types import GraspPlannerType, Touchdown

_T = TypeVar("_T")


@dataclasses.dataclass(frozen=True)
class RobotConfig:
  """Configuration for the robot arm and moving tool frame.

  Attributes:
      arm_part_name: Name of the robot arm part in `solution.world`.
      tool_object_name: Name of the end-effector object in `solution.world`.
      tool_frame_name: Name of the TCP frame on `tool_object_name`.
      enclosure_object_name: Name of the cell enclosure object, if applicable.
      force_sensing: Whether the arm can sense contact forces. Without it,
        `move_to_contact` has no robot to bind to, so compliant touchdowns are
        replaced by linear moves to the seated pose.
  """

  arm_part_name: str
  tool_object_name: str
  tool_frame_name: str
  enclosure_object_name: str | None = None
  force_sensing: bool = True


@dataclasses.dataclass(frozen=True)
class GripperConfig:
  """Configuration for the end-effector gripper adapter.

  Attributes:
      type: Gripper adapter type (`'robotiq'`, `'dio'` or `'pinch'`).
      joint_name: Finger joint name for `RobotiqGripper`.
      open_position: Open stroke position in meters for `RobotiqGripper`.
      close_position: Closed stroke position in meters for `RobotiqGripper`.
      action_name: Optional action resource name for `RobotiqGripper`.
      dio_open_pin: Digital output index to open `DioGripper`.
      dio_close_pin: Digital output index to close `DioGripper`.
      dio_device_name: Optional ADIO device resource name for `DioGripper`.
      dio_output_block_name: Digital output block name for `DioGripper`.
      resource_name: Gripper hardware device instance commanded by
        `PinchGripper` through `ai.intrinsic.control_pinch_gripper`.
      settle_seconds: Dwell after each `PinchGripper` grasp or release.
        `control_pinch_gripper` returns once the command is sent, before the
        fingers stop, so the arm would otherwise move while they are still
        closing or opening. Defaults to `PinchGripper.DEFAULT_SETTLE_SECONDS`.
  """

  type: str
  joint_name: str | None = None
  open_position: float | None = None
  close_position: float | None = None
  action_name: str | None = None
  dio_open_pin: int | None = None
  dio_close_pin: int | None = None
  dio_device_name: str | None = None
  dio_output_block_name: str | None = None
  resource_name: str | None = None
  settle_seconds: float | None = None

  def __post_init__(self) -> None:
    if self.type == "robotiq":
      required = ("joint_name", "open_position", "close_position")
    elif self.type == "dio":
      required = ("dio_open_pin", "dio_close_pin", "dio_output_block_name")
    elif self.type == "pinch":
      required = ("resource_name",)
    else:
      return
    missing = [name for name in required if getattr(self, name) is None]
    if missing:
      raise KeyError(
        f"Missing required configuration field(s) {sorted(missing)} for "
        f"gripper type '{self.type}'"
      )


@dataclasses.dataclass(frozen=True)
class MachineConfig:
  """Configuration for CNC enclosure door, vise, and cycle handshake DIO.

  Attributes:
      door_open_pin: Digital output index to open the CNC door.
      door_close_pin: Digital output index to close the CNC door.
      vise_open_pin: Digital output index to open the pneumatic vise.
      vise_close_pin: Digital output index to clamp the pneumatic vise.
      cycle_start_pin: Digital output index pulsed to trigger cycle start.
      cycle_complete_input_pin: Optional digital input index for cycle done.
      device_name: ADIO device resource name (e.g. `'ur_module'`).
      enclosure_object_name: Scene object name for the CNC enclosure door.
      vise_object_name: Scene object name for the pneumatic vise.
      door_open_joints: Joint position vector for open enclosure door.
      door_closed_joints: Joint position vector for closed enclosure door.
      vise_open_joints: Joint position vector for open vise jaws.
      vise_closed_joints: Joint position vector for clamped vise jaws.
      output_block_name: Digital output block name on the ADIO device.
      input_block_name: Digital input block name on the ADIO device.
  """

  door_open_pin: int
  door_close_pin: int
  vise_open_pin: int
  vise_close_pin: int
  cycle_start_pin: int
  cycle_complete_input_pin: int | None
  device_name: str
  enclosure_object_name: str | None
  vise_object_name: str | None
  door_open_joints: tuple[float, ...]
  door_closed_joints: tuple[float, ...]
  vise_open_joints: tuple[float, ...]
  vise_closed_joints: tuple[float, ...]
  output_block_name: str
  input_block_name: str


@dataclasses.dataclass(frozen=True)
class VisionConfig:
  """Configuration for 3D perception and pose estimation.

  Attributes:
      camera_name: Resource name of the RGB-D camera.
      perception_service_name: Resource name of the pose estimation service.
      pose_estimator_id: Asset ID of the registered pose estimator.
      scene_object_id: Scene object ID updated upon pose detection.
      sensor_ids: Camera sensor stream IDs (e.g. `(1, 4)` for RGB-D).
      min_num_instances: Minimum detected part instances required per capture.
      infeed_mode: Infeed localization strategy (`'perception'` or `'grid'`).
      min_safe_z: Minimum allowable Z coordinate in `root` frame (meters).
  """

  camera_name: str
  perception_service_name: str
  pose_estimator_id: str
  scene_object_id: str
  sensor_ids: tuple[int, ...]
  min_num_instances: int
  infeed_mode: str
  min_safe_z: float


@dataclasses.dataclass(frozen=True)
class FramesConfig:
  """World transform frame names used across machine tending motions.

  Attributes:
      parent_object: World object owning the scene frames (e.g. `'root'`).
      view_frame: Camera observation pose frame name.
      pregrasp_frame: Pre-grasp approach frame name above the workpiece.
      grasp_frame: Target grasp frame name on the workpiece.
      machine_approach_frame: Entry/standby frame outside the CNC enclosure.
      preplace_vise_frame: Pre-placement approach frame above the CNC vise.
      place_vise_frame: Seated part frame inside the CNC vise.
      transit_frame: Optional intermediate waypoint frame for blended transits.
  """

  parent_object: str
  view_frame: str
  pregrasp_frame: str
  grasp_frame: str
  machine_approach_frame: str
  preplace_vise_frame: str
  place_vise_frame: str
  transit_frame: str | None = None


@dataclasses.dataclass(frozen=True)
class CycleConfig:
  """Execution, force, and motion parameters for the machine tending cycle.

  Attributes:
      num_cycles: Number of cycles to run (`1` = single, `>1` = finite loop,
        `<=0` = continuous loop).
      workpiece_id: Name of the workpiece object in `solution.world`.
      approach_offset_z: Vertical offset in meters from `grasp` to `pre_grasp`.
      standoff_distance_meters: Linear approach standoff distance in meters
        prior to compliant `move_to_contact` touchdown.
      retract_distance_meters: Tool `-Z` linear retract distance in meters.
      pick_touchdown_force_newtons: Force threshold for infeed pick contact (N).
      load_seat_force_newtons: Force threshold for seating part in vise (N).
      unload_touchdown_force_newtons: Force threshold for unload contact (N).
      return_touchdown_force_newtons: Force threshold for table placement (N).
      touchdown_timeout_seconds: Timeout for `move_to_contact` actions (s).
      machining_timeout_seconds: Maximum duration to wait for CNC cycle (s).
      return_shift: Optional configuration for applying a randomized positional
        shift when returning the workpiece. If None, the object is placed at
        the exact view frame location.
      place_press_meters: Without force sensing (`robot.force_sensing` False),
        how far past the place pose, along the approach, to move when setting
        the workpiece down (machine load and infeed return), so it is pressed
        onto its support before release. Grasps are unaffected.
      workpiece_support_objects: World objects the workpiece rests on besides
        the enclosure (e.g. the ground at a drop-off). Their contact with the
        workpiece is excluded from collision checks wherever the enclosure's
        is, so the workpiece can be set down touching them.
  """

  num_cycles: int
  workpiece_id: str
  approach_offset_z: float
  standoff_distance_meters: float
  retract_distance_meters: float
  pick_touchdown_force_newtons: float
  load_seat_force_newtons: float
  unload_touchdown_force_newtons: float
  return_touchdown_force_newtons: float
  touchdown_timeout_seconds: float
  machining_timeout_seconds: float
  return_shift: "ReturnShiftConfig | None" = None
  place_press_meters: float = 0.0
  workpiece_support_objects: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class ReturnShiftConfig:
  """Parameters for randomizing the placement position of the returned workpiece."""

  center_x: float
  center_y: float
  bounds_x: float
  bounds_y: float
  bounds_rz_degrees: float = 0.0


@dataclasses.dataclass(frozen=True)
class GraspConfig:
  """Selects and tunes the grasp planning backend used during the infeed pick.

  Only `planner` and `approach_tilt_degrees` are meaningful for the built-in
  `'cuboid_center'` backend; the `moveit_*` fields are forwarded to the
  `intrinsic-moveit` integration and are ignored otherwise.

  Attributes:
      planner: Grasp planner backend (`'cuboid_center'` or `'moveit'`).
      approach_tilt_degrees: `cuboid_center` only. Pitches the grasp about the
        jaw axis so the approach leans this far from vertical, away from the
        robot base, for arms that cannot reach straight down (the reBot inside
        a printer). The pre-grasp backs off along the tilted approach. 0 keeps
        the vertical grasp.
      yaw_symmetry_degrees: `cuboid_center` only. How far the workpiece can
        turn about the vertical and look the same: 180 for a rectangular
        footprint, 90 for a square one, which lets a tilted grasp take
        whichever pair of faces leans away from the robot.
      moveit_tool_frame_name: MoveIt robot model link used as the grasp TCP.
        This is an SRDF link name, not an Object World frame.
      moveit_group_name: MoveIt planning group for the arm.
      moveit_end_effector_group: MoveIt end-effector group.
      moveit_surfaces: Workpiece surfaces to sample grasp candidates on
        (`0:+X, 1:-X, 2:+Y, 3:-Y, 4:+Z, 5:-Z`). Empty means every surface.
      moveit_num_rotations: Grasp candidates per surface, spread evenly about
        the surface normal.
      moveit_retract_dist_m: Distance in meters between the planned grasp and
        pre-grasp frames.
      moveit_timeout_ms: Grasp planning timeout in milliseconds.
      moveit_settle_seconds: Dwell before planning, letting the MoveIt planning
        scene catch up with the workpiece pose perception just published.
  """

  planner: str = GraspPlannerType.CUBOID_CENTER.value
  approach_tilt_degrees: float = 0.0
  yaw_symmetry_degrees: float = 180.0
  moveit_tool_frame_name: str = "hande_tcp"
  moveit_group_name: str = "ur_manipulator"
  moveit_end_effector_group: str = "hand"
  moveit_surfaces: tuple[int, ...] = ()
  moveit_num_rotations: int = 4
  moveit_retract_dist_m: float = 0.05
  moveit_timeout_ms: float = 15000.0
  moveit_settle_seconds: float = 0.3

  def __post_init__(self) -> None:
    valid = sorted(member.value for member in GraspPlannerType)
    if self.planner not in valid:
      raise ValueError(
        f"Unsupported grasp planner '{self.planner}' in section 'grasp'. "
        f"Expected one of {valid}."
      )
    if not 0.0 <= self.approach_tilt_degrees < 90.0:
      raise ValueError(
        f"approach_tilt_degrees must be in [0, 90), got "
        f"{self.approach_tilt_degrees}."
      )
    if self.yaw_symmetry_degrees not in (90.0, 180.0):
      raise ValueError(
        f"yaw_symmetry_degrees must be 90 or 180, got "
        f"{self.yaw_symmetry_degrees}."
      )
    if any(not 0 <= surface <= 5 for surface in self.moveit_surfaces):
      raise ValueError(
        f"moveit_surfaces entries must be in 0..5, got "
        f"{list(self.moveit_surfaces)}."
      )
    if self.moveit_num_rotations <= 0:
      raise ValueError(
        f"moveit_num_rotations must be positive, got "
        f"{self.moveit_num_rotations}."
      )
    if self.moveit_retract_dist_m <= 0.0:
      raise ValueError(
        f"moveit_retract_dist_m must be positive, got "
        f"{self.moveit_retract_dist_m}."
      )
    if self.moveit_timeout_ms <= 0.0:
      raise ValueError(
        f"moveit_timeout_ms must be positive, got {self.moveit_timeout_ms}."
      )
    if self.moveit_settle_seconds < 0.0:
      raise ValueError(
        f"moveit_settle_seconds must not be negative, got "
        f"{self.moveit_settle_seconds}."
      )

  @property
  def planner_type(self) -> GraspPlannerType:
    """Returns `planner` as its enum member."""
    return GraspPlannerType(self.planner)


@dataclasses.dataclass(frozen=True)
class DoorMarkerConfig:
  """One ArUco marker on the printer, for `ai.omts.detect_aruco_markers`.

  Attributes:
      id: ArUco marker id.
      position: (x, y, z) of the marker frame in the printer object's base
        frame, meters, with the door closed.
      quaternion: (x, y, z, w) rotation of the marker frame (OpenCV axes: x
        right, y down, z into the marker) in the printer object's base frame.
  """

  id: int
  position: tuple[float, float, float]
  quaternion: tuple[float, float, float, float]

  def __post_init__(self) -> None:
    if len(self.position) != 3:
      raise ValueError(
        f"Marker {self.id}: position needs 3 values, got {self.position}."
      )
    if len(self.quaternion) != 4:
      raise ValueError(
        f"Marker {self.id}: quaternion needs 4 values (x, y, z, w), got "
        f"{self.quaternion}."
      )
    norm = sum(v * v for v in self.quaternion) ** 0.5
    if abs(norm - 1.0) > 1e-3:
      raise ValueError(
        f"Marker {self.id}: quaternion must be unit length, got norm {norm}."
      )


_DOOR_ORIENTATION_MODES = ("RADIAL", "FIXED_AZIMUTH")
_FRAME_PREFIX_CHARS = frozenset(
  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)


@dataclasses.dataclass(frozen=True)
class DoorConfig:
  """Opening a printer's door by its handle (`src/behaviors/open_door.py`).

  Every geometric quantity is a world frame or a parameter of
  `ai.omts.generate_arc_frames`; the tree computes no poses itself.

  Attributes:
      printer_object_name: World object of the printer.
      hinge_frame_name: Frame of `printer_object_name` on the hinge axis, +z
        along the axis (the arc's pivot).
      grip_frame_name: Frame of `printer_object_name` at the handle's grip
        point; read at the start of the arc, so with the door closed.
      radial_origin_object_name: World object the tool points away from in
        `RADIAL` orientation mode (the robot's base, or `'root'`).
      hinge_joint_name: The printer's door joint.
      hinge_closed_q: The door joint's position with the door closed, rad.
        Opening by theta degrees sets it to `hinge_closed_q - radians(theta)`
        (clamped at 0, fully open).
      look_joints: Arm joint positions from which the wrist camera sees the
        door's marker(s), rad.
      camera_name: Camera resource for the marker detection.
      rgb_sensor: The camera's RGB sensor name.
      marker_size_m: Side of the markers' black square, meters.
      markers: The markers on the printer and their poses in it.
      target_deg: How far to open the door, degrees.
      fallback_deg: Shorter swings to try, in order, when the full one cannot
        be planned, degrees. Each snaps to the nearest waypoint of the full
        arc; angles at or beyond `target_deg` are skipped.
      num_waypoints: Waypoints of the full arc (1..100); waypoint i is at
        `target_deg * (i + 1) / num_waypoints`.
      grip_depth_m: How far past the grip point the tool goes along its
        approach axis, meters.
      approach_offset_m: Pre-grasp and retreat back-off along the approach
        axis, meters.
      detect: Whether to measure the printer's pose from its marker(s) before
        opening. False keeps the configured pose.
      handle_entity_name: The printer's entity the gripper holds; its contact
        with the gripper is excluded from collision checking.
      orientation_mode: `'RADIAL'` (point away from the radial origin) or
        `'FIXED_AZIMUTH'` (`azimuth_deg` for the whole arc).
      azimuth_deg: `FIXED_AZIMUTH` only: the approach azimuth, degrees.
      pitch_deg: Degrees below the horizontal the tool points, in (-90, 90).
      joint_tightness_rad: Joint blending tightness of the swing.
      frame_prefix: Prefix of the arc frames' names.
  """

  printer_object_name: str
  hinge_frame_name: str
  grip_frame_name: str
  radial_origin_object_name: str
  hinge_joint_name: str
  hinge_closed_q: float
  look_joints: tuple[float, ...]
  camera_name: str
  rgb_sensor: str
  marker_size_m: float
  markers: tuple[DoorMarkerConfig, ...]
  target_deg: float
  fallback_deg: tuple[float, ...]
  num_waypoints: int
  grip_depth_m: float
  approach_offset_m: float
  detect: bool = True
  handle_entity_name: str = "crank_handle"
  orientation_mode: str = "RADIAL"
  azimuth_deg: float = 0.0
  pitch_deg: float = 0.0
  joint_tightness_rad: float = 0.05
  frame_prefix: str = "arc"

  def __post_init__(self) -> None:
    if not self.look_joints:
      raise ValueError("door.look_joints must not be empty.")
    if not 0.0 < self.target_deg <= 180.0:
      raise ValueError(
        f"door.target_deg must be in (0, 180], got {self.target_deg}."
      )
    if any(not 0.0 < angle <= 180.0 for angle in self.fallback_deg):
      raise ValueError(
        f"door.fallback_deg entries must be in (0, 180], got "
        f"{list(self.fallback_deg)}."
      )
    if not 1 <= self.num_waypoints <= 100:
      raise ValueError(
        f"door.num_waypoints must be in 1..100, got {self.num_waypoints}."
      )
    if self.grip_depth_m < 0.0:
      raise ValueError(
        f"door.grip_depth_m must not be negative, got {self.grip_depth_m}."
      )
    if self.approach_offset_m <= 0.0:
      raise ValueError(
        f"door.approach_offset_m must be positive, got "
        f"{self.approach_offset_m}."
      )
    if self.marker_size_m <= 0.0:
      raise ValueError(
        f"door.marker_size_m must be positive, got {self.marker_size_m}."
      )
    if self.detect and not self.markers:
      raise ValueError("door.markers must not be empty when door.detect.")
    ids = [marker.id for marker in self.markers]
    if len(set(ids)) != len(ids):
      raise ValueError(f"door.markers ids must be unique, got {ids}.")
    if self.orientation_mode not in _DOOR_ORIENTATION_MODES:
      raise ValueError(
        f"door.orientation_mode must be one of {list(_DOOR_ORIENTATION_MODES)}"
        f", got '{self.orientation_mode}'."
      )
    if not -90.0 < self.pitch_deg < 90.0:
      raise ValueError(
        f"door.pitch_deg must be in (-90, 90), got {self.pitch_deg}."
      )
    if self.joint_tightness_rad <= 0.0:
      raise ValueError(
        f"door.joint_tightness_rad must be positive, got "
        f"{self.joint_tightness_rad}."
      )
    if (
      not self.frame_prefix
      or not self.frame_prefix[0].isalpha()
      or not set(self.frame_prefix) <= _FRAME_PREFIX_CHARS
    ):
      raise ValueError(
        "door.frame_prefix must be letters, digits and '_', starting with a "
        f"letter, got '{self.frame_prefix}'."
      )


@dataclasses.dataclass(frozen=True)
class AppConfig:
  """Top-level configuration for a machine tending cell deployment.

  Attributes:
      cell_name: Identifier of the configured workcell (e.g. `'omts'`).
      robot: Robot arm and tool frame configuration.
      gripper: End-effector gripper configuration.
      vision: 3D perception and pose estimation configuration.
      frames: Named world transform frames for motion planning.
      cycle: Cycle execution, force, and timeout parameters.
      machine: Optional CNC enclosure, vise, and handshake configuration.
      grasp: Grasp planner selection. Defaults to the built-in cuboid-center
        planner when the section is omitted.
      door: Optional printer door opening configuration (`None` when the
        section is omitted).
  """

  cell_name: str
  robot: RobotConfig
  gripper: GripperConfig
  vision: VisionConfig
  frames: FramesConfig
  cycle: CycleConfig
  machine: MachineConfig | None = None
  grasp: GraspConfig = dataclasses.field(default_factory=GraspConfig)
  door: DoorConfig | None = None

  @property
  def pick_touchdown(self) -> Touchdown:
    """Returns compliant touchdown parameters for picking from the infeed."""
    return Touchdown(
      force_n=self.cycle.pick_touchdown_force_newtons,
      standoff_m=self.cycle.standoff_distance_meters,
      timeout_s=self.cycle.touchdown_timeout_seconds,
      retract_after_m=self.cycle.retract_distance_meters,
    )

  @property
  def load_touchdown(self) -> Touchdown:
    """Returns compliant touchdown parameters for seating into the CNC vise."""
    return Touchdown(
      force_n=self.cycle.load_seat_force_newtons,
      standoff_m=self.cycle.standoff_distance_meters,
      timeout_s=self.cycle.touchdown_timeout_seconds,
      retract_after_m=0.0,
    )

  @property
  def unload_touchdown(self) -> Touchdown:
    """Returns compliant touchdown parameters for grasping from the CNC vise."""
    return Touchdown(
      force_n=self.cycle.unload_touchdown_force_newtons,
      standoff_m=(
        self.cycle.standoff_distance_meters + self.cycle.retract_distance_meters
      ),
      timeout_s=self.cycle.touchdown_timeout_seconds,
      retract_after_m=self.cycle.retract_distance_meters,
    )

  @property
  def return_touchdown(self) -> Touchdown:
    """Returns compliant touchdown parameters for returning to the infeed."""
    return Touchdown(
      force_n=self.cycle.return_touchdown_force_newtons,
      standoff_m=(
        self.cycle.standoff_distance_meters + self.cycle.retract_distance_meters
      ),
      timeout_s=self.cycle.touchdown_timeout_seconds,
      retract_after_m=0.0,
    )


def _construct_section(
  cls: type[_T],
  raw_data: dict[str, Any],
  section_name: str,
  file_path: pathlib.Path,
) -> _T:
  """Validates that all fields of `cls` exist in `raw_data[section_name]` and constructs it."""
  if section_name not in raw_data or not isinstance(
    raw_data[section_name], dict
  ):
    raise KeyError(
      f"Missing required configuration section '{section_name}' in {file_path}"
    )

  section_dict = dict(raw_data[section_name])
  if section_name == "gripper":
    gripper_type = section_dict.get("type")
    if gripper_type == "robotiq":
      required_fields = {
        "type",
        "joint_name",
        "open_position",
        "close_position",
      }
    elif gripper_type == "dio":
      required_fields = {
        "type",
        "dio_open_pin",
        "dio_close_pin",
        "dio_output_block_name",
      }
    elif gripper_type == "pinch":
      required_fields = {"type", "resource_name"}
    else:
      required_fields = {"type"}
  else:
    required_fields = {
      f.name
      for f in dataclasses.fields(cls)  # type: ignore[arg-type]
      if f.default is dataclasses.MISSING
      and f.default_factory is dataclasses.MISSING
    }
  missing_fields = required_fields - set(section_dict.keys())
  if missing_fields:
    sorted_missing = sorted(missing_fields)
    raise KeyError(
      f"Missing required configuration field(s) {sorted_missing} in section "
      f"'{section_name}' of {file_path}"
    )

  if section_name == "vision" and isinstance(
    section_dict.get("sensor_ids"), list
  ):
    section_dict["sensor_ids"] = tuple(
      int(x) for x in section_dict["sensor_ids"]
    )
  elif section_name == "cycle":
    if section_dict.get("return_shift") is not None:
      section_dict["return_shift"] = ReturnShiftConfig(
        **section_dict["return_shift"]
      )
    if isinstance(section_dict.get("workpiece_support_objects"), list):
      section_dict["workpiece_support_objects"] = tuple(
        str(x) for x in section_dict["workpiece_support_objects"]
      )
  elif section_name == "machine":
    for joint_key in (
      "door_open_joints",
      "door_closed_joints",
      "vise_open_joints",
      "vise_closed_joints",
    ):
      if isinstance(section_dict.get(joint_key), list):
        section_dict[joint_key] = tuple(
          float(x) for x in section_dict[joint_key]
        )
  elif section_name == "grasp" and isinstance(
    section_dict.get("moveit_surfaces"), list
  ):
    section_dict["moveit_surfaces"] = tuple(
      int(x) for x in section_dict["moveit_surfaces"]
    )
  elif section_name == "door":
    for key in ("look_joints", "fallback_deg"):
      if isinstance(section_dict.get(key), list):
        section_dict[key] = tuple(float(x) for x in section_dict[key])
    section_dict["markers"] = _construct_door_markers(
      section_dict["markers"], file_path
    )

  return cls(**section_dict)


def _construct_door_markers(
  raw_markers: Any, file_path: pathlib.Path
) -> tuple[DoorMarkerConfig, ...]:
  """Builds `door.markers`, failing loudly on a missing marker field."""
  if raw_markers is None:
    return ()
  if not isinstance(raw_markers, list):
    raise ValueError(
      f"Section 'door' field 'markers' of {file_path} must be a list."
    )
  required = {f.name for f in dataclasses.fields(DoorMarkerConfig)}
  markers = []
  for index, raw in enumerate(raw_markers):
    if not isinstance(raw, dict):
      raise ValueError(
        f"Entry {index} of 'door.markers' in {file_path} must be a mapping."
      )
    missing = required - set(raw)
    if missing:
      raise KeyError(
        f"Missing required configuration field(s) {sorted(missing)} in "
        f"section 'door.markers[{index}]' of {file_path}"
      )
    markers.append(
      DoorMarkerConfig(
        id=int(raw["id"]),
        position=tuple(float(v) for v in raw["position"]),
        quaternion=tuple(float(v) for v in raw["quaternion"]),
      )
    )
  return tuple(markers)


def load_app_config(path: str | pathlib.Path) -> AppConfig:
  """Loads and strictly validates an AppConfig from a YAML or JSON configuration file.

  Fails loudly with KeyError if any required section or field is omitted.

  Args:
      path: File path to the YAML configuration file.

  Returns:
      Populated AppConfig dataclass instance.
  """
  file_path = pathlib.Path(path)
  content = file_path.read_text(encoding="utf-8")
  raw_data = yaml.safe_load(content)

  if not isinstance(raw_data, dict):
    raise ValueError(
      f"Configuration file {file_path} must contain a top-level mapping."
    )
  if "cell_name" not in raw_data or not raw_data["cell_name"]:
    raise KeyError(f"Missing required field 'cell_name' in {file_path}")

  machine_config = (
    _construct_section(MachineConfig, raw_data, "machine", file_path)
    if "machine" in raw_data and raw_data["machine"] is not None
    else None
  )
  grasp_config = (
    _construct_section(GraspConfig, raw_data, "grasp", file_path)
    if "grasp" in raw_data and raw_data["grasp"] is not None
    else GraspConfig()
  )
  door_config = (
    _construct_section(DoorConfig, raw_data, "door", file_path)
    if "door" in raw_data and raw_data["door"] is not None
    else None
  )

  return AppConfig(
    cell_name=str(raw_data["cell_name"]),
    robot=_construct_section(RobotConfig, raw_data, "robot", file_path),
    gripper=_construct_section(GripperConfig, raw_data, "gripper", file_path),
    machine=machine_config,
    vision=_construct_section(VisionConfig, raw_data, "vision", file_path),
    frames=_construct_section(FramesConfig, raw_data, "frames", file_path),
    cycle=_construct_section(CycleConfig, raw_data, "cycle", file_path),
    grasp=grasp_config,
    door=door_config,
  )
