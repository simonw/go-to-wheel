"""go-to-wheel: Compile Go CLI programs into Python wheels."""

import argparse
import base64
import csv
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

__version__ = "0.1.0"

# Platform mappings: (goos, goarch) -> wheel platform tag
PLATFORM_MAPPINGS: dict[str, tuple[str, str, str]] = {
    "linux-amd64": ("linux", "amd64", "manylinux_2_17_x86_64"),
    "linux-arm64": ("linux", "arm64", "manylinux_2_17_aarch64"),
    "linux-amd64-musl": ("linux", "amd64", "musllinux_1_2_x86_64"),
    "linux-arm64-musl": ("linux", "arm64", "musllinux_1_2_aarch64"),
    "darwin-amd64": ("darwin", "amd64", "macosx_10_9_x86_64"),
    "darwin-arm64": ("darwin", "arm64", "macosx_11_0_arm64"),
    "windows-amd64": ("windows", "amd64", "win_amd64"),
    "windows-arm64": ("windows", "arm64", "win_arm64"),
}

DEFAULT_PLATFORMS = [
    "linux-amd64",
    "linux-arm64",
    "linux-amd64-musl",
    "linux-arm64-musl",
    "darwin-amd64",
    "darwin-arm64",
    "windows-amd64",
    "windows-arm64",
]


def normalize_package_name(name: str) -> str:
    """Normalize package name for wheel filename (PEP 427)."""
    return name.replace("-", "_").replace(".", "_").lower()


def normalize_import_name(name: str) -> str:
    """Normalize package name for Python import (PEP 8)."""
    return name.replace("-", "_").replace(".", "_").lower()


def compute_file_hash(data: bytes) -> str:
    """Compute SHA256 hash in wheel RECORD format."""
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


def compile_go_binary(
    go_dir: str,
    output_path: str,
    goos: str,
    goarch: str,
    go_binary: str = "go",
    ldflags: str | None = None,
) -> None:
    """Cross-compile Go binary for target platform."""
    env = os.environ.copy()
    env["GOOS"] = goos
    env["GOARCH"] = goarch
    env["CGO_ENABLED"] = "0"

    ldflags_value = "-s -w"
    if ldflags:
        ldflags_value += " " + ldflags

    cmd = [
        go_binary,
        "build",
        f"-ldflags={ldflags_value}",
        "-o",
        output_path,
        ".",
    ]

    result = subprocess.run(
        cmd,
        cwd=go_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Go compilation failed for {goos}/{goarch}:\n{result.stderr}"
        )


def generate_init_py(version: str, binary_name: str) -> str:
    """Generate __init__.py content."""
    return f'''"""Go binary packaged as Python wheel."""

import os
import stat
import subprocess
import sys

__version__ = "{version}"


def get_binary_path():
    """Return the path to the bundled binary."""
    return os.path.join(os.path.dirname(__file__), "bin", "{binary_name}")


def main():
    """Execute the bundled binary."""
    binary = get_binary_path()

    # Ensure binary is executable on Unix
    if sys.platform != "win32":
        current_mode = os.stat(binary).st_mode
        if not (current_mode & stat.S_IXUSR):
            os.chmod(binary, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if sys.platform == "win32":
        # On Windows, use subprocess to properly handle signals
        sys.exit(subprocess.call([binary] + sys.argv[1:]))
    else:
        # On Unix, exec replaces the process
        os.execvp(binary, [binary] + sys.argv[1:])
'''


def generate_main_py() -> str:
    """Generate __main__.py content."""
    return '''from . import main
main()
'''


def generate_metadata(
    name: str,
    version: str,
    description: str = "Go binary packaged as Python wheel",
    requires_python: str = ">=3.10",
    author: str | None = None,
    author_email: str | None = None,
    license_: str | None = None,
    url: str | None = None,
    readme_content: str | None = None,
) -> str:
    """Generate METADATA file content."""
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
        f"Summary: {description}",
    ]

    if author:
        lines.append(f"Author: {author}")
    if author_email:
        lines.append(f"Author-email: {author_email}")
    if license_:
        lines.append(f"License: {license_}")
    if url:
        lines.append(f"Home-page: {url}")

    lines.append(f"Requires-Python: {requires_python}")

    if readme_content:
        lines.append("Description-Content-Type: text/markdown")
        # Add blank line before body, then the README content
        lines.append("")
        lines.append(readme_content)

    return "\n".join(lines) + "\n"


def generate_wheel_metadata(platform_tag: str) -> str:
    """Generate WHEEL file content."""
    return f"""Wheel-Version: 1.0
Generator: go-to-wheel {__version__}
Root-Is-Purelib: false
Tag: py3-none-{platform_tag}
"""


