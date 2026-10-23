# Hardware devices, grippers, robots and ICON

Sources:

- `intrinsic-core/developer_resources/learn/tutorials/{custom_asset_creation_hardware,swap_assets,jog_the_robot}.md`
- `intrinsic-core/developer_resources/learn/tutorials/interactive_tutorials/icon/{robot_bringup.md,icon_introduction/icon_introduction.md,hardware_modules/custom_hardware_modules.md,ros2_bridge_tutorial.md,client_api/move_to_contact_tutorial.md}`
- `intrinsic-core/developer_resources/guides/commission_solution/set_up_robot/{universal_robots_setup,kuka_rsi_setup}.md`
- Configs: `intrinsic-omts/configs/*/icon_config.textproto`, `intrinsic-omts/configs/*/ur_module_config.textproto`

## Vocabulary

| Term | Meaning |
|---|---|
| **Scene object** | Geometry, kinematics and physics only (SDF → gzf). There is no software. |
| **Service** | A long-running container (driver, simulator, planner). It has `real_spec` and `sim_spec` images. |
| **Hardware device** | Asset = 1 scene object + ≥1 service (+ data). The scene object gives collision and kinematics, and the service drives the device. Examples: robot HWMs `ai.intrinsic.ur5e_hardware_module_core`, gripper `ai.intrinsic.robotiq_gripper`, camera `ai.intrinsic.orbbec_gemini_335le`. |
| **Hardware module (HWM)** | ICON-side driver process for a robot or real-time device. It exports *hardware interfaces* such as `joint_position_state`, `joint_position_command`, `force_torque_status`, `standard_digital_output_command`, `analog_input_status`. It is configured with `intrinsic_proto.icon.HardwareModuleConfig`. In sim, Gazebo exposes the interfaces and the HWM is a stub. |
| **ICON / RTCS** | Real-Time Control Service (`ai.intrinsic.generic_realtime_control_service`, instance `icon`), configured with `IconMainConfig`. It maps HWM interfaces into **parts**. |
| **Part** | An atomically commandable unit: `arm` (`HalArmPart`), `adio` (`HalADIOPart`), `ft_sensor` (`HalForceTorqueSensorPart`), grippers. Sessions claim parts exclusively (`Part: 'arm' is already in use`). Each part has a `safety_action_type_name` (`intrinsic.stop`, `intrinsic.empty`). |
| **Action / Reaction** | Real-time control algorithms (move, jog, contact) and real-time condition → response transitions. List them with `inctl icon list-actions`. |

## The name-consistency rule (most common failure)

One physical robot shows up under the **same name** in four places:

1. `intrinsic_asset_instance(instance_name = "ur_module")` in BUILD.
2. The world object name, used in all `*.updates.pbtxt` (`object_name: "ur_module"`) and in `app_config.yaml` (`arm_part_name`, `machine.device_name`).
3. ICON config: every `module_name: "ur_module"`, plus `hardware_resource_name: "ur_module"` on the arm part.
4. The HWM config `name:`, when present.

Error signatures when they disagree:

- `No object with name "X" exists ... could not load resource set into edit world` means an updates file names a missing instance.
- `No object with name "kuka_rsi_hal_module" exists ... Error building Part 'arm'` means the ICON config and instance disagree.
- `Hardware module 'X' does not export interface 'analog_input_status'` means ICON expects an interface the HWM lacks. Remove it from `parts_by_name`.
- `ICON ('control_frequency_hz'): 2000000 ns (500.0 Hz), hardware module reports: 4000000 ns (250.0 Hz)` means the frequencies differ. UR runs at 500 Hz and KUKA RSI at 250 Hz. Match `IconMainConfig.control_frequency_hz` to `HardwareModuleConfig.control_frequency_hz`.

## Grippers: three ways to actuate

