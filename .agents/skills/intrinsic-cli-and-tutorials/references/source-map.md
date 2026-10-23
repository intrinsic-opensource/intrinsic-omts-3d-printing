# Source map: where things live (read this instead of grepping whole repos)

The root is `/home/berti/gits/`. `CORE` = `intrinsic-core/`, `OMTS` = `intrinsic-omts/` (**this repo**), `EX` = `sdk-examples/`.

`CORE` paths refer to the local checkout (a3bd446, tag 20261012.0). `verify_kb.py` confirms they also exist at the OMTS core pin c40e02a, except for the forwarders marked "deleted at pin". To read a pinned file, run `git -C ../intrinsic-core show c40e02a:<path>`.

## Docs and tutorials

| Topic | Path |
|---|---|
| Tutorial index | `CORE/developer_resources/learn/tutorials/README.md` |
| Scene editing | `CORE/developer_resources/learn/tutorials/cell_customization.md` |
| New part | `CORE/developer_resources/learn/tutorials/import_new_part.md` |
| Hardware gripper | `CORE/developer_resources/learn/tutorials/custom_asset_creation_hardware.md` |
| Swap assets/robot | `CORE/developer_resources/learn/tutorials/swap_assets.md` |
| CAD → SDF | `CORE/developer_resources/assets/create_new_assets/convert_3d_models.md` |
| World concepts | `CORE/developer_resources/learn/platform_introduction/world_concepts.md` |
| Glossary | `CORE/developer_resources/learn/glossary/{intrinsic_terms,general_terms}.md` |
| ICON tutorials | `CORE/developer_resources/learn/tutorials/interactive_tutorials/icon/` |
| Robot commissioning | `CORE/developer_resources/guides/commission_solution/set_up_robot/{universal_robots_setup,kuka_rsi_setup}.md` |
| Core agent skills (API level) | `CORE/AGENTS.md`, `CORE/.agents/skills/intrinsic-core-*/`. Tracked copies are in `OMTS/.agents/skills/intrinsic-core-*/`, and `OMTS/AGENTS.md` is the upstream OMTS guide. |
| OMTS docs | `OMTS/README.md` (deploy, perception setup §4.3, run §4.4, tests §5), `OMTS/docs/ARCHITECTURE.md`, `OMTS/{src,tools,configs,models}/README.md`, `OMTS/tests/README.md` |

## Build rules (.bzl)

| Rule | Path |
|---|---|
| `sdf_scene_object` | `CORE/intrinsic_sdk/intrinsic/scene/build_defs/sdf_scene_object.bzl` (forwarder at `CORE/intrinsic/scene/build_defs/`, kept at the pin) |
| `scene_object` (textproto) | `CORE/intrinsic_sdk/intrinsic/scene/build_defs/scene_object.bzl` (the `CORE/intrinsic/scene/build_defs/scene_object.bzl` forwarder is deleted at the pin) |
| `intrinsic_scene_object` | `CORE/intrinsic_sdk/intrinsic/assets/scene_objects/build_defs/scene_object.bzl` |
| `intrinsic_hardware_device` | `CORE/intrinsic_sdk/intrinsic/assets/hardware_devices/build_defs/hardware_device.bzl` |
| `intrinsic_service` | `CORE/intrinsic_sdk/intrinsic/assets/services/build_defs/services.bzl` |
| `intrinsic_data` | `CORE/intrinsic_sdk/intrinsic/assets/data/build_defs/data.bzl` |
| `intrinsic_asset_instance`, `intrinsic_asset_reference` | `CORE/intrinsic_sdk/intrinsic/assets/build_defs/asset.bzl` (the forwarder `CORE/intrinsic/assets/build_defs/asset.bzl` is deleted at the pin) |
| `intrinsic_solution` | `CORE/intrinsic/assets/build_defs/solution.bzl`; deployer `solution_update.go` |
| UR device macro | `CORE/intrinsic_control/intrinsic/icon/hardware_modules/universal_robots/ur_hardware_device.bzl` |

## Protos

| Message | Path |
|---|---|
| ObjectWorldUpdates | `CORE/intrinsic_sdk/intrinsic/world/proto/object_world_updates.proto` |
| Refs | `CORE/intrinsic_apis/intrinsic/world/proto/object_world_refs.proto` |
| ObjectWorldService | `CORE/intrinsic_sdk/intrinsic/world/proto/object_world_service.proto` |
| SceneObjectUpdates | `CORE/intrinsic_apis/intrinsic/scene/proto/v1/scene_object_updates.proto` |
| SceneObjectManifest | `CORE/intrinsic_apis/intrinsic/assets/scene_objects/proto/scene_object_manifest.proto` |
| HardwareDeviceManifest | `CORE/intrinsic_apis/intrinsic/assets/hardware_devices/proto/v1/hardware_device_manifest.proto` |
| ServiceManifest | `CORE/intrinsic_apis/intrinsic/assets/services/proto/service_manifest.proto` |
| Collision settings | `CORE/intrinsic_apis/intrinsic/world/proto/collision_settings.proto` |
| Simulation component | `CORE/intrinsic_apis/intrinsic/world/proto/simulation_component.proto` |

## Python APIs

