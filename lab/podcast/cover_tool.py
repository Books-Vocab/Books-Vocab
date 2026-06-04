# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "python-dotenv"]
# ///
"""Podcast 封面工具 — agent 透過 Bash 驅動的三段漏斗。

  search "<q1>" ["<q2>"...]   海選:Pexels 搜尋+過濾,印精簡 alt 表(純文字,低 token)
  contact <id,id,...>         複選:下載 shortlist→組編號 contact sheet(1 張圖)
  render <id> --color <hex>   定案:下載中選→統一後製→1:1 封面(驗證階段存本地)

設計鐵則:重活全在 code,agent 只回吐 query / 選號 / id。
  - search 只印白名單欄位、capped、pre-filtered → agent 不為垃圾燒 token
  - 不餵逐張原圖;視覺判斷集中在 contact sheet 一張
KEY 來源:lab/podcast/.env 的 PEXELS_API_KEY(同 synthesize.py 讀 Vertex 金鑰模式)。
"""
import argparse, colorsys, io, json, os, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageEnhance, ImageFont
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
KEY = os.environ.get("PEXELS_API_KEY", "").strip()
API = "https://api.pexels.com/v1/search"
SIZE = 1024

def _die(msg): print(f"ERROR: {msg}", file=sys.stderr); sys.exit(1)
def _clamp(v): return max(0, min(255, int(v)))
def _hex2rgb(h): h=h.lstrip("#"); return tuple(int(h[i:i+2],16) for i in (0,2,4))
def _shade(rgb,f):
    return tuple(_clamp(c*f) if f<=1 else _clamp(c+(255-c)*(f-1)) for c in rgb)

_NEUTRAL_COLOR = (90, 96, 112)  # 品牌中性 slate:achromatic 圖的退路

def _derive_color(hexc, min_sat=0.5, val=0.5):
    """從圖的 avg_color 取 series 色:保色相,把飽和度拉到 >=min_sat、明度正規化。
    色相洗白(washed-out)的 avg_color 直接拿去 duotone 會糊成灰,故提飽和。
    但真正 achromatic(純灰/黑/白,色相無定義)不可任意提飽和變紅 ——
    退回品牌中性色。"""
    r,g,b = [c/255 for c in _hex2rgb(hexc)]
    h,s,_ = colorsys.rgb_to_hsv(r,g,b)
    if s < 0.04:  # achromatic:hue 無定義,提飽和會任意挑色 → 用中性 slate
        return _NEUTRAL_COLOR
    r,g,b = colorsys.hsv_to_rgb(h, max(s, min_sat), val)
    return tuple(_clamp(c*255) for c in (r,g,b))

def _get(url, raw=False):
    # Pexels(Cloudflare)對預設 Python-urllib UA 回 403,須帶常規 UA。
    req = urllib.request.Request(url, headers={
        "Authorization": KEY, "User-Agent": "Mozilla/5.0 (kg-cover-tool)"})
    # 網路/HTTP 故障在此收斂成可讀錯誤後 _die,而非吐裸 traceback。
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        _die(f"Pexels HTTP {e.code} {e.reason}({url[:80]})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        _die(f"網路請求失敗:{reason}({url[:80]})")
    if raw:
        return body
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError) as e:
        _die(f"Pexels 回傳非 JSON:{e}")

def _pexels(query, per_page=15, orientation="square"):
    qs = urllib.parse.urlencode({"query": query, "per_page": per_page,
                                 "orientation": orientation, "size": "medium"})
    return _get(f"{API}?{qs}").get("photos", [])

# ---------- 海選 ----------
def cmd_search(args):
    if not KEY: _die("PEXELS_API_KEY 未設(lab/podcast/.env)")
    seen, rows = set(), []
    for q in args.queries:
        for p in _pexels(q, per_page=args.n, orientation=args.orientation):
            if p["id"] in seen: continue
            if min(p["width"], p["height"]) < 800: continue   # 夠裁 1024 方圖
            seen.add(p["id"])
            rows.append(p)
    rows = rows[:args.cap]
    if not rows: _die(f"無候選(queries={args.queries})")
    # 純文字表:agent 看這個做海選。欄位白名單,alt 截斷。
    print(f"# {len(rows)} candidates (query={', '.join(args.queries)})")
    print("idx | id | avg | WxH | alt")
    for i, p in enumerate(rows, 1):
        alt = (p.get("alt") or "").replace("\n"," ")[:90]
        print(f"{i} | {p['id']} | {p['avg_color']} | {p['width']}x{p['height']} | {alt}")

# ---------- 共用:下載+裁方 ----------
def _fetch_square(pid, cell):
    photos = _pexels_by_id(pid)
    src = photos["src"]["large"] if cell > 400 else photos["src"]["medium"]
    im = Image.open(io.BytesIO(_get(src, raw=True)))
    im = ImageOps.exif_transpose(im).convert("RGB")
    s = min(im.size); l=(im.width-s)//2; t=(im.height-s)//2
    return im.crop((l,t,l+s,t+s)).resize((cell,cell), Image.LANCZOS)

