load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

# Test cuboids for the graspability trials (research/tools/README.md),
# deployed with //:rebot_solution only under --//:test_cuboids.
# Generated: a box mesh (OBJ) and a box collision per size.

sdf_scene_object(
    name = "test_cuboid_40x40x22_sdf",
    src = "test_cuboid_40x40x22.sdf",
    sdf_assets = [
        "test_cuboid_40x40x22.mtl",
        "test_cuboid_40x40x22.obj",
    ],
)

intrinsic_scene_object(
    name = "test_cuboid_40x40x22",
    manifest = "test_cuboid_40x40x22_manifest.textproto",
    scene_object = ":test_cuboid_40x40x22_sdf",
)

sdf_scene_object(
    name = "test_cuboid_40x40x20_sdf",
    src = "test_cuboid_40x40x20.sdf",
    sdf_assets = [
        "test_cuboid_40x40x20.mtl",
        "test_cuboid_40x40x20.obj",
    ],
)

intrinsic_scene_object(
    name = "test_cuboid_40x40x20",
    manifest = "test_cuboid_40x40x20_manifest.textproto",
    scene_object = ":test_cuboid_40x40x20_sdf",
)

sdf_scene_object(
    name = "test_cuboid_80x20x40_sdf",
    src = "test_cuboid_80x20x40.sdf",
    sdf_assets = [
        "test_cuboid_80x20x40.mtl",
        "test_cuboid_80x20x40.obj",
    ],
)

intrinsic_scene_object(
    name = "test_cuboid_80x20x40",
    manifest = "test_cuboid_80x20x40_manifest.textproto",
    scene_object = ":test_cuboid_80x20x40_sdf",
)

sdf_scene_object(
    name = "test_cuboid_95x20x40_sdf",
    src = "test_cuboid_95x20x40.sdf",
    sdf_assets = [
        "test_cuboid_95x20x40.mtl",
        "test_cuboid_95x20x40.obj",
    ],
)

intrinsic_scene_object(
    name = "test_cuboid_95x20x40",
    manifest = "test_cuboid_95x20x40_manifest.textproto",
    scene_object = ":test_cuboid_95x20x40_sdf",
)

sdf_scene_object(
    name = "test_cuboid_40x40x40_sdf",
    src = "test_cuboid_40x40x40.sdf",
    sdf_assets = [
        "test_cuboid_40x40x40.mtl",
        "test_cuboid_40x40x40.obj",
    ],
)

intrinsic_scene_object(
    name = "test_cuboid_40x40x40",
    manifest = "test_cuboid_40x40x40_manifest.textproto",
    scene_object = ":test_cuboid_40x40x40_sdf",
)
