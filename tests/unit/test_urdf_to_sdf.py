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

"""Unit tests for the URDF to SDF scene model converter."""

import json
import pathlib
import struct
import xml.etree.ElementTree as ET

import numpy as np
from absl.testing import absltest

from tools.models import urdf_to_sdf

# Unit cube, 12 triangles.
_CUBE_CORNERS = np.array(
  [[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=float
)
_CUBE_FACES = np.array(
  [
    [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5],
    [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
    [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
  ]
)  # fmt: skip


def _write_binary_stl(path: pathlib.Path, vertices, faces) -> None:
  with open(path, "wb") as f:
    f.write(b"\0" * 80)
    f.write(struct.pack("<I", len(faces)))
    for face in faces:
      f.write(struct.pack("<3f", 0, 0, 0))
      for index in face:
        f.write(struct.pack("<3f", *vertices[index]))
      f.write(b"\0\0")


def _read_glb_json(path: pathlib.Path) -> dict:
  data = path.read_bytes()
  magic, version, total = struct.unpack_from("<4sII", data)
  assert magic == b"glTF" and version == 2 and total == len(data)
  (json_length,) = struct.unpack_from("<I", data, 12)
  return json.loads(data[20 : 20 + json_length])


_URDF = """<robot name="two_link">
  <link name="base"><visual><geometry><mesh filename="package://x/cube.STL"/>
  </geometry></visual></link>
  <link name="arm">
    <inertial><origin xyz="0 0 0.1"/><mass value="0.5"/>
      <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/></inertial>
    <visual><origin xyz="0 0 1"/><geometry><mesh filename="cube.STL"/>
    </geometry></visual>
    <collision><geometry><mesh filename="cube.STL"/></geometry></collision>
  </link>
  <joint name="shoulder" type="revolute">
    <origin xyz="0 0 0.2" rpy="0 0 1.5708"/>
    <parent link="base"/><child link="arm"/><axis xyz="0 1 0"/>
    <limit lower="-1" upper="2" effort="3" velocity="4"/>
  </joint>
</robot>
"""


class ReadStlTest(absltest.TestCase):
  def test_binary_stl_welds_shared_corners(self):
    path = pathlib.Path(self.create_tempdir().full_path) / "cube.STL"
    _write_binary_stl(path, _CUBE_CORNERS, _CUBE_FACES)
    vertices, faces = urdf_to_sdf.read_stl(path)
    self.assertLen(vertices, 8)
    self.assertLen(faces, 12)

  def test_ascii_stl(self):
    path = pathlib.Path(self.create_tempdir().full_path) / "tri.stl"
    path.write_text(
      "solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n"
      "vertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n"
    )
    vertices, faces = urdf_to_sdf.read_stl(path)
    self.assertLen(vertices, 3)
    self.assertEqual(
      vertices[faces[0]].tolist(), [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    )


class SimplifyTest(absltest.TestCase):
  def test_cell_larger_than_mesh_collapses_everything(self):
    vertices, faces = urdf_to_sdf.simplify(_CUBE_CORNERS, _CUBE_FACES, 10.0)
    self.assertEmpty(faces)

  def test_small_cell_keeps_mesh(self):
    vertices, faces = urdf_to_sdf.simplify(_CUBE_CORNERS, _CUBE_FACES, 0.1)
    self.assertLen(vertices, 8)
    self.assertLen(faces, 12)


class WriteGlbTest(absltest.TestCase):
  def test_cube_keeps_hard_edges(self):
    path = pathlib.Path(self.create_tempdir().full_path) / "cube.glb"
    urdf_to_sdf.write_glb(
      path,
      [urdf_to_sdf.MeshPart("cube", _CUBE_CORNERS, _CUBE_FACES, (1, 0, 0, 1))],
    )
    gltf = _read_glb_json(path)
    position = gltf["accessors"][0]
    # Each of the 6 sides keeps its own 4 corners for a sharp normal.
    self.assertEqual(position["count"], 24)
    self.assertEqual(position["min"], [0.0, 0.0, 0.0])
    self.assertEqual(position["max"], [1.0, 1.0, 1.0])
    self.assertEqual(gltf["accessors"][2]["count"], 36)
    self.assertEqual(
      gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"],
      [1, 0, 0, 1],
    )


class ConvertTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.src = pathlib.Path(self.create_tempdir().full_path)
    _write_binary_stl(self.src / "cube.STL", _CUBE_CORNERS, _CUBE_FACES)
    (self.src / "robot.urdf").write_text(_URDF)
    self.out = pathlib.Path(self.create_tempdir().full_path)

  def _convert(self, **kwargs) -> ET.Element:
    sdf_path = urdf_to_sdf.convert(
      self.src / "robot.urdf",
      self.src,
      self.out,
      "two_link",
      visual_cell_size=0.0,
      collision_cell_size=0.0,
      **kwargs,
    )
    return ET.parse(sdf_path).getroot().find("model")

  def test_joint_keeps_origin_axis_and_limits(self):
    joint = self._convert().find("joint[@name='shoulder']")
    self.assertEqual(joint.get("type"), "revolute")
    pose = joint.find("pose")
    self.assertEqual(pose.get("relative_to"), "base")
    self.assertEqual(pose.text, "0 0 0.2 0 0 1.5708")
    self.assertEqual(joint.find("parent").text, "base")
    self.assertEqual(joint.find("child").text, "arm")
    self.assertEqual(joint.find("axis/xyz").text, "0 1 0")
    limit = joint.find("axis/limit")
    self.assertEqual(
      [limit.find(k).text for k in ("lower", "upper", "effort", "velocity")],
      ["-1", "2", "3", "4"],
    )

  def test_links_reference_written_meshes(self):
    model = self._convert()
    arm = model.find("link[@name='arm']")
    self.assertEqual(arm.find("pose").get("relative_to"), "shoulder")
    self.assertEqual(arm.find("inertial/mass").text, "0.5")
    self.assertEqual(
      arm.find("visual/geometry/mesh/uri").text, "arm_visual.glb"
    )
    self.assertEqual(
      arm.find("collision/geometry/mesh/uri").text, "arm_collision.glb"
    )
    base = model.find("link[@name='base']")
    self.assertIsNone(base.find("pose"))
    self.assertIsNone(base.find("collision"))
    for name in ("arm_visual", "arm_collision", "base_visual"):
      self.assertTrue((self.out / f"{name}.glb").exists())

  def test_visual_origin_is_baked_into_mesh(self):
    self._convert()
    position = _read_glb_json(self.out / "arm_visual.glb")["accessors"][0]
    self.assertEqual(position["min"], [0.0, 0.0, 1.0])
    self.assertEqual(position["max"], [1.0, 1.0, 2.0])

  def test_exclude_links_drops_subtree_and_its_joint(self):
    model = self._convert(exclude_links=["arm"])
    self.assertEqual(
      [link.get("name") for link in model.iter("link")], ["base"]
    )
    self.assertEmpty(model.findall("joint"))

  def test_root_link_starts_a_separate_model(self):
    model = self._convert(root_link="arm")
    links = model.findall("link")
    self.assertEqual([link.get("name") for link in links], ["arm"])
    self.assertIsNone(links[0].find("pose"))
    self.assertEmpty(model.findall("joint"))

  def test_robot_tags_and_flange_frame(self):
    model = self._convert(ik_solver="kinematic_chain", flange_link="arm")
    ns = "{https://intrinsic.ai/}"
    self.assertEqual(model.find(f"{ns}ik_solver").text, "kinematic_chain")
    self.assertIsNotNone(model.find(f"{ns}cartesian_limits"))
    flange = model.find("frame[@name='flange']")
    self.assertEqual(flange.get("attached_to"), "arm")
    self.assertEqual(flange.get(f"{ns}create_attachment_entity"), "true")

  def test_flange_must_be_in_model(self):
    with self.assertRaises(ValueError):
      self._convert(exclude_links=["arm"], flange_link="arm")

  def test_static_and_color_rules(self):
    model = self._convert(
      static=True,
      color_rules=[urdf_to_sdf.ColorRule("cube*", (0, 1, 0, 1))],
    )
    self.assertEqual(model.find("static").text, "true")
    material = _read_glb_json(self.out / "base_visual.glb")["materials"][0]
    self.assertEqual(
      material["pbrMetallicRoughness"]["baseColorFactor"], [0, 1, 0, 1]
    )


if __name__ == "__main__":
  absltest.main()