def _pexels_by_id(pid):
    return _get(f"https://api.pexels.com/v1/photos/{pid}")

def _font(sz):
    for p in ["/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/PingFang.ttc"]:
        if Path(p).exists():
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
    return ImageFont.load_default()

# ---------- 複選 ----------
def _badge(im, label, cell):
    """左上角黑底白字編號,任何底圖都讀得到。"""
    d = ImageDraw.Draw(im); f = _font(max(20, cell//9))
    bb = d.textbbox((0,0), label, font=f); bw,bh = bb[2]-bb[0], bb[3]-bb[1]
    d.rectangle([0,0,bw+16,bh+14], fill=(0,0,0))
    d.text((8,4), label, font=f, fill=(255,255,255))
    return im

def _compose_contact(items, cell, cols=3, gap=8):
    """純佈局:items=[(idx,pid,Image)] → 拼成 cols 欄的 contact sheet。無網路、可測。"""
    rows = (len(items)+cols-1)//cols
    W = cols*cell+(cols+1)*gap; H = rows*cell+(rows+1)*gap
    canvas = Image.new("RGB",(W,H),(20,20,24))
    for idx,(_i,_pid,im) in enumerate(items):
        r,c = divmod(idx,cols)
        canvas.paste(im,(gap+c*(cell+gap), gap+r*(cell+gap)))
    return canvas

def cmd_contact(args):
    if not KEY: _die("PEXELS_API_KEY 未設")
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    cell = args.cell
    items = [(i, pid, _badge(_fetch_square(pid, cell), str(i), cell))
             for i, pid in enumerate(ids, 1)]
    sheet = _compose_contact(items, cell=cell, cols=3, gap=8)
    out = Path(args.out); sheet.save(out)
    print(f"contact_sheet: {out}  ({sheet.width}x{sheet.height}, {len(items)} cells)")
    for i,pid,_ in items: print(f"  #{i} -> id {pid}")

# ---------- 後製(已驗原型) ----------
def _scrim(im):
    ov = Image.new("L",(SIZE,SIZE),0); d=ImageDraw.Draw(ov)
    for y in range(SIZE):
        t = max(0.0,(y/SIZE-0.55)/0.45); d.line([(0,y),(SIZE,y)], fill=int(180*t*t))
    return Image.composite(Image.new("RGB",(SIZE,SIZE),(8,8,12)), im, ov)
def _duotone(im,rgb):
    g = ImageOps.autocontrast(im.convert("L"),cutoff=2)
    lo,hi = _shade(rgb,0.28),_shade(rgb,1.55); lut=[]
    for ch in range(3): lut += [_clamp(lo[ch]+(hi[ch]-lo[ch])*(i/255)) for i in range(256)]
    return g.convert("RGB").point(lut)
def _softgrade(im,rgb):
    b = ImageEnhance.Color(ImageOps.autocontrast(im,cutoff=1)).enhance(0.45)
    return Image.blend(b, Image.new("RGB",b.size,rgb), 0.30)

def _treat(im, rgb, treatment):
    """裁好的方圖 → 後製(duo/soft) → 底部 scrim。純函式、可測。"""
    base = _duotone(im, rgb) if treatment == "duo" else _softgrade(im, rgb)
    return _scrim(base)

def cmd_render(args):
    if not KEY: _die("PEXELS_API_KEY 未設")
    # --color 顯式則照用;省略則從選中圖的 avg_color 取色(保色相+提飽和),
    # 封面色永遠和照片和諧 → 零額外決策(pipeline cover stage 走此路)。
    if args.color:
        rgb = _hex2rgb(args.color)
    else:
        avg = _pexels_by_id(args.id).get("avg_color") or "#808080"
        rgb = _derive_color(avg)
    im = _fetch_square(args.id, SIZE)
    out = Path(args.out); _treat(im, rgb, args.treatment).save(out)
    print(f"cover: {out}  (id={args.id}, treatment={args.treatment}, "
          f"color=#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X})")

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("queries", nargs="+")
    s.add_argument("--n", type=int, default=15); s.add_argument("--cap", type=int, default=15)
    s.add_argument("--orientation", default="square"); s.set_defaults(fn=cmd_search)
    c = sub.add_parser("contact"); c.add_argument("ids"); c.add_argument("--cell", type=int, default=280)
    c.add_argument("--out", default="/tmp/cover_proto/contact.png"); c.set_defaults(fn=cmd_contact)
    r = sub.add_parser("render"); r.add_argument("id"); r.add_argument("--color", default=None)
    r.add_argument("--treatment", choices=["duo","soft"], default="duo")
    r.add_argument("--out", default="/tmp/cover_proto/cover.png"); r.set_defaults(fn=cmd_render)
    args = ap.parse_args(); args.fn(args)

if __name__ == "__main__": main()
