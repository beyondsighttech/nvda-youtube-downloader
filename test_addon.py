"""Self-contained tests for the NVDA YouTube Downloader add-on.

Runs with plain Python, no test framework needed:

    python test_addon.py

(Also works under pytest if you prefer.)
"""

import glob
import importlib.util
import os
import py_compile
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(BASE_DIR, "globalPlugins", "youtubeDownloader")

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS {name}")
    else:
        failures.append(f"{name} {detail}")
        print(f"FAIL {name} {detail}")


# 1. All sources compile.
for py in glob.glob(os.path.join(PLUGIN_DIR, "*.py")) + [
    os.path.join(BASE_DIR, "build_addon.py")
]:
    try:
        py_compile.compile(py, doraise=True)
        check(f"compile {os.path.basename(py)}", True)
    except py_compile.PyCompileError as e:
        check(f"compile {os.path.basename(py)}", False, str(e))

# 2. Load downloader.py standalone (its NVDA imports fall back to mocks).
spec = importlib.util.spec_from_file_location(
    "addon_downloader", os.path.join(PLUGIN_DIR, "downloader.py")
)
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)

# 3. Quality normalisation: new machine values and legacy 1.3.x labels.
q = downloader.normalise_quality_value
check("quality '320 kbps' -> 320", q("320 kbps") == "320")
check("quality '1080p' -> 1080", q("1080p") == "1080")
check("quality 'Best (Default)' -> best", q("Best (Default)") == "best")
check("quality 'Lossless (Default)' -> best", q("Lossless (Default)") == "best")
check("quality '320' -> 320", q("320") == "320")
check("quality '' -> best", q("") == "best")
check("quality None -> best", q(None) == "best")

# 4. Filename sanitisation strips Windows-invalid characters.
s = downloader.sanitize_filename
check(
    "sanitize invalid chars",
    s('a<b>c:"d/e\\f|g?h*i') == "a_b_c__d_e_f_g_h_i",
    s('a<b>c:"d/e\\f|g?h*i'),
)
check("sanitize dots/spaces", s("  .weird. ") == "weird")
check("sanitize empty", s("") == "Unknown")

# 5. Manifest satisfies add-on store rules.
sys.path.insert(0, BASE_DIR)
import build_addon

manifest = build_addon.parse_manifest(os.path.join(BASE_DIR, "manifest.ini"))
check(
    "manifest version format",
    bool(build_addon.VERSION_RE.match(manifest["version"])),
    manifest["version"],
)
check(
    "manifest name charset",
    bool(build_addon.NAME_RE.match(manifest["name"])),
    manifest["name"],
)
check("manifest url is https", manifest["url"].startswith("https://"))

# 6. No binaries can ever be packaged.
packaged = [arc.lower() for _, arc in build_addon.iter_addon_files()]
check("no .exe packaged", not any(a.endswith(".exe") for a in packaged), str(packaged))
check("no .dll packaged", not any(a.endswith(".dll") for a in packaged))
check("no .pyc packaged", not any(a.endswith(".pyc") for a in packaged))
check(
    "no bin/ dir packaged",
    not any("/bin/" in a or a.startswith("bin/") for a in packaged),
)

print()
if failures:
    print(f"{len(failures)} test(s) FAILED:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("All tests passed.")
