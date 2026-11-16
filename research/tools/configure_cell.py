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
  which keeps the camera where it was relative to the printer, and A's frames
  at the target's height).
* app_config.yaml: configs/rebot/app_config.yaml with the target and the return
  area on the moved bed.
* register.sh: registers the target with the pose estimator (--register_all:
  every target in the library).

It checks the values first (research/tools/cell_checks.py), and refuses to write
if they fail, unless --force. Then it prints the commands to apply them.

  bazel run //research/tools:configure_cell -- --out /tmp/cell
  bazel run //research/tools:configure_cell -- --out /tmp/cell \\
    --printer_distance 0.62 --target test_benchy
"""

import argparse
import re
from pathlib import Path

import numpy as np

from research.tools import a_frames, cell, cell_checks, part_trial

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


def _app_config(name: str, target: dict, return_x: float) -> str:
  config = (cell.CONFIGS / "app_config.yaml").read_text()
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


def main() -> None:
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
  parser.add_argument("--register_all", action="store_true")
  parser.add_argument(
    "--force", action="store_true", help="write even if the checks fail"
  )
  args = parser.parse_args()

  params = cell.parameters()
  distance = args.printer_distance or params["printer_distance_m"]
  offset = tuple(args.camera_offset or params["camera_offset_m"])
  name = args.target or params["target"]
  library = cell.targets()
  if name not in library:
    raise SystemExit(f"{name} not in targets.yaml: {sorted(library)}")
  target = library[name]
  sx, sy, sz = target["size_m"]
  lying = target.get("lying", False)
  half_height = (sx if lying else sz) / 2

  committed_camera = cell_checks.committed_view_camera()
  view = cell_checks.view_for(committed_camera, distance, offset)
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
  )
  print(f"printer {distance} m, camera {offset}, target {name}")
  for p in problems:
    print(f"  FAILS {p}")
  if problems and not args.force:
    raise SystemExit("not written: see research/HANDOFF.md for the limits")
  if not problems:
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
      tilt, part_trial.A_RADIUS, part_trial.A_BEARING, half_height=half_height
    ),
  }
  others = [n for n in library if n != name]
  if args.no_test_parts:
    others = [n for n in others if n == "rebot_printed_part"]
  args.out.mkdir(parents=True, exist_ok=True)
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
  (args.out / "app_config.yaml").write_text(_app_config(name, target, bed[0]))
  chosen = library if args.register_all else {name: target}
  (args.out / "register.sh").write_text(
    "#!/bin/bash\n# Run from the repository root, once per deploy.\nset -e\n"
    + "".join(_register(n, t) for n, t in chosen.items())
  )

  out = args.out.resolve()
  print(f"""Written to {out}. From the repository root:

bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 \\
  --files {out}/cell.updates.pbtxt --reset_sim
bash {out}/register.sh   # once per deploy; moving the cell does not need it
bazel run //src:omts_app -- --address=localhost:17080 \\
  --config={out}/app_config.yaml --num_cycles=1""")


if __name__ == "__main__":
  main()
