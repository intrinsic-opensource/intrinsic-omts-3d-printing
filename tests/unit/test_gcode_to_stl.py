# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for tools/printer/gcode_to_stl.py."""

import json
import math
from pathlib import Path
import struct
import tempfile

from absl.testing import absltest

from tools.printer import gcode_to_stl as g

_DATA = Path(__file__).parent / "testdata"
_ASCII = _DATA / "prusaslicer_2_9_7_part.gcode"
_BINARY = _DATA / "prusaslicer_2_9_7_part.bgcode"


def _volume(triangles) -> float:
  return abs(g_signed_volume(triangles))


def g_signed_volume(triangles) -> float:
  total = 0.0
  for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in triangles:
    total += (
        ax * (by * cz - bz * cy)
        - ay * (bx * cz - bz * cx)
        + az * (bx * cy - by * cx)
    ) / 6
  return total


class ToolpathTest(absltest.TestCase):

  def test_extrusion_becomes_box_of_width_height_length(self):
    text = (
        ";TYPE:Perimeter\n;WIDTH:0.5\n;HEIGHT:0.2\n"
        "M83\nG1 X0 Y0 Z0.2\nG1 X10 Y0 E1\n"
    )
    segments, info = g.parse_toolpaths(text)
    self.assertLen(segments, 1)
    self.assertEqual(segments[0][0], "Perimeter")
    triangles = g.to_triangles(segments)
    self.assertAlmostEqual(_volume(triangles), 10 * 0.5 * 0.2, places=6)
    self.assertEqual(info["layers"], 1)

  def test_travel_and_retraction_are_not_printed(self):
    text = "M83\nG1 X5 Y5 F3000\nG1 E-2\nG1 X9 Y5\nG1 E2\n"
    self.assertEmpty(g.parse_toolpaths(text)[0])

  def test_absolute_extrusion_and_g92(self):
    text = "M82\nG92 E0\nG1 X1 E0.1\nG1 X2 E0.2\nG92 E0\nG1 X3 E0.1\n"
    self.assertLen(g.parse_toolpaths(text)[0], 3)

  def test_spaces_may_be_missing(self):
    text = ";TYPE:Solid infill\nM83\nG1X1Y0E0.1F1200\n"
    segments, _ = g.parse_toolpaths(text)
    self.assertEqual((segments[0][0], segments[0][3]), ("Solid infill", 1.0))

  def test_arc_follows_the_circle(self):
    # Quarter circle, centre (0, 0), from (10, 0) to (0, 10), counter-clockwise.
    text = "M83\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 E1\n"
    segments, _ = g.parse_toolpaths(text)
    self.assertGreater(len(segments), 8)
    for _, x0, y0, x1, y1, *_ in segments:
      self.assertAlmostEqual(math.hypot(x0, y0), 10, places=6)
      self.assertAlmostEqual(math.hypot(x1, y1), 10, places=6)
    self.assertAlmostEqual(segments[-1][3], 0, places=6)
    self.assertAlmostEqual(segments[-1][4], 10, places=6)

  def test_clockwise_arc_goes_the_short_way_around(self):
    text = "M83\nG1 X10 Y0\nG2 X0 Y10 I-10 J0 E1\n"
    segments, _ = g.parse_toolpaths(text)
    longest = max(abs(s[2]) + abs(s[1]) for s in segments)
    self.assertGreater(longest, 0)
    # Clockwise from (10, 0) to (0, 10) sweeps three quarters of a turn.
    self.assertTrue(any(s[2] < -1 for s in segments))

  def test_moving_unretract_is_not_printed(self):
    # PrusaSlicer 3.x tags de-retraction done while travelling.
    text = (
        "M83\n;TYPE:Wipe tower\n;MOVING_UNRETRACT_START\nG1 X5 E0.3\n"
        ";MOVING_UNRETRACT_END\nG1 X9 E0.3\n"
    )
    segments, _ = g.parse_toolpaths(text)
    self.assertEqual([(s[1], s[3]) for s in segments], [(5.0, 9.0)])

  def test_collinear_segments_merge(self):
    text = "M83\nG1 X1 E0.1\nG1 X2 E0.1\nG1 X3 E0.1\nG1 X3 Y1 E0.1\n"
    segments, _ = g.parse_toolpaths(text)
    self.assertLen(g.merge_segments(segments), 2)


