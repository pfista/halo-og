# Optional timer recordings

Timer Audio is a separate optional third-party extra. The recordings are not
bundled in the app, maps or tag files, and are not part of the original Xbox
baseline. The client stores reviewed WAVs under its save root's
`sounds/performance` directory. Timer Audio should remain off unless selected.

The local recordings in `assets/sounds/performance` were imported from existing
user-owned extracted sound tags. Their import manifest records conversion
provenance, **not redistribution permission or authorship**. The operator confirmed
permission to rehost these recordings on October 4, 2026. Keep that confirmation
with the local pack evidence, outside the prepared object directory; it does not
change the manifest or establish an independent third-party license record.
Preparing or validating a different pack does not authorize uploading it.

## Install the recordings

Mac, Windows, Linux and Android download recordings automatically in the
background by default after game data is selected. On Mac, **Halo OG → Settings**
shows progress and lets you opt out or retry a failed download. On Windows,
Linux and Android, set `auto_download = false` under `[timer_audio]` in
`config.toml` to opt out. Restart Halo OG after the first installation
before enabling Timer Sounds in the host's game type. Downloading recordings
does not change game options.
The pack contains 46 clips, about 7.4 MB, downloaded from Cloudflare over HTTPS.
Each clip is checked against its exact size, SHA-256 and PCM format; the complete
pack becomes available together. A failed or cancelled download can be retried.

The managed pack lives at `sounds/performance` under the saves folder. A complete
user-provided pack in the selected game-data folder takes priority. Existing
recordings are preserved; a conflicting managed folder must be moved manually
before downloading a replacement. Availability is fixed for each game launch
to keep network capabilities consistent, so restart after installation.

An explicit helper is also available for offline preparation or troubleshooting.
With Python 3 and this repository, download the same verified pack into a
selected game-data or saves folder:

```sh
python3 tools/download_timer_audio.py \
  --destination "/path/to/game-data-or-saves/sounds/performance"
```

Choose a destination that does not already exist. The helper installs all 46
recordings together and preserves existing files. For Android, download on a
computer and copy the completed `sounds/performance` folder into the game's
data folder. Restart Halo OG after copying it.

## Prepare and inspect locally

```sh
python3 tools/timer_audio_pack.py \
  --source assets/sounds/performance --output build/timer-audio/prepared
python3 tools/publish_timer_audio.py --prepared build/timer-audio/prepared
```

Preparation requires exactly the 46 canonical cues in
`tools/import_performance_audio.py`. Each WAV must have the canonical 44-byte
PCM header, 16-bit mono/stereo samples at 22050 or 44100 Hz, no extra chunks,
positive sample data, at most four seconds and at most 1 MiB. The pack may not
exceed 32 MiB. Symlinks, missing/extra files and existing output destinations
are rejected. Staging publishes the complete local directory atomically;
existing directories are preserved. The optional `import-manifest.json` remains
in the source directory and is excluded from the publishable tree.

The prepared directory contains only `manifest.json` and immutable objects at
`audio/timer/sha256/<sha256>/<cue>.wav`. The exact manifest schema is:

```json
{
  "schema_version": 1,
  "pack_id": "performance-timer-v1",
  "files": [
    {
      "cue": "timerbeep",
      "file_bytes": 9772,
      "sha256": "<64 lowercase hexadecimal characters>",
      "object_key": "audio/timer/sha256/<sha256>/timerbeep.wav"
    }
  ]
}
```

The example shows one entry; a valid manifest requires every canonical cue
exactly once and no additional fields. Manifest size is bounded to 64 KiB.

## Authorized publication

`tools/timer-audio-publisher.json` pins the existing Cloudflare account, `halo`
bucket and `https://dl.oghalo.com/` origin. The separate timer manifest destination
is `https://dl.oghalo.com/audio/timer/v1/current.json`. Map catalogs and allowlists
are unchanged.

Default invocation validates locally, reads no credentials and makes no network
requests. An authorized upload requires **both** `--publish` and
`--redistribution-approved`, plus the operator's recorded permission to distribute
the selected recordings. Use an existing 1Password-mounted credential file from
the approved `oghalo.com` developer environment; never copy token values into
config or logs. The existing credential parser, HTTPS transport and R2 signing
are shared with the map publisher. Credential files are read as data, never
executed.

Objects use conditional create-only writes and must match through private R2
and public HTTPS reads before the mutable manifest advances with its captured
ETag. An ambiguous object upload is recovered only through exact readback;
definitely missing objects permit up to three conditional attempts. Manifest
writes are never blindly retried. A failed verification after the manifest PUT
can leave it published; inspect R2/CDN state before retrying. No delete or rollback
operation is performed by this publisher.
