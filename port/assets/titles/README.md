# Optional menu title redraws

These 34 PNGs and `titles.json` were imported from cybersecurity's
[0182da817285b67eee8264663ca79f7c32d66b5e](https://github.com/cybersecurity/halo-ce-universal/commit/0182da817285b67eee8264663ca79f7c32d66b5e).
They preserve the English Xbox title words, bitmap dimensions and letter
positions. `titles.json` records the original first-mip CRC so modified or
other-language bitmaps retain their original artwork.

All 34 entries were checked against the local English Xbox `assets/maps/ui.map`:
original dimensions, format and first-mip CRC match exactly. The verified map's
SHA-256 is `35e3e560478d85178749be310ad13d6d6ecde618d32675261a3554592333a833`.
`tools/test_menu_assets.py` repeats this check when that local map is available.

Most pictures are four times the original dimensions; the widest is twice
the original dimensions, capped at 2048 pixels. OpenCE is a respaced Newtown
font substitute, not recovered Bungie artwork. See
[font provenance](../fonts/README.md). The original menu positions, sizes
and strings remain controlled by the game's tags.

Halo OG's Asset Quality setting selects these redraws together with the HUD
and dynamic text. Original is the default. No postgame panel, menu layout or
rebranding changes from later upstream commits are included.

Rebuild from an English Xbox UI map with `tools/title_assets.py`; its image
analysis needs Pillow, NumPy and SciPy. The committed PNGs are embedded by
`tools/embed_assets.py`, so building or running the game needs none of those
image analysis packages.
