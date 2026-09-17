#!/usr/bin/env python3
"""Bake a font's TrueType hinting into its outlines for one size.

Renderers that ignore TrueType hints (e.g. macOS Core Text) will then show
the same grid-fitted shapes that a hinting renderer (e.g. Windows ClearType)
shows at that size.

You supply your own font file; the script only transforms it locally.
Do NOT redistribute the output if the input font's license forbids it
(e.g. Microsoft's Consolas license prohibits distributing the font or
derivatives -- use the output for yourself, share this script instead).

Usage:
    python3 hint_bake.py INPUT.ttf --pt 20.5 --dpi 72 --thin 35
    python3 hint_bake.py INPUT.ttf --pt 12 --dpi 96 --thin 0 --output Out.ttf

Options:
    --pt     Target point size (float, e.g. 20.5). Required.
    --dpi    Target resolution. Default 72 (1pt = 1px, macOS).
             Use 96 for Windows sizes (21pt @ 96dpi = 28px).
    --thin   Stem thinning in font units, applied after freezing.
             Default 0 (off). 20-35 is a good range for ~20px Consolas
             (1px ~= upm/px font units). Requires FontForge.
    --interp FreeType hinter version: 40 = DirectWrite (Win 10+, default),
             35 = GDI/Classic.
    --mode   Hinting target: normal (grayscale/ClearType-like, default),
             light (lighter, less snapping), mono (B&W), lcd.
    --family New family name. Default "<orig> Baked <pt>pt".
    --output Output path. Default "<input>-<pt>pt-<dpi>dpi-baked.ttf".

Requires: pip install fonttools freetype-py
          (only for --thin > 0: FontForge, e.g. brew install fontforge)
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import freetype
from freetype.raw import FT_Property_Set, FT_UInt
from ctypes import byref
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.ttLib.tables.ttProgram import Program

MODES = {
    "normal": freetype.FT_LOAD_TARGET_NORMAL,
    "light": freetype.FT_LOAD_TARGET_LIGHT,
    "mono": freetype.FT_LOAD_TARGET_MONO,
    "lcd": freetype.FT_LOAD_TARGET_LCD,
}

FF_THIN_SCRIPT = r"""
import fontforge, sys
src, dst, amount, family, subfam, psname = sys.argv[1:7]
font = fontforge.open(src)
font.selection.all()
font.changeWeight(int(amount), "LCG", 0, 0, "squish")
font.fontname = psname
font.fullname = family if subfam == "Regular" else "%s %s" % (family, subfam)
font.familyname = family
font.generate(dst)
font.close()
print("thinned by %s -> %s" % (amount, dst))
"""


def set_interp(v):
    FT_Property_Set(
        freetype.get_handle(), b"truetype", b"interpreter-version",
        byref(FT_UInt(v)))


def ps_safe(s):
    s = "".join(c for c in s if c.isalnum() or c in ("-", "_"))
    return s[:63]


def derive_names(ftfont, family_new):
    try:
        subfam = ftfont["name"].getDebugName(2) or "Regular"
    except Exception:
        subfam = "Regular"
    full = family_new if subfam == "Regular" else family_new + " " + subfam
    ps = family_new.replace(" ", "") + "-" + subfam.replace(" ", "")
    return subfam, full, ps_safe(ps)


def rename(ftfont, family_new):
    subfam, full, ps = derive_names(ftfont, family_new)
    for plat, enc, lang in [(3, 1, 0x409), (1, 0, 0), (0, 3, 0)]:
        try:
            ftfont["name"].setName(family_new, 1, plat, enc, lang)
            ftfont["name"].setName(subfam, 2, plat, enc, lang)
            ftfont["name"].setName(full, 4, plat, enc, lang)
            ftfont["name"].setName(ps, 6, plat, enc, lang)
        except Exception:
            pass
    existing = set(n.nameID for n in ftfont["name"].names)
    if 16 in existing or 17 in existing:
        for plat, enc, lang in [(3, 1, 0x409), (1, 0, 0), (0, 3, 0)]:
            try:
                ftfont["name"].setName(family_new, 16, plat, enc, lang)
                ftfont["name"].setName(subfam, 17, plat, enc, lang)
            except Exception:
                pass
    return subfam, full, ps


def freeze(src, px, pt, dpi, interp, mode):
    """Run native hints at px device pixels, return (TTFont, upm)."""
    ftfont = TTFont(src)
    if "glyf" not in ftfont:
        sys.exit("error: only TrueType-flavored fonts (glyf table) are supported")
    upm = ftfont["head"].unitsPerEm
    factor = upm / (px * 64)
    print(f"[+] {src}: upm={upm} pt={pt:g} dpi={dpi:g} px={px:g} "
          f"interp=v{interp} mode={mode}")
    if "cvt " not in ftfont or "fpgm" not in ftfont:
        print("[!] warning: no cvt/fpgm hint tables; "
              "output will equal unhinted shapes")
    set_interp(interp)
    face = freetype.Face(src)
    face.set_char_size(int(round(pt * 64)), 0, int(dpi), int(dpi))
    print(f"[+] FreeType ppem={face.size.x_ppem},{face.size.y_ppem} "
          f"(hints snap to integer ppem)")
    flag = freetype.FT_LOAD_NO_BITMAP | MODES[mode]
    glyf_table, hmtx_table = ftfont["glyf"], ftfont["hmtx"]
    n_frozen = n_empty = 0
    for gid, gname in enumerate(ftfont.getGlyphOrder()):
        try:
            face.load_glyph(gid, flag)
        except Exception as e:
            print(f"  gid {gid} {gname}: load fail {e}")
            continue
        gslot = face.glyph
        try:
            npts, ncont = len(gslot.outline.points), len(gslot.outline.contours)
        except Exception:
            npts, ncont = 0, 0
        adv_fu = int(round(gslot.advance.x / 64.0 * upm / px))
        _, orig_lsb = hmtx_table[gname]
        if npts == 0 or ncont == 0:
            g = Glyph()
            g.numberOfContours = 0
            g.xMin = g.yMin = g.xMax = g.yMax = 0
            glyf_table[gname] = g
            hmtx_table[gname] = (adv_fu, orig_lsb)
            n_empty += 1
            continue
        coords = [(int(round(x * factor)), int(round(y * factor)))
                  for x, y in gslot.outline.points]
        g = Glyph()
        g.numberOfContours = len(gslot.outline.contours)
        g.coordinates = GlyphCoordinates(coords)
        g.endPtsOfContours = list(gslot.outline.contours)
        g.flags = bytearray(1 if (t & 1) else 0 for t in gslot.outline.tags)
        g.program = Program()
        xs = [x for x, _ in coords]
        ys = [y for _, y in coords]
        g.xMin, g.yMin, g.xMax, g.yMax = min(xs), min(ys), max(xs), max(ys)
        glyf_table[gname] = g
        hmtx_table[gname] = (adv_fu, orig_lsb)
        n_frozen += 1
    print(f"[+] froze {n_frozen} outlines, {n_empty} empty")
    for tag in ["cvt ", "fpgm", "prep", "hdmx", "VDMX", "LTSH", "DSIG"]:
        if tag in ftfont:
            del ftfont[tag]
            print(f"[+] removed {tag!r}")
    if "gasp" in ftfont:
        ftfont["gasp"].gaspRange = {65535: 10}  # gray + smooth, no gridfit
    return ftfont


def thin_with_fontforge(src, dst, amount, family_new):
    ff = shutil.which("fontforge")
    if not ff:
        sys.exit("error: --thin needs FontForge (e.g. brew install fontforge)")
    probe = TTFont(src)
    subfam, _, ps = derive_names(probe, family_new)
    probe.close()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(FF_THIN_SCRIPT)
        script = f.name
    r = subprocess.run(
        [ff, "-lang=py", "-script", script,
         src, dst, str(-int(amount)), family_new, subfam, ps],
        capture_output=True, text=True)
    os.unlink(script)
    print(r.stdout[-2000:] if r.stdout else "")
    if r.returncode != 0:
        print(r.stderr[-2000:] if r.stderr else "")
        sys.exit(f"error: fontforge failed (exit {r.returncode})")


def main():
    ap = argparse.ArgumentParser(description="Bake TrueType hints for one size.")
    ap.add_argument("src", help="input font file (its license must allow this)")
    ap.add_argument("--pt", type=float, required=True, help="point size, e.g. 20.5")
    ap.add_argument("--dpi", type=float, default=72, help="default 72 (macOS)")
    ap.add_argument("--thin", type=float, default=0,
                    help="stem thinning in font units (0 = off)")
    ap.add_argument("--interp", type=int, default=40, choices=[35, 40])
    ap.add_argument("--mode", default="normal", choices=sorted(MODES))
    ap.add_argument("--family", help="new family name")
    ap.add_argument("--output", help="output path")
    a = ap.parse_args()

    if a.thin < 0:
        sys.exit(f"error: --thin must be >= 0 (got {a.thin:g})")

    px = a.pt * a.dpi / 72
    stem = os.path.splitext(os.path.basename(a.src))[0]
    family = a.family or f"{TTFont(a.src)['name'].getDebugName(1)} " \
                         f"Baked {a.pt:g}pt"
    dst = a.output or f"{stem}-{a.pt:g}pt-{a.dpi:g}dpi-baked.ttf"

    ftfont = freeze(a.src, px, a.pt, a.dpi, a.interp, a.mode)
    if a.thin:
        print(f"[+] thinning stems by {a.thin:g} font units "
              f"(1px ~= {ftfont['head'].unitsPerEm / px:.0f} units here)")
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            tmp = f.name
        rename(ftfont, family)
        ftfont.save(tmp)
        thin_with_fontforge(tmp, dst, a.thin, family)
        os.unlink(tmp)
    else:
        rename(ftfont, family)
        ftfont.save(dst)
    print(f"[+] done: {dst} ({os.path.getsize(dst)} bytes)")


if __name__ == "__main__":
    main()
