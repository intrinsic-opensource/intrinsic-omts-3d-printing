load("@intrinsic-core//bazel:python.bzl", "py_binary", "py_library")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "urdf_to_sdf_lib",
    srcs = ["urdf_to_sdf.py"],
    deps = [
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "urdf_to_sdf",
    srcs = ["urdf_to_sdf.py"],
    main = "urdf_to_sdf.py",
    deps = [
        ":urdf_to_sdf_lib",
    ],
)
