#!/usr/bin/env python3
"""Check production Mac HTTPS + shared directory protocol against the live service.

Creates one synthetic listing and removes it in finally. No game assets,
personal settings, invite passwords, or deployment credentials are needed.
"""
import ctypes
import json
from pathlib import Path
import secrets
import subprocess
import tempfile

from test_game_directory import Game

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://games.oghalo.com"


def main():
    with tempfile.TemporaryDirectory(prefix="halo-directory-native-") as folder:
        library = Path(folder) / "directory.dylib"
        subprocess.run([
            "clang", "-dynamiclib", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra",
            "-Wno-unused-parameter", "-Iport/linux/src", "port/macos/native/HaloDirectoryHTTP.m",
            "port/linux/src/directory_protocol.c", "-framework", "Foundation", "-o", str(library),
        ], cwd=ROOT, check=True)
        lib = ctypes.CDLL(str(library))
        lib.halo_directory_http.argtypes = [ctypes.c_char_p] * 4 + [
            ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.halo_directory_parse_games.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                                    ctypes.POINTER(Game), ctypes.c_int]
        lib.halo_directory_encode.argtypes = [ctypes.POINTER(Game), ctypes.c_char_p, ctypes.c_int]

        def request(method, path, body=None, lease=None, capacity=256 * 1024):
            buffer = ctypes.create_string_buffer(capacity)
            status = ctypes.c_int()
            count = lib.halo_directory_http(method.encode(), (BASE + path).encode(), lease,
                                            body, buffer, capacity, ctypes.byref(status))
            assert count >= 0, "Native HTTPS request failed"
            return status.value, buffer.raw[:count]

        game = Game(name=b"Native directory smoke", map=b"custom map", gametype=b"Slayer",
                    invite=("halo://join/" + secrets.token_hex(32)).encode(), player_count=1,
                    max_players=16, network_version=11, open=1, score_limit=50)
        encoded = ctypes.create_string_buffer(1024)
        assert lib.halo_directory_encode(ctypes.byref(game), encoded, len(encoded))
        status, response = request("POST", "/v1/games", encoded.value)
        assert status == 201, (status, json.loads(response).get("error"))
        lease = json.loads(response)
        token = lease["lease_token"].encode()
        path = "/v1/games/" + lease["id"]
        try:
            status, response = request("GET", "/v1/games")
            games = (Game * 64)()
            count = lib.halo_directory_parse_games(response, len(response), games, 64)
            assert status == 200 and count >= 1
            matched = next(games[i] for i in range(count) if games[i].id.decode() == lease["id"])
            assert matched.score_limit == 50 and matched.oddball_variant == 0
            assert token not in response
            print("PASS native HTTPS registration and shared listing parser")
            assert request("PUT", path, encoded.value, b"0" * 64)[0] == 403
            assert request("PUT", path, encoded.value, token)[0] == 200
            print("PASS native lease ownership and heartbeat")
            # A tiny buffer must fail instead of overflowing or truncating JSON.
            buffer = ctypes.create_string_buffer(8); code = ctypes.c_int()
            assert lib.halo_directory_http(b"GET", (BASE + "/v1/games").encode(), None,
                                            None, buffer, 8, ctypes.byref(code)) == -1
            print("PASS native response cap")
        finally:
            assert request("DELETE", path, lease=token)[0] in (204, 404)
            print("PASS synthetic listing removed")


if __name__ == "__main__":
    main()
