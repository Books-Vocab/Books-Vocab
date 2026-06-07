#!/usr/bin/env -S uv run --with pillow python
"""Render KG promotional screenshots from framed device captures.

Two asset families exist:

* App Store screenshots:
  ``promotion/screenshots/sources/iphone-framed/01_*.png`` -> ``final_*.png``.
  This path reproduces the existing checked-in PNGs pixel-for-pixel.

* Public-site screenshots:
  compact 462x1000 PNGs used by ``backend/index.html``. The original script was
  not checked in; this renderer documents the intended composition from the
  same framed captures so future refreshes are repeatable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by operators.
    raise SystemExit(
        "Pillow is required. Run with: uv run --with pillow promotion/screenshots/scripts/render_screenshots.py"
    ) from exc


class PromoShot(NamedTuple):
    source_stem: str
    app_store_title: str
    app_store_subtitle: str
    web_name: str
    web_title: str
    web_subtitle: str


SHOTS: tuple[PromoShot, ...] = (
    PromoShot(
        "01_vocab_list",
        "你的單字，一目了然",
        "自動追蹤學習進度，掌握每個單字的熟練狀態",
        "iphone-vocab-list.png",
        "你的單字，一目了然",
        "自動追蹤學習進度，掌握每個單字的熟練狀態",
    ),
    PromoShot(
        "02_review_card",
        "在原文語境中複習",
        "釋義、發音、例句、關聯詞——一張卡片全掌握",
        "iphone-review-card.png",
        "在原文語境中複習",
        "釋義、發音、例句、關聯詞——一張卡片全掌握",
    ),
    PromoShot(
        "03_other",
        "單字不再孤立",
        "知識圖譜串起詞彙網絡，越讀越融會貫通",
        "iphone-knowledge-graph.png",
        "單字不再孤立",
        "知識圖譜串起詞彙網絡，越讀越融會貫通",
    ),
    PromoShot(
        "04_reader",
        "閱讀中即查即學",
        "輕觸生詞即時翻譯，閱讀不中斷、學習不費力",
        "iphone-reader.png",
        "閱讀中即查即學",
        "輕觸生詞即時翻譯，閱讀不中斷、學習不費力",
    ),
)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def iphone_source_dir(root: Path) -> Path:
    return root / "promotion/screenshots/sources/iphone-framed"


def app_store_output_dir(root: Path, *, target: str) -> Path:
    if target == "legacy":
        return root / "docs/assets/screenshots/iphone"
    return root / "promotion/screenshots/dist/app-store/iphone"


def web_output_dir(root: Path, *, target: str) -> Path:
    if target == "legacy":
        return root / "backend/static/img/screenshots"
    return root / "promotion/screenshots/dist/web"


def find_pingfang_ttc() -> Path:
    candidates = [
        Path(
            "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
            "86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc"
        ),
        Path(
            "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/"
            "3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc"
        ),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    roots = [
        Path("/System/Library/AssetsV2/com_apple_MobileAsset_Font8"),
        Path("/System/Library/AssetsV2/com_apple_MobileAsset_Font7"),
    ]
    for root in roots:
        if not root.exists():
            continue
        matches = sorted(root.glob("*/AssetData/PingFang.ttc"))
        if matches:
            return matches[0]

    raise FileNotFoundError("Could not locate PingFang.ttc under /System/Library/AssetsV2")


def font_paths() -> tuple[Path, Path]:
    title = Path.home() / "Library/Fonts/NotoSerifCJKtc-Bold.otf"
    if not title.exists():
        raise FileNotFoundError(f"Missing title font: {title}")
    return title, find_pingfang_ttc()


def draw_vertical_gradient(draw: ImageDraw.ImageDraw, width: int, height: int, delta: int = 18) -> None:
    for y in range(height):
        gray = int(255 - (y / height) * delta)
        draw.line([(0, y), (width, y)], fill=(gray, gray, gray, 255))


def centered_text(
    draw: ImageDraw.ImageDraw,
    width: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text(((width - text_width) // 2, y), text, font=font, fill=fill)
    return bbox


def render_app_store(root: Path | None = None, output_dir: Path | None = None, *, target: str = "promotion") -> list[Path]:
    root = root or repo_root_from_script()
    output_dir = output_dir or app_store_output_dir(root, target=target)
    output_dir.mkdir(parents=True, exist_ok=True)

    title_font_path, pingfang_path = font_paths()
    title_font = ImageFont.truetype(str(title_font_path), 92)
    subtitle_font = ImageFont.truetype(str(pingfang_path), 38, index=6)

    target_w, target_h = 1284, 2778
    frame_w = 1200
    written: list[Path] = []
    for shot in SHOTS:
        frame = Image.open(iphone_source_dir(root) / f"{shot.source_stem}.png").convert("RGBA")
        ratio = frame_w / frame.width
        new_h = int(frame.height * ratio)
        frame = frame.resize((frame_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw_vertical_gradient(draw, target_w, target_h)

        title_bbox = centered_text(draw, target_w, 150, shot.app_store_title, title_font, (20, 20, 20))
        title_h = title_bbox[3] - title_bbox[1]
        sub_y = 150 + title_h + 30
        centered_text(draw, target_w, sub_y, shot.app_store_subtitle, subtitle_font, (105, 105, 105))

        frame_x = (target_w - frame_w) // 2
        frame_y = sub_y + 100

        shadow_base = Image.new("RGBA", (target_w, target_h + 200), (0, 0, 0, 0))
        shadow_color = Image.new("RGBA", frame.size, (0, 0, 0, 60))
        shadow_color.putalpha(frame.split()[3])
        shadow_base.paste(shadow_color, (frame_x + 10, frame_y + 18))
        shadow_base = shadow_base.filter(ImageFilter.GaussianBlur(radius=35))
        canvas = Image.alpha_composite(canvas, shadow_base.crop((0, 0, target_w, target_h)))

        phone_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        paste_h = min(new_h, target_h - frame_y)
        if paste_h > 0:
            cropped_frame = frame.crop((0, 0, frame_w, paste_h))
            phone_layer.paste(cropped_frame, (frame_x, frame_y), cropped_frame)
        canvas = Image.alpha_composite(canvas, phone_layer)

        target = output_dir / f"final_{shot.source_stem}.png"
        canvas.convert("RGB").save(target, "PNG")
        written.append(target)
    return written


def render_web(root: Path | None = None, output_dir: Path | None = None, *, target: str = "promotion") -> list[Path]:
    root = root or repo_root_from_script()
    output_dir = output_dir or web_output_dir(root, target=target)
    output_dir.mkdir(parents=True, exist_ok=True)

    title_font_path, pingfang_path = font_paths()
    title_font = ImageFont.truetype(str(title_font_path), 34)
    subtitle_font = ImageFont.truetype(str(pingfang_path), 14, index=6)

    target_w, target_h = 462, 1000
    frame_w = 432
    frame_y = 134
    written: list[Path] = []
    for shot in SHOTS:
        frame = Image.open(iphone_source_dir(root) / f"{shot.source_stem}.png").convert("RGBA")
        frame_h = round(frame.height * frame_w / frame.width)
        frame = frame.resize((frame_w, frame_h), Image.Resampling.BILINEAR)

        canvas = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw_vertical_gradient(draw, target_w, target_h, delta=6)
        centered_text(draw, target_w, 61, shot.web_title, title_font, (20, 20, 20))
        centered_text(draw, target_w, 102, shot.web_subtitle, subtitle_font, (105, 105, 105))
        canvas.alpha_composite(frame, ((target_w - frame_w) // 2, frame_y))

        target = output_dir / shot.web_name
        canvas.convert("RGB").save(target, "PNG")
        written.append(target)
    return written


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["app-store", "web", "all"], default="all")
    parser.add_argument(
        "--target",
        choices=["promotion", "legacy"],
        default="promotion",
        help="promotion writes under promotion/screenshots/dist; legacy refreshes existing consumer paths",
    )
    parser.add_argument("--output-dir", type=Path, help="override output directory; only valid for one variant")
    return parser.parse_args(list(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = repo_root_from_script()
    if args.output_dir and args.variant == "all":
        raise SystemExit("--output-dir requires --variant app-store or --variant web")

    written: list[Path] = []
    if args.variant in {"app-store", "all"}:
        written.extend(
            render_app_store(
                root=root,
                output_dir=args.output_dir if args.variant == "app-store" else None,
                target=args.target,
            )
        )
    if args.variant in {"web", "all"}:
        written.extend(
            render_web(
                root=root,
                output_dir=args.output_dir if args.variant == "web" else None,
                target=args.target,
            )
        )

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
