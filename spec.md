# go-to-wheel Specification

A Python tool that compiles Go CLI programs for multiple architectures and bundles each as a Python wheel with executable entry points.

## Overview

`go-to-wheel` fills the gap identified in the Go/Python ecosystem: there's no equivalent to Rust's `maturin --bindings bin` for Go. This tool takes a Go module directory, cross-compiles it for multiple platforms, and produces properly-tagged Python wheels that can be installed via `pip` or `pipx` to get the Go binary on your PATH.

## Command Line Interface

### Basic Usage

```bash
go-to-wheel path/to/go-folder
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--name NAME` | Python package name | Directory basename |
| `--version VERSION` | Package version | `0.1.0` |
| `--output-dir DIR` | Directory for built wheels | `./dist` |
| `--entry-point NAME` | CLI command name | Same as package name |
| `--platforms PLATFORMS` | Comma-separated list of targets | See default platforms |
| `--go-binary PATH` | Path to Go binary | `go` (from PATH) |
| `--package-path PATH` | Path to the Go package to build | `.` (current directory) |
| `--description TEXT` | Package description | `"Go binary packaged as Python wheel"` |
| `--license LICENSE` | License identifier | None |
| `--author AUTHOR` | Author name | None |
| `--author-email EMAIL` | Author email | None |
| `--url URL` | Project URL | None |
| `--requires-python VERSION` | Python version requirement | `>=3.10` |

### Examples

```bash
# Basic: build wheels for 'mytool' from ./mytool directory
go-to-wheel ./mytool

# Custom package name
go-to-wheel ./mytool --name my-python-tool

# Specific version and output location
go-to-wheel ./mytool --version 1.2.3 --output-dir ./wheels

# Only build for specific platforms
go-to-wheel ./mytool --platforms linux-amd64,darwin-arm64

# Full metadata for PyPI publishing
go-to-wheel ./mytool \
  --name mytool-bin \
  --version 2.0.0 \
  --description "My awesome tool" \
  --license MIT \
  --author "Jane Doe" \
  --author-email "jane@example.com" \
  --url "https://github.com/jane/mytool"

# Build a sub-package (e.g., ./cmd/myapp)
go-to-wheel ./myproject \
  --name myapp \
  --version 1.0.0 \
  --package-path ./cmd/myapp \
  --entry-point myapp
```

## Target Platforms

### Default Platforms

The following platforms are built by default:

| GOOS | GOARCH | Wheel Platform Tag |
|------|--------|-------------------|
| `linux` | `amd64` | `manylinux_2_17_x86_64` |
| `linux` | `arm64` | `manylinux_2_17_aarch64` |
| `linux` | `amd64` | `musllinux_1_2_x86_64` |
| `linux` | `arm64` | `musllinux_1_2_aarch64` |
| `darwin` | `amd64` | `macosx_10_9_x86_64` |
| `darwin` | `arm64` | `macosx_11_0_arm64` |
| `windows` | `amd64` | `win_amd64` |
| `windows` | `arm64` | `win_arm64` |

### Platform Tag Mapping

Platform specification format: `{GOOS}-{GOARCH}[-{variant}]`

Examples:
- `linux-amd64` → `manylinux_2_17_x86_64`
- `linux-amd64-musl` → `musllinux_1_2_x86_64`
- `darwin-arm64` → `macosx_11_0_arm64`
- `darwin-universal2` → builds both amd64 and arm64, combines with `lipo`

## Wheel Structure

Each generated wheel follows PEP 427 format:

```
{package_name}-{version}-py3-none-{platform_tag}.whl
├── {package_name}/
│   ├── __init__.py
│   ├── __main__.py
│   └── bin/
│       └── {binary_name}[.exe]
├── {package_name}-{version}.dist-info/
│   ├── METADATA
│   ├── WHEEL
│   ├── RECORD
│   └── entry_points.txt
```

### Package Structure

#### `__init__.py`

```python
"""Go binary packaged as Python wheel."""

import os
import sys
import subprocess

__version__ = "{version}"

def get_binary_path():
    """Return the path to the bundled binary."""
    return os.path.join(os.path.dirname(__file__), "bin", "{binary_name}")

def main():
    """Execute the bundled binary."""
    binary = get_binary_path()
    if sys.platform == "win32":
        # On Windows, use subprocess to properly handle signals
        sys.exit(subprocess.call([binary] + sys.argv[1:]))
    else:
        # On Unix, exec replaces the process
        os.execvp(binary, [binary] + sys.argv[1:])
```

#### `__main__.py`

```python
from . import main
main()
```

#### `entry_points.txt`

```
[console_scripts]
{entry_point} = {package_name}:main
```

### Why Python Wrapper vs `.data/scripts`

The specification uses a Python wrapper (`console_scripts` entry point) rather than placing the binary directly in `.data/scripts/` because:

1. **Consistent behavior**: Works identically across all platforms
2. **Better error messages**: Can provide helpful messages if binary is missing or incompatible
3. **Future flexibility**: Can add Python-side features (version checking, update notifications, etc.)
4. **pipx compatibility**: Works seamlessly with `pipx install`

## Build Process

### Step 1: Validate Input

1. Verify the Go directory exists
2. Verify it contains a `go.mod` file (is a Go module)
3. Verify Go is installed and accessible
4. Parse package name from directory or `--name` option

