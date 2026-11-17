# Developer & Operational CLI Tools (`tools/`)

Standalone Bazel CLI utilities for cell commissioning, live world inspection,
teleoperation, pose teaching, hardware I/O testing, and code formatting/linting.

## Tool Subpackages

| Directory / Script | Bazel Target / Command | Purpose |
| :--- | :--- | :--- |
| [`world/`](world/README.md) | `//tools/world:apply_scene_updates`<br>`//tools/world:edit_frames_rviz`<br>`//tools/world:inspect_world` | Apply `.pbtxt` world updates live (with optional Gazebo `--reset_sim`), interactively drag/rotate 6-DoF frames and transforms directly in RViz (`edit_frames_rviz.py`, `rviz_marker_node.py`, `rviz_marker_controller.py`, `pbtxt_pose_store.py`), and inspect kinematic trees/transforms. |
| [`jogging/`](jogging/README.md) | `//tools/jogging:jog_interactive`<br>`//tools/jogging:move_to_frame`<br>`//tools/jogging:move_to_joint`<br>`//tools/jogging:store_frame`<br>`//tools/jogging:store_joint_config` | Interactive robot teleoperation, Cartesian/joint moves to named targets, and teaching/persisting frames into `scene.updates.pbtxt`. |
| [`gripper/`](gripper/README.md) | `//tools/gripper:control_gripper` | Open/close Robotiq or DIO grippers interactively or via CLI flags (`--action=open\|close`). |
| [`machine/`](machine/README.md) | `//tools/machine:control_machine` | Actuate CNC enclosure doors, pneumatic vises, and cycle handshake pins (`open_door`, `close_door`, `open_vise`, `close_vise`, `trigger_cycle`, `wait_cycle`). |
| [`printer/`](printer/README.md) | `//tools/printer:gcode_to_stl`<br>`//tools/printer:printer_skills` | Rebuild a compound STL from a print job's G-code (the PrusaLink service does this for each new job), and run and monitor the printer skills. Step by step from the printer to the skills. |
| [`mock_printer/`](mock_printer/README.md) | `python3 tools/mock_printer/mock_printer.py` | A disposable fake PrusaLink printer with a live screen, for testing the printer service. Standalone. |
| [Printer skill demo](../services/prusalink/README.md#terminal-5-see-actual-skill-execution-and-changing-results) | `//tools/printer:printer_skills` | Run read/watch/wait skills through the Executive against PrusaLink; show execution state and typed readiness results without robot motion. |
| [`calibration/`](calibration/README.md) | `//tools/calibration:sample_calibration_poses`<br>`//tools/calibration:calibrate_camera_to_robot`<br>`//tools/calibration:update_robot_kinematics` | Hand-eye ChArUco camera calibration pose sampling, calibration execution, and UR kinematics update helpers. |
| [`models/`](models/README.md) | `//tools/models:urdf_to_sdf` | Convert a URDF with STL meshes into an SDF scene model with simplified GLB meshes. |
| [`format.sh`](format.sh) | `./tools/format.sh` | Formats all Bazel (`buildifier`) and Python/Markdown (`ruff`) files in the repository. |
| [`lint.sh`](lint.sh) | `./tools/lint.sh` | Runs the exact CI lint and format checks (`buildifier --mode=check`, `ruff check`, `ruff format --check`). |
