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

"""A's frames: the app's maths equals the research tool's."""

from absl.testing import absltest

from research.tools import a_frames, cell
from src.core import drop_off

_HEIGHTS = (0.01, 0.015, 0.024, 0.03, 0.045)


def _same_rotation(q, r):
  """Quaternions equal up to sign."""
  dot = sum(a * b for a, b in zip(q, r, strict=True))
  return abs(abs(dot) - 1.0) < 1e-9


class DropOffTest(absltest.TestCase):
  def test_equals_the_research_tools_frames(self):
    for tilt, radius, bearing in ((75.0, 0.55, 130.0), (60.0, 0.5, 120.0)):
      for half_height in _HEIGHTS:
        expected = a_frames.frames(tilt, radius, bearing, half_height)
        got = drop_off.drop_off_frames(tilt, radius, bearing, half_height)
        self.assertCountEqual(got, expected)
        for name, matrix in expected.items():
          position, quaternion = got[name]
          for a, b in zip(position, matrix[:3, 3], strict=True):
            self.assertAlmostEqual(a, b, places=9, msg=f"{name} {half_height}")
          self.assertTrue(
            _same_rotation(quaternion, cell.quat(matrix[:3, :3])), name
          )

  def test_the_committed_frames_are_the_default_parts(self):
    # configs/rebot/scene.updates.pbtxt: place_vise at the default part's rest.
    position, _ = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.015)[
      "place_vise"
    ]
    self.assertAlmostEqual(position[0], -0.3535, places=3)
    self.assertAlmostEqual(position[1], 0.4213, places=3)
    self.assertAlmostEqual(position[2], 0.015)

  def test_a_taller_part_is_set_down_higher_and_nothing_else_moves(self):
    low = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.015)
    high = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.024)
    for name in low:
      (lx, ly, lz), lq = low[name]
      (hx, hy, hz), hq = high[name]
      self.assertAlmostEqual(hz - lz, 0.009)
      self.assertAlmostEqual(hx, lx)
      self.assertAlmostEqual(hy, ly)
      self.assertEqual(hq, lq)

  def test_pre_place_backs_off_and_the_approach_is_above_it(self):
    frames = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.02)
    place, _ = frames["place_vise"]
    pre, _ = frames["pre_place_vise"]
    above, _ = frames["machine_approach"]
    back = sum((a - b) ** 2 for a, b in zip(place, pre, strict=True)) ** 0.5
    self.assertAlmostEqual(back, drop_off.PRE_PLACE_BACK)
    self.assertAlmostEqual(above[2] - pre[2], drop_off.APPROACH_UP)
    self.assertEqual(above[:2], pre[:2])


if __name__ == "__main__":
  absltest.main()
