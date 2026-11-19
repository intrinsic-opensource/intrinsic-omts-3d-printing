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
  detect  capture the RGB sensor, find the markers, compare each marker's pose
          with the belief world's aruco frames (ground truth in simulation)

  bazel run //tools/printer:open_door -- --address=localhost:17080 \
      --mode=detect
"""

import argparse
import sys
from collections.abc import Sequence

import numpy as np
from intrinsic.perception.client.v1.python.camera import cameras
from intrinsic.solutions import deployments, execution
from intrinsic.world.proto import object_world_updates_pb2

from skills.perception import aruco_pose
from src.core import door
from src.core.config import RobotConfig
from src.hardware.robot import Robot

CAMERA_RESOURCE = "orbbec_camera"
RGB_SENSOR = "rgb"
LOOK_CONFIG = "door_look"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument("--mode", choices=["look", "detect"], required=True)
  parser.add_argument("--robot_name", default="rebot")
  parser.add_argument("--joints", nargs=6, type=float, default=None)
  parser.add_argument("--marker_size_m", type=float, default=door.MARKER_SIZE_M)
  parser.add_argument("--png", default=None, help="Save the frame here.")
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


def capture_rgb(solution) -> tuple[np.ndarray, np.ndarray, object]:
  """RGB image (BGR order is not assumed), intrinsics, camera object."""
  handle = solution.resources[CAMERA_RESOURCE]
  camera = cameras.Camera.create_from_resource_handle(handle.proto)
  result = camera.capture()
  images = result.sensor_images
  if RGB_SENSOR not in images:
    sys.exit(f"no {RGB_SENSOR!r} sensor; got {sorted(images)}")
  sensor = images[RGB_SENSOR]
  return np.asarray(sensor.array), np.asarray(sensor.intrinsic_matrix), camera


def detect(solution, args) -> None:
  image, k, _ = capture_rgb(solution)
  print(f"frame {image.shape}, mean {image.mean():.1f}")
  if args.png:
    import cv2  # pylint: disable=import-outside-toplevel

    cv2.imwrite(args.png, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
  gray = image if image.ndim == 2 else image.mean(axis=2).astype(np.uint8)
  corners = aruco_pose.detect_corners(gray)
  print(f"markers found: {sorted(corners)}")
  for marker_id, c in sorted(corners.items()):
    det = aruco_pose.solve_marker(marker_id, c, args.marker_size_m, k)
    print(
      f"  {marker_id}: dist {np.linalg.norm(det.translation):.3f} m,"
      f" incidence {det.incidence_deg:.1f} deg, side {det.side_px:.0f} px,"
      f" reproj {det.reprojection_px:.2f} px, ippe ratio {det.ippe_ratio:.2f}"
    )


def main(argv: Sequence[str] | None = None) -> None:
  args = parse_args(argv)
  solution = deployments.connect(address=args.address)
  if args.mode == "look":
    if args.joints is None:
      sys.exit("--joints is required for --mode=look")
    look(solution, args.robot_name, args.joints)
  else:
    detect(solution, args)


if __name__ == "__main__":
  main()