def generate_entry_points(entry_point: str, import_name: str) -> str:
    """Generate entry_points.txt content."""
    return f"""[console_scripts]
{entry_point} = {import_name}:main
"""


def generate_record(files: dict[str, bytes]) -> str:
    """Generate RECORD file content."""
    output = io.StringIO()
    writer = csv.writer(output)

    for path, content in files.items():
        if path.endswith("RECORD"):
            # RECORD itself has no hash
            writer.writerow([path, "", ""])
        else:
            hash_val = compute_file_hash(content)
            writer.writerow([path, hash_val, len(content)])

    return output.getvalue()


def build_wheel(
    binary_path: str,
    output_dir: str,
    name: str,
    version: str,
    platform_tag: str,
    entry_point: str,
    is_windows: bool = False,
    description: str = "Go binary packaged as Python wheel",
    requires_python: str = ">=3.10",
    author: str | None = None,
    author_email: str | None = None,
    license_: str | None = None,
    url: str | None = None,
    readme_content: str | None = None,
) -> str:
    """Build a wheel file from a compiled binary."""
    normalized_name = normalize_package_name(name)
    import_name = normalize_import_name(name)
    binary_name = entry_point + (".exe" if is_windows else "")

    # Read binary
    with open(binary_path, "rb") as f:
        binary_content = f.read()

    # Generate all files
    files: dict[str, bytes] = {}

    # Package files
    init_content = generate_init_py(version, binary_name).encode("utf-8")
    main_content = generate_main_py().encode("utf-8")

    files[f"{import_name}/__init__.py"] = init_content
    files[f"{import_name}/__main__.py"] = main_content
    files[f"{import_name}/bin/{binary_name}"] = binary_content

    # dist-info files
    dist_info = f"{normalized_name}-{version}.dist-info"

    metadata_content = generate_metadata(
        name,
        version,
        description=description,
        requires_python=requires_python,
        author=author,
        author_email=author_email,
        license_=license_,
        url=url,
        readme_content=readme_content,
    ).encode("utf-8")

    wheel_content = generate_wheel_metadata(platform_tag).encode("utf-8")
    entry_points_content = generate_entry_points(entry_point, import_name).encode(
        "utf-8"
    )

    files[f"{dist_info}/METADATA"] = metadata_content
    files[f"{dist_info}/WHEEL"] = wheel_content
    files[f"{dist_info}/entry_points.txt"] = entry_points_content

    # Generate RECORD (must be last as it includes all other files)
    record_path = f"{dist_info}/RECORD"
    files[record_path] = b""  # Placeholder
    record_content = generate_record(files).encode("utf-8")
    files[record_path] = record_content

    # Build wheel filename
    wheel_name = f"{normalized_name}-{version}-py3-none-{platform_tag}.whl"
    wheel_path = os.path.join(output_dir, wheel_name)

    # Create wheel zip file
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as whl:
        for file_path, content in files.items():
            # Set executable permission for binary
            if "/bin/" in file_path:
                info = zipfile.ZipInfo(file_path)
                # Set Unix permissions: rwxr-xr-x (0755)
                info.external_attr = (stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH) << 16
                whl.writestr(info, content)
            else:
                whl.writestr(file_path, content)

    return wheel_path


