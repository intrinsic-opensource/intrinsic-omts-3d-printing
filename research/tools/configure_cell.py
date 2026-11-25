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

"""Sets the reBot cell's printer distance, camera offset and target, live.

Reads configs/rebot/cell_params.yaml (flags override it) and writes to --out:

* cell.updates.pbtxt: the printer and camera poses, the target on the bed
  centre, the other targets parked, and the frames that follow from them (view,
  which keeps the camera where it was relative to the printer, A's frames and
  the outfeed spots' at the target's height).
* app_config.yaml: configs/rebot/app_config.yaml with the target and the return
  area on the moved bed, and the outfeed spots' frames.
* register.sh: registers the target with the pose estimator (--register_all:
  every target in the library).

It checks the values first (research/tools/cell_checks.py), and refuses to write
if they fail, unless --force. Then it prints the commands to apply them.

With --apply, everything in cell.updates.pbtxt is set on the running cell by
the `ai.omts.configure_cell` skill (skills/cell/) instead, in one update, and in
simulation Gazebo is brought to it: no file is written but app_config.yaml, and
no apply_scene_updates is needed. The checks run first, on the host.

  bazel run //research/tools:configure_cell -- --out /tmp/cell
  bazel run //research/tools:configure_cell -- --out /tmp/cell \\
    --printer_distance 0.62 --target test_benchy
  bazel run //research/tools:configure_cell -- --out /tmp/cell \\
    --outfeed_layout arc --outfeed_count 4
"""

import argparse
import math
import re
from pathlib import Path

import numpy as np

from research.tools import a_frames, cell, cell_checks, part_trial
from src.core import outfeed

MODELS_DIR = "$HOME/intrinsic-models/nvidia_pose_estimator"


def _pose_update(a: str, b: str, position, orientation) -> str:
  p, q = position, orientation
  return f"""updates {{
  update_transform {{
    node_a {{ by_name {a} }}
    node_b {{ by_name {{ object {{ object_name: "{b}" }} }} }}
    node_to_update {{ by_name {{ object {{ object_name: "{b}" }} }} }}
    a_t_b {{
      position {{ x: {p[0]:.4f} y: {p[1]:.4f} z: {p[2]:.4f} }}
      orientation {{ x: {q[0]:.6f} y: {q[1]:.6f} z: {q[2]:.6f} w: {q[3]:.6f} }}
    }}
  }}
}}
"""


def _register(name: str, target: dict) -> str:
  return f"""bazel run -c opt --//:perception_models --//:test_parts \\
  --repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR={MODELS_DIR} \\
  @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- \\
  --address=localhost:17080 --scene_object_id=ai.intrinsic.{name} \\
  --pose_estimator_id={target["pose_estimator_id"]} --refinement_iters=5 \\
  --confidence_threshold={target["confidence_threshold"]} --visibility_threshold=0.15 \\
  --text_prompt="object on a table"
"""


OUTFEED_PREFIX = "outfeed"


def _outfeed_spots(settings: dict) -> list[outfeed.Spot]:
  """The spots of the layout `settings` (cell_params.yaml's `outfeed`) picks."""
  layout, count = settings["layout"], int(settings["count"])
  if layout == "line":
    line = settings["line"]
    return outfeed.line_spots(
      count, line["y"], line["start_x"], line["spacing"]
    )
  if layout == "arc":
    arc = settings["arc"]
    return outfeed.arc_spots(
      count, arc["radius"], arc["start_bearing"], arc["step"]
    )
  raise SystemExit(f"outfeed layout must be line or arc, not {layout!r}")


def _outfeed_config(count: int, transit: bool) -> str:
  """app_config.yaml's `outfeed` section, with `count` spots and, if the cell
  has one, the transit frame."""
  spots = "".join(
    f'    - place_frame: "{place}"\n'
    f'      preplace_frame: "{pre}"\n'
    f'      approach_frame: "{approach}"\n'
    for place, pre, approach in (
      outfeed.frame_names(OUTFEED_PREFIX, k) for k in range(count)
    )
  )
  frame = f'  transit_frame: "{OUTFEED_PREFIX}_transit"\n' if transit else ""
  return "outfeed:\n  spots:\n" + spots + frame


