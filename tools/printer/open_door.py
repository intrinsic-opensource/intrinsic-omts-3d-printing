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

"""Finds the printer's door marker with the wrist camera and moves the arm.

Simulation only (it moves the arm). Modes:

  look      move the arm to a joint configuration (--joints q1..q6)
  detect    run ai.omts.detect_aruco_markers (marker id 1), compare its pose
            and the measured printer pose with the belief world (ground truth
            in simulation)
  discover  detect, then write the measured printer pose to the belief world
            in the same behavior tree (update_world)
  approach  move to a pre-grasp pose, then to the grip (the D handle's
            turning bar)
  pull      approach, close on the grip, pull to --target_deg, release, retreat
  entities, joints
            print the printer's world entities / belief joint positions

--path=blended swings the door in one move_robot call per --chunk_deg, through
waypoints every --wp_deg; --path=stepwise moves --step_deg at a time.
--az_mode=radial (default) points the tool from the robot's base at the grip
point; the bar turns, so the wrist need not. The hinge is passive in Gazebo
(--//models/printer:hinge=passive): run sync_door alongside and pass
--no_belief_door so the belief door follows the real one.

  bazel run //tools/printer:open_door -- --address=localhost:17080 \
      --mode=detect
"""

import argparse
import math
import sys
import time
from collections.abc import Sequence

import numpy as np
from intrinsic.math.python import data_types, proto_conversion
from intrinsic.solutions import behavior_tree as bt
from intrinsic.solutions import deployments, execution
from intrinsic.util.status import extended_status_pb2
from intrinsic.world.proto import object_world_updates_pb2

from src.core import door
from src.core.config import GripperConfig, RobotConfig
from src.hardware.gripper import PinchGripper
from src.hardware.robot import Robot

CAMERA_RESOURCE = "orbbec_camera"
RGB_SENSOR = "rgb"
LOOK_CONFIG = "door_look"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument(
    "--mode",
    choices=[
      "look",
      "detect",
      "discover",
      "approach",
      "pull",
      "entities",
      "joints",
    ],
    required=True,
  )
  parser.add_argument("--robot_name", default="rebot")
  parser.add_argument("--joints", nargs=6, type=float, default=None)
  parser.add_argument("--marker_size_m", type=float, default=door.MARKER_SIZE_M)
  parser.add_argument("--theta_deg", type=float, default=0.0)
  parser.add_argument("--target_deg", type=float, default=135.0)
  parser.add_argument("--step_deg", type=float, default=6.0)
  parser.add_argument("--pregrasp_m", type=float, default=0.06)
  parser.add_argument("--allow_contact", action="store_true")
  parser.add_argument("--hold", action="store_true", help="No release.")
  parser.add_argument(
    "--path",
    choices=["stepwise", "blended"],
    default="blended",
    help="stepwise: one move per step_deg, stopping at each; blended: one "
    "move_robot call per chunk_deg, through waypoints every wp_deg, blended "
    "into one smooth trajectory.",
  )
  parser.add_argument("--chunk_deg", type=float, default=135.0)
  parser.add_argument(
    "--belief_door_at",
    choices=["end", "start"],
    default="end",
    help="Which angle of a chunk the planner's door is placed at: its end "
    "(the door's furthest position) or its start.",
  )
  parser.add_argument("--wp_deg", type=float, default=3.0)
  parser.add_argument(
    "--retry_step_deg",
    type=float,
    default=5.0,
    help="blended path: when a chunk cannot be planned, retry with its end "
    "angle lowered by this much (0: do not retry).",
  )
  parser.add_argument(
    "--motion",
    choices=["LINEAR", "JOINT", "ANY"],
    default="JOINT",
    help="JOINT (default): each waypoint is a joint-space goal, which gets the "
    "arm through the pass over its base axis; LINEAR: straight Cartesian "
    "segments, which fail there (about 60 deg).",
  )
  parser.add_argument("--blend_trans", type=float, default=0.01)
  parser.add_argument("--blend_rot", type=float, default=0.1)
  parser.add_argument("--blend_joint", type=float, default=0.05)
  parser.add_argument("--az", type=float, default=None, help="Tool azimuth.")
  parser.add_argument(
    "--az_mode",
    choices=["radial", "fixed"],
    default="radial",
    help="radial: the tool points from the robot's base at the grip point "
    "(the bar turns, so the wrist need not); fixed: --az for the whole arc.",
  )
  parser.add_argument(
    "--ready",
    nargs=6,
    type=float,
    default=None,
    help="Joint configuration to move to before approaching the grip: it "
    "decides which inverse-kinematics branch (which way the base looks) the "
    "planner picks for the grasp.",
  )
  parser.add_argument(
    "--grip_z",
    type=float,
    default=None,
    help="Diagnostic: grip height in the door frame (default: the D handle's).",
  )
  parser.add_argument("--pitch", type=float, default=None, help="Tool pitch.")
  parser.add_argument(
    "--no_close",
    action="store_true",
    help="Diagnostic: follow the whole path with the gripper left open.",
  )
  parser.add_argument(
    "--no_write_pose",
    dest="write_pose",
    action="store_false",
    help="discover: detect and report, but keep the configured printer pose.",
  )
  parser.add_argument(
    "--no_belief_door",
    dest="belief_door",
    action="store_false",
    help="Do not write the belief door angle during the pull (use with "
    "sync_door, which writes it from Gazebo; both writing would clash).",
  )
  parser.add_argument("--marker_ids", nargs="+", type=int, default=[1])
  return parser.parse_args(argv)


