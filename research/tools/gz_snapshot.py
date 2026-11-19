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

"""Saves a Gazebo camera frame (JSON from `gz topic`) as a PNG and finds markers.

  export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1 GZ_RELAY=<gazebo pod ip>
  timeout 15 gz topic -e -t /orbbec_camera/rgb -n 1 --json-output > rgb.json &
  gz topic -t /orbbec_camera/rgb/trigger -m gz.msgs.Boolean -p 'data: true'
  bazel run //research/tools:gz_snapshot -- rgb.json out.png

Prints each ArUco marker found (id, corner pixels, side in pixels).
"""

import argparse
import base64
import json

import cv2
import numpy as np

from skills.perception import aruco_pose
from src.core import door

# The simulated Orbbec RGB sensor (core orbbec_gemini_335le.sdf).
K = np.array([[597.0, 0, 640.0], [0, 593.0, 400.0], [0, 0, 1.0]])


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("json_file")
  parser.add_argument("png_file")
  parser.add_argument("--theta_deg", type=float, default=0.0)
  args = parser.parse_args()
  with open(args.json_file) as f:
    msg = json.load(f)
  img = np.frombuffer(base64.b64decode(msg["data"]), np.uint8).reshape(
    msg["height"], msg["width"], 3
  )
  bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
  corners = aruco_pose.detect_corners(bgr)
  for marker_id, c in sorted(corners.items()):
    side = np.mean([np.linalg.norm(c[i] - c[(i + 1) % 4]) for i in range(4)])
    print(
      f"marker {marker_id}: side {side:.1f} px, corners {c.round(1).tolist()}"
    )
    cv2.polylines(bgr, [c.astype(np.int32)], True, (0, 255, 0), 2)
    cv2.putText(
      bgr,
      str(marker_id),
      tuple(c[0].astype(int)),
      cv2.FONT_HERSHEY_SIMPLEX,
      1.0,
      (0, 255, 0),
      2,
    )
  dets = {
    i: aruco_pose.solve_marker(i, c, door.MARKER_SIZE_M, K)
    for i, c in corners.items()
  }
  for i, d in sorted(dets.items()):
    print(
      f"  {i}: dist {np.linalg.norm(d.translation):.3f} m, incidence"
      f" {d.incidence_deg:.1f} deg, reproj {d.reprojection_px:.2f} px,"
      f" ippe ratio {d.ippe_ratio:.2f}"
    )
  ids = sorted(dets)
  for a, b in zip(ids, ids[1:], strict=False):
    got = np.linalg.norm(dets[a].translation - dets[b].translation)
    pa = door.marker_in_printer(a, args.theta_deg)[0]
    pb = door.marker_in_printer(b, args.theta_deg)[0]
    want = float(np.linalg.norm(np.array(pa) - np.array(pb)))
    print(
      f"  distance {a}-{b}: {got * 1000:.1f} mm, model {want * 1000:.1f} mm"
      f" ({(got - want) * 1000:+.1f} mm)"
    )
  if not corners:
    print("no markers found")
  cv2.imwrite(args.png_file, bgr)
  print(f"wrote {args.png_file}")


if __name__ == "__main__":
  main()