def _app_config(
  name: str,
  target: dict,
  return_x: float,
  spot_count: int,
  transit: bool = False,
) -> str:
  config = (cell.CONFIGS / "app_config.yaml").read_text()
  config, n = re.subn(
    r"^outfeed:\n  spots:\n(?:    .*\n|      .*\n)+(?:  transit_frame: .*\n)?",
    lambda _: _outfeed_config(spot_count, transit),
    config,
    flags=re.M,
  )
  if n != 1:
    raise SystemExit("the outfeed section not found once in app_config.yaml")
  for key, value in (
    ("workpiece_id", f'"{name}"'),
    ("scene_object_id", f'"ai.intrinsic.{name}"'),
    ("pose_estimator_id", f'"{target["pose_estimator_id"]}"'),
    ("center_x", f"{return_x:.4f}"),
  ):
    config, n = re.subn(
      rf"^(\s*{key}:\s*).*$", rf"\g<1>{value}", config, flags=re.M
    )
    if n != 1:
      raise SystemExit(f"{key} not found once in app_config.yaml")
  return config


def _outfeed_proto(settings: dict, tilt: float, half_height: float):
  """The skill's `Outfeed` for cell_params.yaml's `outfeed` section."""
  from skills.cell import configure_cell_pb2

  common = dict(
    count=int(settings["count"]),
    approach_tilt_degrees=tilt,
    part_half_height_m=half_height,
    frame_prefix=OUTFEED_PREFIX,
  )
  if settings.get("transit_rotation_degrees") is not None:
    common["transit_rotation_degrees"] = float(
      settings["transit_rotation_degrees"]
    )
  if settings["layout"] == "line":
    line = settings["line"]
    return configure_cell_pb2.Outfeed(
      line=configure_cell_pb2.Outfeed.Line(
        y_m=line["y"], start_x_m=line["start_x"], spacing_m=line["spacing"]
      ),
      **common,
    )
  arc = settings["arc"]
  return configure_cell_pb2.Outfeed(
    arc=configure_cell_pb2.Outfeed.Arc(
      radius_m=arc["radius"],
      start_bearing_degrees=arc["start_bearing"],
      step_degrees=arc["step"],
    ),
    **common,
  )


def _apply(
  address: str,
  distance: float,
  offset,
  tilt,
  target_name: str,
  half_height: float,
  lying: bool,
  others,
  outfeed_settings: dict,
) -> None:
  """Sets the printer, the camera mount, the view, A's frames, the outfeed spots'
  frames, the part on the bed and the parked parts with the cluster's
  `configure_cell` skill, in one world update, and in simulation brings Gazebo
  to that world."""
  from intrinsic.math.proto import point_pb2
  from intrinsic.solutions import behavior_tree as bt
  from intrinsic.solutions import deployments, worlds

  from skills.cell import configure_cell_pb2

  def point(v):
    return point_pb2.Point(x=v[0], y=v[1], z=v[2])

  solution = deployments.connect(address=address)
  action = solution.skills.ai.omts.configure_cell(
    printer_distance_m=distance,
    camera_offset_m=point(offset),
    drop_off=configure_cell_pb2.DropOff(
      approach_tilt_degrees=tilt,
      radius_m=part_trial.A_RADIUS,
      bearing_degrees=part_trial.A_BEARING,
      part_half_height_m=half_height,
    ),
    outfeed=_outfeed_proto(outfeed_settings, tilt, half_height),
    target=configure_cell_pb2.Target(
      object_name=target_name,
      bed_top_in_printer_m=point(cell.bed_top_local()),
      part_half_height_m=half_height,
      lying=lying,
    ),
    parked=[
      configure_cell_pb2.ParkedObject(object_name=n, position_m=point(position))
      for n, position in part_trial.parking_positions(others).items()
    ],
  )
  solution.executive.run(bt.Task(action=action, name="Configure the cell"))
  print(f"Applied the cell on {address}")
  if solution.is_simulated:
    # Gazebo changes only when the simulation is brought to the belief world,
    # which starting an operation from it does.
    solution.executive.run(
      bt.BehaviorTree(
        name="Bring the simulation to the belief world",
        root=bt.Sequence(children=[]),
      ),
      start_from_world_state=worlds.EditWorldId.BELIEF,
    )
    print("The simulation now matches")


