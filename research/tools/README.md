# Offline checks for the reBot cell

Scripts behind the reach and clearance numbers in `research/HANDOFF.md`. They
check frames and grasps for the reBot printer-tending cell without a
deployment, and analyse part motion recorded in Gazebo.

They read the cell from the checkout at run time, so an edited config is
checked without rebuilding:

* the printer's pose and the camera mount, from `configs/rebot/*.updates.pbtxt`;
* the printer's collision boxes and bed, from `models/printer/`;
* the arm's link collision meshes, from `models/rebot_b601_rs/`;
* the grasp tilt and pre-grasp offset, from `configs/rebot/app_config.yaml`.

Run them with `bazel run`, which also provides numpy and scipy.

## What they model, and what they don't

* **Kinematics** (`kin.py`): the B601-RS joints copied from its SDF, with the
  tool at the gripper's `tool_frame`. IK is numeric: several seeds, and among
  the solutions, the one whose arm and camera are furthest from the printer.
  The motion planner may choose another.
* **Obstacles** (`cell.py`): the printer's collision boxes plus a plate under
  the heatbed's top surface. No ground, no self-collision, and no other
  objects.
* **Arm bodies:** points on each link's collision mesh (link2 to link6), plus
  boxes for the camera body and the gripper. The gripper box covers the
  fingers, so at a grasp it reaching the bed by a few millimetres is
  expected, not a collision.
* Distances are signed: negative means inside an obstacle. They agreed with
  the planner in the cases checked (link4 4 mm into the Prusa's front rail
  where the planner reported that collision), but treat them as a guide and
  confirm in simulation.

## Tools

| Target | What it does |
| --- | --- |
| `grasp_clearance` | Tilted grasp and pre-grasp over the bed, at offsets around the bed centre and at given yaws: reach, joint margin, and the closest arm or camera body to the printer. Use it after moving the printer or changing the grasp tilt. |
| `config_clearance` | Each body's distance to the printer at joint configurations, in the format of the planner's collision report (`Config: [...] in deg`). Use it to see what a failed plan hit. |
| `a_frames` | A's three frames (place, pre-place, approach) for a tilt, distance and bearing, with the joint margin at each. Prints positions and quaternions for `configs/rebot/scene.updates.pbtxt`. |
| `view_search` | Candidate `view` poses that reach, clear the printer, have a clear line of sight to the part, and see all four bed corners with depth. Also checks the committed `view`. |
| `cuboid_sweep` | Which cuboids the cell can grasp from the bed: sweeps sizes (z up, as printed) and yaws, replays the grasp `omts_app` publishes, and checks jaw width, fingers and palm against the part and printer on the approach and at the grasp, and reach. The grasp rule is reimplemented from `src/utils/dynamic_frame_calculator.py`; keep them in step. |
| `part_trial` | Sets up a graspability trial in simulation with one test part (a cuboid or a cylinder, standing or lying): its placement on the bed, A's frames at its height, and an `app_config` naming it (see below). |
| `prompt_sweep` | Scores SAM 3 text prompts on saved camera images, offline on the CPU, with the pose estimator's own SAM 3 export, preprocessing and tokenizer: presence, regions over a threshold, and the part's score, rank and margin when its pixel box is given. Matches the cluster's first segmentation pass (see below). |
| `configure_cell` | Sets the printer distance, camera offset and target on the running cell, from `configs/rebot/cell_params.yaml` or flags: checks them, then writes the world update, `app_config` and registration script (`research/REBOT_OMTS_APP.md`). |
| `cell_limits` | Sweeps the printer distance and camera offset one at a time, with `configure_cell`'s checks. Results in `research/HANDOFF.md`, section 5d. |
| `release_drift` | From a Gazebo pose recording: how far the part moved at each release, and how long each finger took to open. |

Examples, all from the repository root:

```bash
# Grasp clearance at two tilts, with the part 1 cm to the side
bazel run //research/tools:grasp_clearance -- --tilt 60 75 --dy 0 0.01

# What a failed plan hit (paste the Config line from the error)
bazel run //research/tools:config_clearance -- \
  "[-0.0754,-90.5722,-61.8224,1.2505,-0.1169,-0.0670]"

# A's frames at three distances
bazel run //research/tools:a_frames -- --radius 0.45 0.50 0.55

# View candidates, and a check of the committed view
bazel run //research/tools:view_search

# Graspable cuboids: sizes in mm, yaws in degrees
bazel run //research/tools:cuboid_sweep -- --sizes 20 40 60 80 95 --yaws 0 10 20 45 90
```

## Recording poses in Gazebo

`release_drift` reads Gazebo's pose topic recorded as JSON lines. Record while
`omts_app` runs, from a shell that can reach the cluster's simulation (the
same settings as the Gazebo GUI in `research/REBOT_OMTS_APP.md`):

```bash
export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1 \
  GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 -o jsonpath='{.status.podIP}')
timeout 120 gz topic -e -t /world/default/pose/info --json-output > /tmp/poses.jsonl &
bazel run //src:omts_app -- --address=localhost:17080 \
  --config=configs/rebot/app_config.yaml --num_cycles=1
bazel run //research/tools:release_drift -- /tmp/poses.jsonl
```

The recording holds every model and link pose in the world, so other motion,
such as the fingers during a grasp, can be read from the same file.

## Graspability trials in simulation

`cuboid_sweep` predicts which cuboids are graspable; trials confirm it with
the real app. Deploy the cell with the test parts
([`models/test_cuboids/`](../../models/test_cuboids/),
[`models/test_cylinders/`](../../models/test_cylinders/)), which start parked
on the ground out of reach:

```bash
bazel run -c opt --//:perception_models --//:test_parts \
  --repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR=$HOME/intrinsic-models/nvidia_pose_estimator \
  //:rebot_solution -- --address=localhost:17080
bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 \
  --files --reset_sim
```

Then, per trial, write its files and run the commands the tool prints: apply
the world (the chosen cuboid on the bed and A's frames at its height),
register the part with the pose estimator (once per part and deploy, with
the generic prompt "object on a table" at threshold 0.25, which has worked
for every part so far, `research/HANDOFF.md` step 4c-2), and run one cycle:

```bash
bazel run //research/tools:part_trial -- \
  --part test_cuboid_80x20x40 --yaw 90 --out /tmp/trial
```

Afterwards, `apply_scene_updates --setup rebot --reset_sim` puts the default
part back on the bed and parks the test parts again. (`--files` with no file
names applies nothing; it only resets Gazebo to the current world.)

## Comparing SAM 3 prompts offline

`prompt_sweep` runs the pose estimator's SAM 3 export
(`NVIDIA_POSE_ESTIMATOR_MODELS_DIR`, `research/REBOT_OMTS_APP.md` quick start
step 2) on the CPU with onnxruntime, so prompts can be compared on saved
images in seconds each instead of a registration per prompt on the cluster.
Its scores matched the cluster's to three decimals. onnxruntime is not one of
the solution's Python dependencies; install it into a directory of its own
with the Python Bazel uses, once:

```bash
PY=$(ls -d $(bazel info output_base)/external/rules_python++python+python_3_11_x86_64-unknown-linux-gnu)/bin/python3
$PY -m pip install --target $HOME/.local/share/omts-onnxruntime onnxruntime
```

Save an RGB image from `view` (Gazebo's `/orbbec_camera/rgb` after a
`capture_images`, as in `research/REBOT_OMTS_APP.md`, Debugging), and give the
part's pixel box after the path to get its score, rank and margin:

```bash
PYTHONPATH=$HOME/.local/share/omts-onnxruntime \
  bazel run //research/tools:prompt_sweep -- \
  --image /tmp/box.png:604,363,676,439 \
  --prompt "object" --prompt "object on a table" --threshold 0.35
```

Loading takes a few seconds, each image about 6 s and each prompt well under
a second per image (32 CPU cores).
