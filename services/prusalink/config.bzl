"""Builds the PrusaLink service config from Bazel flags (see //:printer_url)."""

load("@bazel_skylib//rules:common_settings.bzl", "BuildSettingInfo")

def _impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name + ".textproto")
    lines = [
        "# proto-file: google/protobuf/any.proto",
        "# proto-message: google.protobuf.Any",
        "",
        "[type.googleapis.com/omts.prusalink.PrusaLinkConfig] {",
        "  timeout_seconds: 5.0",
        "  enable_job_commands: %s" % (
            "true" if ctx.attr.job_commands[BuildSettingInfo].value else "false"
        ),
    ]
    unload = ctx.attr.unload_bed_max_c[BuildSettingInfo].value
    if unload:
        lines.append("  unload_bed_max_c: %s" % float(unload))
    for field, setting in (
        ("printer_url", ctx.attr.printer_url),
        ("username", ctx.attr.username),
        ("password", ctx.attr.password),
    ):
        value = setting[BuildSettingInfo].value
        if value:
            lines.append("  %s: %s" % (field, json.encode(value)))
    lines.append("}")
    ctx.actions.write(out, "\n".join(lines) + "\n")
    return DefaultInfo(files = depset([out]))

prusalink_config = rule(
    implementation = _impl,
    attrs = {
        "job_commands": attr.label(providers = [BuildSettingInfo]),
        "password": attr.label(providers = [BuildSettingInfo]),
        "printer_url": attr.label(providers = [BuildSettingInfo]),
        "unload_bed_max_c": attr.label(providers = [BuildSettingInfo]),
        "username": attr.label(providers = [BuildSettingInfo]),
    },
)
