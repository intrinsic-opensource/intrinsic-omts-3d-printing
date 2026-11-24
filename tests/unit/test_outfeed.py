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


import math

from absl.testing import absltest

from src.core import drop_off, outfeed


class OutfeedTest(absltest.TestCase):
  def test_the_line_has_evenly_spaced_spots_at_one_yaw(self):
    spots = outfeed.line_spots(5, y=-0.5, start_x=-0.1, spacing=0.1)
    self.assertLen(spots, 5)
    for k, spot in enumerate(spots):
      self.assertAlmostEqual(spot.x, -0.1 + 0.1 * k)
      self.assertEqual(spot.y, -0.5)
      self.assertEqual(spot.yaw_degrees, outfeed.LINE_YAW_DEGREES)

  def test_the_arc_keeps_every_spot_at_one_radius_and_steps_the_bearing(self):
    spots = outfeed.arc_spots(
      5, radius=0.5, start_bearing_degrees=-100.0, step_degrees=12.0
    )
    for k, spot in enumerate(spots):
      self.assertAlmostEqual(math.hypot(spot.x, spot.y), 0.5)
      self.assertAlmostEqual(
        math.degrees(math.atan2(spot.y, spot.x)), -100.0 + 12.0 * k
      )
      self.assertIsNone(spot.yaw_degrees)

  def test_line_frames_share_one_orientation(self):
    frames = [
      outfeed.spot_frames(spot, 75.0, 0.015)
      for spot in outfeed.line_spots(3, -0.5, -0.1, 0.1)
    ]
    for place, pre, approach in frames:
      self.assertEqual(place[1], frames[0][0][1])
      self.assertEqual(pre[1], place[1])
      self.assertEqual(approach[1], place[1])

  def test_arc_frames_turn_with_the_bearing_but_not_the_tilt(self):
    # The same distance and tool pitch at every spot, so the frames differ only
    # by the rotation about the robot's base: the place frames' heights match.
    spots = outfeed.arc_spots(3, 0.5, -100.0, 12.0)
    frames = [outfeed.spot_frames(spot, 75.0, 0.015) for spot in spots]
    self.assertNotEqual(frames[0][0][1], frames[1][0][1])
    for place, pre, approach in frames:
      self.assertAlmostEqual(place[0][2], 0.015)
      self.assertAlmostEqual(math.hypot(*place[0][:2]), 0.5)
      self.assertAlmostEqual(approach[0][2], pre[0][2] + drop_off.APPROACH_UP)

  def test_a_spot_without_a_yaw_equals_a_drop_off_at_its_bearing(self):
    spot = outfeed.arc_spots(1, 0.55, 130.0, 0.0)[0]
    place, pre, approach = outfeed.spot_frames(spot, 75.0, 0.015)
    expected = drop_off.drop_off_frames(75.0, 0.55, 130.0, 0.015)
    for got, key in (
      (place, "place_vise"),
      (pre, "pre_place_vise"),
      (approach, "machine_approach"),
    ):
      for a, b in zip(got[0], expected[key][0], strict=True):
        self.assertAlmostEqual(a, b)

  def test_frame_names(self):
    self.assertEqual(
      outfeed.frame_names("outfeed", 2),
      ("outfeed_2_place", "outfeed_2_preplace", "outfeed_2_approach"),
    )


if __name__ == "__main__":
  absltest.main()
