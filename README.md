# Image Compressor

Desktop GUI (Tkinter + Pillow) for batch image compression.

## Setup
```sh
brew install python-tk@3.14   # macOS: Tk for Homebrew Python
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

## Features
- Reads every format Pillow opens (JPEG, PNG, WEBP, AVIF, HEIC/HEIF, TIFF, GIF, BMP, JPEG2000, PSD, ICO, TGA, ...).
- Writes JPEG, WEBP, AVIF, HEIF, PNG, JPEG2000, TIFF, GIF, BMP, or keeps the source format.
- Quality slider, lossless mode, target file size (binary search on quality).
- Resize to max width/height, grayscale, strip EXIF/GPS (ICC color profile is always kept).
- Lossy PNG via palette quantization (quality maps to color count).
- Animated GIF/WEBP/PNG/AVIF stay animated.
- Keeps the original if compression would make it bigger.
- Batch files or whole folders (recursive), background thread with progress.
- Drag and drop files/folders onto the list (needs `tkinterdnd2`).
- Multi-select (Shift/Cmd-click, Cmd+A): compresses only the selection, or everything if nothing is selected. Delete/Backspace removes selected.

`python test_compressor.py` runs the self-check.