| Approach | What you build | Skill | Notes |
|---|---|---|---|
| Digital I/O | Scene object only, plus mounting updates | `dio_set_output(block_name="standard_out", bit_index=N, value=bool)`, `dio_wait_for_input(...)`, `dio_read_input` | Uses the ICON `adio` part exports (`standard_out`, `standard_in`, `tool_out`, ...). OMTS `DioGripper` in `intrinsic-omts/src/hardware/gripper.py`. |
| Native pinch-gripper driver | Hardware device: scene object + `intrinsic_service` running `resource-pinch-gripper-server-image.tar` with a `PinchGripperPart` Any config | `control_pinch_gripper(position=m, speed=m/s, force=N)` | The driver is chosen by `pinch_gripper_driver_name` (`"RobotiqGripper"` for Robotiq). The WSG32 C++ driver (`Wsg32Gripper`) is in `intrinsic-core/intrinsic_hardware/intrinsic/hardware/gripper/wsg32/` and is linked into the gripper service (`//intrinsic_hardware/intrinsic/hardware/gripper/wsg32:wsg32_gripper`). There is **no prebuilt `ai.intrinsic.wsg32_gripper_strauss` asset** in the repo, despite what the tutorial says. |
| ROS-based service (OMTS Hand-E) | Imported bundle `hand_e_gripper_service` + skill `hand_e_gripper_cmd_skill` | `gripper_cmd_skill` | See `intrinsic-omts/BUILD` (`imported_asset_bundle`). |

`PinchGripperPart` default config (`intrinsic-core/intrinsic/resources/catalog/resourcedata/gripper/robotiq_pinch_gripper_default_config.pbtxt`):

```textproto
# proto-file: google/protobuf/any.proto
# proto-message: Any
[type.googleapis.com/intrinsic_proto.gripper.PinchGripperPart] {
  config: {
    generic_pinch_gripper_config: {
      comm_config: { ip_address: "192.168.1.91" port: 502 }
      physical_config: {
        position: { si_properties: { range: { minimum: 0.0 maximum: 0.05 } increment: 0.001 unit: "meters" }
                    hardware_value_properties: { range: { minimum: 255 maximum: 0 } increment: 1 unit: "" }
                    default_si_value: 0.05 }
        velocity: { si_properties: { range: { minimum: 0.02 maximum: 0.15 } ... unit: "m/s" } ... default_si_value: 0.02 }
        effort:   { si_properties: { range: { minimum: 20.0 maximum: 185.0 } ... unit: "Newton" } ... default_si_value: 20.0 }
      }
      additional_config: { cyclic_routine_frequency_hz: 10.0 status_topic: "robotiq_gripper/gripper/status" }
      pinch_gripper_driver_name: "RobotiqGripper"     # C++ class registered in the gripper service
    }
  }
  grpc_config: { grpc_timeout: { seconds: 10 } }
}
```

The hardware-value range maps linearly to the SI range. Robotiq maps 255→0 m and 0→0.05 m.

## Mounting a tool (gripper, camera, mount plate)

Mounting is scene configuration, not driver configuration. Add a cell `*.updates.pbtxt` with these steps:

1. `update_transform` from the flange to the tool object (mount offset).
2. If the TCP is not already in the SDF, `update_transform` from the tool object to its `tool_frame`, with `node_a_filter.entity_names` set to the body link.
3. `reparent_object` onto the robot with `include_final_entity`.
4. `update_kinematic_object_properties { object { by_name { object_name: "<robot>" } } }`.

Template: `intrinsic-omts/configs/omts/ur_module.attachments.updates.pbtxt`. The **name `gripper`** is assumed by OMTS tools (`--tool_object gripper`) and `app_config.yaml`.

## Robots: hardware-module configs

