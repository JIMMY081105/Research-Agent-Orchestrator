"""Build the native Windows app with the installed Framework compiler, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
INPUTS = ("native/SceneControl.cs", "native/SceneControl.manifest", "tools/build_desktop.py", "config/desktop-dependencies.json")

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def icon_bytes():
    size = 64
    pixels = bytearray()
    letters = ("01110", "10000", "10000", "01110", "00001", "00001", "11110"), ("01111", "10000", "10000", "10000", "10000", "10000", "01111")
    for y in reversed(range(size)):
        for x in range(size):
            bright = (5 <= x < 59 and y in (5, 6, 57, 58)) or (5 <= y < 59 and x in (5, 6, 57, 58))
            for number, glyph in enumerate(letters):
                gx, gy = x - (10 + number * 24), y - 18
                if 0 <= gx < 20 and 0 <= gy < 28 and glyph[gy // 4][gx // 4] == "1":
                    bright = True
            pixels.extend((230, 238, 108, 255) if bright else (20, 15, 9, 255))
    image = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels + bytes(size * size // 8)
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), 22) + image

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependencies", type=Path, required=True)
    args = parser.parse_args()
    if not COMPILER.is_file():
        raise SystemExit("FRAMEWORK_COMPILER_UNAVAILABLE")
    sys.path.insert(0, str(ROOT))
    from researchops.dashboard_bundle import safe_path
    safe_path(ROOT); dependency = safe_path(args.dependencies)
    config = json.loads((ROOT / INPUTS[-1]).read_text(encoding="utf-8-sig"))
    if set(config["files"]) != {"Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll"}:
        raise SystemExit("INVALID_DEPENDENCY_FILESET")
    for name, expected in config["files"].items():
        if digest(safe_path(dependency / name)) != expected:
            raise SystemExit("DEPENDENCY_CONTENT_CHANGED")
    inputs = {name: digest(safe_path(ROOT / name)) for name in INPUTS}
    folder = safe_path(Path(r"E:\Github\Building-Generation-Validation\.runtime\desktop\candidates") / str(uuid.uuid4()))
    app = folder / "app"; app.mkdir(parents=True, exist_ok=False)
    for name in config["files"]:
        shutil.copyfile(dependency / name, app / name)
    (app / "SceneControl.ico").write_bytes(icon_bytes())
    output = app / "SceneControl.exe"
    refs = [COMPILER.parent / (name + ".dll") for name in ("System", "System.Core", "System.Windows.Forms", "System.Drawing", "System.Web.Extensions", "System.Net.Http")]
    refs.extend(app / name for name in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"))
    command = [str(COMPILER), "/nologo", "/target:winexe", "/platform:x64", "/langversion:5", "/optimize+", "/debug-", "/warn:4",
               "/out:" + str(output), "/win32manifest:" + str(ROOT / INPUTS[1]), "/win32icon:" + str(app / "SceneControl.ico")]
    command += ["/reference:" + str(ref) for ref in refs] + [str(ROOT / INPUTS[0])]
    run = subprocess.run(command, capture_output=True, text=True, timeout=90, creationflags=0x08000000)
    (folder / "compiler.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    if run.returncode:
        print(run.stdout + run.stderr)
        raise SystemExit(run.returncode)
    if inputs != {name: digest(ROOT / name) for name in INPUTS}:
        raise SystemExit("BUILD_INPUT_CHANGED")
    binary = output.read_bytes(); pe = struct.unpack_from("<I", binary, 60)[0]
    if binary[:2] != b"MZ" or binary[pe:pe+4] != b"PE\0\0" or struct.unpack_from("<H", binary, pe+4)[0] != 0x8664 or struct.unpack_from("<H", binary, pe+24+68)[0] != 2:
        raise SystemExit("NATIVE_X64_WINDOWED_BINARY_REQUIRED")
    record = {"success": True, "source_inputs": inputs, "app_files": {p.name: digest(p) for p in sorted(app.iterdir())},
              "compiler": {"path": str(COMPILER), "sha256": digest(COMPILER), "version": "NET_FRAMEWORK_CSHARP5"},
              "package": config, "exit_code": run.returncode, "native_arch": "x64", "subsystem": "WINDOWS_GUI"}
    (folder / "build.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "app": str(app), "build": str(folder / "build.json"), "native_arch": "x64", "subsystem": "WINDOWS_GUI"}))

if __name__ == "__main__":
    main()
