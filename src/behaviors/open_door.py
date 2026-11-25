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

"""Opens the printer's door: one behavior tree made of installed skills.

The tree, in order (skill ids in brackets):

  1. Look at the marker: joint move to `door.look_joints`
     [ai.intrinsic.move_robot].
  2. Locate the printer (omitted when `door.detect` is False): detect the
     marker(s) [ai.omts.detect_aruco_markers], then write the measured
     `root_t_printer`, read from the blackboard, as the printer's pose
     [ai.intrinsic.update_world].
  3. Generate the arc frames about the hinge [ai.omts.generate_arc_frames]:
     <prefix>_pregrasp, <prefix>_grasp, <prefix>_wp_00..wp_(N-1) and
     <prefix>_retreat, as root-frame tool poses. Every pose in the tree comes
     from these frames; the tree computes none itself.
  4. Open the gripper, move to <prefix>_pregrasp (ANY) and <prefix>_grasp
     (LINEAR), close on the handle [ai.intrinsic.control_pinch_gripper,
     ai.intrinsic.move_robot].
  5. Swing the door: a Fallback over blended JOINT moves through the first M
     waypoints, the full arc first, then the configured shorter ones. Each is
     followed by an update_world that sets the belief door joint to the angle
     it reached, so later planning sees the open door. When none can be
     planned, the last alternative releases the handle, backs off and fails.
  6. Release the handle and back off by `door.approach_offset_m` along the
     tool's -Z [ai.intrinsic.move_robot, relative].

Besides the skill calls, the pinch gripper adapter adds a short dwell (a
PythonScript sleep) after each gripper command; the belief-door write after a
swing is best effort. The Fallback also fires when a swing fails during motion,
not only when it cannot be planned.

Retreat: the arm ends at the last waypoint of whichever swing ran, and every
waypoint's retreat is that waypoint backed off along the tool's approach axis
(the skill's <prefix>_retreat is exactly that for the full arc). A relative
move along tool -Z therefore reaches the right retreat pose for every
alternative without generating more frames or choosing a frame at run time.

The door is assumed closed when the tree starts (as `grip_frame_name` must be
read at the start of the arc, and the belief door angles written are absolute).
"""

import dataclasses
import math
from collections.abc import Sequence
from typing import Any

from intrinsic.icon.proto import joint_space_pb2
from intrinsic.math.proto import point_pb2, pose_pb2, quaternion_pb2
from intrinsic.solutions import behavior_tree as bt
from intrinsic.world.proto import (
  object_world_refs_pb2,
  object_world_updates_pb2,
)

from src.behaviors.motions import (
  create_move_to_frame_task,
  create_relative_retract_task,
)
from src.core.config import DoorConfig, DoorMarkerConfig
from src.hardware.gripper import GripperInterface
from src.hardware.robot import Robot
from src.utils.math_utils import create_transform_node_ref

# The arc frames are children of the root object.
ROOT_OBJECT = "root"


@dataclasses.dataclass(frozen=True)
class SwingAlternative:
  """One door swing: through the first `num_waypoints` arc waypoints.

  Attributes:
      num_waypoints: How many waypoints of the full arc the swing goes through.
      angle_deg: The door angle at its last waypoint, degrees.
  """

  num_waypoints: int
  angle_deg: float


def pregrasp_frame_name(prefix: str) -> str:
  """generate_arc_frames' pre-grasp frame (start angle, backed off)."""
  return f"{prefix}_pregrasp"


def grasp_frame_name(prefix: str) -> str:
  """generate_arc_frames' grasp frame (start angle)."""
  return f"{prefix}_grasp"


def waypoint_frame_name(prefix: str, index: int) -> str:
  """generate_arc_frames' waypoint frame `index` (0-based, 2 digits)."""
  return f"{prefix}_wp_{index:02d}"


def swing_alternatives(door_cfg: DoorConfig) -> list[SwingAlternative]:
  """The swings to try, longest first: the full arc, then the fallbacks.

  A fallback angle snaps to the nearest waypoint of the full arc (at least
  the first). Angles at or beyond the target, and repeats, are skipped.
  """
  n = door_cfg.num_waypoints
  target = door_cfg.target_deg
  counts = [n]
  for angle in door_cfg.fallback_deg:
    if angle >= target:
      continue
    m = min(n, max(1, round(angle * n / target)))
    if m not in counts:
      counts.append(m)
  return [
    SwingAlternative(num_waypoints=m, angle_deg=target * m / n)
    for m in sorted(counts, reverse=True)
  ]


