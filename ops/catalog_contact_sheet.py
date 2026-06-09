#!/usr/bin/env -S uv run --with pillow --python 3.13 python
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow"]
# ///
"""Composite many catalog PNGs into ONE labeled contact sheet.

Why: "look at these screens" should cost one Read, not N. Reading 6 phone PNGs
separately burns ~6x the image tokens; a single downscaled montage shows the
same thing for one. This is the machine-face way to *see* the gallery — query
review_manifest.json, composite, Read one image — no browser, no server.

Pure grid math (plan_grid / select_items) is stdlib so it stays testable in the
plain venv; Pillow is lazy-imported only for the actual pixel I/O.

Three zoom levels (overview -> detail -> magnify), one tool:
  overview   uv run ops/catalog_contact_sheet.py <root> --surface "Bookshelf View"
             uv run ops/catalog_contact_sheet.py <root> --feature Reader --appearance both --cols 4
  detail     uv run ops/catalog_contact_sheet.py <root> --id <assetID>            # one shot, large, light+dark
             uv run ops/catalog_contact_sheet.py <root> --ids id1,id2,id3         # free composition, in order
  magnify    uv run ops/catalog_contact_sheet.py <root> --surface "Podcast Player View" --zoom center
             uv run ops/catalog_contact_sheet.py <root> --id <assetID> --zoom 0.0,0.45,1.0,0.25
Prints the output PNG path (Read it).
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


def plan_grid(n, cols, cell_w, cell_h, label_h, gap, pad):
    """Canvas size + per-cell top-left positions for an n-item grid.

    cols is capped to n (never leave a wholly empty column). Each cell is a
    cell_w x cell_h image with a label_h strip beneath it; gap separates cells,
    pad frames the whole sheet. Returns (canvas_w, canvas_h, cols, rows, cells).
    """
    if n <= 0:
        return (pad * 2, pad * 2, 1, 0, [])
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    cell_total_h = cell_h + label_h
    canvas_w = pad * 2 + cols * cell_w + (cols - 1) * gap
    canvas_h = pad * 2 + rows * cell_total_h + (rows - 1) * gap
    cells = []
    for i in range(n):
        r, c = divmod(i, cols)
        x = pad + c * (cell_w + gap)
        y = pad + r * (cell_total_h + gap)
        cells.append((x, y))
    return canvas_w, canvas_h, cols, rows, cells


def select_items(manifest, *, surface=None, lane=None, facet=None, feature=None,
                 appearance="light", ids=None, limit=None):
    """Filter manifest items to montage.

    Without `ids`: ordered by surface then canonical state rank (so a surface's
    states read left-to-right in lifecycle order). With `ids` (explicit assetID
    list): selects exactly those, in the REQUESTED order — the free-composition
    path — still honouring the other filters (so `--ids ... --appearance light`
    drops the dark twins). Unknown ids are silently skipped."""
    def keep(it):
        if appearance and appearance != "both" and it["appearance"] != appearance:
            return False
        if surface and it["surface"] != surface:
            return False
        if lane and it["lane"] != lane:
            return False
        if facet and it["stateFacet"] != facet:
            return False
        if feature and it["feature"] != feature:
            return False
        return True

    sel = [it for it in manifest["items"] if keep(it)]
    if ids:
        by_id = {it.get("assetID"): it for it in sel}
        sel = [by_id[i] for i in ids if i in by_id]
    else:
        sel.sort(key=lambda it: (it["surface"], it.get("stateFacetRank", 0),
                                 it["stateLabel"], it["appearance"]))
    if limit is not None:
        sel = sel[:limit]
    return sel


def resolve_crop_box(width, height, region):
    """Resolve a zoom-region spec to an integer pixel box (left, top, right, bottom).

    region: None / "full" -> whole frame; presets top/bottom/left/right/center;
    or "x,y,w,h" as fractions (0..1) of the frame (e.g. "0.6,0.3,0.4,0.2" zooms a
    band). Boxes clamp to image bounds; a degenerate (zero-area) request falls
    back to the full frame rather than an empty crop. Pure math — no Pillow."""
    W, H = width, height
    presets = {
        None: (0.0, 0.0, 1.0, 1.0),
        "full": (0.0, 0.0, 1.0, 1.0),
        "top": (0.0, 0.0, 1.0, 0.5),
        "bottom": (0.0, 0.5, 1.0, 1.0),
        "left": (0.0, 0.0, 0.5, 1.0),
        "right": (0.5, 0.0, 1.0, 1.0),
        "center": (0.25, 0.25, 0.75, 0.75),
    }
    if region in presets:
        fx0, fy0, fx1, fy1 = presets[region]
    else:
        parts = [float(p) for p in str(region).split(",")]
        if len(parts) != 4:
            raise ValueError(f"bad zoom region: {region!r} (want preset or x,y,w,h)")
        x, y, w, h = parts
        fx0, fy0, fx1, fy1 = x, y, x + w, y + h
    left = max(0, min(W, round(fx0 * W)))
    top = max(0, min(H, round(fy0 * H)))
    right = max(0, min(W, round(fx1 * W)))
    bottom = max(0, min(H, round(fy1 * H)))
    if right <= left or bottom <= top:
        return (0, 0, W, H)
    return (left, top, right, bottom)


def _load_font(size):
    from PIL import ImageFont
    for path in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_contact_sheet(items, root, out_path, *, cols=3, cell_w=320,
                         label_h=44, gap=16, pad=24, bg=(245, 244, 240),
                         crop_region=None):
    """Decode each item's PNG, optionally crop to `crop_region` (zoom), resize to
    cell_w (true aspect), paste into a grid, draw a label strip
    (surface · state · facet · light/dark [· zoom]). One PNG out. When cell_w is
    larger than the (cropped) source, Pillow upscales it — that is the magnify."""
    from PIL import Image, ImageDraw

    root = Path(root)
    # Cell height from the FIRST real image's aspect (post-crop) so phones aren't
    # distorted and a zoom band gets its own correct aspect.
    sample = Image.open(root / items[0]["relPath"])
    if crop_region:
        sample = sample.crop(resolve_crop_box(sample.width, sample.height, crop_region))
    aspect = sample.height / sample.width
    cell_h = round(cell_w * aspect)
    sample.close()

    n = len(items)
    canvas_w, canvas_h, cols, rows, cells = plan_grid(
        n, cols, cell_w, cell_h, label_h, gap, pad)
    canvas = Image.new("RGB", (canvas_w, canvas_h), bg)
    draw = ImageDraw.Draw(canvas)
    font = _load_font(20)
    sub = _load_font(16)

    for it, (x, y) in zip(items, cells):
        img = Image.open(root / it["relPath"]).convert("RGBA")
        if crop_region:
            img = img.crop(resolve_crop_box(img.width, img.height, crop_region))
        thumb = img.resize((cell_w, cell_h), Image.LANCZOS)
        # white plate so transparent-margin components read on the warm bg
        plate = Image.new("RGB", (cell_w, cell_h), (255, 255, 255))
        plate.paste(thumb, (0, 0), thumb)
        canvas.paste(plate, (x, y))
        img.close()
        ty = y + cell_h + 4
        title = f"{it['surface']} · {it['stateLabel']}"
        meta = f"{it['stateFacet']} · {it['appearance']}"
        if crop_region:
            meta += f" · zoom:{crop_region}"
        draw.text((x + 2, ty), _clip(title, cell_w, draw, font),
                  fill=(40, 35, 30), font=font)
        draw.text((x + 2, ty + 22), _clip(meta, cell_w, draw, sub),
                  fill=(150, 140, 130), font=sub)

    out_path = Path(out_path)
    canvas.save(out_path)
    return {"out": str(out_path), "count": n, "cols": cols, "rows": rows,
            "width": canvas_w, "height": canvas_h}


def _clip(text, max_w, draw, font):
    if draw.textlength(text, font=font) <= max_w - 4:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w - 4:
        text = text[:-1]
    return text + "…"


def _resolve_manifest(root):
    root = Path(root)
    cand = root / "review_manifest.json" if root.is_dir() else root
    if not cand.exists():
        raise SystemExit(f"manifest not found: {cand}")
    return json.loads(cand.read_text()), (root if root.is_dir() else root.parent)


def main():
    ap = argparse.ArgumentParser(description="Composite catalog PNGs into one contact sheet.")
    ap.add_argument("root", type=Path, help="blessed artifact dir (or review_manifest.json)")
    ap.add_argument("--surface")
    ap.add_argument("--lane")
    ap.add_argument("--facet")
    ap.add_argument("--feature")
    ap.add_argument("--id", help="single shot by assetID (detail view)")
    ap.add_argument("--ids", help="comma-separated assetIDs — free composition, kept in this order")
    ap.add_argument("--zoom", metavar="REGION",
                    help="crop+magnify: full|top|bottom|left|right|center | x,y,w,h fractions")
    ap.add_argument("--appearance", default=None, choices=["light", "dark", "both"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--cell-width", type=int, default=None,
                    help="px per cell (auto: 320 overview, 760 detail/zoom)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    manifest, img_root = _resolve_manifest(args.root)
    ids = None
    if args.ids:
        ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    elif args.id:
        ids = [args.id]
    # detail/zoom -> default to both appearances + bigger cells unless overridden
    detail = bool(ids) or bool(args.zoom)
    appearance = args.appearance or ("both" if detail else "light")
    cell_w = args.cell_width or (760 if detail else 320)
    items = select_items(manifest, surface=args.surface, lane=args.lane,
                         facet=args.facet, feature=args.feature,
                         appearance=appearance, ids=ids, limit=args.limit)
    if not items:
        raise SystemExit("no items match the filter")
    out = args.out or Path(tempfile.gettempdir()) / "catalog_contact_sheet.png"
    info = render_contact_sheet(items, img_root, out, cols=args.cols,
                                cell_w=cell_w, crop_region=args.zoom)
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
    else:
        print(info["out"])
        print(f"{info['count']} shots · {info['cols']}x{info['rows']} grid · "
              f"{info['width']}x{info['height']}px")


if __name__ == "__main__":
    main()
