load("@intrinsic-core//bazel:python.bzl", "py_binary", "py_library")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "pick_and_place",
    srcs = ["pick_and_place.py"],
    data = ["//configs:all_configs"],
    main = "pick_and_place.py",
    deps = [
        "//src/core:config",
        "//src/hardware:gripper",
        "//src/hardware:robot",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:data_types",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:behavior_tree",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:deployments",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:worlds",
    ],
)

py_library(
    name = "control_door_lib",
    srcs = ["control_door.py"],
    deps = [
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:deployments",
    ],
)

py_binary(
    name = "control_door",
    srcs = ["control_door.py"],
    main = "control_door.py",
    deps = [
        ":control_door_lib",
    ],
)
