load("@com_google_protobuf//bazel:proto_library.bzl", "proto_library")
load("@com_google_protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@intrinsic-core//bazel:python.bzl", "py_library")
load("@intrinsic-core//intrinsic_sdk/intrinsic/skills/build_defs:skill.bzl", "py_skill", "skill_manifest")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "aruco_pose",
    srcs = ["aruco_pose.py"],
    deps = [
        "@ai_intrinsic_sdks_pip_deps//numpy",
        "@ai_intrinsic_sdks_pip_deps//opencv_python_headless",
    ],
)

proto_library(
    name = "detect_aruco_markers_proto",
    srcs = ["detect_aruco_markers.proto"],
    deps = ["@intrinsic_apis//intrinsic/math/proto:pose_proto"],
)

py_proto_library(
    name = "detect_aruco_markers_py_pb2",
    deps = [":detect_aruco_markers_proto"],
)

py_library(
    name = "aruco_skills",
    srcs = ["aruco_skills.py"],
    deps = [
        ":aruco_pose",
        ":detect_aruco_markers_py_pb2",
        "@ai_intrinsic_sdks_pip_deps//numpy",
        "@intrinsic-core//intrinsic_perception/intrinsic/perception/client/v1/python/camera:cameras",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:data_types",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:proto_conversion",
        "@intrinsic-core//intrinsic_sdk/intrinsic/skills/python:skill_interface",
        "@intrinsic_apis//intrinsic/skills/proto:footprint_py_pb2",
    ],
)

skill_manifest(
    name = "detect_aruco_markers_manifest",
    src = "detect_aruco_markers.manifest.textproto",
    incompatible_disallow_manifest_dependencies = False,
    deps = [":detect_aruco_markers_proto"],
)

py_skill(
    name = "detect_aruco_markers",
    base_image = "@distroless_python3",
    manifest = ":detect_aruco_markers_manifest",
    deps = [":aruco_skills"],
)
