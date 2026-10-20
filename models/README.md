# 3D Scene Models & Assets (`models/`)

Simulation Description Format (`.sdf`), 3D visual/collision meshes (`.glb`),
and Intrinsic Scene Object manifests (`.textproto`) bundled into
`//:omts_solution`.

## Assets

| Directory | Asset ID | Description |
| :--- | :--- | :--- |
| [`camera_mount/`](camera_mount/) | `ai.intrinsic.camera_mount` | Wrist bracket mounting the Orbbec Gemini 3D camera to the robot flange. |
| [`cnc_enclosure/`](cnc_enclosure/) | `ai.intrinsic.cnc_enclosure` | CNC machine tool enclosure with actuated sliding safety door joint. |
| [`omts_enclosure/`](omts_enclosure/) | `ai.intrinsic.omts_enclosure` | Main robot cell safety enclosure and worktable geometry. |
| [`raw_stock_2x3x5/`](raw_stock_2x3x5/) | `ai.intrinsic.raw_stock_2x3x5` | 2" × 3" × 5" raw stock billet used for pose estimation and manipulation. |
| [`rebot_b601_rs/`](rebot_b601_rs/) | `ai.intrinsic.rebot_b601_rs` | Seeed reBot Arm B601-RS, generated from Seeed's URDF by `//tools/models:urdf_to_sdf`; used by `//:rebot_solution`. |
| [`schunk_egp_64nnb/`](schunk_egp_64nnb/) | `ai.intrinsic.schunk_egp_64nnb` | Schunk EGP 64 pneumatic 2-finger parallel vise with articulated jaw joints (`jaw_l`, `jaw_r`). |
