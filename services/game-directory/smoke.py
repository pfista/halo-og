"""Check the live directory; remove the synthetic listing even on failure."""
import json
import secrets
import urllib.error
import urllib.request

BASE = "https://games.oghalo.com"


def request(path, method="GET", value=None, token=None):
    headers = {"User-Agent": "Halo-OG-Directory-Smoke/1"}
    data = None
    if value is not None:
        data = json.dumps(value).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def main():
    health_status, health = request("/health")
    assert health_status == 200 and health["ok"], (health_status, health)
    print("HTTPS and Durable Object health: passed")
    listing = {
        "name": "Directory deployment check", "map": "downrush", "gametype": "Slayer",
        "invite": "halo://join/" + secrets.token_hex(32), "player_count": 1,
        "max_players": 16, "network_version": 11, "platform": "linux", "build": "service-smoke",
        "score_limit": 50, "oddball_variant": False,
    }
    status, lease = request("/v1/games", "POST", listing)
    assert status == 201, (status, lease.get("error"))
    path = "/v1/games/" + lease["id"]
    try:
        status, games = request("/v1/games?network_version=11")
        assert status == 200
        matched = next(game for game in games["games"] if game["id"] == lease["id"])
        assert matched["score_limit"] == 50 and matched["oddball_variant"] is False
        assert lease["lease_token"] not in json.dumps(games)
        status, filtered = request("/v1/games?network_version=65535")
        assert status == 200 and all(game["id"] != lease["id"] for game in filtered["games"])
        print("Registration, public listing, protocol filtering, credential privacy: passed")
        assert request(path, "PUT", listing, "0" * 64)[0] == 403
        assert request(path, "DELETE", token="0" * 64)[0] == 403
        status, updated = request(path, "PUT", {**listing, "player_count": 2}, lease["lease_token"])
        assert status == 200, (status, updated)
        status, games = request("/v1/games")
        assert status == 200
        matched = next(game for game in games["games"] if game["id"] == lease["id"])
        assert matched["player_count"] == 2 and matched["score_limit"] == 50
        print("Ownership checks and heartbeat update: passed")
    finally:
        status, _ = request(path, "DELETE", token=lease["lease_token"])
        assert status in (204, 404), ("test listing cleanup failed", status)
    status, remaining = request("/v1/games")
    assert status == 200 and all(game["id"] != lease["id"] for game in remaining["games"])
    print("Synthetic listing removed: passed")


if __name__ == "__main__":
    main()