def look(solution, robot_name: str, joints: Sequence[float]) -> None:
  """Moves the arm to a joint configuration (stored as a named one)."""
  world = solution.world
  arm = getattr(world, robot_name)
  world.update_kinematic_object_joint_configurations(
    kinematic_object=arm,
    named_joint_configurations_to_set=[
      object_world_updates_pb2.NamedJointConfiguration(
        name=LOOK_CONFIG, joint_positions=list(joints)
      )
    ],
  )
  robot = Robot(
    solution=solution,
    config=RobotConfig(
      arm_part_name=robot_name,
      tool_object_name="gripper",
      tool_frame_name="tool_frame",
    ),
  )
  try:
    # The arm may be left touching the D handle's bar by an earlier run.
    solution.executive.run(
      robot.build_move_joint_task(
        LOOK_CONFIG,
        excluded_collision_pairs=[("gripper", CONTACT_TARGET)],
      )
    )
  except execution.ExecutionFailedError as e:
    print(f"[!] Motion failed: {e}")
    sys.exit(1)
  print(f"[✓] At {[round(j, 3) for j in joints]}")


def printer_t_marker(marker_id: int, theta_deg: float = 0.0) -> np.ndarray:
  pos, rot = door.marker_in_printer(marker_id, theta_deg)
  m = np.eye(4)
  m[:3, :3] = np.array(rot)
  m[:3, 3] = pos
  return m


def run_detect(solution, ids: Sequence[int], size_m: float):
  """Runs ai.omts.detect_aruco_markers through the executive; the result."""
  executive = solution.executive
  if executive.has_operation and not executive.operation.done:
    raise RuntimeError("The executive has an active operation; stop it first")
  kwargs = {
    "camera": solution.resources[CAMERA_RESOURCE],
    "rgb_sensor": RGB_SENSOR,
    "marker_ids": list(ids),
    "marker_size_m": size_m,
    "_with_recommended_config": False,
  }
  kwargs["printer_t_marker"] = [
    proto_conversion.pose_to_proto(
      data_types.Pose3.from_matrix4x4(printer_t_marker(i))
    )
    for i in ids
  ]
  action = solution.skills.ai.omts.detect_aruco_markers(**kwargs)
  tree = bt.BehaviorTree(
    name="Detect ArUco markers", root=bt.Task(action=action, name="detect")
  )
  executive.run(tree, silence_outputs=True)
  return executive.operation.blackboard.get_value(action.result)


def pose_matrix(pose_proto) -> np.ndarray:
  return proto_conversion.pose_from_proto(pose_proto).matrix4x4()


def detect(solution, args) -> None:
  ids = args.marker_ids
  result = run_detect(solution, ids, args.marker_size_m)
  world = solution.world
  printer = world.printer
  truth = world.get_transform(world.root, printer).matrix4x4()
  for m in result.markers:
    print(
      f"  marker {m.id}: incidence {m.incidence_deg:.1f} deg,"
      f" side {m.side_px:.0f} px, reproj {m.reprojection_px:.2f} px,"
      f" ippe ratio {m.ippe_ratio:.1f}"
    )
    want = truth @ printer_t_marker(m.id)
    got = pose_matrix(m.root_t_marker)
    err_mm = np.linalg.norm(got[:3, 3] - want[:3, 3]) * 1000
    print(f"    root_t_marker error {err_mm:.1f} mm")
  got = pose_matrix(result.root_t_printer)
  dyaw = math.degrees(
    math.atan2(got[1, 0], got[0, 0]) - math.atan2(truth[1, 0], truth[0, 0])
  )
  print(
    f"printer: measured xyz {np.round(got[:3, 3], 4).tolist()},"
    f" belief {np.round(truth[:3, 3], 4).tolist()}"
  )
  print(
    f"  error {np.linalg.norm(got[:2, 3] - truth[:2, 3]) * 1000:.1f} mm in xy,"
    f" {(got[2, 3] - truth[2, 3]) * 1000:.1f} mm in z, yaw {dyaw:.2f} deg,"
    f" joint reproj {result.joint_reprojection_px:.2f} px"
  )


