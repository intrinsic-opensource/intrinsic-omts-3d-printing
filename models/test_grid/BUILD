load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

# A dense grid of small cubes for the graspability trials
# (research/tools/README.md), deployed with //:rebot_solution only under
# --//:test_parts. Generated: one mesh (OBJ) and a box collision per cube.

sdf_scene_object(
    name = "test_grid_sdf",
    src = "test_grid.sdf",
    sdf_assets = [
        "test_grid.mtl",
        "test_grid.obj",
    ],
)

intrinsic_scene_object(
    name = "test_grid",
    manifest = "test_grid_manifest.textproto",
    scene_object = ":test_grid_sdf",
)
