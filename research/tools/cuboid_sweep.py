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

"""Which cuboids the reBot cell can grasp from the Prusa's bed.

Sweeps cuboids of model size x by y by z (z up, as printed) lying at the bed
centre turned by a yaw, computes the grasp omts_app would publish for each
(the cuboid_center rules in src/utils/dynamic_frame_calculator.py, with the
tilt and yaw symmetry from configs/rebot/app_config.yaml), and checks it:

1. the part fits between the open jaws, with a margin per side;
2. on the approach (pre-grasp to grasp, fingers open), the fingers and palm
   stay out of the part and the printer;
3. at the grasp, the closed fingers and the palm stay out of the printer, and
   the palm out of the part;
4. setting the part down at A on the ground (A's frames at the part's
   height and grasp depth, through the press before release), the fingers and
   palm stay above the ground;
5. the arm reaches the pre-grasp and grasp with its links and camera clear of
   the printer (IK with the most clearance).

Prints one line per size and the failures per yaw, then a summary. The
grasp rule is reimplemented here; keep it in step with the calculator.

  bazel run //research/tools:cuboid_sweep
  bazel run //research/tools:cuboid_sweep -- --sizes 20 40 60 80 95 --yaws 0 90
"""

import argparse
import itertools
import json
import math

import numpy as np

from research.tools import a_frames, cell, kin

# Finger joints of models/rebot_b601_rs_gripper (origin xyz, rpy in the
# gripper frame; travel along the joint's z, 0 closed to 0.05 m open).
FINGER_JOINTS = {
  "gripper_left": ((-0.041939, -7.3385e-05, 0), (1.5708, -1.5708, 0)),
  "gripper_right": ((-0.041939, 7.3385e-05, 0), (-1.5708, -1.5708, 0)),
}
FINGER_OPEN = 0.05
# tool_frame in the gripper frame (configs/rebot/rebot.attachments.updates).
GRIPPER_T_TOOL = cell.pose((0, 0, 0), (0.70710678, 0, 0.70710678, 0))


def palm_points(samples: int = 3000) -> np.ndarray:
  """Points on the gripper body's collision mesh (behind the fingers), in the
  tool frame."""
  v, f = cell._load_glb(
    cell.REPO / "models/rebot_b601_rs_gripper/gripper_end_collision.glb"
  )
  rng = np.random.default_rng(0)
  tri = v[f]
  a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
  area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
  i = rng.choice(len(tri), samples, p=area / area.sum())
  u, s = rng.random((2, samples))
  flip = u + s > 1
  u[flip], s[flip] = 1 - u[flip], 1 - s[flip]
  pts = np.vstack(
    [v, a[i] + u[:, None] * (b[i] - a[i]) + s[:, None] * (c[i] - a[i])]
  )
  tool_t_gripper = np.linalg.inv(GRIPPER_T_TOOL)
  return pts @ tool_t_gripper[:3, :3].T + tool_t_gripper[:3, 3]


def finger_points(position: float) -> np.ndarray:
  """Points on both fingers' collision boxes in the tool frame, each finger
  `position` from closed."""
  boxes = json.loads(
    (
      cell.REPO / "models/rebot_b601_rs_gripper/finger_collision_boxes.json"
    ).read_text()
  )
  tool_t_gripper = np.linalg.inv(GRIPPER_T_TOOL)
  pts = []
  for name, (xyz, r) in FINGER_JOINTS.items():
    joint = np.eye(4)
    joint[:3, :3] = kin.rpy(*r)
    joint[:3, 3] = xyz
    travel = np.eye(4)
    travel[2, 3] = position
    for b in boxes[name]:
      t = np.eye(4)
      t[:3, 3] = b["pose"][:3]
      pts.append(
        cell.box_points(
          tool_t_gripper @ joint @ travel @ t, np.zeros(3), b["size"], 3
        )
      )
  return np.vstack(pts)


def finger_slices(position: float) -> list[tuple[np.ndarray, np.ndarray]]:
  """The left finger's collision boxes as (min, max) corners in the tool
  frame, the finger `position` from closed. The boxes are axis-aligned there:
  length along tool z, pad width along tool x, the pad facing -y."""
  boxes = json.loads(
    (
      cell.REPO / "models/rebot_b601_rs_gripper/finger_collision_boxes.json"
    ).read_text()
  )
  xyz, r = FINGER_JOINTS["gripper_left"]
  joint = np.eye(4)
  joint[:3, :3] = kin.rpy(*r)
  joint[:3, 3] = xyz
  travel = np.eye(4)
  travel[2, 3] = position
  t = np.linalg.inv(GRIPPER_T_TOOL) @ joint @ travel
  out = []
  for b in boxes["gripper_left"]:
    corners = cell.box_points(
      t
      @ np.block([[np.eye(3), np.array(b["pose"][:3])[:, None]], [0, 0, 0, 1]]),
      np.zeros(3),
      b["size"],
      2,
    )
    out.append((corners.min(0), corners.max(0)))
  return out


