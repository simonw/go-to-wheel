"""Tests for go-to-wheel."""

import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

from go_to_wheel import build_wheels

# Path to our test Go example
GO_EXAMPLE_DIR = Path(__file__).parent / "go-example"


def get_current_platform() -> str:
    """Get the platform string for the current system."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize machine names
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine

    if system == "linux":
        return f"linux-{arch}"
    elif system == "darwin":
        return f"darwin-{arch}"
    elif system == "windows":
        return f"windows-{arch}"
    else:
        return f"{system}-{arch}"


def get_wheel_platform_tag(platform_str: str) -> str:
    """Get the wheel platform tag for a platform string."""
    mappings = {
        "linux-amd64": "manylinux_2_17_x86_64",
        "linux-arm64": "manylinux_2_17_aarch64",
        "linux-amd64-musl": "musllinux_1_2_x86_64",
        "linux-arm64-musl": "musllinux_1_2_aarch64",
        "darwin-amd64": "macosx_10_9_x86_64",
        "darwin-arm64": "macosx_11_0_arm64",
        "windows-amd64": "win_amd64",
        "windows-arm64": "win_arm64",
    }
    return mappings.get(platform_str, platform_str)


class TestBuildWheels:
    """Tests for the build_wheels function."""

    def test_builds_correct_number_of_wheels_single_platform(self, tmp_path):
        """Test that building for a single platform produces one wheel."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        assert len(wheels) == 1
        assert all(Path(w).exists() for w in wheels)

    def test_builds_correct_number_of_wheels_multiple_platforms(self, tmp_path):
        """Test that building for multiple platforms produces correct number of wheels."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        platforms = ["linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64"]
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=platforms,
        )

        assert len(wheels) == 4
        assert all(Path(w).exists() for w in wheels)

    def test_wheel_filename_format(self, tmp_path):
        """Test that wheel filenames follow PEP 427 format."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        expected_tag = get_wheel_platform_tag(current_platform)

        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-test-tool",
            version="2.3.4",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        wheel_path = Path(wheels[0])
        # Wheel filename: {distribution}-{version}-{python}-{abi}-{platform}.whl
        expected_name = f"my_test_tool-2.3.4-py3-none-{expected_tag}.whl"
        assert wheel_path.name == expected_name

    def test_wheel_contains_required_files(self, tmp_path):
        """Test that the wheel contains all required files."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        with zipfile.ZipFile(wheels[0], "r") as whl:
            names = whl.namelist()

            # Check package files
            assert "go_example/__init__.py" in names
            assert "go_example/__main__.py" in names

            # Check binary exists (with or without .exe)
            binary_files = [n for n in names if n.startswith("go_example/bin/")]
            assert len(binary_files) == 1

            # Check dist-info files
            assert any("METADATA" in n for n in names)
            assert any("WHEEL" in n for n in names)
            assert any("RECORD" in n for n in names)
            assert any("entry_points.txt" in n for n in names)

    def test_wheel_metadata_content(self, tmp_path):
        """Test that METADATA file contains correct content."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-package",
            version="1.2.3",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        with zipfile.ZipFile(wheels[0], "r") as whl:
            metadata_file = [n for n in whl.namelist() if n.endswith("METADATA")][0]
            metadata = whl.read(metadata_file).decode("utf-8")

            assert "Name: my-package" in metadata
            assert "Version: 1.2.3" in metadata
            assert "Requires-Python: >=3.10" in metadata

    def test_wheel_entry_points(self, tmp_path):
        """Test that entry_points.txt contains correct content."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-tool",
            version="1.0.0",
            output_dir=str(output_dir),
            entry_point="mytool",
            platforms=[current_platform],
        )

        with zipfile.ZipFile(wheels[0], "r") as whl:
            ep_file = [n for n in whl.namelist() if n.endswith("entry_points.txt")][0]
            entry_points = whl.read(ep_file).decode("utf-8")

            assert "[console_scripts]" in entry_points
            assert "mytool = my_tool:main" in entry_points

    def test_default_name_from_directory(self, tmp_path):
        """Test that package name defaults to directory basename."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        # go-example directory should produce go_example package
        wheel_path = Path(wheels[0])
        assert "go_example-" in wheel_path.name or "go-example-" in wheel_path.name


