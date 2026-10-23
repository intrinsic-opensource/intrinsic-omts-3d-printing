---
description: "Use when writing Bazel BUILD targets or manifests for Intrinsic assets: sdf_scene_object, intrinsic_scene_object, intrinsic_hardware_device, intrinsic_service, intrinsic_asset_instance, intrinsic_solution, SceneObjectManifest, HardwareDeviceManifest, ServiceManifest, service_config for ICON or hardware modules."
applyTo: "**/models/**, **/*scene_object*manifest.textproto, **/*hardware_device*manifest.textproto, **/*_resource_manifest.textproto"
---
# Intrinsic asset BUILD and manifest rules

Full reference: `.agents/skills/intrinsic-hardware-assets/references/bazel-asset-rules.md`.

## Load paths

These are valid at intrinsic-core 20261012.0 **and** at the OMTS core pin c40e02a, and they match the OMTS `BUILD` and `models/*/BUILD` files. Use the `@intrinsic-core` prefix outside the core repo.

```python
load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")   # or //intrinsic_sdk/intrinsic/scene/build_defs:...
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/hardware_devices/build_defs:hardware_device.bzl", "intrinsic_hardware_device")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/services/build_defs:services.bzl", "intrinsic_service")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl", "intrinsic_asset_instance")
load("@intrinsic-core//intrinsic/assets/build_defs:solution.bzl", "intrinsic_solution")
```

**Never** use:

- `@intrinsic-core//intrinsic/assets/scene_objects/build_defs:...`, which never existed although the tutorials show it.
- `@intrinsic-core//intrinsic/assets/build_defs:asset.bzl` or `//intrinsic/scene/build_defs:scene_object.bzl`, which are deleted at the OMTS pin.

There is also **no** `intrinsic_asset` rule. Proto deps use `@intrinsic-core//intrinsic_sdk/intrinsic/world/proto:...`.

## Rules

- **Manifests** must end in `.textproto` and carry the `# proto-file:` and `# proto-message:` header:
  - Scene objects use `intrinsic_proto.scene_objects.SceneObjectManifest` (`metadata { id { package name } vendor documentation display_name }`).
  - Hardware devices use `intrinsic_proto.hardware_devices.v1.HardwareDeviceManifest` (`metadata` + `graph { nodes { key: "scene_object" ... } nodes { key: "service" ... } }`). The graph has exactly 1 scene object, at least 1 service, and optional data with a `configures {}` edge.
- **Asset ID** = `<package>.<name>`, e.g. `ai.intrinsic.my_part`. The name is alphanumeric plus `_` and starts with a letter.
- **`intrinsic_asset_instance`:**
  - `asset` is an ID **string**, not a label.
  - `instance_name` becomes the world object or service name.
  - Put per-instance driver, HWM or ICON configs (`google.protobuf.Any` textproto) in `service_config`. `config` is a full `InstanceConfig`, and the two are mutually exclusive.
- **`intrinsic_solution`:** every instance's asset must be listed in `assets` (or already installed). `object_world_updates` apply in order. OMTS defaults to `real` mode, so always deploy with `--operation_mode=sim` unless the user says otherwise.
- **Names:** keep robot and device names identical across `instance_name`, `*.updates.pbtxt`, ICON `module_name`/`hardware_resource_name`, and `app_config.yaml`.
- **Build output:** `bazel-bin/<pkg>/<name>.bundle.tar`. To install manually, run `inctl asset install <tar> --address localhost:17080`, then `inctl service add <id> --name <instance> --address localhost:17080`, then `inctl world reset --address localhost:17080`.
