import assert from 'node:assert/strict';
import {test} from 'node:test';
import {Miniflare} from 'miniflare';
import {fileURLToPath} from 'node:url';

const listing = {
  name: 'Directory test', map: 'downrush', gametype: 'Slayer',
  invite: 'halo://join/' + 'a'.repeat(64),
  player_count: 1, max_players: 16, network_version: 11,
  platform: 'macos', build: 'directory-test',
};

async function setup(t, {inspectStorage = false} = {}) {
  const scriptPath = fileURLToPath(new URL('../worker.mjs', import.meta.url));
  const mf = new Miniflare({
    ...(inspectStorage ? {
      // This fixture exists only in Miniflare; production has no inspection API.
      modules: [{
        type: 'ESModule',
        path: fileURLToPath(new URL('../test-worker.mjs', import.meta.url)),
        contents: `
          import worker, {GameDirectory as Directory} from './worker.mjs';
          // Keep minute-based quota assertions independent of the wall clock.
          const fixtureTime = Date.now();
          Date.now = () => fixtureTime;
          export default worker;
          export class GameDirectory extends Directory {
            async fetch(request) {
              if (new URL(request.url).pathname === '/__test/sql') {
                const {query, bindings} = await request.json();
                return Response.json(this.sql.exec(query, ...bindings).toArray());
              }
              return super.fetch(request);
            }
          }
        `,
      }, {type: 'ESModule', path: scriptPath}],
    } : {modules: true, scriptPath}),
    compatibilityDate: '2026-07-30',
    durableObjects: {DIRECTORY: {className: 'GameDirectory', useSQLite: true}},
  });
  t.after(() => mf.dispose());
  const request = (path, method = 'GET', body, token, address = '192.0.2.1') => {
    const headers = {'CF-Connecting-IP': address};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    return mf.dispatchFetch('https://games.oghalo.com' + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
  };
  let storage;
  if (inspectStorage) {
    const namespace = await mf.getDurableObjectNamespace('DIRECTORY');
    const directory = namespace.get(namespace.idFromName('public-games-v1'));
    storage = {async exec(query, ...bindings) {
      const response = await directory.fetch('https://directory.invalid/__test/sql', {
        method: 'POST', body: JSON.stringify({query, bindings}),
      });
      assert.equal(response.status, 200);
      return response.json();
    }};
  }
  return {mf, request, storage};
}

test('register, list, update, remove; leases and addresses never appear in listings', async (t) => {
  const {request} = await setup(t);
  assert.equal((await request('/health')).status, 200);
  const created = await request('/v1/games', 'POST', listing);
  assert.equal(created.status, 201);
  const lease = await created.json();
  assert.match(lease.lease_token, /^[a-f0-9]{64}$/);
  const listed = await (await request('/v1/games?network_version=11')).json();
  assert.equal(listed.games.length, 1);
  assert.equal(listed.games[0].map, 'downrush');
  const responseText = JSON.stringify(listed);
  assert.ok(!responseText.includes(lease.lease_token));
  assert.ok(!responseText.includes('lease_hash'));
  assert.ok(!responseText.includes('address_hash'));
  assert.ok(!responseText.includes('192.0.2.1'));
  assert.equal((await (await request('/v1/games?network_version=12')).json()).games.length, 0);
  assert.equal((await request(`/v1/games/${lease.id}`, 'PUT', {...listing, player_count: 2}, lease.lease_token)).status, 200);
  assert.equal((await (await request('/v1/games')).json()).games[0].player_count, 2);
  assert.equal((await request(`/v1/games/${lease.id}`, 'DELETE', undefined, lease.lease_token)).status, 204);
  assert.equal((await (await request('/v1/games')).json()).games.length, 0);
});

test('a different host cannot edit or delete a listing; invites are immutable', async (t) => {
  const {request} = await setup(t);
  const lease = await (await request('/v1/games', 'POST', listing)).json();
  const path = `/v1/games/${lease.id}`;
  assert.equal((await request(path, 'PUT', listing)).status, 401);
  assert.equal((await request(path, 'PUT', listing, 'b'.repeat(64))).status, 403);
  assert.equal((await request(path, 'DELETE', undefined, 'b'.repeat(64))).status, 403);
  assert.equal((await request(path, 'PUT', {...listing, invite: 'halo://join/' + 'c'.repeat(64)}, lease.lease_token)).status, 409);
  assert.equal((await (await request('/v1/games')).json()).games.length, 1);
});

test('custom map cache names with spaces can be advertised', async (t) => {
  const {request} = await setup(t);
  const response = await request('/v1/games', 'POST', {...listing, map: 'custom map'});
  assert.equal(response.status, 201);
  assert.equal((await (await request('/v1/games')).json()).games[0].map, 'custom map');
  for (const map of ['x'.repeat(32), '../stock'])
    assert.equal((await request('/v1/games', 'POST', {...listing, map})).status, 400);
});

test('score metadata preserves actual limits, zero, Oddball units, and legacy absence', async (t) => {
  const {request} = await setup(t);
  const lease = await (await request('/v1/games', 'POST', {...listing, score_limit: 50})).json();
  const path = `/v1/games/${lease.id}`;
  const current = async () => (await (await request('/v1/games')).json()).games[0];
  assert.equal((await current()).score_limit, 50);
  assert.equal((await request(path, 'PUT', {...listing, gametype: 'Oddball',
    score_limit: 0, oddball_variant: true}, lease.lease_token)).status, 200);
  assert.equal((await current()).score_limit, 0);
  assert.equal((await current()).oddball_variant, true);
  for (const score_limit of [-1, 32768, true, '50', null, 1.5]) {
    assert.equal((await request(path, 'PUT', {...listing, score_limit}, lease.lease_token)).status, 400);
    assert.equal((await current()).score_limit, 0);
  }
  assert.equal((await request(path, 'PUT', {...listing, oddball_variant: 1}, lease.lease_token)).status, 400);
  assert.equal((await request(path, 'PUT', listing, lease.lease_token)).status, 200);
  assert.ok(!Object.hasOwn(await current(), 'score_limit'));
  assert.equal((await current()).oddball_variant, false);
});

test('expired games disappear and their leases cannot revive them', async (t) => {
  const {request} = await setup(t);
  const lease = await (await request('/v1/games', 'POST', listing)).json();
  // Exercise the actual lease timeout and alarm in Cloudflare's runtime.
  await new Promise((resolve) => setTimeout(resolve, 91_000));
  assert.equal((await (await request('/v1/games')).json()).games.length, 0);
  assert.equal((await request(`/v1/games/${lease.id}`, 'PUT', listing, lease.lease_token)).status, 404);
});

test('reads hide expired games without cleanup writes before the alarm runs', async (t) => {
  const {request, storage} = await setup(t, {inspectStorage: true});
  const expired = await (await request('/v1/games', 'POST', listing)).json();
  const live = await (await request('/v1/games', 'POST', {...listing, name: 'Live game'})).json();
  const registrationMinute = (await storage.exec('SELECT minute FROM registrations'))[0].minute;
  // The registration alarm is still 90 seconds in the future. Set this lease
  // to its exact expiry boundary at the fixed fixture time, so reads cannot
  // rely on alarm cleanup or include a lease whose deadline is now.
  await storage.exec('UPDATE games SET expires_at = updated_at WHERE id = ?', expired.id);
  await storage.exec('UPDATE registrations SET minute = ?', registrationMinute - 3);

  assert.equal((await (await request('/health')).json()).active_games, 1);
  for (const path of ['/v1/games', '/v1/games?network_version=11']) {
    const response = await (await request(path)).json();
    assert.deepEqual(response.games.map((game) => game.id), [live.id]);
  }
  assert.equal((await storage.exec('SELECT COUNT(*) AS count FROM games'))[0].count, 2);
  assert.equal((await storage.exec('SELECT COUNT(*) AS count FROM registrations'))[0].count, 1);

  const path = `/v1/games/${expired.id}`;
  assert.equal((await request(path, 'PUT', listing, expired.lease_token)).status, 404);
  assert.equal((await request(path, 'DELETE', undefined, expired.lease_token)).status, 404);
  assert.equal((await storage.exec('SELECT COUNT(*) AS count FROM games'))[0].count, 2);

  // Registration still removes expired rows and stale quota accounting in its
  // transaction before checking limits and adding the new lease.
  const replacement = await request('/v1/games', 'POST', listing);
  assert.equal(replacement.status, 201);
  assert.equal((await storage.exec('SELECT COUNT(*) AS count FROM games'))[0].count, 2);
  assert.deepEqual(await storage.exec('SELECT minute, count FROM registrations'),
    [{minute: registrationMinute, count: 1}]);
});

test('invalid listings and oversized bodies are rejected', async (t) => {
  const {request} = await setup(t);
  for (const change of [
    {invite: 'https://unrelated.example/'}, {map: '../stock'}, {name: '<script>\n'},
    {player_count: 17}, {network_version: 0}, {open: 'true'},
    {map_sha256: 'bad'}, {platform: 'unknown'},
  ]) assert.equal((await request('/v1/games', 'POST', {...listing, ...change})).status, 400);
  assert.equal((await request('/v1/games', 'POST', {...listing, extra: 'x'.repeat(5000)})).status, 413);
  assert.equal((await request('/v1/games?network_version=65536')).status, 400);
  assert.equal((await (await request('/v1/games')).json()).games.length, 0);
});

test('per-address hosting quota is enforced, including concurrent registrations', async (t) => {
  const {request} = await setup(t);
  const responses = await Promise.all(Array.from({length: 12}, (_, index) =>
    request('/v1/games', 'POST', {...listing, name: `Host ${index}`})));
  assert.equal(responses.filter((response) => response.status === 201).length, 8);
  assert.equal(responses.filter((response) => response.status === 429).length, 4);
  assert.equal((await request('/v1/games', 'POST', listing, undefined, '192.0.2.2')).status, 201);
});

test('removing listings does not reset the per-address registration rate limit', async (t) => {
  const {request} = await setup(t, {inspectStorage: true});
  for (let index = 0; index < 12; index++) {
    const created = await request('/v1/games', 'POST', listing);
    assert.equal(created.status, 201);
    const lease = await created.json();
    assert.equal((await request(`/v1/games/${lease.id}`, 'DELETE', undefined, lease.lease_token)).status, 204);
  }
  const limited = await request('/v1/games', 'POST', listing);
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('Retry-After'), '30');
  assert.equal((await limited.json()).error, 'registration_rate_limited');
});
