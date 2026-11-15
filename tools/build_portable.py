"""Build the portable Windows package: the bot, its own Python and every library, in one zip.

    python tools/build_portable.py [--version v1.1.0] [--test]

The result is build/Priestess-Bot-<version>-windows-x64.zip. Unzipped, it runs by double-clicking
启动普瑞赛斯.bat, with nothing else installed. Run this on Windows with a Python of the same
minor version as PYTHON_VERSION (it installs the libraries for the package, at the versions in
requirements.lock); the Python that goes into the package is downloaded from python.org.

Only files Git knows about (tracked, or new and not ignored) are packed, so .env, data/, logs/ and
your voice settings can't end up in the zip.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.14.7"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
# SHA-256 of that file, so a changed or damaged download stops the build.
EMBED_SHA256 = "d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15"  # from python.org's release page

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
NAME = "Priestess-Bot"  # the folder inside the zip: no version, so a new zip unpacks over the old one
# Not needed to run the bot. Dot-files and dot-folders are left out too, except .env.example.
SKIP_PREFIXES = ("tools/", "build/")
KEEP_DOT_FILES = (".env.example",)

# What the package's Python may import from, relative to runtime/. With this file Python ignores
# the registry, PYTHON* variables and the script's own folder, so the bot's folder ("..") is
# listed here, first, as it would be when running `python bot.py`.
PTH_LINES = ["..", "python{mm}.zip", ".", "Lib\\site-packages", "import site"]

SMOKE_TEST = """
import sys
import bot, tray, wizard, config
import davey, discord, imageio_ffmpeg, yt_dlp
assert sys.prefix.endswith("runtime"), sys.prefix
assert davey.__version__.startswith("0.1."), davey.__version__
print("python", sys.version.split()[0], "| discord.py", discord.__version__, "| davey", davey.__version__,
      "| yt-dlp", yt_dlp.version.__version__)
print("ffmpeg", config.ffmpeg_path())
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_python() -> Path:
    """The official embeddable Python, downloaded once into build/cache and checked every time."""
    cache = BUILD / "cache" / EMBED_URL.rsplit("/", 1)[1]
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {EMBED_URL}")
        partial = cache.with_name(cache.name + ".part")
        with urllib.request.urlopen(EMBED_URL, timeout=120) as response, open(partial, "wb") as f:
            shutil.copyfileobj(response, f)
        partial.replace(cache)
    found = sha256(cache)
    if found != EMBED_SHA256:
        sys.exit(f"{cache.name}: SHA-256 is {found}, expected {EMBED_SHA256 or '(not set)'}")
    return cache


def app_files() -> list[str]:
    """Paths (with /) of the files to ship: what Git tracks, plus new files it doesn't ignore."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return sorted(
        path
        for path in listed.split("\0")
        if path
        and not path.startswith(SKIP_PREFIXES)
        and (not path.startswith(".") or path in KEEP_DOT_FILES)
        and (ROOT / path).is_file()
    )


def build(version: str) -> Path:
    package = BUILD / NAME
    if package.exists():
        shutil.rmtree(package)
    runtime = package / "runtime"

    with zipfile.ZipFile(fetch_python()) as embed:
        embed.extractall(runtime)
    mm = "".join(PYTHON_VERSION.split(".")[:2])
    (runtime / f"python{mm}._pth").write_text("\n".join(PTH_LINES).format(mm=mm) + "\n", encoding="ascii")

    site_packages = runtime / "Lib" / "site-packages"
    print("Installing libraries from requirements.lock")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
            "--target", str(site_packages),
            "--no-compile",
            "-r", str(ROOT / "requirements.lock"),
            "pip",  # so yt-dlp can be updated later: runtime\\python -m pip install -U yt-dlp
        ],
        check=True,
    )  # fmt: skip
    shutil.rmtree(site_packages / "bin", ignore_errors=True)  # command-line launchers, tied to this path

    files = app_files()
    for path in files:
        target = package / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    print(f"Copied {len(files)} files of the bot")

    archive = BUILD / f"{NAME}-{version}-windows-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(p for p in package.rglob("*") if p.is_file()):
            z.write(path, f"{NAME}/{path.relative_to(package).as_posix()}")
    return archive


def smoke_test() -> None:
    """Import the bot with the package's own Python, from the package folder."""
    package = BUILD / NAME
    subprocess.run([str(package / "runtime" / "python.exe"), "-c", SMOKE_TEST], cwd=package, check=True)
    for leftover in package.rglob("__pycache__"):  # written by the test, after the zip was made
        shutil.rmtree(leftover, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--version", default="dev", help="goes into the zip's name, e.g. v1.1.0")
    parser.add_argument("--test", action="store_true", help="import the bot with the packaged Python afterwards")
    args = parser.parse_args()
    # pip picks the libraries' files for the Python it runs on (and zhconv has no ready-made
    # wheel, so it is built here), so this Python has to match the one that goes into the package.
    wanted = tuple(int(part) for part in PYTHON_VERSION.split(".")[:2])
    if sys.platform != "win32" or sys.maxsize < 2**32 or sys.version_info[:2] != wanted:
        sys.exit(f"Run this with 64-bit Python {wanted[0]}.{wanted[1]} on Windows (this is {sys.version.split()[0]}).")

    archive = build(args.version)
    if args.test:
        smoke_test()
    print(f"{archive.relative_to(ROOT)}  {archive.stat().st_size / 1e6:.0f} MB  sha256 {sha256(archive)}")


if __name__ == "__main__":
    main()
