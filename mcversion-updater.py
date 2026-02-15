#!/usr/bin/env python3
# Auto Minecraft Update for Panilla
#
# This repo has two different "versions":
# - Mapping version (folder + Java package): v1_21_5  -> `paper-v1_21_5/` and `...paper.v1_21_5...`
# - MC/Paper artifact version (Gradle deps): 1.21.8  -> `io.papermc.paper:paper-api:1.21.8-R0.1-SNAPSHOT`
#
# This script clones the highest existing `paper-vX_Y_Z/` mapping module into a new mapping module,
# updates mapping references, updates Gradle Paper dependency versions to the chosen MC version,
# and wires the new module into `settings.gradle` + `bukkit/build.gradle`.

import os
import json
import re
import shutil
import urllib.request
import urllib.error


def _parse_version(v):
    v = (v or "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise ValueError("Invalid version '%s'. Expected format like 1.21.5" % v)
    return v


def _as_underscored(dotted):
    return dotted.replace(".", "_")


def _mapping_folder(dotted):
    return "paper-v%s" % _as_underscored(dotted)


def _mapping_pkg_segment(dotted):
    return "v%s" % _as_underscored(dotted)


def get_highest_mapping_folder(project_root):
    version_pattern = re.compile(r"^paper-v(\d+_\d+_\d+)$")
    versions = []

    for folder_name in os.listdir(project_root):
        match = version_pattern.match(folder_name)
        if match:
            versions.append((folder_name, match.group(1)))

    if not versions:
        raise ValueError("No `paper-vX_Y_Z` mapping folders found in %s." % project_root)

    highest = max(versions, key=lambda v: list(map(int, v[1].split("_"))))[0]
    return highest


def update_references_in_files(folder_path, old_mapping_dotted, new_mapping_dotted):
    replacements = [
        (old_mapping_dotted, new_mapping_dotted),
        (_as_underscored(old_mapping_dotted), _as_underscored(new_mapping_dotted)),
        (_mapping_pkg_segment(old_mapping_dotted), _mapping_pkg_segment(new_mapping_dotted)),
    ]

    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue

            new_content = content
            for old, new in replacements:
                new_content = new_content.replace(old, new)

            if new_content != content:
                with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_content)


def rename_java_mapping_package_dir(new_folder_path, old_mapping_dotted, new_mapping_dotted):
    java_root = os.path.join(new_folder_path, "src", "main", "java")
    if not os.path.isdir(java_root):
        return

    old_seg = _mapping_pkg_segment(old_mapping_dotted)
    new_seg = _mapping_pkg_segment(new_mapping_dotted)

    for root, dirs, _files in os.walk(java_root, topdown=False):
        for d in dirs:
            if d != old_seg:
                continue
            src = os.path.join(root, d)
            dst = os.path.join(root, new_seg)
            if os.path.exists(dst):
                continue
            os.rename(src, dst)


