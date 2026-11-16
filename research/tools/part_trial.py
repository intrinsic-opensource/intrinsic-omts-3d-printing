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

"""Sets up a graspability trial with one test part in the reBot cell.

For a cell deployed with --//:test_parts, writes to --out:

* trial.updates.pbtxt: the chosen part on the bed centre (and with --grid,
  the dense test grid beside it), standing as
  modelled (model z up) or with --lying on its side (model z along the
  world x axis, toward and away from the robot), then turned by --yaw; the
  other test parts and rebot_printed_part parked on the ground out of the
  arm's reach; and A's frames at the chosen part's height.
* app_config.yaml: configs/rebot/app_config.yaml with the chosen part as the
  workpiece and its own pose estimator id.

and prints the commands to apply the world, register the part and run a cycle
(research/tools/README.md, "Graspability trials"). With --parking, writes only
the parked placements, the file the deploy starts from
(configs/rebot/test_parts.updates.pbtxt).

  bazel run //research/tools:part_trial -- \
    --part test_cuboid_80x20x40 --yaw 90 --out /tmp/trial
  bazel run //research/tools:part_trial -- \
    --part test_cylinder_30x60 --lying --yaw 90 --out /tmp/trial
"""

import argparse
import math
import re
from pathlib import Path

import numpy as np

from research.tools import a_frames, cell

# Name -> model extents along x, y, z (m), from the target library.
PARTS = {name: t["size_m"] for name, t in cell.targets().items()}
# The dense grid (models/test_grid): extents, and its origin's height above
# what it rests on (it sits on its plate's underside).
GRID = "test_grid"
GRID_SIZE = (0.1, 0.1, 0.008)
# Parking spots on the ground, about 1 m from the base (reach 0.78 m).
PARKING_X = -0.85
PARKING_Y0, PARKING_DY = -0.75, 0.25
A_RADIUS, A_BEARING = 0.55, 130.0

HEADER = """\
# proto-file: intrinsic/world/public/proto/object_world_updates.proto
# proto-message: intrinsic_proto.world.ObjectWorldUpdates
"""


def _place(name: str, t: np.ndarray) -> str:
  p = t[:3, 3]
  q = cell.quat(t[:3, :3])
  return f"""updates {{
  reparent_object {{
    object {{ by_name {{ object_name: "{name}" }} }}
    new_parent {{ reference {{ by_name {{ object_name: "root" }} }} }}
  }}
}}
updates {{
  update_transform {{
    node_a {{ by_name {{ object {{ object_name: "root" }} }} }}
    node_b {{ by_name {{ object {{ object_name: "{name}" }} }} }}
    node_to_update {{ by_name {{ object {{ object_name: "{name}" }} }} }}
    a_t_b {{
      position {{ x: {p[0]:.4f} y: {p[1]:.4f} z: {p[2]:.4f} }}
      orientation {{ x: {q[0]:.6f} y: {q[1]:.6f} z: {q[2]:.6f} w: {q[3]:.6f} }}
    }}
  }}
}}
"""


def _frame(name: str, t: np.ndarray) -> str:
  p = t[:3, 3]
  q = cell.quat(t[:3, :3])
  return f"""updates {{
  create_frame {{
    new_frame_name: "{name}"
    parent_t_new_frame {{
      position {{ x: {p[0]:.4f} y: {p[1]:.4f} z: {p[2]:.4f} }}
      orientation {{ x: {q[0]:.6f} y: {q[1]:.6f} z: {q[2]:.6f} w: {q[3]:.6f} }}
    }}
    parent_object_with_filter {{
      reference {{ by_name {{ object_name: "root" }} }}
    }}
  }}
}}
"""


