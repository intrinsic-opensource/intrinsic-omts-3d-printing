# Handoff: 3D Printer Tending

Current state and plan for the printer-tending project, so work can continue on
any machine. The feasibility study is [`PRINTER_UNLOADING.md`](PRINTER_UNLOADING.md);
the arm comparison is [`ARM_SELECTION_REQUEST.md`](ARM_SELECTION_REQUEST.md).
This file records what has been decided and what to do next.

---

## 1. Where Things Are

| Item | Location |
| --- | --- |
| Repo | Fork `https://github.com/NachoRosa95/intrinsic-omts`, branch `research` |
| Research commit | `fbb9606` "Printer unloading viability research", on top of upstream `main` at `48be90d` (#151). Upstream has since been merged in through #156. |
| Study | `research/PRINTER_UNLOADING.md` |
| Arm comparison (decided) | `research/ARM_SELECTION_REQUEST.md` |
| SO-101 URDF | `research/so101_new_calib.urdf`, from the earlier SO-101 evaluation; superseded by the reBot decision |
| reBot URDFs | Base for the sim model: [Seeed-Projects/reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) `urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf` (MIT), which fixes the gripper limits (section 6.2). Originals: [Seeed-Projects/reBot-DevArm](https://github.com/Seeed-Projects/reBot-DevArm) `Rebot_Arm_description/` (Apache-2.0 / CERN-OHL-W-2.0). |
| Reference source | `intrinsic-core` at `main` (past `20261012.0`). OMTS itself pins the `20261012.0` release in `MODULE.bazel` (`INTRINSIC_CORE_RELEASE`), so check behavior against that tag when it matters. |

No code has been written yet. Everything so far is analysis.

---

## 2. Setting Up the New Machine

```bash
# Upstream OMTS as origin (Git LFS is required for *.glb meshes)
git lfs install
git clone https://github.com/intrinsic-ai/intrinsic-omts.git
cd intrinsic-omts

# The fork, which holds the research branch
git remote add fork https://github.com/NachoRosa95/intrinsic-omts.git
git fetch fork && git checkout -b research fork/research

# intrinsic-core next to it, for reading drivers, skills and tutorials
cd .. && git clone https://github.com/intrinsic-ai/intrinsic-core.git
```

This matches the working machine: `origin` is upstream
(`intrinsic-ai/intrinsic-omts`) and `fork` is
`NachoRosa95/intrinsic-omts`. Push research work to `fork`.

For quick analysis scripts (URDF kinematics, 3MF parsing), install `numpy`. The
original machine had no system pip; it was installed per-user with
`get-pip.py --user`, then `python3 -m pip install --user numpy`.

---

## 3. Decisions Taken

### 3.1 Kickoff with Intrinsic (2026-10-20)

| Decision | Consequence |
| --- | --- |
| **Arm: Seeed reBot Arm** | Replaces the SO-101 plan (study section 7). The B601-RS is the working assumption until the variant is confirmed. |
| **Intrinsic adds ICON support for the reBot** | Hardware only, likely for the B601-RS. We do not write or validate a driver; the community-driver risks in `ARM_SELECTION_REQUEST.md` no longer apply to us. The simulation model is ours to build. |
| **Deadline: end of 2026, scope flexible** | Intrinsic's hard deadline. Cut scope rather than slip; the spiral steps make that possible. |
| **Target compute: NVIDIA Jetson (Orin or Thor)** | Intrinsic is adding ARM support; treat it as a given. Seeed sells reBot kits bundled with Jetson Orin or Thor. |
| **Simulation first** | Hardware waits for Intrinsic's ICON support. All milestone 1 work runs in Gazebo (`--operation_mode=sim`). |
| **No printer yet** | The target printer stays undecided. The arm first works on its own in an empty cell, with no obstacles. |
| **Spiral workflow** | Start simple and add complexity in small steps, with something to demo at every step (section 5, and `CLAUDE.md`). |

### 3.2 From the study

Each is recorded in the study with its reasoning.

| Decision | Why | Study section |
| --- | --- | --- |
| Localize parts from the slicer's 3MF plate layout, not vision | The app starts each print and already has the 3MF; avoids per-job pose-estimator training | 4 |
| Plain RGB camera for presence checks (A, B, C), not depth | The project must be open source and accessible; the printer's own camera may cost $0 | 5 |
| **No force sensing** | Lets low-cost position-controlled arms qualify; accepts that short or collapsed prints go undetected | 4.3, 5.5 |
| Host-side loop, one behavior tree built per print job | The layout is only known per job; also the simplest "print done" detection (polling the printer API) | 3.1, 6.1 |
| Grasp planning through OMTS's `GraspPlannerInterface`, with a new plate-footprint backend as the default | Fits the localization/grasp split added upstream in #144/#150; MoveIt stays optional because it needs ROS 2 | 4.4 |
| Footprint grasp math in `src/core/footprint_grasp.py`, with a thin `PlateGraspPlanner` in `src/hardware/` | Pre-print layout validation must run without a solution connection, and `core/` cannot import `intrinsic.*` | 4.4, 6 |

---

## 4. Open Questions

### 4.1 For Intrinsic (answered 2026-10-20)

1. **Scope of the reBot ICON support:** hardware only. No simulation model and
   no gripper. For simulation we use Intrinsic's generic Gazebo stand-in with a
   model built from the URDF (step 1b).
2. **Variant:** to be decided; the B601-RS is most likely.
3. **Timeline:** hard deadline at the end of 2026, with scope flexible to meet
   it.

### 4.2 For the project owner

1. **Target printer and firmware.** Deferred: decides the status API, camera
   source and 3MF variant. Needed before the printer enters the cell.
2. **Sheet swap or direct part grasping.** The study assumes direct grasping
   as the harder case.
3. **Is the uncovered "collapsed or short print" case acceptable?**
4. **MoveIt backend:** worth its ROS 2 setup for printed parts, or is the
   footprint planner enough?

---

## 5. Milestone 1: The reBot Replaces the UR in Simulation

Goal: OMTS runs a pick-and-place cycle in simulation with the reBot instead of
the UR5e, in an empty cell. Each step below ends in a demo.

### Step 1a: The reBot is in the world

**Status: done (2026-10-20).** Deployed to the local cluster in sim.

* New solution target `//:rebot_solution` (root `BUILD`), deployed in sim by
  default, with only the Gazebo simulator and the reBot. It is a separate
  target rather than a `//:setup` value: `tests/unit/test_behaviors.py` parses
  `omts_solution`'s text and requires its current shape, and a separate target
  leaves `omts` and `lab_bb_01` untouched.
* New model `models/rebot_b601_rs/`, generated from the reBot-Isaacsim RS URDF
  (section 6.2) by the new `//tools/models:urdf_to_sdf` (numpy only, unit
  tested in `tests/unit/test_urdf_to_sdf.py`). It writes one simplified,
  colored visual GLB and one coarse collision GLB per link (about 7 MB in all).
  The model is static for now; its README lists the step 1b and 1c follow-ups.
* Verified: `gz sdf -k` passes, `sdf_scene_object` converts the model, an
  offline render shows the arm assembled correctly at two poses,
  `bazel build --nobuild //...` passes, and all 22 unit tests pass.
* **Demo:**

  ```bash
  bazel run -c opt //:rebot_solution -- --address=localhost:17080
  ```

  The reBot stands alone in the world and in Gazebo.

* Result: the belief world holds `rebot` and `root` only. Gazebo
  (`rs-gazebo-simulator-0`) spawned the model with all eight joints and
  attached a `JointPositionController` to each
  (`/model/rebot/joint/<joint>/0/cmd_pos`).
* Learned for step 1b: Gazebo logs "The resource config proto for 'rebot' is
  not a HardwareModuleConfig, will not add a HardwareModuleLauncher system to
  it". ICON control in sim is attached through a hardware module config on the
  resource, which is what the step 1b hardware device provides.

### Step 1b: The reBot moves

* Make the reBot an ICON-controlled hardware device in simulation. In sim mode,
  hardware devices run Intrinsic's generic Gazebo stub (`image_sim =
  gazebo_hwm_stub_image.tar` in `ur_hardware_device.bzl` and the KUKA RSI
  device), not their real driver. The build rule needs only one of `image` and
  `image_sim`. So a sim-only device needs a robot model, not a driver. This is
  ours to build: Intrinsic's support covers hardware only (question 4.1.1).
  Expect friction, since the stand-in has only been used with industrial arms.
* Add an ICON config, joint limits and named joint configurations for the cell.
* Point `robot.arm_part_name` in the new cell's `app_config.yaml` at the reBot.
  `Robot` is vendor-neutral and should need no change.
* **Demo:** `Robot` moves the reBot between named configurations and to a
  Cartesian frame, top-down, in a loop.

### Step 1c: The reBot picks and places a printed part

* Add a light printed-part model as the workpiece, at a fixed known pose
  (`GridInfeedStrategy`, no perception).
* Add a position-only approach in place of the `move_to_contact` touchdown,
  since the reBot has no force-torque sensor (study section 2, `motions.py` row).
* Add a `GripperInterface` for the reBot's two-finger gripper (two prismatic
  joints in the URDF; see section 6 for which URDF's finger limits to use).
* **Demo:** the reBot picks the part, places it at a second pose and repeats.

Milestone 1 is done at the step 1c demo.

### After milestone 1 (sketch, to be re-planned at each step)

* Add a generic printer bed as the pick surface, then the printer as an
  obstacle once the target printer is chosen.
* Pick from a 3MF plate layout with the footprint grasp planner.
* Move to hardware on a Jetson once Intrinsic's ICON support lands.
* Camera presence checks, printer adapter, per-job cycle.

---

## 6. Findings

### 6.1 reBot top-down reach (checked offline, 2026-10-20)

Method: sample 300k random joint configurations within the URDF limits, and
keep those where the tool (`gripper_end`, the TCP in Seeed's MoveIt config)
points within 14° of straight down. Horizontal reach is measured from the base
axis; tip height from the base frame. Self-collision is ignored.

| Tip height above base | Top-down horizontal reach |
| --- | --- |
| −0.10 m | ~0.05–0.55 m |
| 0.00 m | ~0.02–0.52 m |
| +0.10 m | ~0.06–0.49 m |
| +0.20 m | ~0.16–0.36 m |

* Both RS URDFs below agree within a few centimetres.
* The wrist roll (`joint6`) turns exactly about the approach axis, with
  ±3.14 rad of travel, so top-down grasps at any yaw work.
* Maximum reach in any orientation is 0.78 m, consistent with Seeed's 754 mm
  figure.

So the gripper can point straight down over about half a metre around the base,
at bed heights near the base. That is wider than the SO-101's 0.32 m, so reach
is not a concern for milestone 1. Step 1b confirms it with Intrinsic's motion
planner, which also checks self-collision.

### 6.2 reBot gripper finger limits

Seeed's RS URDF (identical in reBot-DevArm, reBotArm_control_py and
reBotArmController_ROS2, apart from mesh paths) gives the two fingers different
travel: 0–0.05 m and 0–0.0715 m, with no mimic tag.

Seeed's [reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) repo
(MIT) fixed this in its RS URDF, `urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf`
(commit of 2026-08-02):

* 0.0715 m was an authoring error. Both fingers use the same mesh, their axes
  are exactly opposed, and the real gripper is one motor driving two racks
  through one pinion, so the fingers move 1:1. Both are now 0–0.05 m, a
  50 mm stroke per finger, matching the motor's calibrated travel.
* Finger effort and velocity are derived from the motor (1904 N, 0.243 m/s)
  instead of placeholder values.
* The 1:1 coupling is authored in the repo's USD and MuJoCo models, but **not**
  as a `<mimic>` tag in the URDF. Our sim model has to add the coupling.
* The same commit documents real-gripper measurements (backlash about ±0.37 mm)
  and Python SDK pitfalls worth reading before hardware work.

That URDF also uses a different sign convention for `joint2`/`joint3`
(−3.14–0 instead of 0–3.14) and slightly wider `joint4` limits. The reach is the
same either way. **Use the reBot-Isaacsim RS URDF as the base for the sim model,
add a finger mimic, and confirm the joint conventions against Intrinsic's
hardware support once it exists.**

---

## 7. Unverified Items

Check these before building on them.

* **Gazebo stub with a non-industrial arm.** The stub is used for UR and KUKA
  devices; nothing found says it is limited to them, but it is untried.
  Friction is expected here (step 1b).
* **5- and 6-joint planning for small arms** in Intrinsic's motion planner is
  untried.
* **Host-side image capture through Intrinsic** was never exercised in this
  repo (`tools/calibration/sample_calibration_poses.py` sets `camera = None`).
  The study avoids it by reading the printer's camera directly.

---

## 8. Housekeeping

* **Local fixes for `20261012.0`:** both are still needed with the pinned
  release. `b7cc503` (no camera args to `estimate_pose_multi_view`) stays
  needed on intrinsic-core `main` too. `c98d44a` (attach and detach via the
  robot) works around `attach_object_to_robot` parenting to the reference's
  final entity. intrinsic-core `main` (`3d137157`) attaches to a gripper's
  base entity again, so `c98d44a` becomes optional, though still correct,
  once OMTS pins a release that includes that change.
* **Upstream gap, still open at `48be90d`:** the solution does not declare
  `dio_wait_for_input`, so `DioCncMachine.build_wait_cycle_complete_task`
  sleeps and never checks the input (study section 3.1).
* **Abandoned draft:** an early draft of the study was started as a Claude Doc
  (`https://claude.ai/code/artifact/3ea4bddf-2151-46ba-b2d6-65779142ea43`),
  with only two sections filled in. The Markdown study replaces it; it can be
  deleted.
