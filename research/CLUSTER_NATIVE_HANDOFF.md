# Handoff: Making the reBot Cell Cluster-Native

Plan to move `//:rebot_solution` from "a host script drives the cluster" to
"the cluster holds the logic", using Intrinsic Core's own building blocks
(services, skills, process assets). Based on `main` at `7c1c659` (2026-11-19).
It does not cover the print flow on `feat/preload-printed-model`; re-check this
plan against it when that branch merges. The overall project plan is
[`HANDOFF.md`](HANDOFF.md); the way of working (spiral, a demo per step) is in
`CLAUDE.md`.

Status (2026-11-19): **C1, C2 and C4 done; C3 explored and paused.** The cluster-native steps that were not paused are finished.

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
| D4 | Cell parameters (printer distance, camera offset, target) live in host files and are applied by a host script. **Closed by C4**: `configure_cell --apply` sets them on the cluster in one call. | `configs/rebot/cell_params.yaml`, `targets.yaml`, `research/tools/configure_cell.py` | Changing the cell means generating a pbtxt, an `app_config` copy and a shell script, then applying them from a checkout. |
| D5 | World edits and simulation resets come from a host tool. | `tools/world/apply_scene_updates.py` | Dev tooling, but the only way runtime parameters change. |
| D6 | Readiness checks, the Gazebo GUI and pose recording use `kubectl` and cluster-internal addresses. | `research/REBOT_OMTS_APP.md`, `research/tools/release_drift.py` | Operational, not architectural. |
| D7 | No in-tree skill source to copy from: `omts_solution`'s custom skills (`hand_e_gripper_cmd`, `moveit_plan_grasp`) are prebuilt release bundles. | `BUILD`, `bazel/gh_release.bzl` | Step 1 below has to establish the pattern (proto, manifest, `py_skill`, tests). |

## 3. Plan

Each step ends in a demo and leaves the `omts` and `lab_bb_01` cells building
(`CLAUDE.md`). New behavior goes alongside the old, behind config, until it is
proven.

### Step C1: `register_pose_estimator` skill (fixes D3, sets the pattern for D7) — DONE 2026-11-19

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

**Done on 2026-11-19** (k3s, sim, with `--//:perception_models`):

* The skill is the one from `feat/preload-printed-model` (its package
  `skills/perception/`, with its unit test), ported as is apart from two
  comments. It reads the scene object from the installed-assets service and has
  the train service build and save the estimator; it returns early if the
  estimator is installed.
* `vision.registration` (optional; `PoseEstimatorRegistration` in
  `src/core/config.py`) holds the train service name, prompt, thresholds and
  iterations. `OrbbecVision` puts a register node in a sequence **ahead of**
  the retried perception, so a failed training is not retried three times.
  Cells without the section build the same tree as before.
* **Result:** after a deploy, with nothing registered by hand, `omts_app`
  finished (62 s). The skill logged "Registered pose estimator ..." for that
  run, and the next run logged "is already installed" and finished (57 s). The
  deploy had removed the earlier registration, so this covers D3.
* `MODULE.bazel` gains `rules_oci` and `use_repo(oci, "distroless_python3")`: a
  `py_skill` needs the base image. Bazel warns that the import is indirect and
  suggests `bazel mod tidy`; that drops the line and breaks the build.
* Known gap: `configs/rebot/targets.yaml` has a threshold per target, and
  `configure_cell` does not carry it into `vision.registration`. All are 0.25
  today, so nothing differs. Registering again under an existing id keeps the
  old settings, so a changed prompt or threshold needs a new `pose_estimator_id`.
* `register_using_ioc_train_service` and `register.sh` still work, and stay
  documented as the manual route.

### Step C2: Grasp-frame skill (fixes D2) — DONE 2026-11-19

