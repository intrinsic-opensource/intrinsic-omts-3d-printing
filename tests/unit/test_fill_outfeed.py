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


from unittest import mock

from absl.testing import absltest

from research.tools import fill_outfeed


def _config():
  return mock.sentinel.config


class FillOutfeedTest(absltest.TestCase):
  def setUp(self):
    super().setUp()
    self.configure = self.enter_context(
      mock.patch.object(fill_outfeed.configure_cell, "main")
    )
    self.run_cycle = self.enter_context(
      mock.patch.object(fill_outfeed.omts_main, "run_machine_tending_pipeline")
    )
    self.enter_context(
      mock.patch.object(fill_outfeed, "load_app_config", return_value=_config())
    )
    self.checks = self.enter_context(
      mock.patch.object(
        fill_outfeed.configure_cell, "check_cell", return_value=[]
      )
    )
    self.out = self.create_tempdir().full_path

  def _main(self, *argv):
    return fill_outfeed.main(["--out", self.out, *argv])

  def test_each_part_goes_on_the_bed_then_runs_its_spots_cycle(self):
    code = self._main("--parts", "rebot_printed_part", "test_benchy")
    self.assertEqual(code, 0)
    targets = [
      call.args[0][call.args[0].index("--target") + 1]
      for call in self.configure.call_args_list
    ]
    self.assertEqual(targets, ["rebot_printed_part", "test_benchy"])
    for call in self.configure.call_args_list:
      self.assertIn("--keep_parked", call.args[0])
      self.assertIn("--apply", call.args[0])
    self.assertEqual(
      [c.kwargs["outfeed_spot"] for c in self.run_cycle.call_args_list], [0, 1]
    )
    for call in self.run_cycle.call_args_list:
      self.assertEqual(call.kwargs["num_cycles_override"], 1)

  def test_it_stops_at_the_first_failure_and_says_how_to_go_on(self):
    self.run_cycle.side_effect = [None, RuntimeError("Execution failed"), None]
    with mock.patch("sys.stderr") as stderr:
      code = self._main(
        "--parts",
        "rebot_printed_part",
        "test_cuboid_40x40x40",
        "test_benchy",
      )
    self.assertEqual(code, 1)
    # The third part is never put on the bed.
    self.assertEqual(self.configure.call_count, 2)
    self.assertEqual(self.run_cycle.call_count, 2)
    message = "".join(c.args[0] for c in stderr.write.call_args_list)
    self.assertIn("STOPPED at spot 1", message)
    self.assertIn(
      "--first_spot 1 --parts test_cuboid_40x40x40 test_benchy", message
    )

  def test_the_checks_run_once_per_part_height_and_not_before_every_part(self):
    # Heights: the default part and the lying cylinder share 15 mm, the cube 20.
    self._main(
      "--parts",
      "rebot_printed_part",
      "test_cylinder_30x60",
      "test_cuboid_40x40x40",
    )
    self.assertEqual(self.checks.call_count, 2)
    half_heights = sorted(c.args[2] for c in self.checks.call_args_list)
    self.assertEqual(half_heights, [0.015, 0.02])
    # The checks include the outfeed's transit frame.
    for call in self.checks.call_args_list:
      self.assertEqual(call.args[4], -90.0)
    for call in self.configure.call_args_list:
      self.assertIn("--skip_checks", call.args[0])
    # The checks come before the first part is put on the bed.
    self.assertEqual(self.configure.call_count, 3)

  def test_a_failed_check_stops_before_anything_is_applied(self):
    self.checks.return_value = ["view: line of sight blocked"]
    self.assertEqual(self._main("--parts", "rebot_printed_part"), 2)
    self.configure.assert_not_called()
    self.run_cycle.assert_not_called()

  def test_force_goes_on_after_a_failed_check(self):
    self.checks.return_value = ["view: line of sight blocked"]
    self.assertEqual(self._main("--parts", "rebot_printed_part", "--force"), 0)
    self.run_cycle.assert_called_once()

  def test_skip_checks_runs_none(self):
    self._main("--parts", "rebot_printed_part", "--skip_checks")
    self.checks.assert_not_called()

  def test_a_reset_also_checks_the_default_targets_height(self):
    self._main("--parts", "test_benchy", "--reset")
    half_heights = sorted(c.args[2] for c in self.checks.call_args_list)
    self.assertEqual(half_heights, [0.015, 0.024])

  def test_a_failed_configure_stops_before_the_cycle(self):
    self.configure.side_effect = SystemExit("not written: checks failed")
    self.assertEqual(self._main("--parts", "rebot_printed_part"), 1)
    self.run_cycle.assert_not_called()

  def test_first_spot_numbers_the_spots_from_there(self):
    self._main("--parts", "test_benchy", "--first_spot", "3")
    self.assertEqual(self.run_cycle.call_args.kwargs["outfeed_spot"], 3)

  def test_reset_parks_everything_first(self):
    self._main("--parts", "rebot_printed_part", "--reset")
    first = self.configure.call_args_list[0].args[0]
    self.assertNotIn("--keep_parked", first)
    self.assertNotIn("--target", first)

  def test_layout_and_count_are_passed_on(self):
    self._main("--parts", "rebot_printed_part", "--outfeed_layout", "arc")
    argv = self.configure.call_args.args[0]
    self.assertEqual(argv[argv.index("--outfeed_layout") + 1], "arc")

  def test_short_parts_unknown_parts_and_too_many_parts_are_refused(self):
    for argv in (
      ["--parts", "test_cuboid_40x40x22"],
      ["--parts", "no_such_part"],
      ["--parts", "rebot_printed_part", "rebot_printed_part"],
      ["--parts", "rebot_printed_part", "--first_spot", "5"],
    ):
      self.assertEqual(self._main(*argv), 2, argv)
    self.configure.assert_not_called()
    self.run_cycle.assert_not_called()

  def test_the_default_parts_are_tall_enough_and_known(self):
    library = fill_outfeed.cell.targets()
    self.assertEmpty(
      fill_outfeed._check(
        fill_outfeed.DEFAULT_PARTS, library, 0, len(fill_outfeed.DEFAULT_PARTS)
      )
    )


if __name__ == "__main__":
  absltest.main()
