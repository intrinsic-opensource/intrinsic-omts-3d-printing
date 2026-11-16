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

"""Geometry of the reBot cell for offline clearance checks.

Read from the repository at run time, so edits to configs/rebot/ or the models
are picked up without rebuilding: the printer's pose and the camera mount
(configs/rebot/*.updates.pbtxt), the printer's collision boxes and bed
(models/printer/), the arm's link collision meshes (models/rebot_b601_rs/) and
the grasp settings (configs/rebot/app_config.yaml). The gripper and camera
bodies are boxes. Distances are signed: negative means inside an obstacle.
"""

import json
import math
import os
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from research.tools import kin

REPO = Path(
  os.environ.get("BUILD_WORKSPACE_DIRECTORY")
  or Path(__file__).resolve().parents[2]
)
CONFIGS = REPO / "configs" / "rebot"

# Gemini 335Le body in the camera frame (models/orbbec_gemini_335le).
CAMERA_BOX = ((0.02375, 0.0, -0.022), (0.124, 0.029, 0.05))
# Half-FOV tangents of the colour camera and the depth sensor's near limit.
CAMERA_TAN_H, CAMERA_TAN_V = 640 / 597, 400 / 593
DEPTH_NEAR = 0.25
# Gripper body in the tool frame (gripper_end_collision.glb bounds).
GRIPPER_BOX = ((0.0, 0.0, -0.115), (0.082, 0.184, 0.084))
# models/rebot_printed_part: 40 x 40 x 30 mm, resting on its 40 x 40 face.
PART_HALF_HEIGHT = 0.015
LINKS = ("link2", "link3", "link4", "link5", "link6")


def pose(xyz, quat_xyzw) -> np.ndarray:
  x, y, z, w = quat_xyzw
  t = np.eye(4)
  t[:3, :3] = [
    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
  ]
  t[:3, 3] = xyz
  return t


