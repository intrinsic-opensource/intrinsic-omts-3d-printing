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

"""How far the part moves at each release, from a Gazebo pose recording.

Reads Gazebo's /world/default/pose/info recorded as JSON lines (README.md,
"Recording poses in Gazebo"). For each release, when the fingers open from a
grasp on the part, prints how far the part moved in the 1.5 s after the
fingers started opening, and how long each finger took to pass 40 mm open.
Finger positions are their joint travel (0 closed, 50 mm open); times are
simulation time from the start of the recording.

  bazel run //research/tools:release_drift -- /tmp/poses.jsonl
"""

import argparse
import json
import math

PART = "rebot_printed_part"
FINGERS = ("gripper_left", "gripper_right")
OPEN_PAST = 0.04
SETTLE = 1.5


def read(path: str) -> dict[str, list[tuple[float, tuple[float, ...]]]]:
  """Name -> [(sim time, position)] for the part and the fingers."""
  tracks = {name: [] for name in (PART, *FINGERS)}
  with open(path) as f:
    for line in f:
      line = line.strip()
      if not line.startswith("{"):
        continue
      msg = json.loads(line)
      stamp = msg.get("header", {}).get("stamp", {})
      t = float(stamp.get("sec", 0)) + float(stamp.get("nsec", 0)) * 1e-9
      for p in msg.get("pose", []):
        if p.get("name") in tracks:
          pos = p.get("position", {})
          tracks[p["name"]].append(
            (t, tuple(float(pos.get(k, 0)) for k in "xyz"))
          )
  return tracks


def travel(position: tuple[float, ...]) -> float:
  """A finger's opening from its link pose in the gripper frame."""
  return abs(position[1])


def at(track, t: float):
  for sample in track:
    if sample[0] >= t:
      return sample
  return track[-1]


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("recording")
  args = parser.parse_args()
  tracks = read(args.recording)
  part, left, right = tracks[PART], *(tracks[f] for f in FINGERS)
  if not part or not left:
    raise SystemExit("no part or finger poses in the recording")
  t0 = left[0][0]
  # A release starts when the left finger leaves a grasp (10-35 mm open:
  # stopped on the part, not fully closed) and opens past 35 mm.
  starts = []
  for prev, cur in zip(left, left[1:], strict=False):
    if travel(prev[1]) < 0.035 <= travel(cur[1]):
      before = at(left, cur[0] - 1.0)
      if 0.01 < travel(before[1]) < 0.035 and (
        not starts or cur[0] - starts[-1] > 3
      ):
        held = travel(before[1])
        starts.append(
          max(
            t for t, p in left if t <= cur[0] and abs(travel(p) - held) < 5e-4
          )
        )
  print(f"{len(starts)} releases")
  for ts in starts:
    p0, p1 = at(part, ts)[1], at(part, ts + SETTLE)[1]
    moved = [(b - a) * 1000 for a, b in zip(p0, p1, strict=True)]
    lags = []
    for track in (left, right):
      lag = next(
        (t - ts for t, p in track if t >= ts and travel(p) > OPEN_PAST)
      )
      lags.append(lag)
    print(
      f"  {ts - t0:7.1f} s at ({p0[0]:.3f}, {p0[1]:.3f}): part moved "
      f"{math.hypot(*moved):5.1f} mm ({moved[0]:+.1f}, {moved[1]:+.1f}, "
      f"{moved[2]:+.1f}); fingers past 40 mm after {lags[0]:.2f} / "
      f"{lags[1]:.2f} s"
    )


if __name__ == "__main__":
  main()