def _turned(pose: np.ndarray, degrees: float) -> np.ndarray:
  """`pose` turned about the world z axis (the robot's base)."""
  turn = np.eye(4)
  turn[:3, :3] = cell.rot_z(math.radians(degrees))
  return turn @ pose


def half_height_of(target: dict) -> float:
  """Half the part's height as it rests on the bed: half its width if it lies."""
  sx, _, sz = target["size_m"]
  return (sx if target.get("lying", False) else sz) / 2


def outfeed_settings_for(
  params: dict, layout: str | None = None, count: int | None = None
) -> dict:
  """cell_params.yaml's `outfeed` section, with the layout and count replaced."""
  settings = dict(params["outfeed"])
  if layout:
    settings["layout"] = layout
  if count:
    settings["count"] = count
  return settings


def check_cell(
  distance: float,
  offset,
  half_height: float,
  spots: list[outfeed.Spot],
  transit_rotation_degrees: float | None = None,
) -> list[str]:
  """The offline checks (research/tools/cell_checks.py) for a part of
  `half_height` and the outfeed `spots`, with the transit frame if there is a
  rotation for it. Slow: about 20 s."""
  view = cell_checks.view_for(
    cell_checks.committed_view_camera(), distance, offset
  )
  c = cell.Cell(samples=800)
  rng = np.random.default_rng(7)
  tilt = cell.app_setting("approach_tilt_degrees")
  approach = cell.app_setting("approach_offset_z")
  problems = (
    cell_checks.check_mount(c)
    + cell_checks.check_view(c, view, half_height, rng)
    + cell_checks.check_grasps(c, half_height, tilt, approach, rng)
    + cell_checks.check_a(
      c, half_height, tilt, part_trial.A_RADIUS, part_trial.A_BEARING, rng
    )
    + cell_checks.check_outfeed(c, half_height, tilt, spots, rng)
  )
  if transit_rotation_degrees is not None:
    problems += cell_checks.check_outfeed_transit(
      c,
      view,
      _turned(view, transit_rotation_degrees),
      half_height,
      tilt,
      spots,
      rng,
    )
  return problems