def quat(r: np.ndarray) -> np.ndarray:
  """Quaternion (x, y, z, w) of a rotation matrix."""
  w = math.sqrt(max(0, 1 + np.trace(r))) / 2
  x = math.copysign(
    math.sqrt(max(0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2, r[2, 1] - r[1, 2]
  )
  y = math.copysign(
    math.sqrt(max(0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2, r[0, 2] - r[2, 0]
  )
  z = math.copysign(
    math.sqrt(max(0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2, r[1, 0] - r[0, 1]
  )
  return np.array([x, y, z, w])


def rot_z(angle: float) -> np.ndarray:
  c, s = math.cos(angle), math.sin(angle)
  return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# --- configs ---------------------------------------------------------------


def _update_blocks(path: Path) -> list[str]:
  """Top-level `updates { ... }` blocks of an ObjectWorldUpdates text file."""
  text = "\n".join(
    line for line in path.read_text().splitlines() if not line.startswith("#")
  )
  blocks, depth, start = [], 0, None
  for i, ch in enumerate(text):
    if ch == "{":
      if depth == 0:
        start = i
      depth += 1
    elif ch == "}":
      depth -= 1
      if depth == 0:
        blocks.append(text[start : i + 1])
  return blocks


def _braced(text: str, key: str) -> str:
  """Contents of the first `key { ... }` in text."""
  i = text.index(key + " {") + len(key) + 2
  depth = 1
  for j in range(i, len(text)):
    depth += {"{": 1, "}": -1}.get(text[j], 0)
    if depth == 0:
      return text[i:j]
  raise ValueError(f"unbalanced braces after {key}")


def _fields(text: str, names: str, default: float) -> list[float]:
  out = []
  for n in names:
    m = re.search(rf"\b{n}:\s*([-+0-9.eE]+)", text)
    out.append(float(m.group(1)) if m else default)
  return out


def _pose_in(block: str, key: str) -> np.ndarray:
  body = _braced(block, key)
  xyz = _fields(_braced(body, "position"), "xyz", 0.0)
  q = _fields(_braced(body, "orientation"), "xyz", 0.0)
  q.append(_fields(_braced(body, "orientation"), "w", 1.0)[0])
  return pose(xyz, q)


def object_pose(path: Path, object_name: str) -> np.ndarray:
  """`a_t_b` of the update_transform that moves object_name."""
  for b in _update_blocks(path):
    if "update_transform" in b and re.search(
      rf'node_b\s*\{{[^}}]*object_name:\s*"{object_name}"', b
    ):
      return _pose_in(b, "a_t_b")
  raise KeyError(f"no update_transform for {object_name} in {path}")


def frame_pose(name: str, path: Path = CONFIGS / "scene.updates.pbtxt"):
  """Pose of a frame created on root by create_frame."""
  for b in _update_blocks(path):
    if re.search(rf'new_frame_name:\s*"{name}"', b):
      return _pose_in(b, "parent_t_new_frame")
  raise KeyError(f"no frame {name} in {path}")


def app_setting(key: str) -> float:
  """A numeric `key: value` from configs/rebot/app_config.yaml."""
  text = (CONFIGS / "app_config.yaml").read_text()
  m = re.search(rf"^\s*{key}:\s*([-+0-9.eE]+)", text, re.M)
  if not m:
    raise KeyError(key)
  return float(m.group(1))


def world_t_printer() -> np.ndarray:
  return object_pose(CONFIGS / "printer.updates.pbtxt", "printer")


def tool_t_camera() -> np.ndarray:
  """Camera pose in the tool frame (the mount is given on the flange)."""
  flange_t_cam = object_pose(
    CONFIGS / "orbbec_gemini.updates.pbtxt", "orbbec_camera"
  )
  flange_t_tool = np.eye(4)
  flange_t_tool[2, 3] = kin.TOOL_Z
  return np.linalg.inv(flange_t_tool) @ flange_t_cam


# --- printer ---------------------------------------------------------------


def _heatbed_bounds() -> tuple[np.ndarray, np.ndarray]:
  verts = [
    line.split()[1:4]
    for line in (REPO / "models/printer/heatbed.obj").read_text().splitlines()
    if line.startswith("v ")
  ]
  v = np.array(verts, float)
  return v.min(0), v.max(0)


def bed_top_local() -> np.ndarray:
  """Centre of the heatbed's top surface, in the printer frame."""
  lo, hi = _heatbed_bounds()
  return np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2]])


def bed_centre() -> np.ndarray:
  """Centre of the bed's top surface, in the world."""
  return (world_t_printer() @ np.append(bed_top_local(), 1))[:3]


def printer_boxes() -> dict[str, tuple[np.ndarray, np.ndarray]]:
  """Name -> (centre, size) in the printer frame: the SDF's collision boxes
  and a 1 cm plate under the heatbed's top surface."""
  root = ET.parse(REPO / "models/printer/3d_printer.sdf").getroot()
  boxes = {}
  for col in root.iter("collision"):
    size = col.find("geometry/box/size")
    if size is None:
      continue
    p = [float(v) for v in col.findtext("pose", "0 0 0 0 0 0").split()]
    if any(abs(a) > 1e-9 for a in p[3:]):
      raise ValueError(f"rotated collision box {col.get('name')}")
    boxes[col.get("name")] = (
      np.array(p[:3]),
      np.array(size.text.split(), float),
    )
  lo, hi = _heatbed_bounds()
  boxes["heatbed"] = (
    np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2] - 0.005]),
    np.array([hi[0] - lo[0], hi[1] - lo[1], 0.01]),
  )
  return boxes


# --- distances -------------------------------------------------------------


def box_sdf(points: np.ndarray, t: np.ndarray, centre, size) -> np.ndarray:
  """Signed distance from points (N, 3) to a box at pose t (centre, size)."""
  q = (points - t[:3, 3]) @ t[:3, :3] - centre
  d = np.abs(q) - np.asarray(size) / 2
  return np.linalg.norm(np.maximum(d, 0), axis=1) + np.minimum(d.max(axis=1), 0)


def box_points(t: np.ndarray, centre, size, n: int = 5) -> np.ndarray:
  """Grid of n^3 points filling a box at pose t."""
  g = [np.linspace(-s / 2, s / 2, n) for s in size]
  pts = np.array([[x, y, z] for x in g[0] for y in g[1] for z in g[2]])
  return (pts + centre) @ t[:3, :3].T + t[:3, 3]