* The `ai.omts.plan_cuboid_grasp` skill (`skills/grasp/`) replaces the
  `bt.PythonScript` of `src/utils/dynamic_frame_calculator.py`. It takes the
  estimate (the `root_t_target` of `estimate_pose_multi_view`, which is in the
  camera's frame), the camera, tool and frame names, tilt and yaw symmetry,
  and does everything the script did: composes the estimate with the camera's
  pose from the world, moves the part's world object there, checks
  `min_safe_z`, and creates or moves the grasp and pre-grasp frames.
* **The skill writes the frames itself** (decided at the start: the
  alternative, returning them for `update_world`, needs CEL values inside an
  `ObjectWorldUpdate`, which is untried). Its footprint locks the world, so it
  must stay in a `bt.Sequence`, as `update_world` must (executive error
  18201). It also returns the three poses.
* The rule is a plain function, `src/core/grasp_math.py` (no `intrinsic`
  imports, as `core/` requires). `tests/unit/test_grasp_math.py` runs the script
  and the function on 300 random poses (tilts 0 to 75, both symmetries, with
  and without a tool orientation) and they agree. `research/tools/cuboid_sweep`
  now calls the function instead of its own copy, and its output is identical
  on a sweep of 3 sizes by 4 yaws.
* Selected by `vision.frame_calculator: script | skill` (default `script`, so
  `omts` and `lab_bb_01` are unchanged; `configs/rebot/app_config.yaml` uses
  `skill`). Not the `grasp.planner` key, which picks who owns the grasp
  frames, not how the part's pose is composed.
* **Result** (k3s, sim, models): a full cycle with the skill finished (61 s), and
  the skill logged a grasp at (0.560, -0.0002, 0.160), the bed centre at the
  part's height.
* Not supported: **preview** (`--simulation_mode=preview` or `fast_preview`).
  A skill's preview world is taken for the real one, and the frames are what
  the following motions need, so the skill refuses it. The script is the
  route for those modes; whether the script itself works in preview was not
  checked.
* Known gaps: a missing part object is skipped with a warning, as the script
  did; a missing camera or parent object is now an error (the script fell
  back to the root). The script is still in the tree for `omts` and
  `lab_bb_01`, so the rule exists twice (script and `grasp_math`) until it is
  retired; the equivalence test is the guard.
* After a deploy that does not restart the simulator, Gazebo keeps the last
  cycle's state, and the first run fails with "0 detections" (SAM 3 sees no part).
  Run `apply_scene_updates --reset_sim` after each deploy (`REBOT_OMTS_APP.md`).

### Step C3: Pick cycle as a process asset (fixes D1) — PAUSED

**Paused on 2026-11-19 in favor of C1.** OMTS uses no processes today, and
what a process buys (starting the cycle from Flowstate, a cycle that does not
depend on a host process) is not needed yet; C1 and C2 fix more for less. What
was learned is below, and the code is kept off this branch: the
`intrinsic_process` Bazel rule, the manifest export tool and a feature request
for Intrinsic are on `feat/process-asset-rule`. Pick C3 up again when
starting from Flowstate matters, and choose then between shipping the manifest
with the solution (needs that rule) and storing the tree again after each
deploy (no rule, but a manual step like the registration C1 removes).

* Keep the tree's shape: the Python builders and `app_config.yaml` stay the
  source of truth (a solution ships one cell's tree, as `//:setup` already
  chooses one cell). Only the destination changes: the tree is stored on the
  solution as a process instead of being run once as an operation. Started
  from Flowstate, or by a thin `omts_app --run_process` call.
* Needs C1 and C2 first, so the process holds no host-side steps.
* Parameters (the cell's frame and object names) and loops (`num_cycles`) are
  still to check.
* **Demo:** run a cycle from Flowstate with the host disconnected.

**Checked on 2026-11-19** (k3s, pinned intrinsic-core, with throwaway scripts
that are not kept):

* SBL stores a Python-built tree as an installed Process asset with
  `tree.set_asset_metadata(id=..., vendor=..., subprocess=True)` and
  `solution.processes.save(tree)`. It shows in `solution.processes`, and
  `executive.run(solution.processes[id])` runs it. No Bazel needed.
* **A deploy removes it.** After `bazel run //:rebot_solution` the stored
  process was gone, like `rs-prusalink` and the pose-estimator registration:
  a deploy uninstalls installed assets the solution does not declare. So a
  tree stored after deploy has to be stored again after every deploy.
* **A process the solution declares survives and runs.** intrinsic-core has no
  Bazel rule for processes, so a prototype (`intrinsic_process`, branch
  `feat/process-asset-rule`; a feature request for Intrinsic) bundled a
  checked-in manifest of a do-nothing tree. Declared in `rebot_solution`'s
  assets, the deploy installed it (`ai.omts.probe_process`), and it ran.
* **The catch:** the manifest must be checked in, but the SBL builders need a
  connected solution to resolve skills, so a hermetic Bazel build cannot
  generate it. It has to be exported from a deployed solution.

**The export route, tried the same day** (the real cell tree, built by
`omts_app`'s own code against the cluster):

* `inctl process get <id>` exports the tree as a `ProcessManifest` textproto
  (915 lines for the reBot cycle), but **only as text**: `--process_format
  binaryproto` is refused for process assets. The text holds the
  `PythonScript` node's parameters as an expanded `Any` of a generated type
  (`gen.sbl_<hash>.Params`) that exists only in the cluster's proto registry, so
  a plain textproto parser cannot read it back ("Type ... not found in
  descriptor pool"). Checking the text in is therefore not enough.
* Building the manifest from SBL instead works: `solution.processes[id]` gives
  the tree and its asset metadata, and a `ProcessManifest` written as a **binary
  proto** (29 KB) keeps the script's parameters packed. The prototype's bundler
  now reads `.binpb` as well as text.
* With that binary manifest declared in `rebot_solution`'s assets, a deploy
  installed the real cell tree, and `executive.run(solution.processes[id])`
  started it on the executive. It got through the arm moves and into the
  perception `Retry` before failing at `estimate_pose_multi_view` ("no healthy
  upstream"): that deploy had no pose-estimator models
  (`--//:perception_models`) and nothing registered. So the bundle and the tree
  execute from storage; **a full cycle from a stored process is not yet run.**
* So the route is: a host tool builds the tree with the cell's config, writes the
  binary manifest to a file in the repo, and `intrinsic_process` bundles it into
  the solution. The file must be rebuilt when the config or the builders
  change.

**The export tool** is on `feat/process-asset-rule` (`tools/cell_process/
export_cell_process.py`, with a `build_tree()` split out of `src/main.py` that
`omts_app` shares). It builds the cell's tree against a deployment without
running it and writes the binary manifest. SBL names the tree, generated
blackboard keys and a script node's parameter package with `uuid4`, so the
tool replaces each distinct id with a same-length token; two builds are then
byte-identical, and `--check` says whether a checked-in manifest is out of
date. The normalized manifest was deployed and ran as before.
* Not checked: a full cycle with the models and registration; a process
  version; the process's parameter interface (cell and frame names as
  parameters) and a repeat count.

### Step C4: Cell configuration in the cluster (fixes D4) — DONE 2026-11-19 (C4a, C4b, C4c)

**Scope, decided on 2026-11-19:** an *apply-only* skill. The checks
(`research/tools/cell_checks.py`: reach, clearance, IK sweeps) are design-time
analysis that needs numpy, scipy and the arm's and printer's meshes from the
checkout, so they stay a host tool you run first. Registration, the third
output of `configure_cell` (`register.sh`), went with C1. The skill applies; it
does not judge.

The skill is built in increments, each its own demo. Every group of values is
optional and independent, so the skill can be called again at any time, from a
tool or inside a tree.

* **C4a (done): the printer, the camera mount and the view.**
  `ai.omts.configure_cell` (`skills/cell/`) sets the printer's x (its distance),
  the camera's position in the flange frame, and moves the `view` frame so the
  camera sees the printer as before. Everything is read from the live world (the
  printer's pose, the flange and tool frames, the camera, the current `view`),
  so it needs no constants from the checkout, and it applies all of it in one
  `UpdateWorldResources` call: all or nothing. Belief world only; Gazebo follows
  after `apply_scene_updates --reset_sim`. No preview. `configure_cell --apply`
  calls it and leaves those three out of `cell.updates.pbtxt`.
* **Result** (k3s, sim): for printer 0.62 m and camera (0.09, -0.024, 0.10), the
  skill's world matches `configure_cell`'s file: printer and camera exactly, the
  view's position to rounding (0.29092, -0.024, 0.22748 against 0.2909, -0.024,
  0.2275) and its orientation within 0.1 degree (the host starts from the
  rounded quaternion of the committed pbtxt; the skill from the world's exact
  one). A full cycle then ran in the moved cell (63 s). Setting the committed
  values back through the skill returned the printer, camera and view to
  their original numbers, with no drift.
  `tests/unit/test_configure_cell.py` covers the geometry with real transform
  math, including the invariant that after a mount change the camera at the
  new `view` is where it was at the old one.
* **C4b (done): A's frames.** The `drop_off` group of the same skill sets
  `place_vise`, `pre_place_vise` and `machine_approach` from the tilt, A's
  radius and bearing and the part's half height, so they follow a part of
  another height without a file. It moves a frame that exists and creates one
  that does not, in the same single update as the printer group. The geometry is
  `src/core/drop_off.py` (plain Python, ported from the print-flow branch with
  its test, which keeps it equal to `research/tools/a_frames.py`);
  `configure_cell --apply` now sends A's frames through the skill too, so its
  file holds only the target and the parked parts. Bounds catch a value in the
  wrong unit (radius up to 2 m, half height up to 0.25 m, depth up to 0.1 m).
* **Result** (k3s, sim): for a part of half height 0.02 m (`test_cuboid_40x40x40`)
  the skill's three frames match the host file's (to its 4-decimal rounding,
  heights 0.02, 0.0407, 0.1407; orientation identical), with the view and printer
  unchanged. Setting the default part back returned the frames to the committed
  ones within the committed file's rounding (under 0.05 mm: the file has 4
  decimals, the skill the exact values). A full cycle then ran (63 s).
  `tests/unit/test_configure_cell.py` covers moved frames, created frames,
  custom names and depth, one update with the printer group, and the bounds.
* **C4c (done): the target and the parked parts.** The `target` group puts a
  named object on the bed at its resting pose (upright, or lying with its model
  z along the world x axis), and `parked` puts other objects at given places.
  The bed comes from a **parameter**, `bed_top_in_printer_m`: the centre of the
  heatbed's top surface in the printer's frame (the host tool reads it from
  `models/printer/heatbed.obj` and passes it). The skill combines it with the
  printer's pose, which it reads or sets in the same call, so a printer move
  carries the part with it. Each object is reparented to the parent first, so a
  part left in the gripper by a failed run is freed. The parking places are the
  tool's convention (`part_trial.parking_positions`), not the skill's. All of it
  is in the same single update as the other groups.
* **`configure_cell --apply` now needs no file and no `apply_scene_updates`.**
  It runs the host checks, calls the skill with every group, and in simulation
  brings Gazebo to the belief world by starting a trivial operation with
  `start_from_world_state=BELIEF` (the platform's own way, instead of
  `apply_scene_updates --reset_sim`). The only file left is `app_config.yaml`,
  because the tree's ids and the return area are fixed when `omts_app` builds it.
  File mode is byte-identical to before.
* **Result** (k3s, sim): one `--apply` call (20 s) moved the printer to 0.62 m
  and the camera to (0.09, -0.024, 0.10); the part's pose matches the host file's
  (0.59049, 0.00001, 0.15843 against 0.5905, 0, 0.1584), and a full cycle then
  ran in the moved cell (61 s), with the part returned near the new bed centre.
  Setting the defaults back through the skill returned the printer, part, A's
  frames and view to the baseline within 0.03 mm (the committed files' rounding).
  Not tried: a control run without the simulator sync, and a target other than
  the default part (the test parts need a `--//:test_parts` deploy; their
  placement is covered by the unit tests, including the lying orientation).
* **Can it change the grasp target later?** In the world, yes (C4b and C4c):
  a call between cycles can move A's frames for a part of another height and
  put another object on the bed (both done). What it cannot change is what the *built
  tree* looks for: `omts_app` fixes the part's object, scene-object id, pose
  estimator and the return area's centre when it builds the tree
  (`vision.*`, `cycle.workpiece_id`, `cycle.return_shift`). A new part needs a
  new run of `omts_app` with its own config, as `configure_cell` writes it
  today, or a tree that reads those from the blackboard, as the print flow does
  (`ai.omts.register_pose_estimator`'s `return_value_key` and one world
  object per cycle). That is a separate step.
* Not covered: the checks run in the skill (they stay a host tool), and
  `cell_params.yaml` as a source for it (the tool still reads it for `--apply`).

### Stays on the host (D5, D6)

`kin`, `cuboid_sweep`, `view_search`, jogging, `apply_scene_updates` and the
`kubectl` / `gz` recipes are development tools. Keep them, and note in their
READMEs that they are not part of the deployed cell.

## 4. Open questions

1. Can a process take parameters and a repeat count? (Intrinsic Core has no
   Bazel rule for processes; see step C3 for what was tried.)
2. Should a skill write the grasp frames, or return them for `update_world`?
3. Is it worth moving the vision and robot adapters' trees into processes
   (one per subtree), or is one cycle process enough?
4. After a deploy, can anything keep the pose-estimator registration (it is an
   installed asset the deploy removes), or is a skill that re-registers on
   every start the right answer?