def discover(solution, args) -> None:
  """detect -> blackboard -> update_world(update_transform) in one tree."""
  executive = solution.executive
  if executive.has_operation and not executive.operation.done:
    raise RuntimeError("The executive has an active operation; stop it first")
  skills = solution.skills.ai
  world = solution.world
  ids = args.marker_ids
  detect_action = skills.omts.detect_aruco_markers(
    camera=solution.resources[CAMERA_RESOURCE],
    rgb_sensor=RGB_SENSOR,
    marker_ids=list(ids),
    marker_size_m=args.marker_size_m,
    printer_t_marker=[
      proto_conversion.pose_to_proto(
        data_types.Pose3.from_matrix4x4(printer_t_marker(i))
      )
      for i in ids
    ],
    _with_recommended_config=False,
  )
  w = skills.intrinsic.update_world.intrinsic_proto.world
  update = skills.intrinsic.update_world(
    update=w.ObjectWorldUpdate(
      update_transform=w.UpdateTransformRequest(
        node_a=world.root,
        node_b=world.printer,
        node_to_update=world.printer,
        a_t_b=detect_action.result.root_t_printer,
      )
    )
  )
  steps = [bt.Task(action=detect_action, name="detect")]
  if args.write_pose:
    steps.append(bt.Task(action=update, name="write printer pose"))
  tree = bt.BehaviorTree(
    name="Discover the printer", root=bt.Sequence(children=steps)
  )
  before = world.get_transform(world.root, world.printer).matrix4x4()
  try:
    executive.run(tree, silence_outputs=True)
  except execution.ExecutionFailedError:
    banner = "!" * 72
    print(banner)
    print("PRINTER NOT DETECTED: the marker was not found (or failed the")
    print("viewing rule). The belief world keeps the CONFIGURED printer pose")
    print(f"{np.round(before[:3, 3], 4).tolist()}; nothing was measured.")
    print("Any motion that follows is planned from that configured pose, as if")
    print("the printer were exactly where the config says.")
    print(banner)
    sys.exit(3)
  after = solution.world.get_transform(
    solution.world.root, solution.world.printer
  ).matrix4x4()
  print(
    "PRINTER DETECTED: pose MEASURED from the marker"
    + (" and written to belief" if args.write_pose else " (not written)")
  )
  print(f"belief printer before {np.round(before[:3, 3], 4).tolist()}")
  print(f"belief printer after  {np.round(after[:3, 3], 4).tolist()}")


def pose_from_matrix(m: np.ndarray) -> data_types.Pose3:
  return data_types.Pose3.from_matrix4x4(m)


def set_frame(world, name: str, root_t_frame: np.ndarray) -> None:
  """Creates or moves a frame on the root object."""
  pose = pose_from_matrix(root_t_frame)
  try:
    node = getattr(world.root, name)
    world.update_transform(node_a=world.root, node_b=node, a_t_b=pose)
  except AttributeError:
    world.create_frame(frame_name=name, parent=world.root, parent_t_frame=pose)


def _status_lines(status, depth: int = 0) -> list[str]:
  """User reports of an ExtendedStatus and its context, as text lines."""
  lines = []
  pad = "  " * depth
  title = status.title or status.status_code.code
  lines.append(f"{pad}{title}")
  if status.user_report.message:
    lines.append(f"{pad}  {status.user_report.message}")
  for inner in status.context:
    lines += _status_lines(inner, depth + 1)
  return lines


def print_failure(solution) -> None:
  """Prints why the last operation failed (the planner's own words)."""
  try:
    err = solution.executive.operation.proto.error
    for detail in err.details:
      status = extended_status_pb2.ExtendedStatus()
      if detail.Unpack(status):
        print("\n".join(_status_lines(status))[:1800])
        return
    print(str(err.message))
  except Exception as exc:  # pylint: disable=broad-exception-caught
    print(f"(no error details: {exc})")


# What the gripper may touch: only the D handle's turning bar.
CONTACT_TARGET = "printer:crank_handle"