def contact_area(grasp, part, size, width, n: int = 6) -> float:
  """Area (m^2) of the left finger's pad that lies on the gripped face: the
  pad's inner surface sampled per box, kept where it falls inside the face."""
  half = np.asarray(size) / 2
  jaw = grasp[:3, 1]
  normal_axis = int(np.argmax(np.abs(part[:3, :3].T @ jaw)))
  in_face = [i for i in range(3) if i != normal_axis]
  area = 0.0
  for lo, hi in finger_slices(width / 2):
    xs = np.linspace(lo[0], hi[0], n)
    zs = np.linspace(lo[2], hi[2], n)
    pts = np.array([[x, lo[1], z] for x in xs for z in zs])
    world = pts @ grasp[:3, :3].T + grasp[:3, 3]
    local = (world - part[:3, 3]) @ part[:3, :3]
    inside = np.all(np.abs(local[:, in_face]) <= half[in_face], axis=1)
    area += inside.mean() * (hi[0] - lo[0]) * (hi[2] - lo[2])
  return area


def _quat_mul(a, b):
  ax, ay, az, aw = a
  bx, by, bz, bw = b
  return (
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  )


def grasp_rotation(part_r: np.ndarray, part_pos, tilt_deg: float, sym: float):
  """The tilted grasp orientation the calculator publishes for a part."""
  ax, az = part_r[:, 0], part_r[:, 2]
  v = ax if abs(ax[2]) < 0.7 else az
  psi = math.atan2(v[1], v[0])
  c1 = (math.cos(psi / 2), math.sin(psi / 2), 0.0, 0.0)
  c2 = (-math.sin(psi / 2), math.cos(psi / 2), 0.0, 0.0)
  candidates = [c1, c2]
  if sym == 90.0:
    quarter = (0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5))
    candidates += [_quat_mul(c1, quarter), _quat_mul(c2, quarter)]

  def outward(q):
    tool_x = cell.pose((0, 0, 0), q)[:3, 0]
    return tool_x[0] * part_pos[0] + tool_x[1] * part_pos[1]

  q = max(candidates, key=outward)
  t = math.radians(tilt_deg)
  q = _quat_mul(q, (0.0, math.sin(t / 2), 0.0, math.cos(t / 2)))
  return cell.pose((0, 0, 0), q)[:3, :3]


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument(
    "--sizes", type=float, nargs="+", default=[20, 40, 60, 80, 95], help="mm"
  )
  parser.add_argument(
    "--yaws", type=float, nargs="+", default=[0, 45, 90, 135], help="deg"
  )
  parser.add_argument("--tilt", type=float, default=None)
  parser.add_argument("--yaw_symmetry", type=float, default=None)
  parser.add_argument(
    "--jaw_margin", type=float, default=5.0, help="mm per side when open"
  )
  parser.add_argument(
    "--depth",
    type=float,
    nargs="+",
    default=None,
    help="grasp depth past the part centre, horizontal (m); default from the config",
  )
  parser.add_argument("--seeds", type=int, default=16)
  args = parser.parse_args()
  tilt = args.tilt or cell.app_setting("approach_tilt_degrees")
  sym = args.yaw_symmetry or cell.app_setting("yaw_symmetry_degrees")
  offset = cell.app_setting("approach_offset_z")
  place_press = cell.app_setting("place_press_meters")
  try:
    config_depth = cell.app_setting("grasp_depth_meters")
  except KeyError:
    config_depth = 0.0
  depths = args.depth or [config_depth]
  # A's frames as configs/rebot/scene.updates.pbtxt places them.
  a_frames_radius, a_frames_bearing = 0.55, 130.0

  c = cell.Cell()
  bed = cell.bed_centre()
  fingers_open = finger_points(FINGER_OPEN)
  palm = palm_points()
  rng = np.random.default_rng(7)
  ik_cache = {}

  def reach(goal: np.ndarray) -> str | None:
    key = tuple(np.round(goal[:3, :].ravel(), 4))
    if key not in ik_cache:
      found = c.best_ik(goal, args.seeds, rng)
      if found is None:
        ik_cache[key] = "no IK"
      else:
        q, clear = found
        d, body = min(
          (v[0], f"{k} {v[1]}") for k, v in clear.items() if k != "gripper"
        )
        if d < 0:
          ik_cache[key] = f"{body} {d * 1000:.0f} mm"
        elif kin.limit_margin(q) < 0.05:
          ik_cache[key] = "joint limit"
        else:
          ik_cache[key] = None
    return ik_cache[key]

  def check(size, yaw, depth) -> tuple[str | None, float]:
    """(None, pad contact area) if graspable, else (the first reason, 0)."""
    sx, sy, sz = (s / 1000 for s in size)
    part = np.eye(4)
    part[:3, :3] = cell.rot_z(math.radians(yaw))
    part[:3, 3] = bed + [0, 0, sz / 2]
    grasp = np.eye(4)
    grasp[:3, :3] = grasp_rotation(part[:3, :3], part[:3, 3], tilt, sym)
    # The calculator pushes a tilted grasp deeper horizontally.
    push = grasp[:3, 2] * [1, 1, 0]
    if np.linalg.norm(push) > 1e-6:
      push /= np.linalg.norm(push)
    grasp[:3, 3] = part[:3, 3] + depth * push
    jaw = grasp[:3, 1]
    width = sum(abs(jaw @ part[:3, i]) * s for i, s in enumerate((sx, sy, sz)))
    if width > 2 * FINGER_OPEN - 2 * args.jaw_margin / 1000:
      return (f"too wide for the jaws ({width * 1000:.0f} mm)", 0.0)
    for s in np.linspace(0, 1, 7):
      t = grasp.copy()
      t[:3, 3] = grasp[:3, 3] - (1 - s) * offset * grasp[:3, 2]
      for label, pts in (("open fingers", fingers_open), ("palm", palm)):
        w = pts @ t[:3, :3].T + t[:3, 3]
        if cell.box_sdf(w, part, np.zeros(3), (sx, sy, sz)).min() < 0:
          return (f"{label} hit the part on the approach", 0.0)
        d, box = c.nearest(w)
        if d < 0:
          return (f"{label} hit the printer ({box}) on the approach", 0.0)
    # Closed fingers and palm at the grasp, and pressed onto the bed when the
    # part is set back down (cycle.place_press_meters along the approach).
    closed = finger_points(width / 2)
    for press in (0.0, place_press):
      t = grasp.copy()
      t[:3, 3] += press * grasp[:3, 2]
      for label, pts in (("closed fingers", closed), ("palm", palm)):
        d, box = c.nearest(pts @ t[:3, :3].T + t[:3, 3])
        if d < 0:
          where = "pressing onto the bed" if press else "at the grasp"
          return (f"{label} hit the printer ({box}) {where}", 0.0)
    # Setting the part down at A, on the ground (z = 0): the fingers and palm
    # from pre_place_vise to place_vise and through the press.
    at_a = a_frames.frames(
      tilt,
      a_frames_radius,
      a_frames_bearing,
      half_height=sz / 2,
      depth=depth,
    )
    place, pre_place = at_a["place_vise"], at_a["pre_place_vise"]
    pressed = place[:3, 3] + place_press * place[:3, 2]
    for s in np.linspace(0, 1, 8):
      t = place.copy()
      t[:3, 3] = pre_place[:3, 3] + s * (pressed - pre_place[:3, 3])
      for label, pts in (("open fingers", fingers_open), ("palm", palm)):
        if (pts @ t[:3, :3].T + t[:3, 3])[:, 2].min() < 0:
          return (f"{label} hit the ground at A", 0.0)
    pre = grasp.copy()
    pre[:3, 3] -= offset * grasp[:3, 2]
    for label, goal in (("pre-grasp", pre), ("grasp", grasp)):
      why = reach(goal)
      if why:
        return (f"{label}: {why}", 0.0)
    return None, contact_area(grasp, part, (sx, sy, sz), width)

  print(
    f"tilt {tilt:.0f} deg, yaw symmetry {sym:.0f}, bed centre "
    f"{np.round(bed, 3).tolist()}; part model x by y by z mm, z up, turned "
    "by yaw about the bed centre; contact = finger pad area on the gripped "
    "face, smallest over the graspable yaws"
  )
  results = {}
  for depth, size in itertools.product(
    depths, itertools.product(args.sizes, repeat=3)
  ):
    checked = {yaw: check(size, yaw, depth) for yaw in args.yaws}
    fails = {yaw: why for yaw, (why, _) in checked.items()}
    results[(depth, size)] = fails
    ok = [y for y, f in fails.items() if f is None]
    label = "x".join(f"{s:.0f}" for s in size)
    if len(depths) > 1:
      label += f" depth {depth * 1000:.0f}"
    status = (
      "all yaws"
      if len(ok) == len(fails)
      else "none"
      if not ok
      else "yaw " + ", ".join(f"{y:.0f}" for y in ok)
    )
    if ok:
      contact = min(checked[y][1] for y in ok) * 1e6
      status += f", contact {contact:.0f} mm^2"
    print(f"{label:20s} graspable: {status}", flush=True)
    for yaw, why in fails.items():
      if why:
        print(f"    yaw {yaw:4.0f}: {why}")
  total = sum(len(f) for f in results.values())
  good = sum(f is None for fs in results.values() for f in fs.values())
  print(f"\n{good} of {total} size and yaw combinations graspable")
  reasons = {}
  for fs in results.values():
    for why in fs.values():
      if why:
        key = why.split(" (")[0]
        reasons[key] = reasons.get(key, 0) + 1
  for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
    print(f"  {n:4d}  {why}")


if __name__ == "__main__":
  main()
