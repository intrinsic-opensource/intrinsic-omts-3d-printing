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
