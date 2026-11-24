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

"""Door angle (the oracle) from a Gazebo pose recording.

Reads Gazebo's /world/default/pose/info recorded as JSON lines (README.md,
"Recording poses in Gazebo"). Prints the door angle theta (0 closed, 180 deg
fully open) for every --every-th sample, then the last theta and where the
printer base went (first to last sample). door_link's pose is relative to the
printer model; with the SDF convention q = pi - theta, theta is minus its yaw,
wrapped to [-90, 270) and clamped to [0, 180].

  bazel run //research/tools:door_angle -- /tmp/poses.jsonl
"""

import argparse
import json
import math

DOOR = "door_link"
PRINTER = "printer"


def yaw(q: dict) -> float:
  x, y, z, w = (float(q.get(k, 0.0)) for k in "xyzw")
  return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def read(path: str) -> list[tuple[float, float, tuple[float, ...]]]:
  """[(sim time, theta in degrees, printer position)] per message."""
  out = []
  with open(path) as f:
    for line in f:
      line = line.strip()
      if not line.startswith("{"):
        continue
      msg = json.loads(line)
      stamp = msg.get("header", {}).get("stamp", {})
      t = float(stamp.get("sec", 0)) + float(stamp.get("nsec", 0)) * 1e-9
      door = printer = None
      for p in msg.get("pose", []):
        if p.get("name") == DOOR:
          door = p
        elif p.get("name") == PRINTER:
          printer = p
      if door is None or printer is None:
        continue
      a = -math.degrees(yaw(door.get("orientation", {})))
      theta = (a + 90.0) % 360.0 - 90.0
      theta = min(max(theta, 0.0), 180.0)
      pos = printer.get("position", {})
      out.append((t, theta, tuple(float(pos.get(k, 0)) for k in "xyz")))
  return out


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("recording")
  parser.add_argument("--every", type=int, default=50)
  args = parser.parse_args()
  samples = read(args.recording)
  if not samples:
    raise SystemExit("no door_link and printer poses in the recording")
  t0 = samples[0][0]
  for t, theta, _pos in samples[:: args.every]:
    print(f"  {t - t0:7.2f} s  theta {theta:7.2f} deg")
  last = samples[-1][1]
  print(f"{len(samples)} samples; last theta {last:.2f} deg")
  x0, y0, _ = samples[0][2]
  x1, y1, _ = samples[-1][2]
  moved = math.dist(samples[0][2], samples[-1][2]) * 1000
  print(
    f"printer base: first ({x0:.4f}, {y0:.4f}) -> last ({x1:.4f}, {y1:.4f}),"
    f" moved {moved:.1f} mm"
  )


if __name__ == "__main__":
  main()
