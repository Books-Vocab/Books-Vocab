#!/usr/bin/env -S uv run --with pillow python
"""Render KG promotional screenshots from framed device captures.

Two output families exist (App Store 1284x2778, public-site compact 462x1000).
Both compose a framed device capture onto a titled canvas via
``fit_frame_into_canvas``, which scales the frame to sit *fully* inside the
canvas — the bottom rounded corner / home indicator / titanium edge stays
visible (an earlier version cropped the frame at the canvas edge, leaving a
flat black bar on dark screenshots).

The framed source + copy are supplied dynamically by the capture_profile
pipeline (``--source-dir`` / ``--shots-json``); the built-in ``SHOTS`` +
``sources/iphone-framed`` path is a static fallback for standalone runs and
engine tests. The live marketing screenshots (``backend/static/img/screenshots``
and the App Store bundle) are produced by that dynamic pipeline, not by the
static ``SHOTS`` path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by operators.
    raise SystemExit(
        "Pillow is required. Run with: uv run --with pillow promotion/screenshots/scripts/render_screenshots.py"
    ) from exc


class PromoShot(NamedTuple):
    source_stem: str
    app_store_output: str
    app_store_title: str
    app_store_subtitle: str
    web_name: str
    web_title: str
    web_subtitle: str


SHOTS: tuple[PromoShot, ...] = (
    PromoShot(
        "01_vocab_list",
        "final_01_vocab_list.png",
        "你的單字，一目了然",
        "自動追蹤學習進度，掌握每個單字的熟練狀態",
        "iphone-vocab-list.png",
        "你的單字，一目了然",
        "自動追蹤學習進度，掌握每個單字的熟練狀態",
    ),
    PromoShot(
        "02_review_card",
        "final_02_review_card.png",
        "在原文語境中複習",
        "釋義、發音、例句、關聯詞——一張卡片全掌握",
        "iphone-review-card.png",
        "在原文語境中複習",
        "釋義、發音、例句、關聯詞——一張卡片全掌握",
    ),
    PromoShot(
        "03_other",
        "final_03_other.png",
        "單字不再孤立",
        "知識圖譜串起詞彙網絡，越讀越融會貫通",
        "iphone-knowledge-graph.png",
        "單字不再孤立",
        "知識圖譜串起詞彙網絡，越讀越融會貫通",
    ),
    PromoShot(
        "04_reader",
        "final_04_reader.png",
        "閱讀中即查即學",
        "輕觸生詞即時翻譯，閱讀不中斷、學習不費力",
        "iphone-reader.png",
        "閱讀中即查即學",
        "輕觸生詞即時翻譯，閱讀不中斷、學習不費力",
    ),
)


def load_shots_manifest(path: Path) -> list[PromoShot]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit("shots json 必須是 array")
    shots: list[PromoShot] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(f"shots[{index}] 必須是 object")
        copy = item.get("copy")
        if not isinstance(copy, dict):
            raise SystemExit(f"shots[{index}].copy 必須是 object")
        source_stem = item.get("sourceStem")
        output_name = item.get("outputName")
        title = copy.get("title")
        subtitle = copy.get("subtitle")
        if not all(isinstance(value, str) and value.strip() for value in (source_stem, output_name, title, subtitle)):
            raise SystemExit(f"shots[{index}] 缺 sourceStem/outputName/copy.title/copy.subtitle")
        shots.append(
            PromoShot(
                source_stem=source_stem.strip(),
                app_store_output=output_name.strip(),
                app_store_title=title.strip(),
                app_store_subtitle=subtitle.strip(),
                web_name=output_name.replace("final_", "iphone-"),
                web_title=title.strip(),
                web_subtitle=subtitle.strip(),
            )
        )
    return shots


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


def fit_frame_into_canvas(
    raw_w: int,
    raw_h: int,
    *,
    target_h: int,
    frame_y: int,
    bottom_margin: int,
    design_w: int,
) -> tuple[int, int]:
    """算出讓 device frame 【完整】放進畫布的 (frame_w, frame_h)——底部圓角/home
    indicator/黑鈦下邊框不被畫布邊界硬切。

    先以 design_w 為基準寬度等比縮放；若這樣 frame 底部會超出可用高度
    (target_h - frame_y - bottom_margin)，改以可用高度反算寬度，保證
    frame_y + frame_h <= target_h - bottom_margin。歷史 bug：render_web 固定
    frame_w=432 貼 y=134，frame 高 897 > 畫布 1000-134，底部 31px 被切成一條
    平黑邊（深色截圖上尤其明顯）。此函式消除該硬切。
    """
    avail_h = target_h - frame_y - bottom_margin
    scaled_h = round(raw_h * design_w / raw_w)
    if scaled_h <= avail_h:
        return design_w, scaled_h
    frame_h = avail_h
    frame_w = round(raw_w * frame_h / raw_h)
    return frame_w, frame_h


def render_app_store(
    root: Path | None = None,
    output_dir: Path | None = None,
    *,
    target: str = "promotion",
    source_dir: Path | None = None,
    shots: Sequence[PromoShot] | None = None,
) -> list[Path]:
    root = root or repo_root_from_script()
    output_dir = output_dir or app_store_output_dir(root, target=target)
    source_dir = source_dir or iphone_source_dir(root)
    shots = tuple(shots or SHOTS)
    output_dir.mkdir(parents=True, exist_ok=True)

    title_font_path, pingfang_path = font_paths()
    title_font = ImageFont.truetype(str(title_font_path), 92)
    subtitle_font = ImageFont.truetype(str(pingfang_path), 38, index=6)

    target_w, target_h = 1284, 2778
    design_frame_w = 1200
    written: list[Path] = []
    for shot in shots:
        raw = Image.open(source_dir / f"{shot.source_stem}.png").convert("RGBA")

        canvas = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        draw_vertical_gradient(draw, target_w, target_h)

        title_bbox = centered_text(draw, target_w, 150, shot.app_store_title, title_font, (20, 20, 20))
        title_h = title_bbox[3] - title_bbox[1]
        sub_y = 150 + title_h + 30
        centered_text(draw, target_w, sub_y, shot.app_store_subtitle, subtitle_font, (105, 105, 105))

        frame_y = sub_y + 100
        # 完整 fit：底部留 90px 白，杜絕底部圓角被畫布硬切（舊版 crop 切掉 ~113px）。
        frame_w, frame_h = fit_frame_into_canvas(
            raw.width, raw.height,
            target_h=target_h, frame_y=frame_y, bottom_margin=90, design_w=design_frame_w,
        )
        frame = raw.resize((frame_w, frame_h), Image.Resampling.LANCZOS)
        frame_x = (target_w - frame_w) // 2

        shadow_base = Image.new("RGBA", (target_w, target_h + 200), (0, 0, 0, 0))
        shadow_color = Image.new("RGBA", frame.size, (0, 0, 0, 60))
        shadow_color.putalpha(frame.split()[3])
        shadow_base.paste(shadow_color, (frame_x + 10, frame_y + 18))
        shadow_base = shadow_base.filter(ImageFilter.GaussianBlur(radius=35))
        canvas = Image.alpha_composite(canvas, shadow_base.crop((0, 0, target_w, target_h)))

        phone_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        phone_layer.paste(frame, (frame_x, frame_y), frame)
        canvas = Image.alpha_composite(canvas, phone_layer)

        target = output_dir / shot.app_store_output
        canvas.convert("RGB").save(target, "PNG")
        written.append(target)
    return written


def render_web(
    root: Path | None = None,
    output_dir: Path | None = None,
    *,
    target: str = "promotion",
    source_dir: Path | None = None,
    shots: Sequence[PromoShot] | None = None,
) -> list[Path]:
    root = root or repo_root_from_script()
    output_dir = output_dir or web_output_dir(root, target=target)
    source_dir = source_dir or iphone_source_dir(root)
    shots = tuple(shots or SHOTS)
    output_dir.mkdir(parents=True, exist_ok=True)

    title_font_path, pingfang_path = font_paths()
    title_font = ImageFont.truetype(str(title_font_path), 34)
    subtitle_font = ImageFont.truetype(str(pingfang_path), 14, index=6)

    target_w, target_h = 462, 1000
    frame_y = 134
    written: list[Path] = []
    for shot in shots:
        raw = Image.open(source_dir / f"{shot.source_stem}.png").convert("RGBA")
        # 完整 fit：底部留 16px 白，手機圓角收尾可見，杜絕舊「黑橫」硬切。
        frame_w, frame_h = fit_frame_into_canvas(
            raw.width, raw.height,
            target_h=target_h, frame_y=frame_y, bottom_margin=16, design_w=432,
        )
        frame = raw.resize((frame_w, frame_h), Image.Resampling.BILINEAR)

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
    parser.add_argument("--source-dir", type=Path, help="override framed screenshot source directory")
    parser.add_argument("--shots-json", type=Path, help="external shots manifest with sourceStem/copy/outputName")
    return parser.parse_args(list(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = repo_root_from_script()
    if args.output_dir and args.variant == "all":
        raise SystemExit("--output-dir requires --variant app-store or --variant web")
    shots = load_shots_manifest(args.shots_json) if args.shots_json else None

    written: list[Path] = []
    if args.variant in {"app-store", "all"}:
        written.extend(
            render_app_store(
                root=root,
                output_dir=args.output_dir if args.variant == "app-store" else None,
                target=args.target,
                source_dir=args.source_dir,
                shots=shots,
            )
        )
    if args.variant in {"web", "all"}:
        written.extend(
            render_web(
                root=root,
                output_dir=args.output_dir if args.variant == "web" else None,
                target=args.target,
                source_dir=args.source_dir,
                shots=shots,
            )
        )

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