def update_paper_dependency_versions(build_gradle_path, mc_version_dotted):
    try:
        with open(build_gradle_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return

    # Handles:
    # '...:paper-api:1.21.8-R0.1-SNAPSHOT'
    # '...:paper-server:1.21.3-R0.1-SNAPSHOT:mojang-mapped'
    content2 = re.sub(
        r"(io\.papermc\.paper:paper-api:)\d+\.\d+\.\d+(-R0\.1-SNAPSHOT)",
        r"\g<1>%s\g<2>" % mc_version_dotted,
        content,
    )
    content2 = re.sub(
        r"(io\.papermc\.paper:paper-server:)\d+\.\d+\.\d+(-R0\.1-SNAPSHOT)",
        r"\g<1>%s\g<2>" % mc_version_dotted,
        content2,
    )

    if content2 != content:
        with open(build_gradle_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content2)


def _insert_after_line(lines, needle, new_line):
    for i, line in enumerate(lines):
        if needle in line:
            # Avoid double insert on reruns
            if i + 1 < len(lines) and lines[i + 1].strip() == new_line.strip():
                return True
            lines.insert(i + 1, new_line)
            return True
    return False


def update_settings_gradle(project_root, old_mapping_dotted, new_mapping_dotted):
    settings_gradle_path = os.path.join(project_root, "settings.gradle")
    with open(settings_gradle_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    old_pkg = _mapping_pkg_segment(old_mapping_dotted)
    new_pkg = _mapping_pkg_segment(new_mapping_dotted)

    old_include = "include(':panilla-paper-%s')" % old_pkg
    new_include = "include(':panilla-paper-%s')\n" % new_pkg

    old_map = "project(':panilla-paper-%s').projectDir = file('paper-%s')" % (old_pkg, old_pkg)
    new_map = "project(':panilla-paper-%s').projectDir = file('paper-%s')\n" % (new_pkg, new_pkg)

    ok1 = _insert_after_line(lines, old_include, new_include)
    ok2 = _insert_after_line(lines, old_map, new_map)

    if not ok1 or not ok2:
        raise ValueError("Could not update settings.gradle (missing expected lines for %s)" % old_pkg)

    with open(settings_gradle_path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def update_bukkit_build_gradle(project_root, old_mapping_dotted, new_mapping_dotted):
    path = os.path.join(project_root, "bukkit", "build.gradle")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    old_pkg = _mapping_pkg_segment(old_mapping_dotted)
    new_pkg = _mapping_pkg_segment(new_mapping_dotted)

    old_dep = "implementation project(':panilla-paper-%s')" % old_pkg
    new_dep = "    implementation project(':panilla-paper-%s')\n" % new_pkg

    ok = _insert_after_line(lines, old_dep, new_dep)
    if not ok:
        raise ValueError("Could not update bukkit/build.gradle (missing dependency for %s)" % old_pkg)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def update_panilla_plugin_init_version(project_root, old_mapping_dotted, new_mapping_dotted, mc_version_dotted, data_version):
    if data_version is None:
        return

    path = os.path.join(
        project_root,
        "bukkit",
        "src",
        "main",
        "java",
        "com",
        "ruinscraft",
        "panilla",
        "bukkit",
        "PanillaPlugin.java",
    )
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    init_idx = content.find("private void initVersion()")
    if init_idx == -1:
        raise ValueError("Could not find initVersion() in PanillaPlugin.java")

    old_pkg = _mapping_pkg_segment(old_mapping_dotted)
    new_pkg = _mapping_pkg_segment(new_mapping_dotted)
    old_pkg_ref = "com.ruinscraft.panilla.paper.%s" % old_pkg

    idx = content.find(old_pkg_ref, init_idx)
    if idx == -1:
        raise ValueError("Could not find mapping reference %s in PanillaPlugin.java" % old_pkg_ref)

    # Find the nearest "// Paper ..." comment above the mapping reference.
    comment_idx = content.rfind("// Paper", init_idx, idx)
    if comment_idx == -1:
        raise ValueError("Could not locate '// Paper ...' comment above %s" % old_pkg_ref)

    line_start = content.rfind("\n", 0, comment_idx) + 1

    # Find end of the block by scanning to first "return;" after the comment, then its closing brace.
    ret_idx = content.find("return;", comment_idx)
    if ret_idx == -1:
        raise ValueError("Could not locate return; inside the old Paper block")
    brace_idx = content.find("}", ret_idx)
    if brace_idx == -1:
        raise ValueError("Could not locate closing brace for the old Paper block")

    block_end = brace_idx + 1
    if block_end < len(content) and content[block_end] == "\n":
        block_end += 1

    old_block = content[line_start:block_end]

    new_block = old_block
    # Replace comment line to reflect the MC/Paper version (not mapping).
    new_block = re.sub(r"(\s*// Paper )[^\n]*", r"\g<1>%s" % mc_version_dotted, new_block)
    new_block = new_block.replace(old_pkg, new_pkg)
    new_block = re.sub(r"(getDataVersion\(\)\s*==\s*)\d+", r"\g<1>%d" % int(data_version), new_block)

    # Keep blocks separated for readability.
    if not new_block.endswith("\n\n"):
        if new_block.endswith("\n"):
            new_block += "\n"
        else:
            new_block += "\n\n"

    # Insert new block before the old one (newest first).
    updated = content[:line_start] + new_block + content[line_start:]
    if updated != content:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated)


def update_paper_module(project_root, new_mapping_dotted, mc_version_dotted, data_version):
    highest_folder = get_highest_mapping_folder(project_root)
    old_mapping_dotted = highest_folder.replace("paper-v", "").replace("_", ".")

    src_folder = os.path.join(project_root, highest_folder)
    new_folder_name = _mapping_folder(new_mapping_dotted)
    dst_folder = os.path.join(project_root, new_folder_name)

    if os.path.exists(dst_folder):
        print("The folder for the new mapping version %s already exists: %s" % (new_mapping_dotted, new_folder_name))
        return

    print("Base mapping folder: %s (mapping %s)" % (highest_folder, old_mapping_dotted))
    print("New mapping folder:  %s (mapping %s)" % (new_folder_name, new_mapping_dotted))
    print("MC/Paper version:    %s (Gradle deps)" % mc_version_dotted)
    if data_version is not None:
        print("Bukkit data version: %s (PanillaPlugin.java initVersion)" % data_version)

    shutil.copytree(src_folder, dst_folder)

    # Keep folder structure in sync with packages.
    rename_java_mapping_package_dir(dst_folder, old_mapping_dotted, new_mapping_dotted)

    # Rewrite mapping references (packages, strings, etc.) in the cloned module.
    update_references_in_files(dst_folder, old_mapping_dotted, new_mapping_dotted)

    # Update Gradle Paper deps to the chosen MC version.
    update_paper_dependency_versions(os.path.join(dst_folder, "build.gradle"), mc_version_dotted)

    # Wire it into Gradle + Bukkit module.
    update_settings_gradle(project_root, old_mapping_dotted, new_mapping_dotted)
    update_bukkit_build_gradle(project_root, old_mapping_dotted, new_mapping_dotted)

    # Optional: update plugin's version switch.
    update_panilla_plugin_init_version(project_root, old_mapping_dotted, new_mapping_dotted, mc_version_dotted, data_version)

    print("Done.")


def fetch_data_version_from_mojang(mc_version_dotted):
    """
    Attempts to resolve Mojang's DataVersion (world_version.version) for a given release like 1.21.8.
    This matches what Bukkit exposes via Bukkit.getUnsafe().getDataVersion().
    """
    manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
    try:
        with urllib.request.urlopen(manifest_url, timeout=10) as resp:
            manifest = json.load(resp)
    except Exception:
        return None

    version_info = None
    for v in manifest.get("versions", []):
        if v.get("id") == mc_version_dotted:
            version_info = v
            break
    if not version_info:
        return None

    url = version_info.get("url")
    if not url:
        return None

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            meta = json.load(resp)
    except Exception:
        return None

    wv = meta.get("world_version") or {}
    dv = wv.get("version")
    if isinstance(dv, int):
        return dv
    return None


if __name__ == "__main__":
    project_root = os.path.dirname(os.path.abspath(__file__))

    new_mapping = _parse_version(input("Enter the new mapping version (e.g., 1.21.6): "))
    mc_version = input("Enter the MC/Paper version for Gradle deps (blank = same): ").strip()
    mc_version = _parse_version(mc_version) if mc_version else new_mapping

    data_version_s = input("Enter Bukkit data version (blank = auto/skip): ").strip()
    data_version = int(data_version_s) if data_version_s else None
    if data_version is None:
        detected = fetch_data_version_from_mojang(mc_version)
        if detected is not None:
            print("Detected DataVersion for %s: %d" % (mc_version, detected))
            data_version = detected
        else:
            print("Could not auto-detect DataVersion for %s (no network or unknown version). Skipping PanillaPlugin.java update." % mc_version)

    update_paper_module(project_root, new_mapping, mc_version, data_version)
