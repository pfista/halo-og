# Halo OG app icon

Selected by the user on October 4, 2026 using an attached image: the original
dark-background concept with weathered olive armor, a gold visor, and a subtle
etched "Halo OG" on the visible side. Preserve the selected render's weathering
and dark green background; no finish refinement was applied.

Created from scratch with OpenAI's built-in image generation tool; no original
game artwork was supplied as an input. The tool did not expose a model version.

The selected render was exported as an opaque 1024 × 1024 PNG at
`Assets.xcassets/AppIcon.appiconset/AppIcon.png`. iOS uses that asset directly;
`tools/macos_build.py` derives `AppIcon.icns` from the same image for Mac builds.
Keep the canvas square with no baked rounded corners.

## Generation prompt

This is the original request that produced the selected render. Its requested
graphite finish rendered as weathered olive, which the user explicitly chose.

```text
Use case: stylized-concept
Asset type: a new premium macOS game app icon concept, square 1:1 canvas.
Primary request: Create a fresh modern interpretation of Master Chief's original Halo Combat Evolved Mark V helmet, recognizable olive armored sci-fi helmet silhouette and iconic wide gold visor, newly rendered art from scratch.
Subject: Helmet only, no torso, no human face. Bold angular brow, characteristic side armor and chin, refined strong silhouette.
Composition/framing: One large centered helmet in a subtle three-quarter view, showing enough of one side for a small etched inscription. Entire helmet visible with generous consistent safe margin, approximately 76% of canvas height. Designed to remain legible at small Dock sizes. Fill the square canvas with background; no device mockup, no sheet, no multiple icons, no caption or border.
Text (verbatim): "Halo OG". Tiny subtle laser-etched lettering on the visible temple-side armor panel, precise H a l o space O G, recessed tone-on-tone lettering catching a faint edge highlight, around 5% of overall image width; it must look physically engraved into armor, never a large headline or floating wordmark. This is the only text.
Constraints: original generated artwork, clean modern app-icon polish, highly readable silhouette and visor, limited surface details, no watermark, no official logo, no numbers, no weapons, no extra objects.
Style/medium: Premium contemporary 3D app icon, sculptural angular helmet with simplified original Mark V proportions and precise machined forms.
Scene/backdrop: Very dark graphite-to-black smooth background with a restrained soft olive glow, no scenery.
Color palette: Deep desaturated green graphite armor, bright warm champagne-gold visor, muted olive accents.
Materials/textures: Satin graphite ceramic armor, refined brushed metal bevels, black joints, smooth metallic visor with one broad elegant reflection. Avoid busy scratches.
Lighting/mood: Cinematic but clearly lit, clean gold visor accent, subtle cool green rim light around outer silhouette, broad readable illuminated armor planes. Helmet must not vanish into background.
```
