"""Build script for the NVDA YouTube Downloader add-on.

Creates a deterministic ``.nvda-addon`` package (zip) containing the add-on
source and documentation. Binaries (yt-dlp.exe, ffmpeg.exe, ffprobe.exe) are
downloaded at runtime by the add-on itself and are never bundled.

Usage:
    python build_addon.py                # build dist/youtubeDownloader-<version>.nvda-addon
    python build_addon.py --check        # validate manifest + packaging inputs only
    python build_addon.py --print-version  # print the manifest version (for CI)
"""

import argparse
import hashlib
import os
import re
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")

# Fixed timestamp for every zip entry so the same source always produces a
# byte-identical package (reproducible builds -> verifiable SHA-256).
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)

# Files/dirs that make up the add-on package.
INCLUDES = ["manifest.ini", "globalPlugins", "doc"]

# Binaries are fetched at runtime; they must never end up in the package.
EXCLUDED_DIRS = {"__pycache__", "bin"}
EXCLUDED_EXTENSIONS = (".pyc", ".exe", ".dll", ".zip")

# Add-on store validation rules (see nvaccess/addon-datastore submissionGuide).
REQUIRED_FIELDS = ("name", "summary", "author", "version", "docFileName")
VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def parse_manifest(manifest_path):
    """Parses manifest.ini into a dict (comments/blank lines skipped)."""
    fields = {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                raise SystemExit(f"manifest.ini: unparsable line: {raw_line!r}")
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def validate_manifest(manifest_path):
    """Validates the manifest against add-on store requirements. Exits non-zero on failure."""
    if not os.path.isfile(manifest_path):
        raise SystemExit(f"manifest.ini not found at {manifest_path}")

    fields = parse_manifest(manifest_path)
    errors = []

    for field in REQUIRED_FIELDS:
        if not fields.get(field):
            errors.append(f"missing required field: {field}")

    version = fields.get("version", "")
    if version and not VERSION_RE.match(version):
        errors.append(
            f"version {version!r} is not 'major.minor' or 'major.minor.patch' (store requirement)"
        )

    name = fields.get("name", "")
    if name and not NAME_RE.match(name):
        errors.append(
            f"name {name!r} must contain only letters, numbers, underscores and hyphens"
        )

    for url_field in ("url", "downloadURL", "updateURL"):
        value = fields.get(url_field)
        if value and not value.startswith("https://"):
            errors.append(f"{url_field} must start with https:// (got {value!r})")

    doc_file = fields.get("docFileName", "")
    doc_dir = os.path.join(BASE_DIR, "doc")
    doc_found = False
    if doc_file and os.path.isdir(doc_dir):
        doc_found = any(
            os.path.isfile(os.path.join(doc_dir, lang, doc_file))
            for lang in os.listdir(doc_dir)
        )
    if doc_file and not doc_found:
        errors.append(
            f"docFileName {doc_file!r} not found under doc/<lang>/ "
            "(NVDA resolves it per-language, e.g. doc/en/readme.html)"
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(f"manifest validation failed ({len(errors)} error(s))")

    print(f"Manifest OK: {name} {version} by {fields.get('author', '?')}")
    return fields


def iter_addon_files():
    """Yields (absolute_path, archive_name) for every file that belongs in the package."""
    for item in INCLUDES:
        item_path = os.path.join(BASE_DIR, item)
        if os.path.isfile(item_path):
            yield item_path, item
        elif os.path.isdir(item_path):
            for root, dirs, files in os.walk(item_path):
                # In-place so os.walk skips excluded dirs entirely.
                dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
                for file_name in sorted(files):
                    if file_name.endswith(EXCLUDED_EXTENSIONS):
                        continue
                    file_path = os.path.join(root, file_name)
                    yield file_path, os.path.relpath(file_path, BASE_DIR)


def build_addon_package():
    fields = validate_manifest(os.path.join(BASE_DIR, "manifest.ini"))
    version = fields["version"]

    os.makedirs(DIST_DIR, exist_ok=True)
    output_filename = os.path.join(DIST_DIR, f"youtubeDownloader-{version}.nvda-addon")

    print(f"Creating package: {output_filename}")
    # ZIP_STORED (no compression) so the output is byte-identical across
    # platforms: deflate streams differ between zlib builds, which would
    # break SHA-256 verification. The package is small plain text anyway.
    with zipfile.ZipFile(output_filename, "w", zipfile.ZIP_STORED) as addon_zip:
        for file_path, arcname in iter_addon_files():
            info = zipfile.ZipInfo(arcname, date_time=FIXED_ZIP_TIME)
            # 0o644 == rw-r--r-- : fixed permission bits for reproducibility.
            info.external_attr = 0o644 << 16
            with open(file_path, "rb") as src:
                addon_zip.writestr(info, src.read(), zipfile.ZIP_STORED)

    package_files = [arcname for _, arcname in iter_addon_files()]
    print(f"Packaged {len(package_files)} file(s):")
    for arcname in package_files:
        print(f"  {arcname}")

    checksum = sha256_of(output_filename)
    size_kb = os.path.getsize(output_filename) / 1024
    print(f"Package created successfully ({size_kb:.1f} KB)")
    print(f"SHA-256: {checksum}")
    return output_filename


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Build the NVDA add-on package.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the manifest and packaging inputs without building",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="print the version from manifest.ini and exit",
    )
    args = parser.parse_args()

    manifest_path = os.path.join(BASE_DIR, "manifest.ini")
    if args.print_version:
        fields = parse_manifest(manifest_path)
        print(fields.get("version", ""))
        return

    if args.check:
        validate_manifest(manifest_path)
        missing = [
            item
            for item in INCLUDES
            if not os.path.exists(os.path.join(BASE_DIR, item))
        ]
        if missing:
            raise SystemExit(f"packaging validation failed, missing includes: {missing}")
        print("Packaging validation OK.")
        return

    build_addon_package()


if __name__ == "__main__":
    main()
