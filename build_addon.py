import os
import zipfile

def get_version_from_manifest(manifest_path):
    with open(manifest_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('version'):
                return line.split('=')[1].strip()
    return "0.0.0"

def create_addon_package():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    manifest_path = os.path.join(base_dir, "manifest.ini")
    version = get_version_from_manifest(manifest_path)
    
    output_filename = os.path.join(base_dir, f"youtubeDownloader-{version}.nvda-addon")
    
    # Files/Dirs to include
    includes = ['manifest.ini', 'globalPlugins', 'doc']
    
    print(f"Creating package: {output_filename}")
    
    # Binaries (yt-dlp.exe, ffmpeg.exe, ...) are downloaded at runtime by the
    # add-on itself, so they must never be bundled into the package.
    excluded_dirs = {'__pycache__', 'bin'}
    excluded_extensions = ('.pyc', '.exe', '.dll', '.zip')
    
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as addon_zip:
        for item in includes:
            item_path = os.path.join(base_dir, item)
            if os.path.isfile(item_path):
                addon_zip.write(item_path, item)
            elif os.path.isdir(item_path):
                for root, dirs, files in os.walk(item_path):
                    # Exclude unwanted directories (in-place so os.walk skips them)
                    dirs[:] = [d for d in dirs if d not in excluded_dirs]
                    
                    for file in files:
                        if file.endswith(excluded_extensions):
                            continue
                            
                        file_path = os.path.join(root, file)
                        # Archive name should be relative to base_dir
                        arcname = os.path.relpath(file_path, base_dir)
                        addon_zip.write(file_path, arcname)
                        
    print("Package created successfully!")

if __name__ == "__main__":
    create_addon_package()
