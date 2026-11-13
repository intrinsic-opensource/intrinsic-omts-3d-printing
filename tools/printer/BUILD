load("@intrinsic-core//bazel:python.bzl", "py_binary", "py_library")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "printer_skills",
    srcs = ["printer_skills.py"],
    main = "printer_skills.py",
    deps = [
        "//services/prusalink:prusalink_py_pb2",
        "//skills/printer:job_model_py_pb2",
        "//skills/printer:read_printer_status_py_pb2",
        "@com_github_grpc_grpc//src/python/grpcio/grpc:grpcio",
        "@com_google_protobuf//:protobuf_python",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:behavior_tree",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:deployments",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:execution",
    ],
)

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
    name = "gcode_to_stl_lib",
    srcs = ["gcode_to_stl.py"],
)

py_binary(
    name = "gcode_to_stl",
    srcs = ["gcode_to_stl.py"],
    main = "gcode_to_stl.py",
)