def hinge_position(door_cfg: DoorConfig, angle_deg: float) -> float:
  """The door joint's position (rad) with the door open by `angle_deg`."""
  return max(0.0, door_cfg.hinge_closed_q - math.radians(angle_deg))


def _contact_pairs(
  door_cfg: DoorConfig, tool_object_name: str
) -> list[tuple[str, str]]:
  """The gripper may touch the handle it holds, nothing else."""
  handle = f"{door_cfg.printer_object_name}:{door_cfg.handle_entity_name}"
  return [(tool_object_name, handle)]


def _marker_pose(marker: DoorMarkerConfig) -> pose_pb2.Pose:
  x, y, z = marker.position
  qx, qy, qz, qw = marker.quaternion
  return pose_pb2.Pose(
    position=point_pb2.Point(x=x, y=y, z=z),
    orientation=quaternion_pb2.Quaternion(x=qx, y=qy, z=qz, w=qw),
  )


def build_locate_printer_subtree(
  solution: Any, door_cfg: DoorConfig
) -> bt.Node:
  """Detects the printer's marker(s) and writes the measured printer pose.

  The detection's `root_t_printer` goes to update_world through the
  blackboard, in the same tree.
  """
  skills = solution.skills.ai
  detect = skills.omts.detect_aruco_markers(
    camera=solution.resources[door_cfg.camera_name],
    rgb_sensor=door_cfg.rgb_sensor,
    marker_ids=[marker.id for marker in door_cfg.markers],
    marker_size_m=door_cfg.marker_size_m,
    printer_t_marker=[_marker_pose(marker) for marker in door_cfg.markers],
  )
  update_world = skills.intrinsic.update_world
  world_ns = update_world.intrinsic_proto.world
  printer = create_transform_node_ref(door_cfg.printer_object_name)
  write_pose = update_world(
    update=world_ns.ObjectWorldUpdate(
      update_transform=world_ns.UpdateTransformRequest(
        node_a=create_transform_node_ref(ROOT_OBJECT),
        node_b=printer,
        node_to_update=printer,
        a_t_b=detect.result.root_t_printer,
      )
    )
  )
  return bt.Sequence(
    name="Door: locate the printer",
    children=[
      bt.Task(action=detect, name="Door: detect the printer's marker"),
      bt.Task(action=write_pose, name="Door: write the measured printer pose"),
    ],
  )


def build_generate_arc_frames_task(
  solution: Any, door_cfg: DoorConfig
) -> bt.Node:
  """Writes the pre-grasp, grasp, waypoint and retreat frames of the arc.

  Opening the door by theta is a rotation of -theta about the hinge's +z.
  """
  arc_skill = solution.skills.ai.omts.generate_arc_frames
  orientation_cls = arc_skill.omts.motion.ToolOrientation
  orientation = orientation_cls(
    mode=getattr(orientation_cls.Mode, door_cfg.orientation_mode),
    azimuth_deg=door_cfg.azimuth_deg,
    pitch_deg=door_cfg.pitch_deg,
  )
  printer = door_cfg.printer_object_name
  action = arc_skill(
    pivot_frame=create_transform_node_ref(printer, door_cfg.hinge_frame_name),
    grip_frame=create_transform_node_ref(printer, door_cfg.grip_frame_name),
    radial_origin_frame=create_transform_node_ref(
      door_cfg.radial_origin_object_name
    ),
    total_angle_deg=-door_cfg.target_deg,
    num_waypoints=door_cfg.num_waypoints,
    orientation=orientation,
    grip_depth_m=door_cfg.grip_depth_m,
    approach_offset_m=door_cfg.approach_offset_m,
    frame_prefix=door_cfg.frame_prefix,
  )
  return bt.Task(
    action=action,
    name=(
      f"Door: generate the arc frames ({door_cfg.target_deg:g} deg,"
      f" {door_cfg.num_waypoints} waypoints)"
    ),
  )


def build_set_belief_door_task(
  solution: Any, door_cfg: DoorConfig, angle_deg: float
) -> bt.Node:
  """Sets the belief door joint (only it) to `angle_deg` open."""
  update = object_world_updates_pb2.ObjectWorldUpdate(
    update_object_joint=object_world_updates_pb2.UpdateObjectJointRequest(
      object=object_world_refs_pb2.ObjectReference(
        by_name=object_world_refs_pb2.ObjectReferenceByName(
          object_name=door_cfg.printer_object_name
        )
      ),
      joint_name=door_cfg.hinge_joint_name,
      joint_position=hinge_position(door_cfg, angle_deg),
    )
  )
  return bt.Task(
    action=solution.skills.ai.intrinsic.update_world(update=update),
    name=f"Door: belief door at {angle_deg:.0f} deg",
  )


