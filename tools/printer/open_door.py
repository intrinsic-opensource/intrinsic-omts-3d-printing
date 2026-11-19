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

"""Finds the printer's door markers with the wrist camera and moves the arm.

Simulation only (it moves the arm). Modes:

  look    move the arm to a joint configuration (--joints q1..q6)
  discover  detect, then write the measured printer pose to the belief world
          in the same behavior tree (update_world)
  detect  run ai.omts.detect_aruco_markers, compare each marker's pose and the
          measured printer pose with the belief world (ground truth in
          simulation)

  bazel run //tools/printer:open_door -- --address=localhost:17080 \
      --mode=detect
"""

import argparse
import math
import sys
from collections.abc import Sequence

import numpy as np
from intrinsic.math.python import data_types, proto_conversion
from intrinsic.solutions import behavior_tree as bt
from intrinsic.solutions import deployments, execution
from intrinsic.world.proto import object_world_updates_pb2

from src.core import door
from src.core.config import RobotConfig
from src.hardware.robot import Robot

CAMERA_RESOURCE = "orbbec_camera"
RGB_SENSOR = "rgb"
LOOK_CONFIG = "door_look"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument(
    "--mode", choices=["look", "detect", "discover"], required=True
  )
  parser.add_argument("--robot_name", default="rebot")
  parser.add_argument("--joints", nargs=6, type=float, default=None)
  parser.add_argument("--marker_size_m", type=float, default=door.MARKER_SIZE_M)
  parser.add_argument("--marker_ids", nargs="+", type=int, default=[1, 2])
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
    solution.executive.run(robot.build_move_joint_task(LOOK_CONFIG))
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


def run_detect(solution, ids: Sequence[int], size_m: float, with_printer: bool):
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
  if with_printer:
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
  result = run_detect(solution, ids, args.marker_size_m, True)
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
    print(
      f"    root_t_marker error {np.linalg.norm(got[:3, 3] - want[:3, 3]) * 1000:.1f} mm"
    )
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
  tree = bt.BehaviorTree(
    name="Discover the printer",
    root=bt.Sequence(
      children=[
        bt.Task(action=detect_action, name="detect"),
        bt.Task(action=update, name="write printer pose"),
      ]
    ),
  )
  before = world.get_transform(world.root, world.printer).matrix4x4()
  executive.run(tree, silence_outputs=True)
  after = solution.world.get_transform(
    solution.world.root, solution.world.printer
  ).matrix4x4()
  print(f"belief printer before {np.round(before[:3, 3], 4).tolist()}")
  print(f"belief printer after  {np.round(after[:3, 3], 4).tolist()}")


def main(argv: Sequence[str] | None = None) -> None:
  args = parse_args(argv)
  solution = deployments.connect(address=args.address)
  if args.mode == "look":
    if args.joints is None:
      sys.exit("--joints is required for --mode=look")
    look(solution, args.robot_name, args.joints)
  elif args.mode == "detect":
    detect(solution, args)
  else:
    discover(solution, args)


if __name__ == "__main__":
  main()