### Step 2: Cross-Compile

For each target platform:

```bash
GOOS={goos} GOARCH={goarch} CGO_ENABLED=0 go build \
  -ldflags="-s -w" \
  -o {output_path} \
  {go_module_path}/{package_path}
```

Notes:
- `CGO_ENABLED=0` ensures static binaries (no libc dependency issues)
- `-ldflags="-s -w"` strips debug info and reduces binary size
- Windows builds automatically get `.exe` extension
- `package_path` specifies the package path to build (defaults to current directory `.`)

### Step 3: Build Wheels

For each compiled binary:

1. Create temporary directory structure
2. Copy binary to `{package_name}/bin/`
3. Generate `__init__.py` and `__main__.py`
4. Generate `METADATA`, `WHEEL`, and `entry_points.txt`
5. Calculate `RECORD` with SHA256 hashes
6. Zip into wheel with correct filename

### Step 4: Output

1. Move wheels to output directory
2. Print summary of built wheels
3. Return success/failure status

## Metadata Files

### METADATA (PEP 566)

```
Metadata-Version: 2.1
Name: {package_name}
Version: {version}
Summary: {description}
License: {license}
Author: {author}
Author-email: {author_email}
Home-page: {url}
Requires-Python: {requires_python}
```

### WHEEL (PEP 427)

```
Wheel-Version: 1.0
Generator: go-to-wheel {go_to_wheel_version}
Root-Is-Purelib: false
Tag: py3-none-{platform_tag}
```

### RECORD (PEP 376)

CSV file with columns: `path,hash,size`

```
{package_name}/__init__.py,sha256={hash},{size}
{package_name}/__main__.py,sha256={hash},{size}
{package_name}/bin/{binary},sha256={hash},{size}
{package_name}-{version}.dist-info/METADATA,sha256={hash},{size}
{package_name}-{version}.dist-info/WHEEL,sha256={hash},{size}
{package_name}-{version}.dist-info/entry_points.txt,sha256={hash},{size}
{package_name}-{version}.dist-info/RECORD,,
```

## Error Handling

| Error Condition | Behavior |
|-----------------|----------|
| Go not found | Exit with error, suggest installing Go |
| Not a Go module | Exit with error, explain `go.mod` requirement |
| Compilation fails for a platform | Log warning, continue with other platforms, exit non-zero at end |
| All compilations fail | Exit with error |
| Output directory not writable | Exit with error |
| Invalid package name | Exit with error, explain PEP 503 naming rules |

## Package Name Validation

Package names must be valid Python package names per PEP 503:
- Lowercase letters, digits, hyphens, underscores, periods
- Must start with a letter or digit
- Normalized: hyphens and underscores become hyphens for wheel filename

The import name (used for the Python package directory) follows PEP 8:
- Replace hyphens with underscores
- Example: `my-tool` becomes `my_tool/`

## Future Considerations

### Potential Future Features (Not in Initial Scope)

1. **Configuration file support**: `pyproject.toml` or `go-to-wheel.toml`
2. **Automatic version detection**: Parse from `VERSION` file, git tags, or Go code
3. **Multiple entry points**: For Go modules that build multiple binaries
4. **Universal2 macOS builds**: Combine arm64 and x86_64 into single binary
5. **Source distribution (sdist)**: That compiles on install
6. **PyPI publishing integration**: `go-to-wheel publish` command
7. **Build caching**: Skip unchanged platforms
8. **Custom ldflags**: For version embedding, etc.

## Dependencies

The tool itself requires:
- Python >= 3.10
- No external Python dependencies (uses stdlib only)

Build requirements:
- Go >= 1.16 (for `go mod` support)

## Installation

```bash
pip install go-to-wheel
# or
pipx install go-to-wheel
```

## Output Example

```
$ go-to-wheel ./myapp --name myapp-bin --version 1.0.0

go-to-wheel v0.1.0
Building myapp-bin v1.0.0 from ./myapp

Compiling for 8 platforms...
  ✓ linux/amd64 (12.3 MB)
  ✓ linux/arm64 (11.8 MB)
  ✓ linux/amd64 (musl) (12.1 MB)
  ✓ linux/arm64 (musl) (11.6 MB)
  ✓ darwin/amd64 (12.5 MB)
  ✓ darwin/arm64 (12.0 MB)
  ✓ windows/amd64 (12.7 MB)
  ✓ windows/arm64 (12.2 MB)

Building wheels...
  ✓ myapp_bin-1.0.0-py3-none-manylinux_2_17_x86_64.whl
  ✓ myapp_bin-1.0.0-py3-none-manylinux_2_17_aarch64.whl
  ✓ myapp_bin-1.0.0-py3-none-musllinux_1_2_x86_64.whl
  ✓ myapp_bin-1.0.0-py3-none-musllinux_1_2_aarch64.whl
  ✓ myapp_bin-1.0.0-py3-none-macosx_10_9_x86_64.whl
  ✓ myapp_bin-1.0.0-py3-none-macosx_11_0_arm64.whl
  ✓ myapp_bin-1.0.0-py3-none-win_amd64.whl
  ✓ myapp_bin-1.0.0-py3-none-win_arm64.whl

Done! Built 8 wheels in ./dist
```
