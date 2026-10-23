load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

sdf_scene_object(
    name = "printer_scene_object",
    src = "3d_printer.sdf",
    sdf_assets = ["3d_printer.glb"],
)

intrinsic_scene_object(
    name = "printer",
    manifest = "printer_manifest.textproto",
    scene_object = ":printer_scene_object",
)
