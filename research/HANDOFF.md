# Handoff: 3D Printer Unloading Research

Snapshot of the printer-unloading research so it can continue on another
machine. The study itself is [`PRINTER_UNLOADING.md`](PRINTER_UNLOADING.md);
this file covers setup, decisions taken, and what to do next.

---

## 1. Where Things Are

| Item | Location |
| --- | --- |
| Repo | Fork `https://github.com/NachoRosa95/intrinsic-omts`, branch `research` |
| Research commit | `fbb9606` "Printer unloading viability research", on top of upstream `main` at `48be90d` (#151) |
| Study | `research/PRINTER_UNLOADING.md` |
| SO-101 URDF | `research/so101_new_calib.urdf`, copied from [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) `Simulation/SO101/` |
| Reference source | `intrinsic-core` at tag `20260922.0`, the same release OMTS pins in `MODULE.bazel` (`INTRINSIC_CORE_RELEASE`) |

No code has been written yet. Everything so far is analysis.

---

## 2. Setting Up the New Machine

```bash
# OMTS fork on the research branch (Git LFS is required for *.glb meshes)
git lfs install
git clone https://github.com/NachoRosa95/intrinsic-omts.git
cd intrinsic-omts && git checkout research

# Upstream remote, to pull new OMTS changes
git remote add upstream https://github.com/intrinsic-ai/intrinsic-omts.git

# intrinsic-core next to it, for reading drivers, skills and tutorials
cd .. && git clone https://github.com/intrinsic-ai/intrinsic-core.git
cd intrinsic-core && git checkout 20260922.0
```

The `upstream` URL is assumed from the fork's name; confirm it before relying
on it.

For quick analysis scripts (URDF kinematics, 3MF parsing), install `numpy`. The
original machine had no system pip; it was installed per-user with
`get-pip.py --user`, then `python3 -m pip install --user numpy`.

---

## 3. Decisions Taken

Each decision is recorded in the study with its reasoning; this is the short
list.

| Decision | Why | Study section |
| --- | --- | --- |
| Localize parts from the slicer's 3MF plate layout, not vision | The app starts each print and already has the 3MF; avoids per-job pose-estimator training | 4 |
| Plain RGB camera for presence checks (A, B, C), not depth | The project must be open source and accessible; the printer's own camera may cost $0 | 5 |
| **No force sensing** | Lets low-cost position-controlled arms qualify; accepts that short or collapsed prints go undetected | 4.3, 5.5 |
| Host-side loop, one behavior tree built per print job | The layout is only known per job; also the simplest "print done" detection (polling the printer API) | 3.1, 6.1 |
| Grasp planning through OMTS's `GraspPlannerInterface`, with a new plate-footprint backend as the default | Fits the localization/grasp split added upstream in #144/#150; MoveIt stays optional because it needs ROS 2 | 4.4 |
| SO-101 as the low-cost arm candidate, via Intrinsic's `icon_hwm_controller` ROS 2 bridge | No low-cost arm has a native ICON driver; the bridge plus an existing Feetech `ros2_control` driver avoids writing a custom C++ module | 7 |

---

## 4. Open Decisions (Need the Project Owner)

1. **Target printer and firmware.** This decides the status API, the camera
   source and the 3MF variant. For the SO-101 it also decides whether the bed
   is reachable at all (a bed-slinger parked toward the arm is needed).
2. **Sheet swap or direct part grasping.** The study assumes direct grasping
   as the harder case.
3. **Is the uncovered "collapsed or short print" case acceptable?**
4. **MoveIt backend:** worth its ROS 2 setup for printed parts, or is the
   footprint planner enough?

---

## 5. Next Steps

In the order of study section 8.1:

1. **`plate_layout.py` + `footprint_grasp.py`** in `src/core/`, with unit
   tests against real 3MFs from the target slicer. Pure Python, no hardware.
   Follow repo conventions: 2-space indentation, Apache header, a
   `py_library`/`py_test` per module in the package `BUILD`, tests declared
   in `tests/unit/BUILD`.
2. **Camera path:** pull one snapshot from the printer's camera (or a USB
   webcam) and run check C against a saved empty-bed reference.
3. **SO-101 spike:** deploy
   [`icon_hwm_controller`](https://github.com/intrinsic-ai/icon-hwm-controller)
   with a Feetech `ros2_control` driver
   ([`ros-physical-ai/feetech_ros2_driver`](https://github.com/ros-physical-ai/feetech_ros2_driver))
   and run one OMTS `Robot` move. In parallel, check bed coverage in simulation
   with the URDF.
4. Calibration print, printer adapter, printer cell config and the per-job
   tree.

---

## 6. Unverified Items

These are stated in the study as assumptions or estimates. Check them before
building on them.

* **SO-101 accuracy ±3–5 mm** is derived from 0.5° gear backlash at 0.3 m plus
  link flex. It has not been measured.
* **SO-101 payload ~500 g** comes from an unsourced spec page.
* **SO-101 gripper opening width** has not been measured.
* **Bridge compatibility:** `icon_hwm_controller` targets ROS 2 Kilted on
  Ubuntu 24.04; whether the Feetech driver builds there is unknown. So is the
  control rate the servo bus sustains, and whether ICON accepts it.
* **5-joint arm planning:** nothing found in `intrinsic-core` excludes it, but
  it has not been tried.
* **Host-side image capture through Intrinsic** was never exercised in this
  repo (`tools/calibration/sample_calibration_poses.py` sets `camera = None`).
  The study avoids it by reading the printer's camera directly.

### Reproducing the SO-101 reach numbers

The reach figures (0.47 m max, 0.32 m top-down) came from a throwaway script
that was not saved. To reproduce: parse the URDF joint chain from `base_link`
to `gripper_frame_link`, sample about 200k random configurations within the
joint limits, and record the tip's horizontal distance from the
`shoulder_pan` joint. Count only samples where the tool's +Z axis (the approach
axis, verified as wrist → fingertip) points within about 14° of straight down.

---

## 7. Housekeeping

* **`CLAUDE.md` is out of date** with upstream #149/#131: it still mentions
  `UrRobot`/`RobotInterface` and a standby move inside the machining subtree.
  Update it before relying on it.
* **Upstream gap, still open at `48be90d`:** the solution does not declare
  `dio_wait_for_input`, so `DioCncMachine.build_wait_cycle_complete_task`
  sleeps and never checks the input (study section 3.1).
* **Abandoned draft:** an early draft of the study was started as a Claude Doc
  (`https://claude.ai/code/artifact/3ea4bddf-2151-46ba-b2d6-65779142ea43`),
  with only two sections filled in. The Markdown study replaces it; it can be
  deleted.