class BinaryGcodeTest(absltest.TestCase):

  def test_heatshrink_literals_and_backreference(self):
    # literal 'a', literal 'b', backref offset 2 count 4 -> "ababab".
    bits = "1" + f"{ord('a'):08b}" + "1" + f"{ord('b'):08b}"
    bits += "0" + f"{1:011b}" + f"{3:04b}"
    bits += "0" * (-len(bits) % 8)
    data = int(bits, 2).to_bytes(len(bits) // 8, "big")
    self.assertEqual(g.heatshrink_decompress(data, 11, 4), b"ababab")

  def test_heatshrink_reaches_into_zero_window(self):
    bits = "0" + f"{1:011b}" + f"{1:04b}"  # offset 2 count 2, nothing yet
    bits += "0" * (-len(bits) % 8)
    data = int(bits, 2).to_bytes(len(bits) // 8, "big")
    self.assertEqual(g.heatshrink_decompress(data, 11, 4), b"\0\0")

  def test_meatpack_packed_and_literal_characters(self):
    enable = b"\xff\xff\xfb"
    # "1" low nibble, "2" high nibble; then 'G' packs, 'Z' does not.
    data = enable + bytes([0x21]) + bytes([0xFD]) + b"Z"
    self.assertEqual(g.meatpack_decode(data), b"12GZ")
    literal = enable + bytes([0x3F]) + b"Z"  # first literal, second '3'
    self.assertEqual(g.meatpack_decode(literal), b"Z3")

  def test_binary_and_ascii_exports_give_same_toolpaths(self):
    text, meta = g.read_gcode(_BINARY)
    self.assertIn("printer_metadata", meta)
    self.assertEqual(
        g.parse_toolpaths(text)[0], g.parse_toolpaths(g.read_gcode(_ASCII)[0])[0]
    )

  def test_bad_file_raises(self):
    with self.assertRaises(ValueError):
      g.read_bgcode(b"NOPE")


class ConvertTest(absltest.TestCase):

  def test_convert_writes_compound_and_per_type_meshes(self):
    with tempfile.TemporaryDirectory() as tmp:
      out = Path(tmp) / "out"
      summary = g.convert(_BINARY, out)
      self.assertTrue((out / "compound.stl").is_file())
      self.assertTrue((out / "by_type" / "support_material.stl").is_file())
      self.assertTrue(summary["types"]["Support material"]["included"])
      self.assertEqual(json.loads((out / "summary.json").read_text()), summary)
      count = struct.unpack("<I", (out / "compound.stl").read_bytes()[80:84])[0]
      self.assertEqual(count, summary["compound"]["triangles"])
      # The part (L-shaped, 25 mm tall) sits on the bed.
      bounds = summary["compound"]["bounds"]
      self.assertAlmostEqual(bounds["min"][2], 0.0, places=3)
      self.assertAlmostEqual(bounds["max"][2], 25.0, delta=0.1)

  def test_part_and_supports_are_separate_files(self):
    with tempfile.TemporaryDirectory() as tmp:
      out = Path(tmp) / "out"
      summary = g.convert(_ASCII, out)
      self.assertTrue((out / "part.stl").is_file())
      self.assertTrue((out / "supports.stl").is_file())
      self.assertEqual(
        summary["supports"]["types"],
        ["Support material", "Support material interface"],
      )
      self.assertNotIn("Support material", summary["part"]["types"])
      self.assertNotIn("Skirt/Brim", summary["part"]["types"])
      self.assertEqual(
        summary["part"]["triangles"] + summary["supports"]["triangles"]
        + summary["types"]["Skirt/Brim"]["triangles"],
        summary["compound"]["triangles"],
      )

  def test_exclude_removes_a_type_from_the_compound(self):
    with tempfile.TemporaryDirectory() as tmp:
      kept = g.convert(_ASCII, Path(tmp) / "a")["compound"]["triangles"]
      fewer = g.convert(_ASCII, Path(tmp) / "b", exclude=("Support material",))
      self.assertLess(fewer["compound"]["triangles"], kept)


if __name__ == "__main__":
  absltest.main()
