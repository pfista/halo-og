# Fonts

Halo OG selectively imports these fonts and notices from cybersecurity's
[0182da817285b67eee8264663ca79f7c32d66b5e](https://github.com/cybersecurity/halo-ce-universal/commit/0182da817285b67eee8264663ca79f7c32d66b5e)
at the user's request. They are enabled by Asset Quality: Upres; Original
keeps the maps' fonts and artwork. OpenCE is an internal
typeface filename only: this import changes no visible branding, original
menu words or menu structure.

The fonts the game's text is drawn with, at the display's resolution, in
place of the bitmap fonts of the maps (`port/linux/src/text_hires.c`).
`fonts.json` says which font draws each of the maps' font tags.

| File | Draws | From |
| --- | --- | --- |
| `OGMenuLarge.ttf` | `ui\large_ui` | Halo OG: rebuilt from that tag's own letters (`tools/og_font.py`) |
| `OGMessage.ttf` | `ui\interstate` | Halo OG: rebuilt from that tag's own letters, which are `ui\large_ui`'s set one pixel closer |
| `OGMenuSmall.ttf` | `ui\small_ui` | Halo OG: rebuilt from that tag's own letters |
| `OGConsole.ttf` | the version label on the main menu, at three quarters of its size | Halo OG: rebuilt from the console's font, `old tags\internal system plain` |
| `Overpass-900.ttf`, `Overpass-750.ttf` | nothing in the game; the text tests' substitute typeface | Overpass, weights 900 and 750 |
| `OpenCE-Regular.ttf` | the menus' titles, as pictures (`port/assets/titles`) | OpenCE: Newtown, respaced for this project (`tools/title_font.py`) |
| `Newtown-Regular.ttf` | (OpenCE's source) | Newtown by Roger White, unmodified |

The OG fonts are work in progress and under review letter by letter.
Each is drawn from its font tag's pixels alone, with no other typeface:
`tools/og_font.py` decodes the tag's 16 stored levels to the share of each
pixel a letter covers, finds the smoothest shape that every pixel would store
the same way, and writes its outline with the tag's own advances, 64 font
units to the pixel. `--weight` moves every edge out by a part of a pixel: the
maps store faint pixels brighter than their share, so the original reads
heavier on screen than its true shape. The large and message fonts are at
their true weight, as chosen in review; the small and console fonts carry
0.15 of a pixel until theirs is chosen. To rebuild them (NumPy, Pillow,
potracer and fontTools, and game data):

    python3 tools/og_font.py --output port/assets/fonts --fonts 'ui\large_ui,ui\interstate'
    python3 tools/og_font.py --output port/assets/fonts --weight 0.15 \
      --fonts 'ui\small_ui,old tags\internal system plain'

`fonts.json` marks them with `units_per_pixel`, and the game then draws each
glyph from the pen, where its outline lies. A font without it is a substitute
typeface: sized by the tag's capital height and fitted into each original
glyph's ink. Overpass was that substitute through 0.6. The maps' fonts are
Interstate (Tobias Frere-Jones, The Font Bureau), a commercial typeface that
cannot be shipped, and Overpass (Red Hat, Delve Withrington) follows the same
Highway Gothic road-sign alphabet under the SIL Open Font License 1.1
(`Overpass-OFL.txt`). It stays here for the tests of the substitute path.

To compare a font with the maps' own letters run
`python3 tools/font_lab.py --output build/font-lab/<new folder>`, with
`--review` for the short page.

The menus' titles are pictures of text in the maps, set in another
commercial typeface. OpenCE (Open Community Edition) stands in for it:
Newtown, a typeface in the same style by Roger White (1994), which its author
released into the public domain (`Newtown-LICENSE.txt` quotes his statement
and where it is archived), respaced for this project. Only its spacing is
changed, its outlines are Newtown's: each letter's side spaces and the
kerning pairs are measured from where the letters sit in the maps' titles.
OpenCE is under the SIL Open Font License 1.1 (`OpenCE-OFL.txt`), without a
Reserved Font Name. It is not embedded: `tools/title_assets.py` draws the
titles with it, and the builds embed those pictures. To measure its spacing
again and rebuild it:

    python3 tools/title_font.py --measure    # paste the values into tools/title_font.py
    python3 tools/title_font.py
    python3 tools/title_assets.py --map assets/maps/ui.map

The Overpass files are static instances of Google Fonts' variable Overpass
(`ofl/overpass/Overpass[wght].ttf`, google/fonts commit
9710da1eacb3be272583c3224dcb70f9da6eadbb), made with fontTools:

    python3 -m fontTools.varLib.instancer 'Overpass[wght].ttf' wght=900 -o Overpass-900.ttf
    python3 -m fontTools.varLib.instancer 'Overpass[wght].ttf' wght=750 -o Overpass-750.ttf

The builds embed the fonts `fonts.json` lists (`tools/embed_assets.py`). The
release packages still carry `Overpass-OFL.txt`.
