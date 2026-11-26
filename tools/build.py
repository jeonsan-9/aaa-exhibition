#!/usr/bin/env python3
"""AAA 천체사진전 빌드 스크립트.

zip(사진 + 작품목록) 을 읽어서 전시 사이트(dist/)를 만든다.

  python tools/build.py

읽는 곳 (뒤에 있는 것이 같은 이름의 앞 것을 덮어쓴다)
  exhibitions/<이름>/      풀어 놓은 폴더
  inbox/<이름>.zip         레포에 올린 zip
  .inbox-release/**/*.zip  GitHub 릴리스에 첨부한 zip (Actions 가 내려받음)

만드는 곳
  dist/<이름>/index.html   전시 한 개
  dist/index.html          가장 최근 전시로 이동
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
import shutil
import sys
import unicodedata
import zipfile
from pathlib import Path

from PIL import Image, ImageOps

try:  # 아이폰 HEIC
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001
    pass
try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None
try:
    import openpyxl
except Exception:  # noqa: BLE001
    openpyxl = None

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DIST = ROOT / "dist"
WORK = ROOT / ".build"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif"}
DEFAULT_SECTION = "본 전시"
RESERVED = {"upload", "assets", "index"}
FORM = ROOT / "양식" / "작품목록_양식.xlsx"
E = html.escape
warnings: list[str] = []


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  ! {msg}")


def nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s))


def key(s) -> str:
    return re.sub(r"\s+", "", nfc(s)).lower()


# ───────────────────────── zip ─────────────────────────
def zip_name(info: zipfile.ZipInfo) -> str:
    """윈도우에서 만든 zip 의 한글 파일명(cp949)을 복구한다."""
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            raw = name.encode("cp437")
            for enc in ("utf-8", "cp949"):
                try:
                    name = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
        except UnicodeEncodeError:
            pass
    return nfc(name.replace("\\", "/"))


def extract(zpath: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = zip_name(info)
            parts = [p for p in name.split("/") if p not in ("", ".", "..")]
            if info.is_dir() or not parts or "__MACOSX" in parts or parts[-1].startswith("."):
                continue
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def slugify(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", nfc(name).strip()).strip("-").lower()
    return s or "exhibition"


# ───────────────────────── 표 읽기 ─────────────────────────
WORK_FIELDS = [  # 순서가 곧 우선순위. 머리글에 이 낱말이 들어 있으면 그 칸으로 본다.
    ("title", ["제목", "작품명", "title"]),
    ("comment", ["코멘트", "설명", "소개", "소감", "이야기", "comment", "description"]),
    ("aff", ["소속", "학교", "학과", "affiliation"]),
    ("file", ["파일", "사진", "file", "photo", "image"]),
    ("author", ["이름", "성함", "작가", "촬영자", "author", "name"]),
    ("date", ["촬영일", "날짜", "일시", "date"]),
    ("place", ["장소", "촬영지", "위치", "place", "location"]),
    ("gear", ["장비", "카메라", "망원경", "gear", "equipment"]),
    ("settings", ["촬영정보", "설정", "노출", "settings", "exposure"]),
    ("section", ["구분", "전시실", "섹션", "section"]),
    ("order", ["순서", "번호", "order"]),
]
INFO_FIELDS = [
    ("title", ["제목", "전시명", "title"]),
    ("edition", ["회차", "edition"]),
    ("term", ["학기", "term"]),
    ("period", ["기간", "period"]),
    ("tagline", ["한줄", "부제", "tagline"]),
    ("intro", ["소개", "서문", "intro"]),
    ("music", ["음악", "bgm", "music"]),
    ("guestbook", ["방명록", "guestbook"]),
    ("cover", ["대표사진", "대표", "cover"]),
    ("host", ["주최", "동아리", "host"]),
]


def cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y.%m.%d")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return nfc(v).replace("\r\n", "\n").replace("\r", "\n").strip()


def map_headers(headers: list[str], fields) -> dict[int, str]:
    out: dict[int, str] = {}
    used: set[str] = set()
    for field, words in fields:
        for i, h in enumerate(headers):
            if i in out or field in used:
                continue
            if any(w in key(h) for w in words):
                out[i] = field
                used.add(field)
    return out


def rows_to_works(rows: list[list[str]]) -> list[dict]:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    cols = map_headers(rows[0], WORK_FIELDS)
    if not cols:
        warn("작품목록 첫 줄에서 '제목/이름/파일명/코멘트' 같은 머리글을 찾지 못했습니다.")
        return []
    works = []
    for r in rows[1:]:
        w = {f: (r[i] if i < len(r) else "") for i, f in cols.items()}
        if any(w.values()):
            works.append(w)
    return works


def parse_info(pairs) -> tuple[dict, dict]:
    """(전시정보, 전시실별 소개)"""
    info: dict[str, str] = {}
    rooms: dict[str, str] = {}
    for k, v in pairs:
        k, v = nfc(k).strip(), cell(v)
        if not k or not v:
            continue
        kk = key(k)
        if kk.endswith("소개") and kk not in ("소개", "전시소개", "작품소개"):
            rooms[key(k.strip()[:-2])] = v
            continue
        for field, words in INFO_FIELDS:
            if field not in info and any(w in kk for w in words):
                info[field] = v
                break
    return info, rooms


def rows_to_greetings(rows: list[list[str]]) -> list[dict]:
    rows = [r for r in rows if any(c for c in r)]
    if len(rows) < 2:
        return []
    cols = map_headers(rows[0], [("role", ["직함", "직책", "role"]), ("name", ["이름", "name"]), ("text", ["글", "인사", "내용", "text"])])
    out = []
    for r in rows[1:]:
        g = {f: (r[i] if i < len(r) else "") for i, f in cols.items()}
        if g.get("text"):
            out.append(g)
    return out


def read_source(folder: Path) -> tuple[list[dict], dict, dict, list[dict], bool]:
    works: list[dict] = []
    info: dict = {}
    rooms: dict = {}
    greetings: list[dict] = []
    has_table = False
    files = sorted(p for p in folder.rglob("*") if p.is_file() and not p.name.startswith("~$"))

    for p in files:
        ext = p.suffix.lower()
        if ext in (".xlsx", ".xlsm") and openpyxl:
            wb = openpyxl.load_workbook(p, data_only=True)
            for ws in wb.worksheets:
                rows = [[cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
                name = key(ws.title)
                if "인사" in name or "greet" in name:
                    greetings = greetings or rows_to_greetings(rows)
                elif "정보" in name or "설정" in name or "info" in name:
                    i, r = parse_info((r[0], r[1]) for r in rows if len(r) > 1)
                    info = {**i, **info}
                    rooms = {**r, **rooms}
                elif not works:
                    works = rows_to_works(rows)
                    has_table = has_table or bool(works)
        elif ext == ".csv" and not works:
            raw = p.read_bytes()
            for enc in ("utf-8-sig", "cp949"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                warn(f"{p.name}: 글자 인코딩을 읽지 못했습니다. UTF-8 로 저장해 주세요.")
                continue
            works = rows_to_works([[cell(c) for c in row] for row in csv.reader(text.splitlines(keepends=True))])
            has_table = has_table or bool(works)
        elif ext in (".yml", ".yaml") and yaml:
            data = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
            if isinstance(data, dict):
                for k in list(data):
                    if "인사" in key(k) and isinstance(data[k], list):
                        for g in data.pop(k):
                            if isinstance(g, dict):
                                gg = {key(a): cell(b) for a, b in g.items()}
                                greetings.append({"name": gg.get("이름", ""), "role": gg.get("직함", ""), "text": gg.get("글", "")})
                i, r = parse_info(data.items())
                info = {**info, **i}
                rooms = {**rooms, **r}
    return works, info, rooms, greetings, has_table


# ───────────────────────── 사진 ─────────────────────────
def match_photos(works: list[dict], folder: Path, has_table: bool) -> list[dict]:
    photos = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXT)
    by_name = {key(p.name): p for p in photos}
    by_stem = {key(p.stem): p for p in photos}
    used: set[Path] = set()
    out = []
    for w in works:
        p = None
        f = w.get("file", "")
        if f:
            f = f.split("/")[-1].split("\\")[-1]
            p = by_name.get(key(f)) or by_stem.get(key(f)) or by_stem.get(key(Path(f).stem))
        if p is None and w.get("author"):
            cands = [q for q in photos if q not in used and key(w["author"]) in key(q.stem)]
            if w.get("title"):
                both = [q for q in cands if key(w["title"]) in key(q.stem)]
                cands = both or cands
            p = cands[0] if cands else None
        if p is None or p in used:
            warn(f"사진을 찾지 못해 건너뜀: {w.get('title') or '(제목 없음)'} / {w.get('author', '')} / 파일명 '{f}'")
            continue
        used.add(p)
        out.append({**w, "path": p})
    for p in photos:
        if p in used:
            continue
        if has_table:
            warn(f"작품목록에 없는 사진이라 맨 뒤에 붙임: {p.name}")
        stem = re.sub(r"^\d+[\s._-]*", "", p.stem)
        a, _, t = stem.partition("_")
        out.append({"author": a.strip() if t else "", "title": (t or a).replace("_", " ").strip(), "path": p})
    return out


def exif_fill(w: dict, im: Image.Image) -> None:
    try:
        ex = im.getexif()
        sub = ex.get_ifd(0x8769)
    except Exception:  # noqa: BLE001
        return
    if not w.get("gear") and ex.get(0x0110):
        w["gear"] = str(ex.get(0x0110)).strip("\x00 ")
    if not w.get("date") and sub.get(36867):
        w["date"] = str(sub[36867])[:10].replace(":", ".")
    if not w.get("settings"):
        bits = []
        t = sub.get(33434)
        if t:
            t = float(t)
            bits.append(f"{t:g}초" if t >= 1 else f"1/{round(1 / t)}초")
        if sub.get(33437):
            bits.append(f"f/{float(sub[33437]):g}")
        if sub.get(34855):
            bits.append(f"ISO {sub[34855]}")
        if len(bits) >= 2:
            w["settings"] = " · ".join(bits)


def process_image(w: dict, n: int, outdir: Path) -> None:
    with Image.open(w["path"]) as im:
        exif_fill(w, im)
        im = ImageOps.exif_transpose(im).convert("RGB")
        w["w"], w["h"] = im.size
        r, g, b = im.resize((1, 1), Image.BOX).getpixel((0, 0))
        w["color"] = f"#{r:02x}{g:02x}{b:02x}"
        full = im.copy()
        full.thumbnail((2400, 2400), Image.LANCZOS)
        full.save(outdir / f"{n:02d}.webp", "WEBP", quality=84, method=5)
        small = im.copy()
        small.thumbnail((1100, 1100), Image.LANCZOS)
        small.save(outdir / f"{n:02d}-s.webp", "WEBP", quality=80, method=5)
    w["full"], w["thumb"] = f"img/{n:02d}.webp", f"img/{n:02d}-s.webp"


# ───────────────────────── HTML ─────────────────────────
def paras(text: str) -> str:
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    return "".join("<p>" + E(b.strip()).replace("\n", "<br>") + "</p>" for b in blocks)


def excerpt(text: str, n: int = 74) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= n else flat[:n].rstrip() + "…"


def youtube_id(url: str) -> str:
    m = re.search(r"(?:youtu\.be/|v=|/embed/|/shorts/)([A-Za-z0-9_-]{6,})", url or "")
    return m.group(1) if m else ""


FONTS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
    "&family=IBM+Plex+Sans+KR:wght@300;400;500;600&family=Noto+Serif+KR:wght@300;400;600&display=swap"
)


def render(slug: str, info: dict, rooms: dict, greetings: list[dict], works: list[dict], others: list[tuple[str, str]]) -> str:
    title = info.get("title") or f"{slug} 천체사진전"
    host = info.get("host") or "계명대학교 천체관측 동아리 AAA"
    term = info.get("term") or slug
    edition = info.get("edition", "")
    tagline = info.get("tagline", "")
    intro = info.get("intro", "")
    yt = youtube_id(info.get("music", ""))
    guestbook = info.get("guestbook", "")
    authors = list(dict.fromkeys(w["author"] for w in works if w.get("author")))

    # 전시실 나누기
    sections: list[tuple[str, list[dict]]] = []
    for w in works:
        name = w.get("section") or DEFAULT_SECTION
        for s in sections:
            if s[0] == name:
                s[1].append(w)
                break
        else:
            sections.append((name, [w]))

    cover = works[0]
    want = info.get("cover", "")
    for w in works:
        if want and (key(want) in (key(w["path"].name), key(w["path"].stem)) or key(want) == key(w.get("title", "")) or want.strip().lstrip("0") == str(w["n"])):
            cover = w

    # 한 줄로 쪼갠 제목: "2026년 1학기 AAA 천체사진전" → 작은 줄 + 큰 줄
    m = re.match(r"^(.*?)\s*((?:천체\s*)?사진전.*)$", title)
    t_small, t_big = (m.group(1), m.group(2)) if m and m.group(1) else ("", title)

    facts = []
    if info.get("period"):
        facts.append(("기간", info["period"]))
    facts.append(("작품", f"{len(works)}점"))
    facts.append(("참여", f"{len(authors)}명"))
    if len(sections) > 1:
        facts.append(("전시실", f"{len(sections)}개"))

    def piece(w: dict) -> str:
        ar = w["w"] / w["h"]
        shape = "land" if ar > 1.15 else ("square" if ar > 0.9 else "port")
        meta = " · ".join(x for x in (w.get("place"), w.get("date")) if x)
        by = E(w.get("author", "")) + (f' <span class="aff">{E(w["aff"])}</span>' if w.get("aff") else "")
        ex = excerpt(w.get("comment", ""))
        return (
            f'<article class="piece {shape}" id="p-{w["n"]:02d}" data-i="{w["n"] - 1}" style="--ar:{ar:.4f};--c:{w["color"]}">'
            f'<button class="frame" type="button" aria-label="{E(w.get("title", ""))} 크게 보기">'
            f'<img src="{w["thumb"]}" width="{w["w"]}" height="{w["h"]}" loading="lazy" decoding="async" alt="{E(w.get("title", ""))}"></button>'
            f'<div class="label"><span class="no">No. {w["n"]:02d}</span><h3>{E(w.get("title") or "무제")}</h3>'
            + (f'<p class="by">{by}</p>' if by else "")
            + (f'<p class="meta">{E(meta)}</p>' if meta else "")
            + (f'<p class="ex">{E(ex)}</p>' if ex else "")
            + '<span class="more">자세히 보기</span></div></article>'
        )

    track = []
    for i, (name, ws) in enumerate(sections, 1):
        room_intro = rooms.get(key(name), "")
        track.append(
            f'<div class="room"><span class="room-no">제{i}전시실</span><h3>{E(name)}</h3>'
            f'<p class="room-count">{len(ws)}점 · No. {ws[0]["n"]:02d}–{ws[-1]["n"]:02d}</p>'
            + (f'<div class="room-intro">{paras(room_intro)}</div>' if room_intro else "")
            + "</div>"
        )
        track.extend(piece(w) for w in ws)

    g_html = ""
    if greetings:
        tabs = "".join(
            f'<button type="button" role="tab" id="gt-{i}" aria-controls="gp-{i}" aria-selected="{"true" if i == 0 else "false"}">'
            f'<span>{E(g.get("role", ""))}</span>{E(g.get("name", ""))}</button>'
            for i, g in enumerate(greetings)
        )
        panels = "".join(
            f'<article role="tabpanel" id="gp-{i}" aria-labelledby="gt-{i}"{"" if i == 0 else " hidden"}>{paras(g["text"])}'
            f'<p class="sign">{E(g.get("role", ""))} <b>{E(g.get("name", ""))}</b></p></article>'
            for i, g in enumerate(greetings)
        )
        g_html = (
            '<section class="greetings band" id="greetings"><div class="in"><h2>인사말</h2>'
            f'<div class="g-tabs" role="tablist" aria-label="인사말을 쓴 사람">{tabs}</div><div class="g-panels">{panels}</div></div></section>'
        )

    bgm = ""
    if yt:
        bgm = (
            '<div class="bgm-line"><p>준비된 음악과 함께 감상하시길 권합니다.</p>'
            f'<a class="bgm" href="https://youtu.be/{yt}" target="_blank" rel="noopener" data-yt="{yt}">'
            '<i aria-hidden="true"></i><span>음악 켜기</span></a></div>'
        )
    foreword = ""
    if intro or bgm:
        foreword = f'<section class="foreword band" id="foreword"><div class="in"><h2>작품 소개</h2><div class="prose">{paras(intro)}</div>{bgm}</div></section>'

    guest = ""
    if guestbook:
        guest = (
            '<section class="guest band" id="guestbook"><div class="in"><h2>방명록</h2>'
            "<p>전시를 보고 떠오른 말을 남겨 주세요. 사진을 낸 부원들이 하나씩 읽습니다.</p>"
            f'<a class="cta" href="{E(guestbook)}" target="_blank" rel="noopener">방명록 쓰러 가기 <span aria-hidden="true">↗</span></a></div></section>'
        )

    nav = "".join(
        f'<a href="#{i}">{t}</a>'
        for i, t, on in (("greetings", "인사말", g_html), ("foreword", "작품 소개", foreword), ("hall", "전시실", True), ("guestbook", "방명록", guest))
        if on
    )
    credits = "".join(f"<li>{E(a)}</li>" for a in authors)
    past = "".join(f'<a href="../{E(s)}/">{E(t)}</a>' for s, t in others)

    data = [
        {k: w.get(k, "") for k in ("n", "title", "author", "aff", "date", "place", "gear", "settings", "comment", "full", "thumb", "w", "h", "color")}
        | {"section": w.get("section") or DEFAULT_SECTION}
        for w in works
    ]
    desc = tagline or excerpt(intro, 120) or title
    cover_ar = cover["w"] / cover["h"]

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!--head-->
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:image" content="{cover['thumb']}">
<meta name="theme-color" content="#1a1917">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="assets/style.css">
<!--/head-->
</head>
<body>
<!--body-->
<div class="app" data-embed="on">
<header class="nav">
  <a class="nav-id" href="#top"><b>AAA</b><span>{E(term)}</span></a>
  <nav aria-label="전시 안내">{nav}</nav>
  <div class="nav-right">
    <button class="nav-index" type="button" data-open-index>작품 목록 <span>{len(works)}</span></button>
    <a class="nav-upload" href="../upload/">작품 올리기</a>
  </div>
</header>

<main id="top">
<section class="entrance">
  <div class="entrance-in">
    <div class="entrance-text">
      <p class="eyebrow">{E(host)}{f" · {E(edition)}" if edition else ""}</p>
      <h1>{f"<small>{E(t_small)}</small>" if t_small else ""}{E(t_big)}</h1>
      {f'<p class="tagline">{E(tagline)}</p>' if tagline else ""}
      <dl class="facts">{"".join(f"<div><dt>{E(k)}</dt><dd>{E(v)}</dd></div>" for k, v in facts)}</dl>
      <a class="cta" href="#hall">전시실로 들어가기 <span aria-hidden="true">→</span></a>
    </div>
    <figure class="entrance-piece" style="--ar:{cover_ar:.4f};--c:{cover['color']}">
      <button class="frame" type="button" data-open="{cover['n'] - 1}" aria-label="{E(cover.get('title', ''))} 크게 보기"><img src="{cover['thumb']}" width="{cover['w']}" height="{cover['h']}" alt="{E(cover.get('title', ''))}"></button>
      <figcaption><span class="no">No. {cover['n']:02d}</span> {E(cover.get('title', ''))} <i>{E(cover.get('author', ''))}</i></figcaption>
    </figure>
  </div>
</section>
{g_html}
{foreword}
<section class="hall" id="hall" aria-label="전시실">
  <div class="hall-sticky">
    <div class="track">{"".join(track)}<div class="room exit"><span class="room-no">출구</span><h3>관람해 주셔서<br>고맙습니다</h3>{'<a class="cta" href="#guestbook">방명록 남기기 <span aria-hidden="true">→</span></a>' if guest else ""}</div></div>
    <div class="floor" aria-hidden="true"></div>
    <div class="hud">
      <p class="hud-now"><b class="hud-count">01</b><span> / {len(works):02d}</span><em class="hud-title"></em></p>
      <div class="hud-rail" aria-hidden="true"><i></i></div>
      <div class="hud-btns"><button type="button" data-step="-1" aria-label="이전 작품">←</button><button type="button" data-step="1" aria-label="다음 작품">→</button></div>
    </div>
  </div>
</section>
{guest}
</main>

<footer class="foot band"><div class="in">
  <div class="credits"><h2>참여 작가</h2><ul>{credits}</ul></div>
  <div class="foot-meta">
    <p><b>{E(title)}</b><br>{E(host)}</p>
    {'<p class="past"><a class="foot-upload" href="../upload/">전시 올리기</a></p>' if upload_url() else ""}
    {f'<p class="past"><span>다른 전시</span>{past}</p>' if past else ""}
  </div>
</div></footer>

<dialog class="viewer" aria-label="작품 보기">
  <div class="viewer-stage"><img alt=""></div>
  <aside class="viewer-side">
    <div class="viewer-text"></div>
    <div class="viewer-nav"><button type="button" data-v="-1">← 이전</button><span class="viewer-count"></span><button type="button" data-v="1">다음 →</button></div>
  </aside>
  <button class="viewer-close" type="button" aria-label="닫기">닫기</button>
</dialog>

<dialog class="index" aria-label="작품 목록">
  <div class="index-head"><h2>작품 목록</h2><button type="button" class="index-close">닫기</button></div>
  <div class="index-grid"></div>
</dialog>
<div class="bgm-dock" hidden></div>
</div>
<script type="application/json" id="works-data">{json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}</script>
<script src="assets/app.js"></script>
<!--/body-->
</body>
</html>
"""


