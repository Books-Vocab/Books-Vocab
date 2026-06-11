#!/usr/bin/env -S uv run --with pillow --python 3.13 python
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow"]
# ///
"""Composite many UI PNGs into ONE labeled contact sheet.

Why: "look at these screens" should cost one Read, not N. Reading 6 phone PNGs
separately burns ~6x the image tokens; a single downscaled montage shows the
same thing for one. This is the machine-face way for an agent to *see* the
gallery — catalog snapshots, UITest step screenshots, or raw PNG files — no
browser, no server, one image artifact.

Pure grid math (plan_grid / select_items) is stdlib so it stays testable in the
plain venv; Pillow is lazy-imported only for the actual pixel I/O.

Three zoom levels (overview -> detail -> magnify), one tool:
  overview   uv run ops/catalog_contact_sheet.py <root> --surface "Bookshelf View"
             uv run ops/catalog_contact_sheet.py <root> --feature Reader --appearance both --cols 4
             uv run ops/catalog_contact_sheet.py /tmp/kg_ios_ui_steps.x --source uitest --take evenly:4
  detail     uv run ops/catalog_contact_sheet.py <root> --id <assetID>            # one shot, large, light+dark
             uv run ops/catalog_contact_sheet.py <root> --ids id1,id2,id3         # free composition, in order
  magnify    uv run ops/catalog_contact_sheet.py <root> --surface "Podcast Player View" --zoom center
             uv run ops/catalog_contact_sheet.py <root> --id <assetID> --zoom 0.0,0.45,1.0,0.25
Agentic visual review:
  quick 4    uv run ops/catalog_contact_sheet.py <ui-step-dir> --source uitest --take evenly:4 --manifest-out auto
  raw pngs   uv run ops/catalog_contact_sheet.py /tmp/screens --source images --contains player --take first,last

Prints the output PNG path (Read it). With --json, prints machine-readable
artifact metadata including selected items and an absolute image path.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

# Sheets this tool writes back into the scanned directory; never re-ingest
# them as input shots on a later pass over the same dir.
GENERATED_SHEET_NAMES = {"contact_sheet.png", "quick4_contact_sheet.png"}


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


class SourceBundle:
    def __init__(self, *, manifest, image_root, source_kind, manifest_path=None):
        self.manifest = manifest
        self.image_root = Path(image_root)
        self.source_kind = source_kind
        self.manifest_path = Path(manifest_path) if manifest_path else None


def select_items(manifest, *, surface=None, lane=None, facet=None, feature=None,
                 appearance="light", ids=None, contains=None, limit=None,
                 device=None):
    """Filter manifest items to montage.

    Without `ids`: ordered by surface then canonical state rank (so a surface's
    states read left-to-right in lifecycle order). With `ids` (explicit assetID
    list): selects exactly those, in the REQUESTED order — the free-composition
    path — still honouring the other filters (so `--ids ... --appearance light`
    drops the dark twins). Unknown ids are silently skipped.

    Multi-device manifests: `device` defaults to the canonical device
    (manifest `devices[0]`) so state rows don't interleave iPhone/iPad twins;
    pass a device name to montage another device, or "all" to disable the
    filter. Explicit `ids` skip the default (an assetID already pins one
    device's shot) but still honour an explicit `device`. Legacy manifests
    without `devices` are unaffected."""
    if device is None:
        if ids:
            device = "all"
        else:
            devices = manifest.get("devices") or []
            device = devices[0] if devices else None

    def keep(it):
        if device and device != "all" and it.get("device") != device:
            return False
        if appearance and appearance != "both" and it.get("appearance") != appearance:
            return False
        if surface and it.get("surface") != surface:
            return False
        if lane and it.get("lane") != lane:
            return False
        if facet and it.get("stateFacet") != facet:
            return False
        if feature and it.get("feature") != feature:
            return False
        if contains:
            haystack = " ".join(str(it.get(k, "")) for k in (
                "assetID", "surface", "lane", "stateFacet", "stateLabel",
                "feature", "appearance", "relPath",
            )).lower()
            if contains.lower() not in haystack:
                return False
        return True

    sel = [it for it in manifest["items"] if keep(it)]
    if ids:
        by_id = {it.get("assetID"): it for it in sel}
        sel = [by_id[i] for i in ids if i in by_id]
    else:
        sel.sort(key=lambda it: (it.get("surface", ""), it.get("stateFacetRank", 0),
                                 it.get("stateLabel", ""), it.get("appearance", "")))
    if limit is not None:
        sel = sel[:limit]
    return sel


def apply_take(items, take):
    """Select a compact journey from already-filtered items.

    Grammar:
      first,last          -> first and last item
      first,last,N        -> named picks + 1-based integer picks
      1,3,8              -> explicit 1-based positions
      evenly:4            -> four evenly-spaced steps, including endpoints
      every:2             -> every second item

    Unknown tokens are ignored deliberately: this is an agent convenience layer,
    not a brittle parser that should fail a whole visual review because one
    optional pick is absent.
    """
    if not take or not items:
        return items
    n = len(items)
    selected_indexes: list[int] = []

    def add(index):
        if 0 <= index < n and index not in selected_indexes:
            selected_indexes.append(index)

    for raw in str(take).split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token == "first":
            add(0)
        elif token == "last":
            add(n - 1)
        elif token in {"middle", "mid"}:
            add((n - 1) // 2)
        elif token.startswith("evenly:"):
            try:
                count = max(1, int(token.split(":", 1)[1]))
            except ValueError:
                continue
            span = min(count, n)
            if span <= 1:
                add(0)
            else:
                for i in range(span):
                    add(round(i * (n - 1) / (span - 1)))
        elif token.startswith("every:"):
            try:
                step = max(1, int(token.split(":", 1)[1]))
            except ValueError:
                continue
            for index in range(0, n, step):
                add(index)
        else:
            try:
                add(int(token) - 1)
            except ValueError:
                continue
    return [items[index] for index in selected_indexes]


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


def read_png_size(path: Path) -> tuple[int, int]:
    import struct

    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or len(header) < 24:
        return (0, 0)
    return struct.unpack(">II", header[16:24])


def render_contact_sheet(items, root, out_path, *, cols=3, cell_w=320,
                         label_h=44, gap=16, pad=24, bg=(245, 244, 240),
                         crop_region=None, cell_h=None):
    """Decode each item's PNG, optionally crop to `crop_region` (zoom), resize to
    cell_w (true aspect), paste into a grid, draw a label strip
    (surface · state · facet · light/dark [· zoom]). One PNG out. When cell_w is
    larger than the (cropped) source, Pillow upscales it — that is the magnify."""
    from PIL import Image, ImageDraw

    root = Path(root)
    # Cell height defaults from the FIRST real image's aspect (post-crop) so the
    # historic catalog path stays byte-compatible in spirit. Rendering itself
    # still preserves each image's aspect and letterboxes heterogeneous images.
    sample = Image.open(root / items[0]["relPath"])
    if crop_region:
        sample = sample.crop(resolve_crop_box(sample.width, sample.height, crop_region))
    aspect = sample.height / sample.width if sample.width else 1
    cell_h = cell_h or round(cell_w * aspect)
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
        ratio = min(cell_w / img.width, cell_h / img.height) if img.width and img.height else 1
        thumb_w = max(1, round(img.width * ratio))
        thumb_h = max(1, round(img.height * ratio))
        thumb = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        # white plate so transparent-margin components read on the warm bg
        plate = Image.new("RGB", (cell_w, cell_h), (255, 255, 255))
        paste_x = (cell_w - thumb_w) // 2
        paste_y = (cell_h - thumb_h) // 2
        plate.paste(thumb, (paste_x, paste_y), thumb)
        canvas.paste(plate, (x, y))
        img.close()
        ty = y + cell_h + 4
        title = f"{it.get('surface', 'UI')} · {it.get('stateLabel', it.get('assetID', 'shot'))}"
        meta = f"{it.get('stateFacet', 'state')} · {it.get('appearance', 'light')}"
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


def _ui_step_label(path: Path) -> tuple[int, str]:
    stem = path.stem
    head, sep, tail = stem.partition("-")
    if sep and head.isdigit():
        return int(head), tail
    return 1_000_000, stem


def build_ui_step_manifest(root: Path) -> dict:
    items = []
    paths = sorted(
        (p for p in root.glob("*.png") if p.name not in GENERATED_SHEET_NAMES),
        key=lambda p: (_ui_step_label(p)[0], p.name),
    )
    for fallback_rank, path in enumerate(paths, start=1):
        rank, label = _ui_step_label(path)
        if rank == 1_000_000:
            rank = fallback_rank
        items.append({
            "assetID": path.stem,
            "relPath": path.name,
            "surface": "UITest Step",
            "lane": "ui-test",
            "stateFacet": "step",
            "stateFacetRank": rank,
            "stateLabel": label,
            "feature": "UITest",
            "appearance": "light",
            "width": read_png_size(path)[0],
            "height": read_png_size(path)[1],
        })
    return {"schema": "kg.visual-review.manifest.v1", "source": "uitest", "items": items}


def build_images_manifest(paths: list[Path], root: Path | None = None) -> SourceBundle:
    if not paths:
        raise SystemExit("no PNG files found")
    if root is None:
        root = Path(os.path.commonpath([str(p) for p in paths]))
    root = Path(root)
    items = []
    for rank, path in enumerate(sorted(paths), start=1):
        rel = path.relative_to(root) if path.is_relative_to(root) else Path(path.name)
        label = path.stem
        width, height = read_png_size(path)
        items.append({
            "assetID": path.stem,
            "relPath": rel.as_posix(),
            "surface": path.parent.name or "Images",
            "lane": "images",
            "stateFacet": "image",
            "stateFacetRank": rank,
            "stateLabel": label,
            "feature": "Images",
            "appearance": "light",
            "width": width,
            "height": height,
        })
    return SourceBundle(
        manifest={"schema": "kg.visual-review.manifest.v1", "source": "images", "items": items},
        image_root=root,
        source_kind="images",
    )


def _resolve_source(root, source="auto"):
    root = Path(root)
    source = source or "auto"
    if source not in {"auto", "catalog", "uitest", "images"}:
        raise SystemExit(f"unknown source: {source}")

    if source in {"auto", "catalog"}:
        cand = root / "review_manifest.json" if root.is_dir() else root
        if cand.exists():
            return SourceBundle(
                manifest=json.loads(cand.read_text()),
                image_root=(root if root.is_dir() else root.parent),
                source_kind="catalog",
                manifest_path=cand,
            )
        if source == "catalog":
            raise SystemExit(f"manifest not found: {cand}")

    if source in {"auto", "uitest"} and root.is_dir():
        pngs = sorted(p for p in root.glob("*.png") if p.name not in GENERATED_SHEET_NAMES)
        if pngs:
            return SourceBundle(
                manifest=build_ui_step_manifest(root),
                image_root=root,
                source_kind="uitest",
            )
        if source == "uitest":
            raise SystemExit(f"no UITest step PNGs found in: {root}")

    if source in {"auto", "images"}:
        if root.is_file() and root.suffix.lower() == ".png":
            return build_images_manifest([root], root=root.parent)
        if root.is_dir():
            pngs = sorted(p for p in root.rglob("*.png") if p.name not in GENERATED_SHEET_NAMES)
            if pngs:
                return build_images_manifest(pngs, root=root)
        if source == "images":
            raise SystemExit(f"no PNG files found: {root}")

    raise SystemExit(f"could not resolve visual source: {root}")


def write_selected_manifest(path: Path, *, source: SourceBundle, out: Path, info: dict, items: list[dict]):
    payload = {
        "schema": "kg.visual-review.sheet.v1",
        "source": source.source_kind,
        "imageRoot": str(source.image_root),
        "inputManifest": str(source.manifest_path) if source.manifest_path else None,
        "contactSheet": str(out),
        "render": info,
        "items": items,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main():
    ap = argparse.ArgumentParser(description="Composite UI PNGs into one agent-friendly contact sheet.")
    ap.add_argument("root", type=Path, help="artifact dir, review_manifest.json, UITest step dir, or PNG dir")
    ap.add_argument("--source", default="auto", choices=["auto", "catalog", "uitest", "images"],
                    help="input adapter (default: auto-detect)")
    ap.add_argument("--surface")
    ap.add_argument("--lane")
    ap.add_argument("--facet")
    ap.add_argument("--feature")
    ap.add_argument("--contains", help="substring filter across labels, ids, relPath, feature, surface")
    ap.add_argument("--device", help='device dir name (e.g. "iPad Pro 11 landscape"); '
                    'default = canonical device (manifest devices[0]); "all" disables the filter')
    ap.add_argument("--id", help="single shot by assetID (detail view)")
    ap.add_argument("--ids", help="comma-separated assetIDs — free composition, kept in this order")
    ap.add_argument("--take", help="compact selection: evenly:4 | first,last | 1,3,8 | every:2")
    ap.add_argument("--zoom", metavar="REGION",
                    help="crop+magnify: full|top|bottom|left|right|center | x,y,w,h fractions")
    ap.add_argument("--appearance", default=None, choices=["light", "dark", "both"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--cell-width", type=int, default=None,
                    help="px per cell (auto: 320 overview, 760 detail/zoom)")
    ap.add_argument("--cell-height", type=int, default=None,
                    help="fixed px cell height; image is aspect-fit letterboxed")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--manifest-out", nargs="?", const="auto",
                    help="write selected visual-review manifest JSON (path or 'auto')")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    source = _resolve_source(args.root, args.source)
    manifest, img_root = source.manifest, source.image_root
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
                         appearance=appearance, ids=ids, contains=args.contains,
                         limit=args.limit, device=args.device)
    items = apply_take(items, args.take)
    if not items:
        raise SystemExit("no items match the filter")
    out = args.out or Path(tempfile.gettempdir()) / f"{source.source_kind}_contact_sheet.png"
    info = render_contact_sheet(items, img_root, out, cols=args.cols,
                                cell_w=cell_w, crop_region=args.zoom,
                                cell_h=args.cell_height)
    manifest_payload = None
    if args.manifest_out:
        manifest_path = (
            out.with_suffix(".visual_review.json")
            if args.manifest_out == "auto"
            else Path(args.manifest_out)
        )
        manifest_payload = write_selected_manifest(
            manifest_path, source=source, out=out, info=info, items=items
        )
    if args.json:
        payload = {
            **info,
            "source": source.source_kind,
            "imageRoot": str(img_root),
            "items": items,
        }
        if manifest_payload:
            payload["visualReviewManifest"] = str(manifest_path)
            payload["manifestPath"] = str(manifest_path)
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(info["out"])
        print(f"{info['count']} shots · {info['cols']}x{info['rows']} grid · "
              f"{info['width']}x{info['height']}px")
        if args.manifest_out:
            print(f"manifest={manifest_path}")


if __name__ == "__main__":
    main()
