"""Deploy only the Halo OG directory, using an approved 1Password mount."""
import argparse
import json
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "wrangler.jsonc").read_text())
HOSTNAME = "games.oghalo.com"


def load_token(path):
    for line in Path(path).read_text().splitlines():
        if line.startswith("CLOUDFLARE_WORKERS_API_TOKEN="):
            token = line.split("=", 1)[1].strip().strip("\"'")
            if token:
                return token
    raise SystemExit("CLOUDFLARE_WORKERS_API_TOKEN is missing from the approved mount")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, help="Existing approved 1Password mount")
    parser.add_argument("--check", action="store_true", help="Check access without deploying")
    args = parser.parse_args()
    token = load_token(args.env_file)

    def api(method, path, value=None, raw=None, content_type=None, allow_missing=False):
        headers = {"Authorization": "Bearer " + token}
        if raw is not None:
            data = raw
            headers["Content-Type"] = content_type
        elif value is not None:
            data = json.dumps(value).encode()
            headers["Content-Type"] = "application/json"
        else:
            data = None
        request = urllib.request.Request("https://api.cloudflare.com/client/v4" + path,
                                         data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_missing:
                return None
            details = json.load(error)
            raise SystemExit(json.dumps({"operation": method + " " + path,
                                         "status": error.code, "errors": details.get("errors")})) from None
        if not result.get("success"):
            raise SystemExit(json.dumps({"operation": method + " " + path, "errors": result.get("errors")}))
        return result.get("result")

    account = CONFIG["account_id"]
    worker = CONFIG["name"]
    base = f"/accounts/{account}/workers"
    zones = api("GET", "/zones?name=oghalo.com")
    if len(zones) != 1 or zones[0]["account"]["id"] != account:
        raise SystemExit("The credential must cover oghalo.com in the configured Halo account")
    zone = zones[0]["id"]
    existing = api("GET", f"{base}/scripts/{worker}/settings", allow_missing=True)
    domains = api("GET", f"{base}/domains")
    assigned = next((domain for domain in domains if domain.get("hostname") == HOSTNAME), None)
    if assigned and assigned.get("service") != worker:
        raise SystemExit("games.oghalo.com already belongs to another Worker; no changes made")
    records = api("GET", f"/zones/{zone}/dns_records?name={HOSTNAME}")
    if records and not assigned:
        raise SystemExit("games.oghalo.com has an existing DNS record; no changes made")
    print(json.dumps({"access_verified": True, "worker": worker, "hostname": HOSTNAME,
                      "worker_exists": existing is not None}))
    if args.check:
        return

    metadata = {
        "main_module": "worker.mjs",
        "compatibility_date": CONFIG["compatibility_date"],
        "bindings": [{"type": "durable_object_namespace", "name": "DIRECTORY", "class_name": "GameDirectory"}],
    }
    if existing is None:
        metadata["migrations"] = {"new_tag": "v1", "new_sqlite_classes": ["GameDirectory"]}
    else:
        # Settings responses do not always include migration_tag. Pin the
        # existing namespace instead of creating or migrating storage again.
        bindings = existing.get("bindings", [])
        binding = next((item for item in bindings if item.get("name") == "DIRECTORY"), None)
        if (existing.get("migration_tag") not in (None, "v1") or not binding or
                binding.get("type") != "durable_object_namespace" or
                binding.get("class_name") != "GameDirectory" or not binding.get("namespace_id")):
            raise SystemExit("Unexpected Durable Object binding; refusing to overwrite this Worker")
        metadata["bindings"][0]["namespace_id"] = binding["namespace_id"]
    boundary = "halo-og-" + secrets.token_hex(16)
    body = bytearray()
    for name, filename, mime, data in [
        ("metadata", "metadata.json", "application/json", json.dumps(metadata).encode()),
        ("worker.mjs", "worker.mjs", "application/javascript+module", (ROOT / "worker.mjs").read_bytes()),
    ]:
        body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                     f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n").encode())
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    deployed = api("PUT", f"{base}/scripts/{worker}", raw=bytes(body),
                   content_type="multipart/form-data; boundary=" + boundary)
    print(json.dumps({"worker_uploaded": True, "worker_id": deployed.get("id")}))
    domain = api("PUT", f"{base}/domains", {"hostname": HOSTNAME, "service": worker,
                 "environment": "production", "zone_id": zone})
    api("POST", f"{base}/scripts/{worker}/subdomain", {"enabled": False, "previews_enabled": False})
    print(json.dumps({"custom_domain_attached": True, "hostname": domain.get("hostname"),
                      "url": "https://" + HOSTNAME, "workers_dev_enabled": False}))


if __name__ == "__main__":
    main()