def _load_glb(path: Path) -> tuple[np.ndarray, np.ndarray]:
  data = path.read_bytes()
  n = struct.unpack("<I", data[12:16])[0]
  doc = json.loads(data[20 : 20 + n])
  bin_start = 20 + n + 8

  def accessor(i, dtype, width):
    a = doc["accessors"][i]
    view = doc["bufferViews"][a["bufferView"]]
    off = bin_start + view.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(data, dtype, a["count"] * width, off).reshape(
      -1, width
    )

  prim = doc["meshes"][0]["primitives"][0]
  verts = accessor(prim["attributes"]["POSITION"], np.float32, 3).astype(float)
  faces = accessor(prim["indices"], np.uint32, 1).reshape(-1, 3)
  return verts, faces


def link_points(samples: int = 3000, seed: int = 0) -> dict[str, np.ndarray]:
  """Points on each arm link's collision mesh (vertices plus surface samples),
  in the link frame."""
  rng = np.random.default_rng(seed)
  out = {}
  for name in LINKS:
    v, f = _load_glb(REPO / f"models/rebot_b601_rs/{name}_collision.glb")
    tri = v[f]
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    i = rng.choice(len(tri), samples, p=area / area.sum())
    u, s = rng.random((2, samples))
    flip = u + s > 1
    u[flip], s[flip] = 1 - u[flip], 1 - s[flip]
    surface = a[i] + u[:, None] * (b[i] - a[i]) + s[:, None] * (c[i] - a[i])
    out[name] = np.vstack([v, surface])
  return out


class Cell:
  """Printer obstacles and arm bodies, for clearance at joint configurations."""

  def __init__(self, samples: int = 3000):
    self.printer = world_t_printer()
    self.boxes = printer_boxes()
    self.links = link_points(samples)
    self.camera = tool_t_camera()

  def nearest(self, points: np.ndarray) -> tuple[float, str]:
    """Signed distance from points to the nearest printer box, and its name."""
    return min(
      (float(box_sdf(points, self.printer, c, s).min()), name)
      for name, (c, s) in self.boxes.items()
    )

  def bodies(self, q) -> dict[str, np.ndarray]:
    """World points of each arm link, the camera and the gripper at q."""
    tool, frames = kin.fk(q)
    out = {}
    for i, name in enumerate(LINKS):
      t = frames[i + 1]
      out[name] = self.links[name] @ t[:3, :3].T + t[:3, 3]
    out["camera"] = box_points(tool @ self.camera, *CAMERA_BOX)
    out["gripper"] = box_points(tool, *GRIPPER_BOX)
    return out

  def clearance(self, q) -> dict[str, tuple[float, str]]:
    """Per body: distance to the nearest printer box, and that box's name."""
    return {name: self.nearest(p) for name, p in self.bodies(q).items()}

  def best_ik(self, goal: np.ndarray, seeds: int = 20, rng=None):
    """The IK solution whose arm and camera are furthest from the printer.

    Returns (q, clearance) or None. The gripper is left out of the choice: at
    a grasp it is meant to be close to the bed."""
    best = None
    for q in kin.ik(goal, seeds, rng):
      c = self.clearance(q)
      key = min(d for name, (d, _) in c.items() if name != "gripper")
      if best is None or key > best[0]:
        best = (key, q, c)
    return None if best is None else best[1:]


def grasp_pose(x, y, z, tilt_deg: float, yaw_deg: float = 0.0) -> np.ndarray:
  """Tool pose for a grasp at (x, y, z), pitched tilt_deg from vertical about
  the jaw axis so the approach leans away from the robot along +x, then
  turned yaw_deg about z (cuboid_center's tilted grasp)."""
  t = math.radians(tilt_deg)
  down = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float)
  pitch = np.array(
    [[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]]
  )
  out = np.eye(4)
  out[:3, :3] = rot_z(math.radians(yaw_deg)) @ down @ pitch
  out[:3, 3] = (x, y, z)
  return out