def knob_matrix(
  root_t_printer: np.ndarray,
  theta_deg: float,
  back_m: float = 0.0,
  az_mode: str = "radial",
) -> np.ndarray:
  """Root-frame 4x4 of the tool at the D handle's grip point at angle theta.

  The position follows the door's arc. The tool is level; its azimuth is
  either fixed (az_mode "fixed", KNOB_APPROACH_AZ_DEG) or "radial": it points
  along the line from the robot's base to the grip point, so the arm reaches
  straight at its target and the wrist joint stays near its centre. Because
  the bar turns freely about the vertical axis, the tool's azimuth is free
  once the handle is held. back_m backs off along the approach axis; the tool
  goes GRIP_DEPTH_M past the bar's axis so the bar sits on the fingers' flat
  pads.
  """
  centre = (root_t_printer @ np.append(door.knob_in_printer(theta_deg), 1.0))[
    :3
  ]
  az = None
  if az_mode == "radial":
    az = math.degrees(math.atan2(centre[1], centre[0]))
  m = np.eye(4)
  m[:3, :3] = np.array(door.knob_tool_rotation_world(az))
  m[:3, 3] = centre + (door.GRIP_DEPTH_M - back_m) * m[:3, 2]
  return m


def grasp_target(
  root_t_printer: np.ndarray, args, theta_deg: float, back_m: float = 0.0
) -> np.ndarray:
  return knob_matrix(root_t_printer, theta_deg, back_m, args.az_mode)


def approach(solution, args) -> None:
  """Moves the tool to a pre-grasp pose, then to the handle (no pulling)."""
  if args.ready is not None:
    look(solution, args.robot_name, args.ready)
  world = solution.world
  robot = Robot(
    solution=solution,
    config=RobotConfig(
      arm_part_name=args.robot_name,
      tool_object_name="gripper",
      tool_frame_name="tool_frame",
    ),
  )
  root_t_printer = world.get_transform(world.root, world.printer).matrix4x4()
  theta = args.theta_deg
  pre = grasp_target(root_t_printer, args, theta, args.pregrasp_m)
  grasp = grasp_target(root_t_printer, args, theta)
  set_frame(world, "door_pregrasp", pre)
  set_frame(world, "door_grasp", grasp)
  print(f"pre-grasp {np.round(pre[:3, 3], 3).tolist()}")
  print(f"grasp     {np.round(grasp[:3, 3], 3).tolist()}")
  pairs = [("gripper", CONTACT_TARGET)] if args.allow_contact else None
  gripper = PinchGripper(
    solution=solution,
    config=GripperConfig(type="pinch", resource_name="gripper"),
  )
  steps = [
    gripper.build_open_task(name="open the gripper"),
    robot.build_move_cartesian_task(
      "door_pregrasp", "root", "ANY", excluded_collision_pairs=pairs
    ),
    robot.build_move_cartesian_task(
      "door_grasp", "root", "LINEAR", excluded_collision_pairs=pairs
    ),
  ]
  for step in steps:
    try:
      solution.executive.run(step, silence_outputs=True)
    except execution.ExecutionFailedError as e:
      print(f"[!] {e}")
      print_failure(solution)
      sys.exit(1)
    print(f"[✓] {step.name}")


