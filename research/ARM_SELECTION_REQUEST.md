# Decision Request: Choosing the Replacement Arm

> [!IMPORTANT]
> **Decided at the kickoff meeting with Intrinsic (2026-10-20): the Seeed reBot
> Arm.** Intrinsic is adding ICON support for it, which removes the driver risk
> this document weighs (sections 2 and 3.2). The variant is not yet confirmed;
> the B601-RS remains the working assumption. The rest of this document is kept
> as the record of the comparison. Current plan: `HANDOFF.md`.
>
> `PRINTER_UNLOADING.md` was later trimmed to the printer-side design. Its
> section numbers cited here (4.3 for the SO-101 figure, and all of section 7)
> refer to its version at commit `6b33ad7`.

The target solution is an arm that unloads a 3D printer (`HANDOFF.md`,
`PRINTER_UNLOADING.md`). The first milestone replaces the industrial arm in
OMTS, a UR5e, with a smaller, cheaper arm that can handle 3D prints. The OMTS
workpiece will be swapped for a printed part.

A Seeed Studio reBot Arm was proposed, but the arm is our choice, not a
requirement. Since most low-cost arms can do the task, this document compares
them on what drives the schedule: **how much of the driver already exists**.

**Short answer.** The **UFactory Lite 6** (~$3,600 kit with grippers) is the
fastest path. It is the only candidate whose driver is maintained by the arm's
vendor. The **reBot B601-RS** (~$1,700) and the **SO-101** (~$230) cost less and
are open hardware, but their drivers are community projects. Each needs a short
spike before we commit to it.

---

## 1. What the Arm Has to Do

| Need | Basis |
| --- | --- |
| Pick light parts | Prints weigh tens of grams. The gripper's weight still counts against the arm's payload. |
| Top-down grasps at any yaw | The footprint grasp planner sets the jaw direction from each part's shape (`PRINTER_UNLOADING.md` 4.4). This needs a wrist roll joint. |
| Reach across the bed | Assumed easy: the printer parks its bed toward the arm at the end of each print (`PRINTER_UNLOADING.md` 4.2, 7.2). |
| No force-torque sensor | Force sensing was dropped so low-cost arms qualify (`HANDOFF.md` 3). |
| Low cost, ideally open | The project aims to be open source and accessible (`HANDOFF.md` 3). |

**Accuracy has no established requirement.** The study's error budget
(`PRINTER_UNLOADING.md` 4.3) estimates about ±1 mm overall with a UR and about
±5 mm with an SO-101. It judges ±5 mm workable for most parts, at the cost of
wider grasp margins. The real tolerance is set by the gripper's sideways slack
(opening minus part width, since closing the jaws re-centres the part) and its
vertical margin above the bed. Neither is known until the gripper and typical
parts are chosen. This document therefore treats accuracy as a cost, not a cut-off.

---

## 2. Why the Driver Decides the Schedule

Intrinsic's real-time control service (ICON) accepts a non-UR arm through its
ROS 2 bridge, `icon_hwm_controller`. The bridge needs a `ros2_control` hardware
plugin for the arm. With a working plugin, the rest of the work is much the
same for every arm:

* Package the driver, the bridge and a status/fault node in a container, and
  install it as an Intrinsic hardware device (intrinsic-core
  `ros2_bridge_tutorial.md`).
* Convert the arm's URDF to an SDF scene model, and add joint limits.
* Write a `GripperInterface` for the arm's gripper. The bridge carries arm
  joints only, so the gripper is commanded outside ICON.
* Set up the real-time Linux PC that ICON needs, which every option requires
  (`PRINTER_UNLOADING.md` 7.2, risk 6).

The bridge targets ROS 2 Kilted. Without a working plugin, the fallback is a
custom ICON hardware module, which is real-time C++ against the motors. The study
estimates that at weeks (`PRINTER_UNLOADING.md` 7.1). So the arms differ mainly
in how much driver work comes first:

| Driver state | Work before the shared steps |
| --- | --- |
| Vendor-maintained | Build it on Kilted |
| Community-maintained | Build it on Kilted, then validate it on the real arm and fix what breaks |
| None | Write one (weeks) |

---

## 3. Candidates

Prices are online list prices from October 2026. Repeatability figures are the
vendors' claims unless marked otherwise.

| Arm | Price | Joints | Repeatability | Gripper | Open hardware | Driver |
| --- | --- | --- | --- | --- | --- | --- |
| **UFactory Lite 6** | ~$3,000 arm; ~$3,600 kit with grippers | 6 | ±0.5 mm | UFactory grippers in the kit | No | [`xarm_ros2`](https://github.com/xArm-Developer/xarm_ros2), BSD-3. **Vendor.** Jazzy and Rolling branches. |
| **reBot B601-RS** | ~$1,700, power supply extra | 6 | < 0.2 mm | Motorized, on the arm's CAN bus | Yes (CERN-OHL-W-2.0) | [`robstride_ros2_control`](https://github.com/s2015-turtle/robstride_ros2), MIT. **Community.** CI includes Kilted; tested only against a simulated motor. |
| **SO-101** | ~$230 per leader + follower pair | 5 | ±3–5 mm (study estimate, not measured) | Single pivoting jaw | Yes | [`feetech_ros2_driver`](https://github.com/ros-physical-ai/feetech_ros2_driver), BSD-3. **Community.** Generic Feetech servo plugin; CI on Humble, Jazzy, Rolling. |
| Annin AR4 | ~$2,000 to build | 6 | 0.2 mm claimed | Servo gripper | Yes | [`ar4_ros_driver`](https://github.com/ycheng517/ar4_ros_driver), MIT. **Community.** Used on real arms; Jazzy. |

All four arms reach further than the SO-101, and the study found the SO-101's
reach workable with the bed parked toward the arm.

### 3.1 UFactory Lite 6

* **Driver.** UFactory maintains the `ros2_control` plugin
  (`uf_robot_hardware/UFRobotSystemHardware`). There is no Kilted branch. A build
  from the Rolling branch should be a small change, but is untested.
* **Gripper.** For the `lite` model the plugin forces `add_gripper` off, so the
  gripper sits outside `ros2_control`. OMTS would drive it through UFactory's
  SDK from a new `GripperInterface`. This is new code, but not driver code.
* **Trade-off.** It costs about twice the reBot and is closed hardware.

### 3.2 reBot B601-RS

Seeed's ROS 2 stack
([reBotArmController_ROS2](https://github.com/Seeed-Projects/reBotArmController_ROS2),
also the
[danieldoradotalaveron-rb fork](https://github.com/danieldoradotalaveron-rb/reBotArmController_ROS2))
drives the real arm with a Python node. Its `ros2_control` setup is a simulated
stand-in for MoveIt. The hardware hub
([reBot-DevArm](https://github.com/Seeed-Projects/reBot-DevArm)) has build files
and URDFs but no driver code. The community RobStride plugin is therefore the
only driver, and it leaves these open:

1. **Never run on hardware.** Its README lists watchdog timing, bus faults and
   motor dynamics as unvalidated.
2. **Timing.** The bridge runs in lockstep with ICON, with a deadline every
   cycle. The plugin passes each CAN frame as a ROS message through a separate
   `ros2_socketcan` node, which is not built for hard deadlines. The CAN bus
   itself should allow about 500 Hz for seven motors at 1 Mbit/s (our estimate).
3. **Gripper.** The gripper is a seventh motor on the same bus, and only one
   process can own the bus. So the gripper has to run in the same plugin, under
   a ROS gripper controller that OMTS reaches through a new skill.
4. **Protocol.** The plugin needs the motors in RobStride's private protocol.
   Seeed's configuration suggests they already are; this is unconfirmed.

If 1–3 fail, the fix is C++ in a third-party driver, and in the worst case a
custom module. In its favour, the reBot has the best specs here on paper. Its
parts list includes a ~$15 PCAN-compatible USB-CAN adapter, which Linux normally
sees as a standard SocketCAN device.

### 3.3 SO-101

This is the arm `PRINTER_UNLOADING.md` section 7 already planned around.

* **Driver.** A generic Feetech `ros2_control` plugin, with CI on Humble, Jazzy
  and Rolling, but not Kilted. SO-101-specific ROS 2 packages build on it
  (`PRINTER_UNLOADING.md` 7.3). How fast the servo bus can run, and whether ICON
  accepts that rate, are open (7.2, risk 4).
* **Arm.** Five joints still allow top-down grasps at any yaw (7.2). The
  pivoting jaw does not self-centre, so the grasp planner needs a different
  contact model (7.2, risk 3). The accuracy estimate (±3–5 mm) means wider grasp
  margins.
* **Trade-off.** It is by far the cheapest and is open hardware. Its arm is the
  weakest here.

### 3.4 Annin AR4

Its driver is the most proven of the community ones, but:

* `ros2_control` runs at **60 Hz** over a 115200-baud serial link to the arm's
  controller board. The bridge locks ICON to the driver's rate, so 60 Hz is a
  slow control loop.
* A hands-on review of the MK3 found significant backlash, and the joint
  encoders are not used for closed-loop control.
* It is a DIY build.

It offers no clear advantage over the reBot or the SO-101, and is not proposed
as an option.

### 3.5 Ruled out

* **ROBOTIS OpenMANIPULATOR-X** (~$1,600, vendor driver): no wrist roll, so it
  cannot grasp top-down at any yaw.
* **Larger vendor-supported arms** (Fairino FR3 ~$6,100, Trossen WidowX AI
  ~$5,900, UFactory xArm 6 ~$9,000): good drivers, but two to five times the
  reBot's price for capability a print does not need.
* **No usable driver:** AgileX PiPER (its official `ros2_control` setup is
  simulation only), Interbotix arms (their `ros_control` layer forwards to
  their own SDK node) and the ARX X5.

---

## 4. Options

| | Option | Arm cost | Driver risk | Time to first OMTS move |
| --- | --- | --- | --- | --- |
| **A** | UFactory Lite 6 | ~$3,600 | Low | Shortest: shared steps plus a Kilted build |
| **B** | reBot B601-RS, after a spike | ~$1,700 + power supply | Medium to high: driver never run on hardware | Spike plus shared steps; weeks more if the spike fails |
| **C** | SO-101, after a spike | ~$230 | Medium: driver in use, bus rate unknown | Spike plus shared steps, plus grasp-planner work for the pivoting jaw |

The time column is relative. None of these paths has been tried, so absolute
figures would be guesses.

**Recommendation: A.** It best fits the aim of saving time and effort,
because its driver is the only vendor-maintained one. It costs more and gives up
open hardware.

**If cost or open hardware matters more than schedule:** spike B or C. Run one
spike at a time and fall back to A if it fails. Pass criteria:

1. The plugin drives every arm joint through `icon_hwm_controller` on Kilted.
2. ICON holds a control rate the driver sustains, with no missed deadlines
   over 30 minutes of continuous motion.
3. One OMTS `Robot` move (`move_robot`) runs end to end.
4. The gripper opens and closes while ICON holds the arm.

---

## 5. Decisions Needed

1. **Schedule or cost and openness:** take A, or spike B or C first?
2. **Budget ceiling** for the arm.
3. **Target printer**, still open in `HANDOFF.md`. This document assumes it
   parks its bed toward the arm. A printer that cannot do that, such as an
   enclosed CoreXY, would make reach a deciding factor again.

---

## 6. Unverified Items

* Whether `xarm_ros2`, `robstride_ros2_control` and `feetech_ros2_driver` build
  and run on Kilted.
* The control rate each driver sustains, and whether ICON accepts it unchanged.
* The Lite 6 gripper's control interface and opening width.
* The reBot gripper's type and opening width, and its motors' CAN protocol.
* The real accuracy each arm achieves; the SO-101 figure is an estimate.
* Prices: retailer listings, not quotes.
