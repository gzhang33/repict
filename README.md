# repict

English| [中文](README_CN.md)

A simple and easy-to-use image format converter tool that supports WebP, HEIC, JPEG, and PNG output via CLI or Web UI.

![Web UI Preview](docs/assets/screenshots/preview-hero.png)

## Features

- 🖼️ Batch convert images to WebP, HEIC, JPEG, or PNG format
- 📦 Recursive directory scanning support
- 🎨 Customizable quality parameter (0-100)
- 🌐 Web UI interface with drag-and-drop upload
- 🔄 Cross-format conversion (e.g., PNG → WebP, JPEG → HEIC)
- 💾 Option to overwrite existing output files
- 🗑️ Option to delete original images after conversion
- 📊 Display conversion statistics and file size optimization

## Installation

### Method 1: Install from Source

```bash
# Clone the repository
git clone <repository-url>
cd repict

# Install dependencies
pip install -r requirements.txt

# Install package (optional, enables command-line tools)
pip install .
```

### Method 2: Direct Usage (No Installation Required)

Ensure dependencies are installed:

```bash
pip install Pillow Flask werkzeug
```

## Usage

### Command-Line Mode (CLI)

#### Basic Usage

```bash
# Convert all images in current directory
python main.py

# Convert images in specified directory
python main.py --dir ./images

# Set quality parameter (0-100, default: 80)
python main.py --dir ./images --quality 90

# Scan only current directory, no subdirectories
python main.py --dir ./images --no-recursive

# Overwrite existing WebP files
python main.py --dir ./images --overwrite

# Delete original images after conversion
python main.py --dir ./images --replace
```

#### Using Command-Line Tools After Installation

If installed via `pip install .`, you can use directly:

```bash
repict --dir ./images --quality 85
```

### Web UI Mode

#### Start Web Server

```bash
# Use default configuration (127.0.0.1:5000)
python main.py web

# Specify port
python main.py web --port 8080

# Specify output directory
python main.py web --output-dir ./output

# Specify host and port
python main.py web --host 0.0.0.0 --port 5000
```

#### Run Web Application Directly

```bash
python src/repict/web/app.py --port 5000
```

#### Using Web Tool After Installation

```bash
repict-web --port 5000
```

#### Web UI Features

- Drag-and-drop or click to upload multiple image files
- Set quality parameter (0-100)
- Specify output subdirectory
- Option to overwrite existing files
- Display conversion results and statistics

![Conversion Results](docs/assets/screenshots/preview-results.png)

Visit `http://localhost:5000` to use the Web UI.

## Command-Line Arguments

### CLI Mode Arguments

- `--dir DIR`: Target directory (default: current directory)
- `--quality QUALITY`: Output quality 0-100 (default: 80)
- `--no-recursive`: Do not scan subdirectories recursively
- `--overwrite`: Overwrite existing output files
- `--replace`: Delete original image files after conversion

### Web Mode Arguments

- `--host HOST`: Server host address (default: 127.0.0.1)
- `--port PORT`: Server port (default: 5000)
- `--output-dir OUTPUT_DIR`: Output directory (default: output)

## Project Structure

```
repict/
├── src/
│   └── repict/
│       ├── __init__.py
│       ├── core.py          # Core conversion logic
│       ├── cli.py           # Command-line tool
│       └── web/             # Web UI
│           ├── app.py       # Flask application
│           ├── static/      # Static resources
│           └── templates/  # HTML templates
├── docs/
│   └── assets/
│       └── screenshots/    # Project screenshots
├── main.py                  # Unified entry point
├── pyproject.toml           # Project configuration
├── requirements.txt        # Dependencies list
└── README.md              # Documentation
```

## Requirements

- Python >= 3.8
- Pillow >= 9.0.0
- Flask >= 2.0.0
- werkzeug >= 2.0.0

## Examples

### Batch Convert and Delete Originals

```bash
python main.py --dir ./photos --quality 85 --replace
```

### Start Web Server for LAN Access

```bash
python main.py web --host 0.0.0.0 --port 8080
```

### Conversion Output Example

```
Converted: photo1.jpg -> photo1.webp
Converted: photo2.png -> photo2.webp
Deleted original: photo1.jpg

Summary:
  Scanned files: 10
  Eligible images: 2
  Converted: 2
  Skipped (existing webp): 0
  Deleted originals: 2
  Failed: 0
  Total size before (converted): 5.23 MB
  Total size after  (webp):      3.45 MB
  Saved: 1.78 MB (34.05%)
```

## Contributing

Issues and Pull Requests are welcome!