def pull(solution, args) -> None:
  """Approach, close on the grip, pull along the door's arc, release."""
  approach(solution, args)
  world = solution.world
  robot = Robot(
    solution=solution,
    config=RobotConfig(
      arm_part_name=args.robot_name,
      tool_object_name="gripper",
      tool_frame_name="tool_frame",
    ),
  )
  gripper = PinchGripper(
    solution=solution,
    config=GripperConfig(type="pinch", resource_name="gripper"),
  )
  root_t_printer = world.get_transform(world.root, world.printer).matrix4x4()
  pairs = [("gripper", CONTACT_TARGET)]

  def run(node, quiet_failure=False):
    try:
      solution.executive.run(node, silence_outputs=True)
    except execution.ExecutionFailedError as e:
      if quiet_failure:
        print(f"[-] {node.name}: not plannable")
      else:
        print(f"[!] {node.name}: {e}")
        print_failure(solution)
      return False
    print(f"[✓] {node.name}")
    return True

  if args.no_close:
    print("DIAGNOSTIC: the gripper stays open")
  elif not run(gripper.build_close_task(name="close on the grip")):
    sys.exit(1)
  theta = args.theta_deg

  def set_belief_door(angle_deg: float) -> None:
    # The hinge is passive, so the belief world does not follow it: tell the
    # planner where the door is (commanded angle) so the arm avoids it.
    printer = world.get_kinematic_object("printer")
    names = list(printer.joint_entity_names)
    positions = [float(v) for v in printer.joint_positions]
    positions[names.index("door_hinge")] = door.theta_to_q(angle_deg)
    world.update_joint_positions(printer, positions)

  started = time.time()
  if args.path == "stepwise":
    while theta < args.target_deg - 1e-9:
      theta = min(theta + args.step_deg, args.target_deg)
      if args.belief_door:
        set_belief_door(theta)
      set_frame(
        world, "door_grasp_k", grasp_target(root_t_printer, args, theta)
      )
      ok = run(
        robot.build_move_cartesian_task(
          "door_grasp_k",
          "root",
          "LINEAR",
          excluded_collision_pairs=pairs,
          name=f"pull to {theta:.0f} deg",
        )
      )
      if not ok:
        break
  else:
    while theta < args.target_deg - 1e-9:
      # A chunk is planned whole: one unreachable sample fails all of it. When
      # it does, retry with the end angle lowered until it plans, so the door
      # opens as far as the arm reaches (--retry_step_deg 0 disables this).
      end = min(theta + args.chunk_deg, args.target_deg)
      step = args.retry_step_deg
      floor = theta + args.wp_deg
      done = False
      while True:
        n = max(1, round((end - theta) / args.wp_deg))
        angles = [theta + (end - theta) * (i + 1) / n for i in range(n)]
        if args.belief_door:
          set_belief_door(end if args.belief_door_at == "end" else theta)
        frames = []
        for i, a in enumerate(angles):
          name = f"door_arc_{i}"
          set_frame(world, name, grasp_target(root_t_printer, args, a))
          frames.append(("root", name))
        blend = {}
        if args.motion == "JOINT":
          blend["joint_tightness_rad"] = args.blend_joint
        else:
          blend["corner_rounding"] = (args.blend_trans, args.blend_rot)
        last_try = step <= 0 or end - step < floor - 1e-9
        done = run(
          robot.build_move_blended_cartesian_task(
            frames,
            motion_type=args.motion,
            excluded_collision_pairs=pairs,
            name=f"arc {theta:.0f} -> {end:.0f} deg ({n} waypoints,"
            f" {args.motion})",
            **blend,
          ),
          quiet_failure=not last_try,
        )
        if done or last_try:
          break
        end -= step
      if not done:
        break
      lowered = end < min(theta + args.chunk_deg, args.target_deg) - 1e-9
      theta = end
      if lowered:
        break  # the arm's reach ends here; do not retry further chunks
  print(
    f"PATH {args.path} {args.motion}: reached {theta:.0f} deg of "
    f"{args.target_deg:.0f} in {time.time() - started:.1f} s"
  )
  if args.hold:
    print("holding the grip (--hold)")
    return
  run(gripper.build_open_task(name="release"))
  set_frame(
    world,
    "door_retreat",
    grasp_target(root_t_printer, args, theta, args.pregrasp_m),
  )
  run(
    robot.build_move_cartesian_task(
      "door_retreat",
      "root",
      "LINEAR",
      excluded_collision_pairs=pairs,
      name="retreat",
    )
  )


def main(argv: Sequence[str] | None = None) -> None:
  args = parse_args(argv)
  if args.az is not None:
    door.KNOB_APPROACH_AZ_DEG = args.az
  if args.pitch is not None:
    door.KNOB_APPROACH_PITCH_DEG = args.pitch
  if args.grip_z is not None:
    door.KNOB_POS = (door.KNOB_POS[0], door.KNOB_POS[1], args.grip_z)
  solution = deployments.connect(address=args.address)
  if args.mode == "look":
    if args.joints is None:
      sys.exit("--joints is required for --mode=look")
    look(solution, args.robot_name, args.joints)
  elif args.mode == "detect":
    detect(solution, args)
  elif args.mode == "discover":
    discover(solution, args)
  elif args.mode == "joints":
    arm = solution.world.get_kinematic_object(args.robot_name)
    print("arm joints", [round(float(v), 3) for v in arm.joint_positions])
  elif args.mode == "entities":
    printer = solution.world.get_object("printer")
    w = solution.world
    print("printer in root", w.get_transform(w.root, w.printer).translation)
    print("joints", list(w.get_kinematic_object("printer").joint_positions))
    print(
      "tool in root", w.get_transform(w.root, w.gripper.tool_frame).translation
    )
    print([n for n in dir(printer) if not n.startswith("_")])
    for n in (
      "child_names",
      "child_ids",
      "id",
      "joint_entity_names",
      "joint_entity_ids",
    ):
      if hasattr(printer, n):
        print(n, getattr(printer, n))
  elif args.mode == "approach":
    approach(solution, args)
  else:
    args.allow_contact = True
    pull(solution, args)


if __name__ == "__main__":
  main()