class TestWheelExecution:
    """Tests for executing the built wheel."""

    def test_wheel_binary_executes(self, tmp_path):
        """Test that the binary in the wheel can be executed."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        wheel_path = wheels[0]

        # Use uv run to test the wheel
        result = subprocess.run(
            ["uv", "run", "--with", wheel_path, "go-example", "--version"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "go-example 1.0.0" in result.stdout

    def test_wheel_binary_with_arguments(self, tmp_path):
        """Test that arguments are passed correctly to the binary."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        wheel_path = wheels[0]

        result = subprocess.run(
            ["uv", "run", "--with", wheel_path, "go-example", "--echo", "hello", "world"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "hello world" in result.stdout

    def test_python_m_execution(self, tmp_path):
        """Test that python -m package_name works."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        wheel_path = wheels[0]

        # Create a temporary venv and install the wheel
        venv_dir = tmp_path / "venv"
        subprocess.run(["uv", "venv", str(venv_dir)], check=True)

        # Get the python path
        if sys.platform == "win32":
            python_path = venv_dir / "Scripts" / "python.exe"
        else:
            python_path = venv_dir / "bin" / "python"

        # Install the wheel
        subprocess.run(
            ["uv", "pip", "install", wheel_path, "--python", str(python_path)],
            check=True,
        )

        # Test python -m execution
        result = subprocess.run(
            [str(python_path), "-m", "go_example", "--version"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "go-example 1.0.0" in result.stdout

    def test_python_m_with_arguments(self, tmp_path):
        """Test that python -m passes arguments correctly."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="go-example",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        wheel_path = wheels[0]

        # Create a temporary venv and install the wheel
        venv_dir = tmp_path / "venv"
        subprocess.run(["uv", "venv", str(venv_dir)], check=True)

        if sys.platform == "win32":
            python_path = venv_dir / "Scripts" / "python.exe"
        else:
            python_path = venv_dir / "bin" / "python"

        subprocess.run(
            ["uv", "pip", "install", wheel_path, "--python", str(python_path)],
            check=True,
        )

        result = subprocess.run(
            [str(python_path), "-m", "go_example", "--echo", "test", "args"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "test args" in result.stdout


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_go_directory(self, tmp_path):
        """Test that invalid Go directory raises error."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        with pytest.raises(FileNotFoundError):
            build_wheels(
                str(tmp_path / "nonexistent"),
                name="test",
                output_dir=str(output_dir),
            )

    def test_directory_without_go_mod(self, tmp_path):
        """Test that directory without go.mod raises error."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        # Create empty directory
        go_dir = tmp_path / "empty"
        go_dir.mkdir()

        with pytest.raises(ValueError, match="go.mod"):
            build_wheels(
                str(go_dir),
                name="test",
                output_dir=str(output_dir),
            )


class TestPackageNaming:
    """Tests for package naming conventions."""

    def test_hyphen_to_underscore_in_import_name(self, tmp_path):
        """Test that hyphens are converted to underscores in import name."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-cool-tool",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        with zipfile.ZipFile(wheels[0], "r") as whl:
            names = whl.namelist()
            # Import name should use underscores
            assert any("my_cool_tool/__init__.py" in n for n in names)

    def test_wheel_filename_uses_underscores(self, tmp_path):
        """Test that wheel filename uses underscores per PEP 427."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-cool-tool",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        wheel_path = Path(wheels[0])
        # PEP 427: Replace hyphens with underscores in wheel filename
        assert "my_cool_tool-" in wheel_path.name


class TestReadmeOption:
    """Tests for the --readme option."""

    def test_readme_in_metadata(self, tmp_path):
        """Test that README content appears in METADATA as long description."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        # Create a README file
        readme_path = tmp_path / "README.md"
        readme_content = "# My Tool\n\nThis is a great tool.\n\n## Features\n\n- Fast\n- Simple"
        readme_path.write_text(readme_content)

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-tool",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
            readme=str(readme_path),
        )

        with zipfile.ZipFile(wheels[0], "r") as whl:
            metadata_file = [n for n in whl.namelist() if n.endswith("METADATA")][0]
            metadata = whl.read(metadata_file).decode("utf-8")

            # Should have content type header
            assert "Description-Content-Type: text/markdown" in metadata
            # Should have the README content as the body
            assert "# My Tool" in metadata
            assert "This is a great tool." in metadata
            assert "## Features" in metadata

    def test_readme_file_not_found(self, tmp_path):
        """Test that non-existent README file raises error."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        with pytest.raises(FileNotFoundError, match="README"):
            build_wheels(
                str(GO_EXAMPLE_DIR),
                name="my-tool",
                version="1.0.0",
                output_dir=str(output_dir),
                platforms=[current_platform],
                readme=str(tmp_path / "nonexistent.md"),
            )

    def test_metadata_without_readme(self, tmp_path):
        """Test that METADATA without README has no long description."""
        output_dir = tmp_path / "dist"
        output_dir.mkdir()

        current_platform = get_current_platform()
        wheels = build_wheels(
            str(GO_EXAMPLE_DIR),
            name="my-tool",
            version="1.0.0",
            output_dir=str(output_dir),
            platforms=[current_platform],
        )

        with zipfile.ZipFile(wheels[0], "r") as whl:
            metadata_file = [n for n in whl.namelist() if n.endswith("METADATA")][0]
            metadata = whl.read(metadata_file).decode("utf-8")

            # Should not have content type header when no README
            assert "Description-Content-Type:" not in metadata