# ───────────────────────── 올리기 페이지 ─────────────────────────
def upload_url() -> str:
    """config.json 의 upload_url (올리기 서버 주소). 없으면 빈 문자열."""
    try:
        url = str(json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("upload_url") or "").strip()
    except (OSError, ValueError):
        return ""
    return url.rstrip("/") if url.startswith("https://") else ""


def build_upload_page(existing: list[str]) -> None:
    page = ROOT / "pages" / "upload.html"
    if not page.exists():
        return
    out = DIST / "upload"
    out.mkdir(parents=True)
    shutil.copytree(SITE, out / "assets")
    if FORM.exists():
        shutil.copy(FORM, out / "form.xlsx")
    conf = {"url": upload_url(), "existing": existing}
    text = page.read_text(encoding="utf-8").replace("__CONFIG__", json.dumps(conf, ensure_ascii=False).replace("</", "<\\/"))
    (out / "index.html").write_text(text, encoding="utf-8")


# ───────────────────────── 실행 ─────────────────────────
def collect_sources() -> dict[str, Path]:
    src: dict[str, Path] = {}
    exh = ROOT / "exhibitions"
    if exh.is_dir():
        for d in sorted(exh.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                src[slugify(d.name)] = d
    zips = sorted((ROOT / "inbox").glob("*.zip")) + sorted((ROOT / ".inbox-release").rglob("*.zip"))
    for z in zips:
        slug = slugify(z.stem)
        # 릴리스에 zip 이 하나뿐이면 릴리스 이름(태그)이 곧 전시 주소다
        if z.parent.parent.name == ".inbox-release" and len(list(z.parent.glob("*.zip"))) == 1:
            slug = slugify(z.parent.name)
        if slug in RESERVED:
            warn(f"{z.name}: '{slug}' 는 전시 이름으로 쓸 수 없습니다. 건너뜁니다.")
            continue
        dest = WORK / "src" / slug
        print(f"압축 풀기: {z.relative_to(ROOT)}")
        try:
            extract(z, dest)
        except zipfile.BadZipFile:
            warn(f"{z.name}: zip 파일이 깨졌습니다. 건너뜁니다.")
            continue
        src[slug] = dest
    return src


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    sources = collect_sources()
    built = []
    for slug, folder in sources.items():
        print(f"\n[{slug}]")
        works, info, rooms, greetings, has_table = read_source(folder)
        if not has_table:
            warn("작품목록(xlsx/csv)이 없어 사진 파일명으로만 구성합니다. (이름_제목.jpg)")
        works = match_photos(works, folder, has_table)
        if not works:
            warn("사진이 한 장도 없어 건너뜁니다.")
            continue

        def order(iw):
            i, w = iw
            try:
                return (float(w.get("order") or "inf"), i)
            except ValueError:
                return (float("inf"), i)

        works = [w for _, w in sorted(enumerate(works), key=order)]
        # 같은 전시실끼리 모으되, 처음 나온 순서를 지킨다
        names = list(dict.fromkeys((w.get("section") or DEFAULT_SECTION) for w in works))
        if DEFAULT_SECTION in names:
            names.insert(0, names.pop(names.index(DEFAULT_SECTION)))
        works = [w for name in names for w in works if (w.get("section") or DEFAULT_SECTION) == name]

        out = DIST / slug
        (out / "img").mkdir(parents=True)
        for n, w in enumerate(works, 1):
            w["n"] = n
            process_image(w, n, out / "img")
        shutil.copytree(SITE, out / "assets")
        built.append((slug, info, rooms, greetings, works))
        print(f"  작품 {len(works)}점")

    build_upload_page([b[0] for b in built])
    (DIST / ".nojekyll").write_text("")
    if not built:
        print("전시가 하나도 없습니다. inbox/ 에 zip 을 넣어 주세요.")
        (DIST / "index.html").write_text("<!doctype html><meta charset=utf-8><title>AAA 천체사진전</title><p>준비 중입니다.</p>", encoding="utf-8")
        return 0

    built.sort(key=lambda b: b[0], reverse=True)
    titles = [(b[0], b[1].get("title") or b[0]) for b in built]
    for slug, info, rooms, greetings, works in built:
        others = [t for t in titles if t[0] != slug]
        (DIST / slug / "index.html").write_text(render(slug, info, rooms, greetings, works, others), encoding="utf-8")
    latest = built[0][0]
    (DIST / "index.html").write_text(
        f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>AAA 천체사진전</title>'
        f'<meta http-equiv="refresh" content="0; url={latest}/"><a href="{latest}/">전시로 이동</a></html>',
        encoding="utf-8",
    )
    (DIST / ".nojekyll").write_text("")
    print(f"\n완료: 전시 {len(built)}개 → dist/  (첫 화면: {latest})")
    if warnings:
        print(f"확인할 것 {len(warnings)}건:")
        for w in warnings:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
