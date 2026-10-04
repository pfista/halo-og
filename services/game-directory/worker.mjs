const TTL_SECONDS = 90;
const HEARTBEAT_SECONDS = 30;
const MAX_GAMES = 256;
const MAX_GAMES_PER_ADDRESS = 8;
const MAX_BODY_BYTES = 4096;
const MAX_CREATES_PER_MINUTE = 12;
const encoder = new TextEncoder();

class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
  }
}

function json(value, status = 200, extra = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      ...extra,
    },
  });
}

async function digest(value) {
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value)));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function text(value, name, maximum, required = true) {
  if (value === undefined && !required) return '';
  if (typeof value !== 'string' || value.length > maximum || /[^\x20-\x7e]/.test(value)) {
    throw new ApiError(400, `invalid_${name}`);
  }
  const result = value.trim();
  if (required && !result) throw new ApiError(400, `invalid_${name}`);
  return result;
}

function integer(value, name, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new ApiError(400, `invalid_${name}`);
  }
  return value;
}

function boolean(value, name, fallback) {
  if (value === undefined) return fallback;
  if (typeof value !== 'boolean') throw new ApiError(400, `invalid_${name}`);
  return value;
}

function validateListing(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new ApiError(400, 'invalid_listing');
  const invite = text(body.invite, 'invite', 76).toLowerCase();
  if (!/^halo:\/\/join\/[0-9a-f]{64}$/.test(invite)) throw new ApiError(400, 'invalid_invite');
  const map = text(body.map, 'map', 32);
  if (map.length > 31 || !/^[a-zA-Z0-9_-][a-zA-Z0-9_ -]*$/.test(map) || map.endsWith(' ')) {
    throw new ApiError(400, 'invalid_map');
  }
  const maximum = integer(body.max_players, 'max_players', 1, 128);
  const platform = text(body.platform, 'platform', 16, false);
  if (platform && !['macos', 'windows', 'linux', 'android', 'ios'].includes(platform)) {
    throw new ApiError(400, 'invalid_platform');
  }
  const checksum = text(body.map_sha256, 'map_sha256', 64, false).toLowerCase();
  if (checksum && !/^[0-9a-f]{64}$/.test(checksum)) throw new ApiError(400, 'invalid_map_sha256');
  if (body.netcode !== undefined && body.netcode !== 'distributed') throw new ApiError(400, 'invalid_netcode');
  return {
    name: text(body.name, 'name', 32),
    map,
    gametype: text(body.gametype, 'gametype', 24),
    player_count: integer(body.player_count, 'player_count', 0, maximum),
    max_players: maximum,
    network_version: integer(body.network_version, 'network_version', 1, 65535),
    netcode: 'distributed',
    platform,
    build: text(body.build, 'build', 64, false),
    map_sha256: checksum,
    open: boolean(body.open, 'open', true),
    in_progress: boolean(body.in_progress, 'in_progress', false),
    has_teams: boolean(body.has_teams, 'has_teams', false),
    invite,
  };
}

async function readListing(request) {
  if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
    throw new ApiError(415, 'json_required');
  }
  if (Number(request.headers.get('Content-Length')) > MAX_BODY_BYTES) throw new ApiError(413, 'listing_too_large');
  if (!request.body) throw new ApiError(400, 'invalid_json');
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      throw new ApiError(413, 'listing_too_large');
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let body;
  try { body = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)); }
  catch { throw new ApiError(400, 'invalid_json'); }
  return validateListing(body);
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === 'GET' && url.pathname === '/') {
        return json({
          service: 'Halo OG game directory',
          api_version: 1,
          games: '/v1/games',
          health: '/health',
          heartbeat_seconds: HEARTBEAT_SECONDS,
          expiry_seconds: TTL_SECONDS,
          transport: 'direct-p2p',
          client_integration: 'native-desktop-source',
        });
      }
      if (!/^\/(?:health|v1\/games(?:\/[0-9a-f-]{36})?)$/.test(url.pathname)) {
        throw new ApiError(404, 'not_found');
      }
      // Only the Cloudflare edge's address header is used; the DO is private.
      const headers = new Headers(request.headers);
      headers.set('X-Directory-Address', await digest(request.headers.get('CF-Connecting-IP') || 'local-test'));
      const forwarded = new Request(request, {headers});
      return await env.DIRECTORY.get(env.DIRECTORY.idFromName('public-games-v1')).fetch(forwarded);
    } catch (error) {
      return json({error: error instanceof ApiError ? error.message : 'service_unavailable'},
        error instanceof ApiError ? error.status : 503);
    }
  },
};