def main(argv: list[str] | None = None) -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--out", type=Path, required=True)
  parser.add_argument("--printer_distance", type=float, default=None)
  parser.add_argument(
    "--camera_offset",
    type=float,
    nargs=3,
    default=None,
    metavar=("X", "Y", "Z"),
  )
  parser.add_argument("--target", default=None)
  parser.add_argument(
    "--no_test_parts",
    action="store_true",
    help="the cell was deployed without --//:test_parts: park nothing",
  )
  parser.add_argument(
    "--outfeed_layout",
    choices=("line", "arc"),
    default=None,
    help="the outfeed line's layout (default: cell_params.yaml's)",
  )
  parser.add_argument("--outfeed_count", type=int, default=None)
  parser.add_argument(
    "--skip_checks",
    action="store_true",
    help="do not run the offline checks (about 20 s each time), because the "
    "caller has run them for these values (fill_outfeed does, once)",
  )
  parser.add_argument(
    "--keep_parked",
    action="store_true",
    help="leave the other parts where they are instead of parking them, so "
    "parts already on the outfeed line stay there",
  )
  parser.add_argument("--register_all", action="store_true")
  parser.add_argument(
    "--apply",
    action="store_true",
    help="set the cell with the configure_cell skill on the running cell "
    "instead of writing cell.updates.pbtxt, and sync the simulation",
  )
  parser.add_argument("--address", default="localhost:17080")
  parser.add_argument(
    "--force", action="store_true", help="write even if the checks fail"
  )
  args = parser.parse_args(argv)

  params = cell.parameters()
  distance = args.printer_distance or params["printer_distance_m"]
  offset = tuple(args.camera_offset or params["camera_offset_m"])
  name = args.target or params["target"]
  library = cell.targets()
  if name not in library:
    raise SystemExit(f"{name} not in targets.yaml: {sorted(library)}")
  target = library[name]
  lying = target.get("lying", False)
  half_height = half_height_of(target)

  outfeed_settings = outfeed_settings_for(
    params, args.outfeed_layout, args.outfeed_count
  )
  spots = _outfeed_spots(outfeed_settings)

  view = cell_checks.view_for(
    cell_checks.committed_view_camera(), distance, offset
  )
  tilt = cell.app_setting("approach_tilt_degrees")
  transit_degrees = outfeed_settings.get("transit_rotation_degrees")
  problems = (
    []
    if args.skip_checks
    else check_cell(distance, offset, half_height, spots, transit_degrees)
  )
  print(
    f"printer {distance} m, camera {offset}, target {name}, outfeed "
    f"{outfeed_settings['layout']} x {len(spots)}"
  )
  for p in problems:
    print(f"  FAILS {p}")
  if problems and not args.force:
    raise SystemExit("not written: see research/HANDOFF.md for the limits")
  if args.skip_checks:
    print("  checks skipped")
  elif not problems:
    print("  checks pass")

  rest = np.eye(3)
  if lying:
    rest = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
  on_bed = np.eye(4)
  on_bed[:3, :3] = rest
  bed = cell.bed_centre()
  on_bed[:3, 3] = bed + [0, 0, half_height]
  printer = cell.world_t_printer()
  flange_t_cam = cell.object_pose(
    cell.CONFIGS / "orbbec_gemini.updates.pbtxt", "orbbec_camera"
  )
  frames = {
    "view": view,
    **a_frames.frames(
      tilt,
      part_trial.A_RADIUS,
      part_trial.A_BEARING,
      half_height=half_height,
    ),
  }
  for k, spot in enumerate(spots):
    spot_frames = a_frames.frames(
      tilt,
      math.hypot(spot.x, spot.y),
      math.degrees(math.atan2(spot.y, spot.x)),
      half_height=half_height,
      yaw=spot.yaw_degrees,
    )
    for frame_name, key in zip(
      outfeed.frame_names(OUTFEED_PREFIX, k),
      ("place_vise", "pre_place_vise", "machine_approach"),
      strict=True,
    ):
      frames[frame_name] = spot_frames[key]
  if transit_degrees is not None:
    frames[f"{OUTFEED_PREFIX}_transit"] = _turned(view, transit_degrees)
  others = [n for n in library if n != name]
  if args.no_test_parts:
    others = [n for n in others if n == "rebot_printed_part"]
  if args.keep_parked:
    others = []
  args.out.mkdir(parents=True, exist_ok=True)
  (args.out / "app_config.yaml").write_text(
    _app_config(name, target, bed[0], len(spots), transit_degrees is not None)
  )
  out = args.out.resolve()

  if args.apply:
    _apply(
      args.address,
      distance,
      offset,
      tilt,
      name,
      half_height,
      lying,
      others,
      outfeed_settings,
    )
    print(f"""The app's config for this target is in {out}/app_config.yaml.
Nothing is left to apply by hand. From the repository root:

bazel run //src:omts_app -- --address=localhost:17080 \\
  --config={out}/app_config.yaml --num_cycles=1""")
    return

  (args.out / "cell.updates.pbtxt").write_text(
    part_trial.HEADER
    + f"\n# Printer at {distance} m, camera at {offset}, target {name}.\n\n"
    + _pose_update(
      '{ object { object_name: "root" } }',
      "printer",
      printer[:3, 3],
      cell.quat(printer[:3, :3]),
    )
    + _pose_update(
      '{ frame { object_name: "rebot" frame_name: "flange" } }',
      "orbbec_camera",
      offset,
      cell.quat(flange_t_cam[:3, :3]),
    )
    + part_trial._place(name, on_bed)
    + part_trial.parked(others)
    + "".join(part_trial._frame(n, t) for n, t in frames.items())
  )
  chosen = library if args.register_all else {name: target}
  (args.out / "register.sh").write_text(
    "#!/bin/bash\n# Run from the repository root, once per deploy.\nset -e\n"
    + "".join(_register(n, t) for n, t in chosen.items())
  )

  print(f"""Written to {out}. From the repository root:

bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 \\
  --files {out}/cell.updates.pbtxt --reset_sim
bash {out}/register.sh   # once per deploy; moving the cell does not need it
bazel run //src:omts_app -- --address=localhost:17080 \\
  --config={out}/app_config.yaml --num_cycles=1""")


if __name__ == "__main__":
  main()