UR (`intrinsic-omts/configs/omts/ur_module_config.textproto`, the instance's `service_config`):

```textproto
[type.googleapis.com/intrinsic_proto.icon.HardwareModuleConfig]: {
  module_config: { [type.googleapis.com/intrinsic_proto.icon.UniversalRobotsModuleConfig]: {
      robot_ip: "192.170.10.100"  default_advanced_control: {} } }
  drives_realtime_clock: true
  simulation_module_config: { additional_devices: { name: "analog_input" analog_input: { num_inputs: 2 } } }
  control_frequency_hz: 500
}
```

KUKA RSI: defaults are in `intrinsic-core/intrinsic_control/intrinsic/icon/hardware_modules/kuka_rsi/kuka_rsi_default_config.textproto`. Key fields:

- `local_rsi_host` / `local_rsi_port` (5852)
- `digital_input_names` / `digital_output_names`
- `eki_status_client_params` / `eki_control_client_params` (`eki_address`, ports 54600/54601)
- `drives_realtime_clock: true`
- `control_frequency_hz: 250`

## ICON main config (`IconMainConfig`, the `icon` instance's `service_config`)

Structure, from `intrinsic-omts/configs/omts/icon_config.textproto`:

```textproto
[type.googleapis.com/intrinsic_proto.icon.IconMainConfig]: {
  intrinsic_runtime { name: "intrinsic_runtime" }
  control_frequency_hz: 500                         # must equal the HWM's
  services: { world_service_from_grpc: { world_id: "world" }
              kinematics_from_world_service: true  assembly_from_world_service: true }
  realtime_control_config: {
    parts_by_name: { key: "adio" value: { part_type_name: "HalADIOPart"
        config: { [type.googleapis.com/intrinsic_proto.icon.HalADIOPartConfig]: {
          digital_inputs:  { interface: { module_name: "ur_module" interface_name: "standard_digital_input_status" } export_name: "standard_in" }
          digital_outputs: { interface: { module_name: "ur_module" interface_name: "standard_digital_output_command" } export_name: "standard_out" }
          ... } }
        safety_action_type_name: "intrinsic.empty" } }
    parts_by_name: { key: "arm" value: { part_type_name: "HalArmPart"
        config: { [type.googleapis.com/intrinsic_proto.icon.HalArmPartConfig]: {
          joint_position_command: { module_name: "ur_module" interface_name: "joint_position_command" }
          joint_position_state:   { module_name: "ur_module" interface_name: "joint_position_state" }
          joint_velocity_state, payload_command, payload_state, linear_joint_acceleration_filter_config ... } }
        safety_action_type_name: "intrinsic.stop"
        hardware_resource_name: "ur_module" } }
    parts_by_name: { key: "ft_sensor" value: { part_type_name: "HalForceTorqueSensorPart" ... } }
  }
}
```

ICON reads kinematics from the **world** (`kinematics_from_world_service`). The robot geometry and limits therefore come from the scene object plus your `ur_module.limits.updates.pbtxt`.

Force/torque part fields:

- `force_torque_state` / `force_torque_command` / `joint_position_state` bindings
- `world_robot_collection_name`
- `target_link_name: "wrist_3_link"`, `ft_sensor_link_name: "InternalForceTorqueSensor"`
- `force_control_settings { excessive_force_threshold: 85 excessive_torque_threshold: 8.5 virtual_translational_inertia: 15 virtual_rotational_inertia: 1 sensed_wrench_deadband {...} }`

Virtual inertia must exceed the payload inertia.

Auto-generate a starting config from a running solution. Port-forward the RTCS, then run `curl localhost:9091/v1/mainConfig:autoGenerate?world_id=world | jq`.

## Swap the robot (UR → KUKA KR10), from the swap_assets tutorial

1. `BUILD` assets: replace `@intrinsic-core//intrinsic_control/intrinsic/icon/hardware_modules/universal_robots:ur3e_hardware_module_core` with `@intrinsic-core//intrinsic_control/intrinsic/icon/hardware_modules/kuka_rsi:kr10_r1100_2_hardware_module`.
2. Instances: replace `:ur_module` with `:kuka_rsi_hal_module`, i.e. `intrinsic_asset_instance(name="kuka_rsi_hal_module", asset="ai.intrinsic.kuka_kr10_hardware_module", instance_name="kuka_rsi_hal_module", service_config=":kuka_rsi_config.textproto")`.
3. Copy the default KUKA config: `cp ~/intrinsic-core/intrinsic_control/intrinsic/icon/hardware_modules/kuka_rsi/kuka_rsi_default_config.textproto kuka_rsi_config.textproto`.
4. ICON: point `icon` `service_config` to `//configs:kr_10/icon_config.textproto`. Its module names are renamed, it runs at 250 Hz, the I/O differs, and it has no FT sensor.
5. Rename the robot in the scene: `sed -i "s/ur_module/kuka_rsi_hal_module/g" configs/lab_bb_01/*.updates.pbtxt`. Verify with `grep ur_module configs/lab_bb_01/*.updates.pbtxt`, which should print nothing.
6. Redeploy:
   ```bash
   inctl solution stop --address localhost:17080
   bazel run //:omts_solution --config=lab_bb_01 -- --address localhost:17080 --operation_mode=sim
   ```
7. Check `inctl icon status --address localhost:17080 --instance_name icon`, then reopen Gazebo and RViz. RViz needs a MarkerArray display, not RobotModel.
8. Revert: `git checkout BUILD configs/lab_bb_01/*.updates.pbtxt`, remove the copied config, and redeploy.

The OMTS `BUILD` comment says the KUKA cell is not fully wired: `configs/kr_10/` exists, but the `setup` flag has no value for it.

## Real robot bring-up (only with user consent)

1. Run `sudo ~/intrinsic-core/intrinsic_runtime/setup_realtime.sh`, then `sudo reboot`. Without it you get `Failed to parse [/proc/cmdline]`, or the `rs-icon-0` pod stays Pending on node affinity. **Never** run `sudo bazel`. From a Bzlmod workspace use `cat "$(bazel info output_base)/external/intrinsic-core+/intrinsic_runtime/setup_realtime.sh" | sudo -E bash`.
2. Network:
   - UR: a static NIC, e.g. `192.170.10.123/24`, applied with `sudo netplan apply`. Check the dashboard with `curl --max-time 3 <robot_ip>:29999`. `Received HTTP/0.9` means OK; a timeout means it is disabled or unreachable.
   - KUKA: RSI on 192.168.10.x (UDP, real-time) and EKI on 192.168.11.x (TCP). It needs the `IntrinsicBase`/`IntrinsicExtended` `.kop` packages and `$MOVE_ENABLE`/`$DRIVES_ON`/`$CONF_MESS` loopback wiring (`$OUT[421-423]` → `$IN[421-423]`).
3. Deploy with `--operation_mode=real`, then check:
   ```bash
   inctl icon status
   inctl icon clear-faults
   inctl icon enable
   inctl icon list-parts
   inctl icon config
   inctl service state list
   inctl service state restart <name>
   inctl gpio list-signals
   inctl gpio read-signals --signal_names=di_1
   inctl gpio write-signal --signal_name=do_1 --value=true
   ```
   Add `--address localhost:17080` (and `--instance_name icon`) to each.

## Custom hardware modules (C++) and the ROS 2 bridge

- Start from the loopback module, which echoes commanded positions:
  - `//intrinsic_control/intrinsic/icon/hardware_modules/loopback:loopback_hardware_module` (library)
  - `:loopback_hardware_module_main` (binary)
  - `:loopback_hardware_module_image` (image)
  - Device bundle example: `//intrinsic_control/intrinsic/icon/hardware_modules/kuka_rsi:kr6_r900_2_loopback_hardware_module` → `.bundle.tar`
- Install it and add the instance:
  ```bash
  inctl asset install <bundle.tar> --address localhost:17080
  inctl service add ai.intrinsic.loopback_hardware_module --name=kuka_rsi_hal_module --address localhost:17080
  ```
  This needs a running solution in **real** mode, because in sim the HWM is not executed.
- Real-time rules:
  - No heap allocation in `ReadStatus()` / `ApplyCommand()`. Test with `cc_test_and_malloc_test` and `IF_INTRINSIC_MALLOC_TEST_EXPECT_NO_ALLOCATIONS()`.
  - Use `alwayslink = 1` for static registration.
  - Set `drives_realtime_clock` on exactly one module.
- `ros2_control` robots: `github.com/intrinsic-ai/icon-hwm-controller`. Build the `icon_hwm_base` image with Docker Compose, then wrap a launch file that keeps only `joint_state_broadcaster` and `joint_trajectory_controller`. Optionally add an `OperationalStatus` publisher plus a `std_srvs/Trigger` fault-clear service. Package it as a hardware device (`bazel build :rrbot_hardware_device`) and install the bundle.

## Fault quick reference

| Symptom | Fix |
|---|---|
| `inctl icon status` reports FAULTED with `'ur_module': The server is gone` after a Gazebo restart | `inctl icon clear-faults --address localhost:17080 --instance_name icon`. Repeat if needed. |
| `Part: 'arm' is already in use` | `inctl icon disable ...` then `inctl icon enable ...` |
| `Goal violates Part limits` | Jogged past the limits. Restart the jog tool. |
| `Error: rpc error: code = Unimplemented` from `inctl icon` | Wrong `--instance_name`, or ICON is not running (deployed `real` without RT setup). Check with `k9s -n app-resources -c pods`. |
| `inctl icon list-parts` does not show the gripper | The gripper instance is missing from `instances=[...]`. |
| `PinchGripperFactory: unknown driver` | The driver library is not linked into the gripper service deps. |