def parked(names) -> str:
  out = []
  for i, name in enumerate(names):
    t = np.eye(4)
    if name == GRID:
      # Static, origin at its base: park it flat on the ground.
      t[:3, 3] = (PARKING_X + 0.2, PARKING_Y0 + i * PARKING_DY, 0.0)
    else:
      t[:3, 3] = (PARKING_X, PARKING_Y0 + i * PARKING_DY, PARTS[name][2] / 2)
    out.append(_place(name, t))
  return "".join(out)


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--part", choices=sorted(PARTS), default=None)
  parser.add_argument("--yaw", type=float, default=0.0, help="deg")
  parser.add_argument(
    "--lying",
    action="store_true",
    help="lay the part on its side, model z along the world x axis",
  )
  parser.add_argument("--out", type=Path, default=None)
  parser.add_argument("--parking", type=Path, default=None)
  parser.add_argument(
    "--grid",
    type=float,
    default=None,
    metavar="Y",
    help="also put the dense test grid on the bed, centred Y m to the side",
  )
  parser.add_argument(
    "--depth",
    type=float,
    default=0.0,
    help=(
      "grasp.grasp_depth_meters for the trial (m); needs that option, "
      "stashed for now (research/HANDOFF.md)"
    ),
  )
  parser.add_argument(
    "--text_prompt",
    default="object on a table",
    help="SAM 3 prompt; this generic one has worked for every part so far",
  )
  parser.add_argument(
    "--confidence_threshold",
    type=float,
    default=0.25,
    help="SAM 3 threshold; low enough to keep the part, the mesh fit picks it",
  )
  args = parser.parse_args()

  test_parts = [n for n in PARTS if n != "rebot_printed_part"] + [GRID]
  if args.parking:
    args.parking.write_text(
      HEADER
      + "\n# Test parts parked on the ground, out of the reBot's reach, for"
      + "\n# the graspability trials (research/tools/README.md). Loaded by"
      + "\n# //:rebot_solution only with --//:test_parts. Written by"
      + "\n# //research/tools:part_trial --parking.\n\n"
      + parked(test_parts)
    )
    print(f"wrote {args.parking}")
    return
  if not (args.part and args.out):
    parser.error("--part and --out are required (or --parking)")

  args.out.mkdir(parents=True, exist_ok=True)
  sx, sy, sz = PARTS[args.part]
  rest = np.eye(3)
  height = sz
  if args.lying:
    # A quarter turn about y: model z to world x, model x straight down.
    rest = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
    height = sx
  on_bed = np.eye(4)
  on_bed[:3, :3] = cell.rot_z(math.radians(args.yaw)) @ rest
  on_bed[:3, 3] = cell.bed_centre() + [0, 0, height / 2]
  tilt = cell.app_setting("approach_tilt_degrees")
  frames = a_frames.frames(
    tilt, A_RADIUS, A_BEARING, half_height=height / 2, depth=args.depth
  )
  updates = (
    HEADER
    + f"\n# Graspability trial: {args.part} on the bed"
    + (", lying" if args.lying else "")
    + f", yaw {args.yaw:g} deg.\n\n"
    + _place(args.part, on_bed)
    + parked([n for n in PARTS if n != args.part] + [GRID])
    + "".join(_frame(name, t) for name, t in frames.items())
  )
  if args.grid is not None:
    grid = np.eye(4)
    grid[:3, 3] = cell.bed_centre() + [0, args.grid, 0]
    updates += "\n# The dense test grid on the bed.\n" + _place(GRID, grid)
  (args.out / "trial.updates.pbtxt").write_text(updates)

  # The service caches an estimator's settings by id, so the id names the
  # prompt.
  prompt_id = re.sub(r"\W+", "_", args.text_prompt)
  estimator = f"ai.intrinsic.{args.part}_{prompt_id}"
  config = (cell.CONFIGS / "app_config.yaml").read_text()
  for key, value in (
    ("workpiece_id", args.part),
    ("scene_object_id", f"ai.intrinsic.{args.part}"),
    ("pose_estimator_id", estimator),
  ):
    config, n = re.subn(
      rf'^(\s*{key}:\s*)"[^"]*"', rf'\g<1>"{value}"', config, flags=re.M
    )
    if n != 1:
      raise SystemExit(f"{key} not found once in app_config.yaml")
  n = 1
  if args.depth:
    config, n = re.subn(
      r"^(\s*)grasp_depth_meters:.*$",
      rf"\g<1>grasp_depth_meters: {args.depth}",
      config,
      flags=re.M,
    )
  if not n:
    config, n = re.subn(
      r"^(\s*)(yaw_symmetry_degrees:.*)$",
      rf"\g<1>\g<2>\n\g<1>grasp_depth_meters: {args.depth}",
      config,
      flags=re.M,
    )
  if n != 1:
    raise SystemExit("could not set grasp_depth_meters in app_config.yaml")
  (args.out / "app_config.yaml").write_text(config)

  out = args.out.resolve()
  print(f"""Trial files in {out}. From the repository root:

bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 \\
  --files {out}/trial.updates.pbtxt --reset_sim
bazel run -c opt \\
  --repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR=$HOME/intrinsic-models/nvidia_pose_estimator \\
  @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- \\
  --address=localhost:17080 --scene_object_id=ai.intrinsic.{args.part} \\
  --pose_estimator_id={estimator} --refinement_iters=5 \\
  --confidence_threshold={args.confidence_threshold} --visibility_threshold=0.15 \\
  --text_prompt="{args.text_prompt}"
bazel run //src:omts_app -- --address=localhost:17080 \\
  --config={out}/app_config.yaml --num_cycles=1""")


if __name__ == "__main__":
  main()