export class GameDirectory {
  constructor(ctx) {
    this.ctx = ctx;
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS games (
      id TEXT PRIMARY KEY, lease_hash TEXT NOT NULL, address_hash TEXT NOT NULL,
      listing TEXT NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
    )`);
    this.sql.exec('CREATE INDEX IF NOT EXISTS games_expiry ON games(expires_at)');
    this.sql.exec(`CREATE TABLE IF NOT EXISTS registrations (
      address_hash TEXT PRIMARY KEY, minute INTEGER NOT NULL, count INTEGER NOT NULL
    )`);
  }

  cleanup(now) {
    this.sql.exec('DELETE FROM games WHERE expires_at <= ?', now);
    this.sql.exec('DELETE FROM registrations WHERE minute < ?', Math.floor(now / 60000) - 1);
  }

  async alarm() {
    this.cleanup(Date.now());
    const next = this.sql.exec('SELECT MIN(expires_at) AS next FROM games').one().next;
    if (next !== null) await this.ctx.storage.setAlarm(next);
  }

  async fetch(request) {
    try {
      const url = new URL(request.url);
      const now = Date.now();
      const address = request.headers.get('X-Directory-Address');
      this.cleanup(now);
      if (request.method === 'GET' && url.pathname === '/health') {
        const active = this.sql.exec('SELECT COUNT(*) AS count FROM games').one().count;
        return json({ok: true, service: 'halo-og-directory', api_version: 1, active_games: active});
      }
      if (request.method === 'GET' && url.pathname === '/v1/games') {
        const version = url.searchParams.get('network_version');
        if (version !== null && !/^[1-9][0-9]{0,4}$/.test(version)) throw new ApiError(400, 'invalid_network_version');
        if (version !== null && Number(version) > 65535) throw new ApiError(400, 'invalid_network_version');
        const games = this.sql.exec('SELECT id, listing, expires_at, updated_at FROM games').toArray()
          .map((row) => ({id: row.id, ...JSON.parse(row.listing),
            expires_at: Math.floor(row.expires_at / 1000), updated_at: Math.floor(row.updated_at / 1000)}))
          .filter((game) => version === null || game.network_version === Number(version))
          .sort((a, b) => b.player_count - a.player_count || a.name.localeCompare(b.name));
        return json({api_version: 1, server_time: Math.floor(now / 1000), games}, 200,
          {'Access-Control-Allow-Origin': '*'});
      }
      if (request.method === 'POST' && url.pathname === '/v1/games') {
        const listing = await readListing(request);
        const token = randomToken();
        const tokenHash = await digest(token);
        const id = crypto.randomUUID();
        const expires = now + TTL_SECONDS * 1000;
        // Synchronous transaction: simultaneous requests cannot bypass quotas.
        this.ctx.storage.transactionSync(() => {
          this.cleanup(now);
          const count = this.sql.exec('SELECT COUNT(*) AS count FROM games').one().count;
          const owned = this.sql.exec('SELECT COUNT(*) AS count FROM games WHERE address_hash = ?', address).one().count;
          if (count >= MAX_GAMES) throw new ApiError(503, 'directory_full');
          if (owned >= MAX_GAMES_PER_ADDRESS) throw new ApiError(429, 'too_many_hosted_games');
          const minute = Math.floor(now / 60000);
          const rate = this.sql.exec('SELECT minute, count FROM registrations WHERE address_hash = ?', address).toArray()[0];
          if (rate?.minute === minute && rate.count >= MAX_CREATES_PER_MINUTE) throw new ApiError(429, 'registration_rate_limited');
          this.sql.exec('INSERT OR REPLACE INTO registrations VALUES (?, ?, ?)', address, minute,
            rate?.minute === minute ? rate.count + 1 : 1);
          this.sql.exec('INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)',
            id, tokenHash, address, JSON.stringify(listing), expires, now);
        });
        const alarm = await this.ctx.storage.getAlarm();
        if (alarm === null || alarm > expires) await this.ctx.storage.setAlarm(expires);
        return json({id, lease_token: token, expires_at: Math.floor(expires / 1000),
          heartbeat_seconds: HEARTBEAT_SECONDS}, 201);
      }
      const match = /^\/v1\/games\/([0-9a-f-]{36})$/.exec(url.pathname);
      if (match && ['PUT', 'DELETE'].includes(request.method)) {
        const token = request.headers.get('Authorization')?.match(/^Bearer ([0-9a-f]{64})$/)?.[1];
        if (!token) throw new ApiError(401, 'lease_required');
        const hash = await digest(token);
        const row = this.sql.exec('SELECT * FROM games WHERE id = ?', match[1]).toArray()[0];
        if (!row || row.expires_at <= Date.now()) throw new ApiError(404, 'game_expired');
        if (row.lease_hash !== hash) throw new ApiError(403, 'invalid_lease');
        if (request.method === 'DELETE') {
          this.sql.exec('DELETE FROM games WHERE id = ? AND lease_hash = ?', match[1], hash);
          return new Response(null, {status: 204, headers: {'Cache-Control': 'no-store'}});
        }
        const listing = await readListing(request);
        const original = JSON.parse(row.listing);
        if (listing.invite !== original.invite) throw new ApiError(409, 'invite_change_requires_registration');
        const updated = Date.now();
        const expires = updated + TTL_SECONDS * 1000;
        // Recheck after awaiting the body, including deletion/expiry races.
        const result = this.sql.exec('UPDATE games SET listing = ?, expires_at = ?, updated_at = ? '
          + 'WHERE id = ? AND lease_hash = ? AND expires_at > ?',
          JSON.stringify(listing), expires, updated, match[1], hash, updated);
        if (result.rowsWritten === 0) throw new ApiError(404, 'game_expired');
        return json({id: match[1], expires_at: Math.floor(expires / 1000), heartbeat_seconds: HEARTBEAT_SECONDS});
      }
      throw new ApiError(405, 'method_not_allowed');
    } catch (error) {
      return json({error: error instanceof ApiError ? error.message : 'service_unavailable'},
        error instanceof ApiError ? error.status : 503,
        error instanceof ApiError && error.status === 429 ? {'Retry-After': '30'} : {});
    }
  }
}