def build_wheels(
    go_dir: str,
    *,
    name: str | None = None,
    version: str = "0.1.0",
    output_dir: str = "./dist",
    entry_point: str | None = None,
    platforms: list[str] | None = None,
    go_binary: str = "go",
    description: str = "Go binary packaged as Python wheel",
    requires_python: str = ">=3.10",
    author: str | None = None,
    author_email: str | None = None,
    license_: str | None = None,
    url: str | None = None,
    readme: str | None = None,
    ldflags: str | None = None,
    set_version_var: str | None = None,
) -> list[str]:
    """
    Build Python wheels from a Go module.

    Args:
        go_dir: Path to Go module directory
        name: Python package name (defaults to directory basename)
        version: Package version
        output_dir: Directory to write wheels to
        entry_point: CLI command name (defaults to package name)
        platforms: List of target platforms (defaults to all supported)
        go_binary: Path to Go binary
        description: Package description
        requires_python: Python version requirement
        author: Author name
        author_email: Author email
        license_: License identifier
        url: Project URL
        readme: Path to README markdown file for PyPI long description
        ldflags: Additional Go linker flags (appended to default -s -w)
        set_version_var: Go variable to set to the package version via
            -X ldflag (e.g. "main.version")

    Returns:
        List of paths to built wheel files
    """
    go_path = Path(go_dir).resolve()

    # Validate Go directory
    if not go_path.exists():
        raise FileNotFoundError(f"Go directory not found: {go_dir}")

    if not (go_path / "go.mod").exists():
        raise ValueError(f"Not a Go module: {go_dir} (no go.mod file found)")

    # Read README file if provided
    readme_content: str | None = None
    if readme:
        readme_path = Path(readme)
        if not readme_path.exists():
            raise FileNotFoundError(f"README file not found: {readme}")
        readme_content = readme_path.read_text(encoding="utf-8")

    # Set defaults
    if name is None:
        name = go_path.name

    if entry_point is None:
        entry_point = name

    if platforms is None:
        platforms = DEFAULT_PLATFORMS

    # Build combined ldflags: set_version_var first, then user ldflags
    # (so explicit ldflags can override set_version_var if both set the same var)
    combined_ldflags_parts: list[str] = []
    if set_version_var:
        combined_ldflags_parts.append(f"-X {set_version_var}={version}")
    if ldflags:
        combined_ldflags_parts.append(ldflags)
    combined_ldflags = " ".join(combined_ldflags_parts) if combined_ldflags_parts else None

    # Create output directory
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Build wheels
    built_wheels: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        for platform_str in platforms:
            if platform_str not in PLATFORM_MAPPINGS:
                print(f"Warning: Unknown platform {platform_str}, skipping")
                continue

            goos, goarch, platform_tag = PLATFORM_MAPPINGS[platform_str]
            is_windows = goos == "windows"

            # Compile binary
            binary_ext = ".exe" if is_windows else ""
            binary_path = os.path.join(tmp_dir, f"{entry_point}_{platform_str}{binary_ext}")

            try:
                compile_go_binary(
                    str(go_path),
                    binary_path,
                    goos,
                    goarch,
                    go_binary,
                    ldflags=combined_ldflags,
                )
            except RuntimeError as e:
                print(f"Warning: {e}")
                continue

            # Build wheel
            wheel_path = build_wheel(
                binary_path,
                str(out_path),
                name,
                version,
                platform_tag,
                entry_point,
                is_windows=is_windows,
                description=description,
                requires_python=requires_python,
                author=author,
                author_email=author_email,
                license_=license_,
                url=url,
                readme_content=readme_content,
            )

            built_wheels.append(wheel_path)

    return built_wheels


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="go-to-wheel",
        description="Compile Go CLI programs into Python wheels",
    )

    parser.add_argument(
        "go_dir",
        help="Path to Go module directory",
    )
    parser.add_argument(
        "--name",
        help="Python package name (defaults to directory basename)",
    )
    parser.add_argument(
        "--version",
        default="0.1.0",
        help="Package version (default: 0.1.0)",
    )
    parser.add_argument(
        "--output-dir",
        default="./dist",
        help="Directory for built wheels (default: ./dist)",
    )
    parser.add_argument(
        "--entry-point",
        help="CLI command name (defaults to package name)",
    )
    parser.add_argument(
        "--platforms",
        help="Comma-separated list of target platforms",
    )
    parser.add_argument(
        "--go-binary",
        default="go",
        help="Path to Go binary (default: go)",
    )
    parser.add_argument(
        "--description",
        default="Go binary packaged as Python wheel",
        help="Package description",
    )
    parser.add_argument(
        "--requires-python",
        default=">=3.10",
        help="Python version requirement (default: >=3.10)",
    )
    parser.add_argument(
        "--author",
        help="Author name",
    )
    parser.add_argument(
        "--author-email",
        help="Author email",
    )
    parser.add_argument(
        "--license",
        dest="license_",
        help="License identifier",
    )
    parser.add_argument(
        "--url",
        help="Project URL",
    )
    parser.add_argument(
        "--readme",
        help="Path to README markdown file for PyPI long description",
    )
    parser.add_argument(
        "--ldflags",
        help="Additional Go linker flags appended to the default '-s -w' "
        "(e.g. '-X main.version=1.0.0')",
    )
    parser.add_argument(
        "--set-version-var",
        help="Go variable to set to the package version via -X ldflag "
        "(e.g. 'main.version'). The value is taken from --version automatically.",
    )

    args = parser.parse_args()

    # Parse platforms
    platforms = None
    if args.platforms:
        platforms = [p.strip() for p in args.platforms.split(",")]

    print(f"go-to-wheel v{__version__}")
    print(f"Building from {args.go_dir}")
    print()

    try:
        wheels = build_wheels(
            args.go_dir,
            name=args.name,
            version=args.version,
            output_dir=args.output_dir,
            entry_point=args.entry_point,
            platforms=platforms,
            go_binary=args.go_binary,
            description=args.description,
            requires_python=args.requires_python,
            author=args.author,
            author_email=args.author_email,
            license_=args.license_,
            url=args.url,
            readme=args.readme,
            ldflags=args.ldflags,
            set_version_var=args.set_version_var,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not wheels:
        print("Error: No wheels were built", file=sys.stderr)
        return 1

    print(f"Built {len(wheels)} wheel(s):")
    for wheel in wheels:
        print(f"  {wheel}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
