# Community-map reconstruction: set aside

Local reconstruction and package-only distribution have been set aside. The
current desktop release downloads complete playable `.map` files from Cloudflare
R2, including their normal embedded Halo dependencies. No Invader tools, tag
extraction, or `.mapog` expansion are required by players.

See [playtesting](playtesting.md#community-maps) for automatic downloads and
[map publishing](map-publishing.md) for the live complete-map catalog.

The earlier `.hogpkg` developer prototype and its optional native helper build
scripts remain available for reference. They are not enabled in the player UI,
not bundled by the default release builds, and not part of the release path.
The helper workflow is manual only. The compressed `.mapog` runtime has been
removed. Neither these prototypes nor the hosted complete maps establish that
community maps contain only community-authored assets.
