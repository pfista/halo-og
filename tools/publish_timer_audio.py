#!/usr/bin/env python3
"""Validate optional third-party timer audio; publish only with both explicit flags."""
import argparse
import hashlib
from pathlib import Path
import re
import sys

if __package__:
    from .publish_map_catalog import HTTPS, R2, PublishError, derive_s3_credentials, load_token, parse_json, read_regular
    from .timer_audio_pack import MANIFEST_KEY, MAX_MANIFEST_BYTES, validate_prepared
else:
    from publish_map_catalog import HTTPS, R2, PublishError, derive_s3_credentials, load_token, parse_json, read_regular
    from timer_audio_pack import MANIFEST_KEY, MAX_MANIFEST_BYTES, validate_prepared

DEFAULT_CONFIG = Path(__file__).with_name("timer-audio-publisher.json")
CONFIG = {"schema_version": 1, "account_id": "39353b0c2249998b78adc016897ef725", "bucket": "halo",
          "public_base_url": "https://dl.oghalo.com/", "manifest_key": MANIFEST_KEY}


def load_config(path=DEFAULT_CONFIG):
    config = parse_json(read_regular(path, 16384))
    if not isinstance(config, dict) or config != CONFIG or type(config.get("schema_version")) is not int:
        raise PublishError("Timer publisher configuration must match the pinned account, bucket and audio destination")
    return config


def require_exact(response, data, label, *, manifest_pending=True):
    state = "; manifest was not advanced" if manifest_pending else "; manifest publication may already have completed"
    if response.status != 200:
        raise PublishError(f"{label} failed (HTTP {response.status})" + state)
    if len(response.body) != len(data) or hashlib.sha256(response.body).digest() != hashlib.sha256(data).digest():
        raise PublishError(label + " has different bytes" + state)


def publish(prepared, config, r2, http, *, redistribution_approved=False, progress=print):
    if not redistribution_approved:
        raise PublishError("Timer audio publication requires explicit redistribution approval")
    if config != CONFIG or type(config.get("schema_version")) is not int:
        raise PublishError("Timer publication is limited to the pinned audio destination")
    current = validate_prepared(prepared.directory)
    if current != prepared:
        raise PublishError("Prepared timer pack changed after validation; manifest was not advanced")
    # Keep the current manifest's ETag before any immutable object is created.
    old = r2.request("GET", config["manifest_key"], limit=MAX_MANIFEST_BYTES)
    if old.status == 404:
        condition = {"If-None-Match": "*"}
    elif old.status == 200 and re.fullmatch(r'"[A-Za-z0-9_-]{1,128}"', old.headers.get("etag", "")):
        condition = {"If-Match": old.headers["etag"]}
    else:
        raise PublishError(f"Cannot safely inspect the current timer manifest (HTTP {old.status})")
    for entry in prepared.files:
        key, cue = entry["object_key"], entry["cue"]
        wav = read_regular(prepared.directory / key, entry["file_bytes"])
        if len(wav) != entry["file_bytes"] or hashlib.sha256(wav).hexdigest() != entry["sha256"]:
            raise PublishError("Prepared timer WAV changed after validation; manifest was not advanced")
        existing = r2.request("GET", key, limit=len(wav))
        if existing.status == 404:
            for attempt in range(1, 4):
                try:
                    result = r2.request("PUT", key, body=wav, headers={"If-None-Match": "*",
                                        "Content-Type": "audio/wav", "Cache-Control": "public, max-age=31536000, immutable"})
                except PublishError:
                    try:
                        existing = r2.request("GET", key, limit=len(wav))
                        if existing.status == 404 and attempt < 3:
                            progress(f"Retrying immutable timer cue {cue} after missing readback (attempt {attempt + 1}/3)")
                            continue
                        require_exact(existing, wav, "Immutable timer cue " + cue)
                    except PublishError:
                        raise PublishError(f"Immutable timer cue {cue} upload response failed and stored bytes could not be verified; manifest was not advanced") from None
                else:
                    if result.status not in (200, 201, 204, 409, 412):
                        raise PublishError(f"Immutable timer upload failed (HTTP {result.status}); manifest was not advanced")
                    existing = r2.request("GET", key, limit=len(wav))
                break
        require_exact(existing, wav, "Immutable timer cue " + cue)
        public = http.request("GET", config["public_base_url"] + key,
                              headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"}, limit=len(wav))
        require_exact(public, wav, "Public timer cue " + cue)
        progress("Verified public timer cue " + cue)
    if validate_prepared(prepared.directory) != prepared:
        raise PublishError("Prepared timer pack changed during publication; manifest was not advanced")
    if old.status != 200 or old.body != prepared.manifest:
        try:
            result = r2.request("PUT", config["manifest_key"], body=prepared.manifest,
                                headers={**condition, "Content-Type": "application/json", "Cache-Control": "no-cache"})
        except PublishError:
            raise PublishError("Timer manifest upload response failed; publication may already have completed. Inspect the current manifest before retrying") from None
        if result.status in (409, 412):
            raise PublishError("Current timer manifest changed during publication; it was not overwritten. Validate and retry")
        if result.status not in (200, 201, 204):
            raise PublishError(f"Timer manifest publication failed (HTTP {result.status})")
    private = r2.request("GET", config["manifest_key"], limit=MAX_MANIFEST_BYTES)
    require_exact(private, prepared.manifest, "Published timer manifest", manifest_pending=False)
    public = http.request("GET", config["public_base_url"] + config["manifest_key"],
                          headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"}, limit=MAX_MANIFEST_BYTES)
    if public.status != 200 or public.body != prepared.manifest:
        raise PublishError(f"R2 timer manifest matches prepared bytes but exact public verification failed (HTTP {public.status}); inspect CDN caching before retrying")
    progress("Published and verified " + config["public_base_url"] + config["manifest_key"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--credential-file", type=Path, help="Existing 1Password-mounted literal token file")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--redistribution-approved", action="store_true", help="Operator confirms rights to distribute the reviewed recordings")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        prepared = validate_prepared(args.prepared)
        print(f"Validated {len(prepared.files)} optional timer cues for {config['bucket']}/{config['manifest_key']}")
        if not args.publish:
            print("Local validation only; no credentials read or network requests made.")
            return
        if not args.redistribution_approved:
            raise PublishError("--publish also requires --redistribution-approved; source ownership alone is not a redistribution rights record")
        token = load_token(args.credential_file)
        http = HTTPS()
        access, secret = derive_s3_credentials(token, config, http)
        del token
        publish(prepared, config, R2(config, access, secret, http), http, redistribution_approved=True)
    except (PublishError, OSError, ValueError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, PublishError) else "Local timer input could not be read or validated"
        parser.exit(1, "Timer publication failed: " + message + "\n")


if __name__ == "__main__":
    main()