| API | Path |
|---|---|
| ObjectWorldClient | `CORE/intrinsic_sdk/intrinsic/world/python/object_world_client.py`, resources in `object_world_resources.py` |
| SBL | `CORE/intrinsic_sdk/intrinsic/solutions/{deployments,worlds,behavior_tree,simulation}.py` |
| Math | `CORE/intrinsic_sdk/intrinsic/math/python/{data_types,pose3,rotation3}.py` |
| ICON client | `CORE/intrinsic_control/intrinsic/icon/python/icon_api.py` |

## SDF converter

- Tags: `CORE/intrinsic_sdk/intrinsic/scene/sdf/custom_tags.h`
- Conversion: `CORE/intrinsic_sdk/intrinsic/scene/sdf/entity_from_sdf.cc`, `CORE/intrinsic_sdk/intrinsic/world/conversion/sdf/`

## inctl sources

| Command group | Path |
|---|---|
| Root, icon, gpio, world | `CORE/intrinsic_sdk/intrinsic/tools/inctl/cmd/` (`root.go`, `icon_*.go`, `gpio_*.go`, `world/reset.go`, `solution/`). `world print` exists only at the pin. |
| `asset ...` | `CORE/intrinsic_sdk/intrinsic/assets/inctl/` |
| `service ...` | `CORE/intrinsic_sdk/intrinsic/assets/services/inctl/` |
| Shared flags | `CORE/intrinsic_sdk/intrinsic/assets/cmdutils.go` |

## Example hardware and parts in core

| Kind | Path |
|---|---|
| Gripper device | `CORE/intrinsic/resources/catalog/resourcedata/gripper/` |
| Gripper models | `CORE/intrinsic_control/intrinsic/models/assets/standard_tooling/robotiq_hande/` |
| Cameras | `CORE/intrinsic_perception/intrinsic/perception/cameras/hardware_devices/` |
| Robot models (xacro → SDF) | `CORE/intrinsic_control/intrinsic/models/robot_definitions/{ur,kuka,...}/` |
| Robot HWMs | `CORE/intrinsic_control/intrinsic/icon/hardware_modules/{universal_robots,kuka_rsi,abb,loopback,gazebo_hwm_stub}/` |
| F/T sensor device | `CORE/intrinsic_hardware/intrinsic/hardware/force_torque/axia80_net/` |
| Gripper drivers | `CORE/intrinsic_hardware/intrinsic/hardware/gripper/{robotiq,wsg32,service}/` |
| IMTS demo parts (raw stock glbs, cnc enclosure) | `CORE/intrinsic/models/assets/imts/`, `CORE/intrinsic/resources/catalog/resourcedata/product/imts/` |
| World-modifying skills | `CORE/intrinsic/skills/apps/{update_world,attach_object_to_robot,detach_object}.*`, `CORE/intrinsic/world/skills/create_object/` |
| DIO skills | `CORE/intrinsic_control/intrinsic/icon/skills/` (`dio_set_output`, `dio_read_input`, `dio_wait_for_input`) |
| Pose estimation (current OMTS) | `CORE/intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools/` (`register_using_ioc_train_service`), `CORE/intrinsic_perception/intrinsic/perception/service/ioc_pose_estimator/` (`run_pose_estimation`). The `nvidia_pose_estimator` service exists **only at the pin**: run `git -C ../intrinsic-core show c40e02a:intrinsic_perception/intrinsic/perception/service/nvidia_pose_estimator/README.md`. |

## OMTS (this repo)

| Kind | Path |
|---|---|
| Solution | `OMTS/BUILD` (`omts_solution`, instances, `select` on `//:setup`), `OMTS/.bazelrc` (`--config=omts\|lab_bb_01`, the perception build flags), `OMTS/MODULE.bazel` (`INTRINSIC_CORE_COMMIT` + `git_override` + patches) |
| Scene | `OMTS/configs/{omts,lab_bb_01,kr_10,common}/` (`*.updates.pbtxt`, `icon_config.textproto`, `ur_module_config.textproto`, `app_config.yaml`) |
| Scene tests | `OMTS/tests/unit/test_world_configs.py` (frame lists, base-transform rule), `OMTS/tests/unit/test_apply_scene_updates.py`, `OMTS/tests/unit/test_edit_frames_rviz.py` |
| Models | `OMTS/models/{camera_mount,cnc_enclosure,omts_enclosure,raw_stock_2x3x5,schunk_egp_64nnb}/` |
| Tools | `OMTS/tools/{world,jogging,gripper,machine,calibration}/` (the old pose-estimation tools package was removed in #161) |
| App | `OMTS/src/{main.py,behaviors/,hardware/,core/,utils/}` |
| Core patches | `OMTS/bazel/patches/` |
| Upstream agent setup | `OMTS/AGENTS.md`, `OMTS/.agents/skills/intrinsic-core-*/` (tracked) |

## sdk-examples (sibling; Flowstate SDK `@ai_intrinsic_sdks`)

| Kind | Path |
|---|---|
| World notebooks | `EX/notebooks/003_world.ipynb` (world API), `EX/notebooks/011_scene_object_import.ipynb` (gRPC import) |
| Skill using the world | `EX/skills/use_world/` |
| Other skills | `EX/skills/{say_skill,validate_pose,...}/` |
| Services | `EX/services/` |
