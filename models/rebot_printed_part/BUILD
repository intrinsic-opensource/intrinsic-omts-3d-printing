load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

sdf_scene_object(
    name = "rebot_printed_part_scene_object",
    src = "rebot_printed_part.sdf",
    sdf_assets = ["printed_part_visual.glb"],
)

intrinsic_scene_object(
    name = "rebot_printed_part",
    manifest = "rebot_printed_part_manifest.textproto",
    scene_object = ":rebot_printed_part_scene_object",
)
