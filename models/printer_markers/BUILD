load("@intrinsic-core//bazel:python.bzl", "py_binary")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "make_markers",
    srcs = ["make_markers.py"],
    main = "make_markers.py",
    deps = [
        "//src/core:door",
        "@ai_intrinsic_sdks_pip_deps//numpy",
        "@ai_intrinsic_sdks_pip_deps//opencv_python_headless",
    ],
)
