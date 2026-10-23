"""Image compression core. No GUI code here so it can be tested and scripted."""
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

try:
    import pillow_heif
    pillow_heif.register_heif_opener()  # adds HEIC/HEIF read + write
except ImportError:
    pass

Image.init()

# Output formats offered in the GUI: Pillow format name -> file extension.
OUTPUT_FORMATS = {
    "JPEG": ".jpg", "WEBP": ".webp", "AVIF": ".avif", "HEIF": ".heic",
    "PNG": ".png", "JPEG2000": ".jp2", "TIFF": ".tiff", "GIF": ".gif", "BMP": ".bmp",
}
OUTPUT_FORMATS = {f: e for f, e in OUTPUT_FORMATS.items() if f in Image.SAVE}
LOSSY = {"JPEG", "WEBP", "AVIF", "HEIF", "JPEG2000"}
ANIMATED = {"GIF", "WEBP", "PNG", "AVIF"}
EXIF_OK = {"JPEG", "WEBP", "PNG", "AVIF", "HEIF", "TIFF"}
NO_ALPHA = {"JPEG", "BMP"}

# Every extension Pillow (plus plugins) can open.
INPUT_EXTENSIONS = sorted(e for e, f in Image.registered_extensions().items() if f in Image.OPEN)


@dataclass
class Options:
    fmt: str = "KEEP"            # "KEEP" or a key of OUTPUT_FORMATS
    quality: int = 80            # 1-100
    lossless: bool = False
    max_width: int = 0           # 0 = no limit
    max_height: int = 0
    target_kb: int = 0           # 0 = off; lossy formats only, overrides quality
    strip_metadata: bool = True
    grayscale: bool = False
    skip_if_larger: bool = True  # keep original bytes when compression does not help
    suffix: str = "_compressed"
    out_dir: str = ""            # "" = next to source


@dataclass
class Result:
    src: Path
    dst: Path
    old_size: int
    new_size: int
    note: str = ""


def _prepare(frame, opts, fmt):
    frame = ImageOps.exif_transpose(frame)
    if opts.max_width or opts.max_height:
        frame.thumbnail((opts.max_width or 10**6, opts.max_height or 10**6), Image.LANCZOS)
    has_alpha = frame.mode in ("RGBA", "LA", "PA") or (frame.mode == "P" and "transparency" in frame.info)
    if opts.grayscale:
        frame = frame.convert("LA" if has_alpha and fmt not in NO_ALPHA else "L")
    elif has_alpha and fmt in NO_ALPHA:
        rgba = frame.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        frame = bg
    elif frame.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
        frame = frame.convert("RGBA" if has_alpha else "RGB")  # CMYK, I;16, F, etc.
    if fmt == "JPEG" and frame.mode not in ("RGB", "L"):
        frame = frame.convert("RGB")
    if fmt == "PNG" and not opts.lossless and opts.quality < 100:
        # Lossy PNG: reduce palette. quality 100 -> 256 colors, 1 -> 2 colors.
        colors = max(2, round(256 * opts.quality / 100))
        frame = frame.convert("RGBA" if frame.mode in ("RGBA", "LA", "PA", "P") else "RGB")
        frame = frame.quantize(colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
    return frame


def _save_kwargs(fmt, opts, quality, src_img):
    kw = {}
    if fmt == "JPEG":
        kw = dict(quality=quality, optimize=True, progressive=True, subsampling=0 if quality >= 90 else 2)
    elif fmt == "WEBP":
        kw = dict(quality=100 if opts.lossless else quality, lossless=opts.lossless, method=6)
    elif fmt == "AVIF":
        kw = dict(quality=100 if opts.lossless else quality, speed=4)
    elif fmt == "HEIF":
        kw = dict(quality=-1 if opts.lossless else quality)  # -1 = lossless in pillow-heif
    elif fmt == "JPEG2000":
        # quality maps to compression ratio: 100 -> 1:1 (lossless), 1 -> ~100:1
        kw = dict(irreversible=not opts.lossless, quality_mode="rates",
                  quality_layers=[1 if opts.lossless else max(1, 101 - quality)])
    elif fmt == "PNG":
        kw = dict(optimize=True, compress_level=9)
    elif fmt == "TIFF":
        kw = dict(compression="tiff_adobe_deflate")
    elif fmt == "GIF":
        kw = dict(optimize=True)
    if "icc_profile" in src_img.info and fmt != "GIF":
        kw["icc_profile"] = src_img.info["icc_profile"]  # keep colors correct even when stripping metadata
    if not opts.strip_metadata and fmt in EXIF_OK:
        exif = ImageOps.exif_transpose(src_img).getexif()  # orientation already applied to pixels
        if exif:
            kw["exif"] = exif.tobytes()
    return kw


def _encode(img, fmt, opts, quality):
    frames = [_prepare(f.copy(), opts, fmt) for f in ImageSequence.Iterator(img)] if fmt in ANIMATED else [_prepare(img, opts, fmt)]
    kw = _save_kwargs(fmt, opts, quality, img)
    if len(frames) > 1:
        kw.update(save_all=True, append_images=frames[1:], loop=img.info.get("loop", 0),
                  duration=img.info.get("duration", 100))
    buf = io.BytesIO()
    frames[0].save(buf, fmt, **kw)
    return buf.getvalue()


def compress(src, opts: Options) -> Result:
    src = Path(src)
    old_size = src.stat().st_size
    with Image.open(src) as img:
        src_fmt = img.format
        fmt = img.format if opts.fmt == "KEEP" else opts.fmt
        if fmt == "MPO":
            fmt = "JPEG"  # multi-picture JPEGs from phones/cameras
        if fmt not in OUTPUT_FORMATS:
            fmt = "PNG"  # source format we cannot write (PSD, ICNS, ...): fall back to lossless PNG
        note = ""
        if opts.target_kb and fmt in LOSSY and not opts.lossless:
            data, q = _search_quality(img, fmt, opts, opts.target_kb * 1024)
            note = f"q={q}" + ("" if len(data) <= opts.target_kb * 1024 else " (target not reached)")
        else:
            data = _encode(img, fmt, opts, opts.quality)

    ext = src.suffix if fmt == src_fmt else OUTPUT_FORMATS[fmt]
    out_dir = Path(opts.out_dir) if opts.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{src.stem}{opts.suffix}{ext}"
    if dst.resolve() == src.resolve():
        raise ValueError("output would overwrite the source; set a suffix or another output folder")

    if opts.skip_if_larger and len(data) >= old_size and dst.suffix.lower() == src.suffix.lower():
        data = src.read_bytes()
        note = "already optimal, original kept"
    dst.write_bytes(data)
    return Result(src, dst, old_size, len(data), note)


def _search_quality(img, fmt, opts, target):
    """Binary search the highest quality whose output fits in target bytes."""
    lo, hi, best = 1, 100, None
    while lo <= hi:
        q = (lo + hi) // 2
        data = _encode(img, fmt, opts, q)
        if len(data) <= target:
            best, lo = (data, q), q + 1
        else:
            hi = q - 1
    return best or (_encode(img, fmt, opts, 1), 1)
