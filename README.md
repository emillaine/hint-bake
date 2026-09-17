# hint-bake

Bake a font's TrueType hinting into its outlines for one size.

Some renderers ignore TrueType hints entirely (e.g. macOS Core Text), so a
well-hinted font can look blurry or off-shape there. This script runs the
font's real native hints in FreeType at your target size and writes the
grid-fitted outlines back into a new font, which then renders the same
shapes anywhere -- no hinter required.

Works with any TrueType-flavored font (`glyf` table). Best with fonts that
carry hint bytecode (`cvt`/`fpgm`); without it the script warns and the
output equals the unhinted shapes.

## Motivation

Fonts like Microsoft's **Consolas** were hinted for **Windows ClearType**,
but **macOS** Core Text ignores those hints, so the same font looks
off-shape there. This freezes the ClearType shapes into plain outlines so
your programming font keeps its hinted forms on a Mac (same shapes, not
pixel-crisp -- macOS still smooths in grayscale).

## Requirements

```sh
pip install fonttools freetype-py
```

Only `--thin` needs more: FontForge (e.g. `brew install fontforge`).

## Usage

```sh
python3 hint_bake.py INPUT.ttf --pt 20.5 --dpi 72 --thin 35
python3 hint_bake.py INPUT.ttf --pt 12 --dpi 96 --thin 0 --output Out.ttf
```

* `--pt`: target point size, fractions allowed (required).
* `--dpi`: target resolution, default `72` (macOS: 1pt = 1px). Use `96` for Windows sizes, e.g. 21pt @ 96dpi = 28px.
* `--thin`: stem thinning in font units, default `0` (off). `20-35` suits ~20px text (1px ~= `upm / px` units). Requires FontForge.
* `--interp`: hinter version: `40` = DirectWrite (default), `35` = GDI classic.
* `--mode`: hinting target: `normal` (default), `light`, `mono`, `lcd`.
* `--family`: new family name (default: `<orig> Baked <pt>pt`).
* `--output`: output path (default: `<input>-<pt>pt-<dpi>dpi-baked.ttf`).

## How it works

1. Sets the FreeType char size from `--pt`/`--dpi` (fractional sizes supported).
2. Loads every glyph with the font's native hinter and reads back the fitted outline + advance.
3. Rescales from pixels to the font's units-per-em and rewrites `glyf`/`hmtx`.
4. Strips the now-redundant hint bytecode (`fpgm`, `prep`, `cvt`, `hdmx`, `VDMX`, `LTSH`) and the `DSIG` signature, sets `gasp` to grayscale without gridfitting, and renames the family so the bake installs side-by-side with the original.
5. With `--thin`, erodes stems via FontForge `changeWeight`; advances are untouched, so monospace stays monospace.

Note: TrueType hints snap to integer pixels-per-em, so e.g. 20.5pt @ 72dpi
is hinted at 21ppem and scaled -- the script reports the rounded ppem.

## License note

Bring your own font file: the script only transforms it locally. Do not
redistribute the output unless the input font's license allows derivatives
(many commercial fonts, e.g. Microsoft's, prohibit this -- use such bakes
for yourself and share the script instead).

Related: [fonttools-opentype-hinting-freezer](https://github.com/twardoch/fonttools-opentype-hinting-freezer)
does integer-ppem freezing as a maintained package; this script adds
fractional pt/dpi sizing, stem thinning, and side-by-side renaming.
