"""Self-check: python test_compressor.py"""
import tempfile
from pathlib import Path

from PIL import Image

from compressor import OUTPUT_FORMATS, Options, compress

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    src = d / "photo.png"
    img = Image.radial_gradient("L").resize((800, 600)).convert("RGB")
    img.putalpha(200)
    img.save(src)
    out = d / "out"

    for fmt in ["KEEP", *OUTPUT_FORMATS]:
        r = compress(src, Options(fmt=fmt, quality=60, max_width=400, out_dir=str(out), skip_if_larger=False))
        with Image.open(r.dst) as o:
            assert o.width == 400, (fmt, o.size)
        print(f"{fmt:9} {r.old_size:>8} -> {r.new_size:>8} {r.dst.name}")

    r = compress(src, Options(fmt="JPEG", target_kb=5, out_dir=str(out)))
    assert r.new_size <= 5 * 1024 or "not reached" in r.note, r
    print("target:", r.new_size, r.note)

    gif = d / "anim.gif"
    frames = [Image.new("RGB", (64, 64), (i * 60, 0, 255 - i * 60)) for i in range(4)]
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=80)
    r = compress(gif, Options(fmt="WEBP", out_dir=str(out)))
    assert Image.open(gif).n_frames == 4 and Image.open(r.dst).n_frames == 4

    try:
        compress(src, Options(suffix=""))
        raise AssertionError("overwrote source")
    except ValueError:
        pass
print("ok")
