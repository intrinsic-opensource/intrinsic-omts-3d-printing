# 3D Scene Models & Assets (`models/`)

Simulation Description Format (`.sdf`), 3D visual/collision meshes (`.glb`),
and Intrinsic Scene Object manifests (`.textproto`) bundled into
`//:omts_solution` and `//:rebot_solution`.

## Assets

| Directory | Asset ID | Description |
| :--- | :--- | :--- |
| [`camera_mount/`](camera_mount/) | `ai.intrinsic.camera_mount` | Wrist bracket mounting the Orbbec Gemini 3D camera to the robot flange. |
| [`cnc_enclosure/`](cnc_enclosure/) | `ai.intrinsic.cnc_enclosure` | CNC machine tool enclosure with actuated sliding safety door joint. Not used by any cell since the printer replaced it in `omts`. |
| [`omts_enclosure/`](omts_enclosure/) | `ai.intrinsic.omts_enclosure` | Main robot cell safety enclosure and worktable geometry. |
| [`printer/`](printer/) | `ai.intrinsic.printer` | Prusa Core One printer: frame meshes with box collisions for its walls, front bezels and rail, internal towers, X-axis rail and hotend, and a separate heatbed link (bed top at z = 0.1434). In the `omts` cell (where the CNC stood) and the reBot cell. |
| [`raw_stock_2x3x5/`](raw_stock_2x3x5/) | `ai.intrinsic.raw_stock_2x3x5` | 2" × 3" × 5" raw stock billet used for pose estimation and manipulation. |
| [`rebot_b601_rs/`](rebot_b601_rs/) | `ai.intrinsic.rebot_b601_rs` | Seeed reBot Arm B601-RS (6 DoF, no gripper) as a simulation-only ICON hardware device, generated from Seeed's URDF by `//tools/models:urdf_to_sdf`; used by `//:rebot_solution`. |
| [`rebot_b601_rs_gripper/`](rebot_b601_rs_gripper/) | `ai.intrinsic.rebot_b601_rs_gripper` | The reBot B601-RS two-finger gripper, mounted on the arm's flange by `configs/rebot/`. |
| [`rebot_ground/`](rebot_ground/) | `ai.intrinsic.rebot_ground` | Ground slab the reBot cell stands on; also the drop-off surface behind the robot. |
| [`rebot_printed_part/`](rebot_printed_part/) | `ai.intrinsic.rebot_printed_part` | 40 × 40 × 30 mm printed part the reBot cell finds and unloads from the printer's bed. |
| [`schunk_egp_64nnb/`](schunk_egp_64nnb/) | `ai.intrinsic.schunk_egp_64nnb` | Schunk EGP 64 pneumatic 2-finger parallel vise with articulated jaw joints (`jaw_l`, `jaw_r`). Not used by any cell since the printer replaced the CNC in `omts`. |
