# Handoff: Making the reBot Cell Cluster-Native

Plan to move `//:rebot_solution` from "a host script drives the cluster" to
"the cluster holds the logic", using Intrinsic Core's own building blocks
(services, skills, process assets). Based on `main` at `7c1c659` (2026-11-19).
It does not cover the print flow on `feat/preload-printed-model`; re-check this
plan against it when that branch merges. The overall project plan is
[`HANDOFF.md`](HANDOFF.md); the way of working (spiral, a demo per step) is in
`CLAUDE.md`.

Status: **analysis only, nothing implemented.**

---

## 1. Where `main` stands

Already native: ICON, motion planner, Gazebo, the NVIDIA pose estimator, the
train service, the Orbbec driver and the ROS bridge are solution instances. The
only skills declared are stock ones (`move_robot`, `move_to_contact`,
`attach_object_to_robot`, `detach_object`, `update_world`, `capture_images`,
`estimate_pose_multi_view`, `control_pinch_gripper`). The scene comes through
`object_world_updates`, and the arm, gripper, ground and printed part are
installed assets.

`rebot_solution` has **no custom skills or services of its own**.

## 2. Deviations

| # | Deviation | Where | Cost today |
| --- | --- | --- | --- |
| D1 | The orchestrator is a host process: it builds one `BehaviorTree` in Python and calls `executive.run`. Nothing is stored on the solution. | `src/main.py`, `src/behaviors/`, `src/hardware/` | Not startable from Flowstate; a host crash or disconnect ends the run. |
| D2 | Grasp planning is a `PythonScript` shipped into the executive; it edits the world directly and has no typed interface. | `src/utils/dynamic_frame_calculator.py`, `src/hardware/vision.py` | The grasp rule exists twice (`research/tools/cuboid_sweep.py` reimplements it, "keep them in step"). Cannot import `src.*`. |
| D3 | Pose-estimator registration is a manual host step, repeated after every deploy (a deploy removes it). | `research/REBOT_OMTS_APP.md` quick start step 4, `configure_cell`'s `register.sh` | The cell is unusable after a deploy until someone runs a script (about a minute). The estimator id and threshold are copied by hand into three places. |
| D4 | Cell parameters (printer distance, camera offset, target) live in host files and are applied by a host script. | `configs/rebot/cell_params.yaml`, `targets.yaml`, `research/tools/configure_cell.py` | Changing the cell means generating a pbtxt, an `app_config` copy and a shell script, then applying them from a checkout. |
| D5 | World edits and simulation resets come from a host tool. | `tools/world/apply_scene_updates.py` | Dev tooling, but the only way runtime parameters change. |
| D6 | Readiness checks, the Gazebo GUI and pose recording use `kubectl` and cluster-internal addresses. | `research/REBOT_OMTS_APP.md`, `research/tools/release_drift.py` | Operational, not architectural. |
| D7 | No in-tree skill source to copy from: `omts_solution`'s custom skills (`hand_e_gripper_cmd`, `moveit_plan_grasp`) are prebuilt release bundles. | `BUILD`, `bazel/gh_release.bzl` | Step 1 below has to establish the pattern (proto, manifest, `py_skill`, tests). |

## 3. Plan

Each step ends in a demo and leaves the `omts` and `lab_bb_01` cells building
(`CLAUDE.md`). New behavior goes alongside the old, behind config, until it is
proven.

### Step C1: `register_pose_estimator` skill (fixes D3, sets the pattern for D7)

* New package `skills/perception/` with the proto, manifest, `py_skill` target
  and an `absltest` test, and a `//skills/perception:register_pose_estimator_skill`
  entry in `rebot_solution`'s assets.
* Parameters: the scene-object asset, the estimator id, prompt and thresholds.
  It trains through the deployed train service and returns the estimator id in
  the form `estimate_pose_multi_view` takes. It succeeds without training when
  the estimator is already installed, so a tree can call it every cycle.
* The skill declares the services it uses as `ResolvedDependency` fields of its
  parameters, as intrinsic-core's `estimate_pose_multi_view` does, so it needs
  no equipment manifest.
* `omts_app` runs it as a first node of the tree when `vision` names a
  registration; the manual step stays documented as a fallback.
* **Demo:** deploy, run `omts_app` with no `register.sh` step, and the cycle
  finds the part.
* To check first: how the skill reaches the train service's long-running
  operation, and that a deploy followed by a second run takes the
  "already registered" path.

### Step C2: Grasp-frame skill (fixes D2)

* A skill that takes the estimated pose (and the camera and tool names, tilt
  and yaw symmetry) and returns the grasp and pre-grasp frames; a following
  `update_world` writes them, or the skill writes them itself like the MoveIt
  planner does. Decide which when starting: the footprint must lock the world
  (executive error 18201, `CLAUDE.md`).
* The math moves out of the script into a plain module that both the skill and
  `research/tools/cuboid_sweep.py` import, ending the duplicate.
* Selected through the existing `grasp.planner` config key
  (`GraspPlannerInterface`), next to `cuboid_center` and `moveit`.
* **Demo:** the same pick cycle with the new planner; the cuboid sweep's
  results unchanged.
* The `PythonScript` also updates the part's pose and applies `min_safe_z`;
  keep those (in the skill, or as a separate small node) so behavior stays the
  same.

### Step C3: Pick cycle as a process asset (fixes D1)

* Save the tree `omts_app` builds as a process on the solution
  (`solution.processes`; `ProcessAsset` in intrinsic-core), with the cell's
  frame and object names as parameters, started from Flowstate or by a thin
  `omts_app --run_process` call.
* Needs C1 and C2 first, so the process holds no host-side steps.
* To check first: that the pinned intrinsic-core builds a process asset from
  Bazel (only `process_asset.proto` and the `solution.processes` provider were
  found), and how parameters and loops (`num_cycles`) are expressed.
* **Demo:** run a cycle from Flowstate with the host disconnected.

### Step C4: Cell configuration in the cluster (fixes D4)

* Replace `configure_cell`'s file output with a skill (or service config) that
  takes printer distance, camera offset and target, runs the same checks
  (`research/tools/cell_checks.py`) and applies the world update itself.
* Keep `cell_params.yaml` as the source for a first run.
* **Demo:** change the printer distance with a single call to the cluster, with
  no `/tmp/cell` files and no `apply_scene_updates`.

### Stays on the host (D5, D6)

`kin`, `cuboid_sweep`, `view_search`, jogging, `apply_scene_updates` and the
`kubectl` / `gz` recipes are development tools. Keep them, and note in their
READMEs that they are not part of the deployed cell.

## 4. Open questions

1. Does the pinned Intrinsic Core build a process asset from Bazel, and can a
   process take parameters and a repeat count?
2. Should a skill write the grasp frames, or return them for `update_world`?
3. Is it worth moving the vision and robot adapters' trees into processes
   (one per subtree), or is one cycle process enough?
4. After a deploy, can anything keep the pose-estimator registration (it is an
   installed asset the deploy removes), or is a skill that re-registers on
   every start the right answer?