def build_swing_fallback(
  solution: Any,
  robot: Robot,
  gripper: GripperInterface,
  door_cfg: DoorConfig,
  contact: Sequence[tuple[str, str]],
) -> bt.Node:
  """Tries the swings longest first; each records the angle it reached."""
  prefix = door_cfg.frame_prefix
  tries: list[bt.Node] = []
  for alternative in swing_alternatives(door_cfg):
    frames = [
      (ROOT_OBJECT, waypoint_frame_name(prefix, i))
      for i in range(alternative.num_waypoints)
    ]
    label = f"{alternative.angle_deg:.0f} deg"
    tries.append(
      bt.Sequence(
        name=f"Door: swing to {label}",
        children=[
          robot.build_move_blended_cartesian_task(
            frames,
            motion_type="JOINT",
            excluded_collision_pairs=contact,
            name=(
              f"Door: swing to {label}"
              f" ({alternative.num_waypoints} waypoints, JOINT)"
            ),
            joint_tightness_rad=door_cfg.joint_tightness_rad,
          ),
          # Best effort: a failed belief write must not count as a failed
          # swing, or the Fallback would swing the arm again.
          bt.Fallback(
            name=f"Door: record the door at {label} (best effort)",
            children=[
              build_set_belief_door_task(
                solution, door_cfg, alternative.angle_deg
              ),
              bt.Sequence(name="Door: belief door not updated", children=[]),
            ],
          ),
        ],
      )
    )
  tries.append(
    bt.Sequence(
      name="Door: no swing plannable",
      children=[
        gripper.build_open_task(name="Door: release the handle (no swing)"),
        create_relative_retract_task(
          robot,
          door_cfg.approach_offset_m,
          excluded_collision_pairs=contact,
          task_name="Door: back off the handle (no swing)",
        ),
        bt.Fail(
          failure_message="No door swing could be planned or executed",
          name="Door: not opened",
        ),
      ],
    )
  )
  return bt.Fallback(children=tries, name="Door: swing")


def build_open_door_tree(
  solution: Any,
  robot: Robot,
  gripper: GripperInterface,
  door_cfg: DoorConfig,
  *,
  tool_object_name: str = "gripper",
  name: str = "Open the printer door",
) -> bt.Node:
  """Builds the door-opening tree (see the module docstring).

  Args:
      solution: Connected SBL solution (its skills and resources).
      robot: Robot adapter of the arm.
      gripper: Gripper adapter.
      door_cfg: The door section of the cell configuration.
      tool_object_name: World object of the gripper; only its contact with the
        handle is excluded from collision checking.
      name: Name of the returned Sequence.

  Returns:
      A Sequence node; wrap it in `bt.BehaviorTree` to run it.
  """
  contact = _contact_pairs(door_cfg, tool_object_name)
  prefix = door_cfg.frame_prefix
  children: list[bt.Node] = [
    # The arm may be left touching the handle by an earlier run.
    robot.build_move_joint_task(
      joint_space_pb2.JointVec(joints=list(door_cfg.look_joints)),
      name="Door: look at the marker",
      excluded_collision_pairs=contact,
    )
  ]
  if door_cfg.detect:
    children.append(build_locate_printer_subtree(solution, door_cfg))
  children += [
    build_generate_arc_frames_task(solution, door_cfg),
    gripper.build_open_task(name="Door: open the gripper"),
    create_move_to_frame_task(
      robot,
      pregrasp_frame_name(prefix),
      ROOT_OBJECT,
      motion_type="ANY",
      excluded_collision_pairs=contact,
      task_name="Door: move to the pre-grasp (ANY)",
    ),
    create_move_to_frame_task(
      robot,
      grasp_frame_name(prefix),
      ROOT_OBJECT,
      motion_type="LINEAR",
      excluded_collision_pairs=contact,
      task_name="Door: move to the grasp (LINEAR)",
    ),
    gripper.build_close_task(name="Door: close on the handle"),
    build_swing_fallback(solution, robot, gripper, door_cfg, contact),
    gripper.build_open_task(name="Door: release the handle"),
    create_relative_retract_task(
      robot,
      door_cfg.approach_offset_m,
      excluded_collision_pairs=contact,
      task_name=(
        f"Door: retreat {door_cfg.approach_offset_m * 100:.1f} cm (-Z tool)"
      ),
    ),
  ]
  return bt.Sequence(name=name, children=children)
