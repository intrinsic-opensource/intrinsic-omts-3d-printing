# Feature Request: Carry mimic joints from SDF scene objects to simulation

**Component:** Intrinsic world and scene object conversion
(`intrinsic/scene/sdf/convert_to_sdf.cc` and
`intrinsic/simulation/world/world_object_plugin.cc` in intrinsic-core)

## Summary

A gripper whose fingers are driven together by one actuator cannot be
simulated as one: a `<mimic>` coupling in the scene object's SDF is dropped
when the world is converted for Gazebo, and the actuated gripper plugin then
drives each finger with its own controller. Carrying mimic joints through the
conversion, and having the plugin drive only the leading joint, would let the
simulated gripper move like the real one.

## Current behavior

* Gazebo supports mimic joints: SDF 1.11+ has `<mimic>` inside a joint's
  `<axis>`, gz-sim's physics system applies it
  (`gz-sim/src/systems/physics/Physics.cc`), and Bullet Featherstone, the
  simulator's default engine, implements it as a gear constraint
  (`gz-physics/bullet-featherstone/src/JointFeatures.cc`).
* Intrinsic does not pass it on. An SDF scene object becomes world entities,
  and the simulator's SDF is written back from their `KinematicsComponent`.
  `JointSpecToString` (`convert_to_sdf.cc`) writes the axis, limits, effort,
  velocity, acceleration, jerk and damping, and nothing for a mimic. The one
  passthrough, the deprecated `kGazeboJointPhysics` user data, is appended
  after `</axis>`, where `<mimic>` is not valid. The kinematics library has
  linear joint dependencies (`Joint::LinearDependency`), but rejects a joint
  with no input of its own (`alpha_self` of zero), noting that such a
  "mimicked joint" is "not supported yet"
  (`intrinsic_kinematics/intrinsic/kinematics/joint.h`).
* The actuated gripper plugin is given every prismatic or revolute joint with
  finite limits (`world_object_plugin.cc`) and runs one PD controller per
  joint, all with the same target. So even with the coupling kept, the
  following joint would get a controller of its own fighting it.

## Observed impact

OMTS printer tending simulates the Seeed reBot Arm B601-RS gripper, whose two
fingers are driven by one linear actuator. In simulation each finger is its
own actuator, and they come apart whenever contact loads them unequally:

* While a grasp is held on the bed, the fingers drift sideways together and
  snap back when the arm lifts. The part is welded to one finger and the other
  keeps pushing on it.
* At release, one finger can stay against the part for 0.2–1.8 s while the
  other opens, or the part follows one finger by up to a full finger travel
  (28 mm), in recorded runs.
* The cell works around it by pressing the part onto its support before
  opening.

A real one-actuator gripper keeps the fingers symmetric, so these effects are
simulation artifacts. The workaround and the time spent diagnosing them would
not be needed with the coupling.

## Suggested fix

1. **Keep mimic joints through the conversion.** Read `<mimic>` (leader joint,
   multiplier, offset) when importing an SDF scene object, store it on the
   following joint's kinematics, and write it back in `JointSpecToString`.
2. **Drive only leading joints in the actuated gripper plugin.** Leave
   following joints out of its joint list, so the coupling alone moves them.
3. Optionally, let the kinematics library's `LinearDependency` accept a
   joint with no input of its own, so the planner and world see the following
   finger in the right place.

## Benefit

Grippers with coupled fingers (most parallel and rack-and-pinion grippers)
behave in simulation as on hardware. Grasps stay centred, releases are clean,
and cells don't need contact workarounds that may not transfer to the real
gripper.
