/* Hidden Fiesta caches share the community downloader's bounded HTTPS,
   real-directory checks and exclusive publication. Unlike visible community
   maps, these are requested individually and are never put in the map list. */
/* The v2 inventory admits larger catalogs; v1 stays available to older apps. */
#define ARSENAL_CATALOG_URL "https://dl.oghalo.com/catalogs/testing/arsenals-v2.json"
#define ARSENAL_WEAPON_LIST_SHA256 "2856504cbd257e1b18c273caa64237fbfe77dc77d22cce1a7fa0a0abfc53f71f"
#define MAX_MANIFEST_BYTES 4096
/* Admission covers the entire index; caches are downloaded individually. */
#define ARSENAL_MAX_BATCH_BYTES (4ULL * 1024 * 1024 * 1024)

struct arsenal_entry {
    char logical[32], physical[32], base_sha256[65], cache_sha256[65], manifest_sha256[65];
    char cache_key[160], manifest_key[160];
    unsigned long long cache_bytes, declared_bytes, manifest_bytes;
};
struct arsenal_catalog { struct arsenal_entry entries[MAX_MAPS]; unsigned count; };
struct arsenal_request {
    char logical[32], base_sha256[65], expected_sha256[65];
    char cache_path[PATH_BYTES], manifest_path[PATH_BYTES];
    int status, queued;
};
static struct arsenal_request arsenal_requests[MAX_MAPS];
static unsigned arsenal_request_count;
static SDL_AtomicInt arsenal_lock;
static int arsenal_worker_running;

static void arsenal_acquire(void)
{ while (!SDL_CompareAndSwapAtomicInt(&arsenal_lock, 0, 1)) {} }
static void arsenal_release(void)
{ SDL_CompareAndSwapAtomicInt(&arsenal_lock, 1, 0); }
static int arsenal_digest(const char *hex)
{
    if (!hex || strlen(hex) != 64) return 0;
    for (unsigned i = 0; i < 64; i++)
        if (!((hex[i] >= '0' && hex[i] <= '9') || (hex[i] >= 'a' && hex[i] <= 'f'))) return 0;
    return 1;
}
static int arsenal_logical(const char *name)
{
    static const char *forbidden[] = { "ui", "a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40", "con", "prn", "aux", "nul" };
    size_t size;
    if (!name || !(size = strlen(name)) || size > 31 || name[size - 1] == ' ' ||
        !((name[0] >= 'a' && name[0] <= 'z') || (name[0] >= '0' && name[0] <= '9'))) return 0;
    for (size_t i = 0; i < size; i++)
        if (!((name[i] >= 'a' && name[i] <= 'z') || (name[i] >= '0' && name[i] <= '9') || name[i] == '_' || name[i] == '-' || name[i] == ' ')) return 0;
    for (unsigned i = 0; i < sizeof(forbidden) / sizeof(*forbidden); i++) if (!strcmp(name, forbidden[i])) return 0;
    return !(size == 4 && (!strncmp(name, "com", 3) || !strncmp(name, "lpt", 3)) && name[3] >= '1' && name[3] <= '9');
}
static int arsenal_physical(const char *logical, const char *physical)
{
    char expected[32];
    if (!arsenal_logical(logical)) return 0;
    if (strlen(logical) <= 23) snprintf(expected, sizeof(expected), "_fiesta_%s", logical);
    else {
        struct sha256 hash; unsigned char digest[32];
        sha256_begin(&hash); sha256_add(&hash, logical, (int)strlen(logical)); sha256_end(&hash, digest);
        memcpy(expected, "_fiestah_", 9);
        for (unsigned i = 0; i < 8; i++) snprintf(expected + 9 + i * 2, 3, "%02x", digest[i]);
    }
    return !strcmp(expected, physical);
}
static int arsenal_object(struct json *j, struct arsenal_entry *entry)
{
    unsigned fields = 0; char key[32], expected[160];
    memset(entry, 0, sizeof(*entry));
    if (!token(j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(j, key, sizeof(key)) || !token(j, ':')) return 0;
        if (!strcmp(key, "logical_map")) { bit = 1; if (!string(j, entry->logical, sizeof(entry->logical))) return 0; }
        else if (!strcmp(key, "physical_map")) { bit = 2; if (!string(j, entry->physical, sizeof(entry->physical))) return 0; }
        else if (!strcmp(key, "base_sha256")) { bit = 4; if (!string(j, entry->base_sha256, sizeof(entry->base_sha256))) return 0; }
        else if (!strcmp(key, "cache_sha256")) { bit = 8; if (!string(j, entry->cache_sha256, sizeof(entry->cache_sha256))) return 0; }
        else if (!strcmp(key, "manifest_sha256")) { bit = 16; if (!string(j, entry->manifest_sha256, sizeof(entry->manifest_sha256))) return 0; }
        else if (!strcmp(key, "cache_object_key")) { bit = 32; if (!string(j, entry->cache_key, sizeof(entry->cache_key))) return 0; }
        else if (!strcmp(key, "manifest_object_key")) { bit = 64; if (!string(j, entry->manifest_key, sizeof(entry->manifest_key))) return 0; }
        else if (!strcmp(key, "cache_file_bytes")) { bit = 128; if (!integer(j, &entry->cache_bytes) || entry->cache_bytes < 2048 || entry->cache_bytes > MAX_MAP_BYTES) return 0; }
        else if (!strcmp(key, "cache_declared_bytes")) { bit = 256; if (!integer(j, &entry->declared_bytes) || entry->declared_bytes < 2048 || entry->declared_bytes > MAX_MAP_BYTES) return 0; }
        else if (!strcmp(key, "manifest_bytes")) { bit = 512; if (!integer(j, &entry->manifest_bytes) || !entry->manifest_bytes || entry->manifest_bytes > MAX_MANIFEST_BYTES) return 0; }
        else return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (token(j, '}')) break;
        if (!token(j, ',')) return 0;
    }
    if (fields != 1023 || !arsenal_physical(entry->logical, entry->physical) || !arsenal_digest(entry->base_sha256) ||
        !arsenal_digest(entry->cache_sha256) || !arsenal_digest(entry->manifest_sha256)) return 0;
    snprintf(expected, sizeof(expected), "arsenals/v1/sha256/%s/%s.map", entry->cache_sha256, entry->physical);
    if (strcmp(expected, entry->cache_key)) return 0;
    snprintf(expected, sizeof(expected), "arsenals/v1/sha256/%s/%s.json", entry->manifest_sha256, entry->physical);
    return !strcmp(expected, entry->manifest_key);
}
static int parse_arsenal_catalog(const unsigned char *data, size_t size, struct arsenal_catalog *catalog)
{
    struct json j = { data, data + size }; unsigned fields = 0;
    char key[32], value[80]; unsigned long long number, total = size;
    memset(catalog, 0, sizeof(*catalog));
    if (!size || size > MAX_CATALOG_BYTES || !token(&j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(&j, key, sizeof(key)) || !token(&j, ':')) return 0;
        if (!strcmp(key, "schema_version")) { bit = 1; if (!integer(&j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "profile")) { bit = 2; if (!string(&j, value, sizeof(value)) || strcmp(value, "fiesta-arsenal-v1")) return 0; }
        else if (!strcmp(key, "generation")) { bit = 4; if (!integer(&j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "weapon_list_sha256")) { bit = 8; if (!string(&j, value, sizeof(value)) || strcmp(value, ARSENAL_WEAPON_LIST_SHA256)) return 0; }
        else if (!strcmp(key, "arsenals")) {
            bit = 16; if (!token(&j, '[')) return 0;
            if (!token(&j, ']')) for (;;) {
                struct arsenal_entry *entry;
                if (catalog->count == MAX_MAPS) return 0;
                entry = &catalog->entries[catalog->count];
                if (!arsenal_object(&j, entry)) return 0;
                for (unsigned i = 0; i < catalog->count; i++)
                    if (!strcmp(catalog->entries[i].logical, entry->logical) && !strcmp(catalog->entries[i].base_sha256, entry->base_sha256)) return 0;
                total += entry->cache_bytes + entry->manifest_bytes;
                if (total > ARSENAL_MAX_BATCH_BYTES) return 0;
                catalog->count++;
                if (token(&j, ']')) break;
                if (!token(&j, ',')) return 0;
            }
        } else return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (token(&j, '}')) break;
        if (!token(&j, ',')) return 0;
    }
    whitespace(&j); return fields == 31 && catalog->count && j.p == j.end;
}
static int arsenal_read_small(const char *path, unsigned char *data, unsigned capacity, size_t *length)
{
    unsigned long long size; file_handle file = read_open(path); size_t have = 0; int okay = 0;
    if (file == BAD_FILE) return 0;
    if (!file_size(file, &size) || !size || size > capacity) goto done;
    while (have < size) {
        int count = read_bytes(file, data + have, (unsigned)(size - have));
        if (count <= 0) goto done; have += (unsigned)count;
    }
    unsigned char extra;
    okay = read_bytes(file, &extra, 1) == 0;
    if (okay) *length = have;
done:
    file_close(file); return okay;
}
static int arsenal_manifest(const char *path, const struct arsenal_entry *entry)
{
    unsigned char bytes[MAX_MANIFEST_BYTES]; size_t length;
    char key[32], value[80]; unsigned fields = 0; unsigned long long number;
    if (!verify_payload(path, NULL, entry->manifest_bytes, entry->manifest_sha256, 0) ||
        !arsenal_read_small(path, bytes, sizeof(bytes), &length)) return 0;
    struct json j = { bytes, bytes + length };
    if (!token(&j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(&j, key, sizeof(key)) || !token(&j, ':')) return 0;
        if (!strcmp(key, "schema_version")) { bit = 1; if (!integer(&j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "generation")) { bit = 2; if (!integer(&j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "logical_map")) { bit = 4; if (!string(&j, value, sizeof(value)) || strcmp(value, entry->logical)) return 0; }
        else if (!strcmp(key, "physical_map")) { bit = 8; if (!string(&j, value, sizeof(value)) || strcmp(value, entry->physical)) return 0; }
        else if (!strcmp(key, "base_sha256")) { bit = 16; if (!string(&j, value, sizeof(value)) || strcmp(value, entry->base_sha256)) return 0; }
        else if (!strcmp(key, "cache_sha256")) { bit = 32; if (!string(&j, value, sizeof(value)) || strcmp(value, entry->cache_sha256)) return 0; }
        else if (!strcmp(key, "weapon_list_sha256")) { bit = 64; if (!string(&j, value, sizeof(value)) || strcmp(value, ARSENAL_WEAPON_LIST_SHA256)) return 0; }
        else if (!strcmp(key, "cache_file_bytes")) { bit = 128; if (!integer(&j, &number) || number != entry->cache_bytes) return 0; }
        else if (!strcmp(key, "cache_declared_bytes")) { bit = 256; if (!integer(&j, &number) || number != entry->declared_bytes) return 0; }
        else return 0;
        if (fields & bit) return 0; fields |= bit;
        if (token(&j, '}')) break;
        if (!token(&j, ',')) return 0;
    }
    whitespace(&j); return fields == 511 && j.p == j.end;
}
static int arsenal_directory(const char *parent, const char *name, char *out, size_t capacity)
{
    int found = find_child(parent, name, out, capacity);
    if (found == 1) return path_kind(out) == 2;
    if (found < 0 || !join_path(out, capacity, parent, name)) return 0;
    if (!make_directory(out)) {
        if (find_child(parent, name, out, capacity) != 1) return 0;
    }
    return real_directory_chain(out);
}
static int arsenal_download(struct arsenal_request *request)
{
    char maps[PATH_BYTES], arsenal[PATH_BYTES], destination[PATH_BYTES], partial[PATH_BYTES] = "";
    char catalog_path[PATH_BYTES] = "", map_partial[PATH_BYTES] = "", json_partial[PATH_BYTES] = "";
    char base_path[PATH_BYTES], name[40], url[256], error[256] = "";
    unsigned char *data = NULL; struct arsenal_catalog *catalog = NULL;
    struct arsenal_entry *entry = NULL; int result = -1, own_partial = 0;
    size_t size; const char *root = platform_data_root();
    if (!real_directory_chain(root) || find_child(root, "maps", maps, sizeof(maps)) != 1 ||
        path_kind(maps) != 2 || !stock_profile(maps)) goto done;
    for (unsigned i = 0; i < 32; i++) {
        snprintf(name, sizeof(name), ".halo-og-arsenal-%llu-%u", (unsigned long long)SDL_GetTicksNS(), i);
        if (!join_path(partial, sizeof(partial), maps, name)) break;
        if (make_directory(partial)) { own_partial = 1; break; }
    }
    if (!own_partial || !join_path(catalog_path, sizeof(catalog_path), partial, "catalog.partial") ||
        !join_path(map_partial, sizeof(map_partial), partial, "cache.partial") ||
        !join_path(json_partial, sizeof(json_partial), partial, "manifest.partial")) goto done;
    platform_log("Fiesta weapons: checking %s for %s", ARSENAL_CATALOG_URL, request->logical);
    if (!update_download_limited(ARSENAL_CATALOG_URL, catalog_path, MAX_CATALOG_BYTES, NULL, NULL, error, sizeof(error))) goto done;
    data = malloc(MAX_CATALOG_BYTES); catalog = malloc(sizeof(*catalog));
    if (!data || !catalog || !arsenal_read_small(catalog_path, data, MAX_CATALOG_BYTES, &size) ||
        !parse_arsenal_catalog(data, size, catalog)) goto done;
    for (unsigned i = 0; i < catalog->count; i++) {
        struct arsenal_entry *candidate = &catalog->entries[i];
        if (!strcmp(candidate->logical, request->logical) && !strcmp(candidate->base_sha256, request->base_sha256) &&
            (!request->expected_sha256[0] || !strcmp(candidate->cache_sha256, request->expected_sha256))) { entry = candidate; break; }
    }
    if (!entry) { snprintf(error, sizeof(error), "no published arsenal matches the original map and host revision"); goto done; }
    snprintf(name, sizeof(name), "%s.map", request->logical);
    if (find_child(maps, name, base_path, sizeof(base_path)) != 1 ||
        !verify_payload(base_path, request->logical, 0, request->base_sha256, 0)) {
        snprintf(error, sizeof(error), "original map changed or does not match the requested arsenal"); goto done;
    }
    if (!arsenal_directory(maps, "arsenal", arsenal, sizeof(arsenal)) ||
        !arsenal_directory(arsenal, "v1", destination, sizeof(destination))) goto done;
    snprintf(name, sizeof(name), "%s.map", entry->physical);
    int have_map = find_child(destination, name, request->cache_path, sizeof(request->cache_path));
    if (have_map < 0 || (have_map && !verify_payload(request->cache_path, entry->physical, entry->cache_bytes, entry->cache_sha256, entry->declared_bytes)) ||
        (!have_map && !join_path(request->cache_path, sizeof(request->cache_path), destination, name))) {
        snprintf(error, sizeof(error), "existing arsenal cache is different or unsafe; preserved"); goto done;
    }
    snprintf(name, sizeof(name), "%s.json", entry->physical);
    int have_manifest = find_child(destination, name, request->manifest_path, sizeof(request->manifest_path));
    if (have_manifest < 0 || (have_manifest && !arsenal_manifest(request->manifest_path, entry)) ||
        (!have_manifest && !join_path(request->manifest_path, sizeof(request->manifest_path), destination, name))) {
        snprintf(error, sizeof(error), "existing arsenal manifest is different or unsafe; preserved"); goto done;
    }
    if (!have_manifest) {
        if (!object_url(url, sizeof(url), entry->manifest_key) ||
            !update_download_limited(url, json_partial, entry->manifest_bytes, NULL, NULL, error, sizeof(error)) ||
            !arsenal_manifest(json_partial, entry) || !sync_file(json_partial)) goto done;
    }
    if (!have_map) {
        unsigned last = 0;
        platform_log("Fiesta weapons: downloading %s (%llu bytes)", request->logical, entry->cache_bytes);
        if (!object_url(url, sizeof(url), entry->cache_key) ||
            !update_download_limited(url, map_partial, entry->cache_bytes, map_progress, &last, error, sizeof(error)) ||
            !verify_payload(map_partial, entry->physical, entry->cache_bytes, entry->cache_sha256, entry->declared_bytes) || !sync_file(map_partial)) goto done;
    }
    /* Recheck ancestors and case aliases immediately before publication.
       A racing file always wins; accept it only if it is the exact object. */
    if (!real_directory_chain(destination)) goto done;
    snprintf(name, sizeof(name), "%s.map", entry->physical);
    int race = find_child(destination, name, request->cache_path, sizeof(request->cache_path));
    if (race < 0 || (!race && (!join_path(request->cache_path, sizeof(request->cache_path), destination, name) ||
        !publish_file(map_partial, request->cache_path)))) goto done;
    if (!verify_payload(request->cache_path, entry->physical, entry->cache_bytes, entry->cache_sha256, entry->declared_bytes)) goto done;
    snprintf(name, sizeof(name), "%s.json", entry->physical);
    race = find_child(destination, name, request->manifest_path, sizeof(request->manifest_path));
    if (race < 0 || (!race && (!join_path(request->manifest_path, sizeof(request->manifest_path), destination, name) ||
        !publish_file(json_partial, request->manifest_path)))) goto done;
    if (!arsenal_manifest(request->manifest_path, entry)) goto done;
    result = 1;
    platform_log("Fiesta weapons: %s cache and manifest verified and installed", request->logical);
done:
    if (result != 1) platform_log("Fiesta weapons: %s download failed: %s", request->logical, error[0] ? error : "identity, compatibility or safe publication check failed");
    free(data); free(catalog);
    if (own_partial) {
        if (*catalog_path) remove_file(catalog_path);
        if (*map_partial) remove_file(map_partial);
        if (*json_partial) remove_file(json_partial);
        remove_directory(partial);
    }
    return result;
}
static int arsenal_worker(void *unused)
{
    (void)unused;
    for (;;) {
        struct arsenal_request request; unsigned index;
        arsenal_acquire();
        for (index = 0; index < arsenal_request_count; index++) if (arsenal_requests[index].queued) break;
        if (index == arsenal_request_count) { arsenal_worker_running = 0; arsenal_release(); return 0; }
        request = arsenal_requests[index]; arsenal_requests[index].queued = 0;
        arsenal_release();
        int result = arsenal_download(&request);
        arsenal_acquire();
        memcpy(arsenal_requests[index].cache_path, request.cache_path, sizeof(request.cache_path));
        memcpy(arsenal_requests[index].manifest_path, request.manifest_path, sizeof(request.manifest_path));
        arsenal_requests[index].status = result;
        arsenal_release();
    }
}
int halo_arsenal_download_request(const char *logical_map, const char *base_sha256_hex, const char *cache_sha256_hex)
{
    unsigned index; int status, start = 0;
    const char *expected = cache_sha256_hex ? cache_sha256_hex : "";
    if (!arsenal_logical(logical_map) || !arsenal_digest(base_sha256_hex) || (*expected && !arsenal_digest(expected)) ||
        !config_boolean("community_maps.auto_download")) return 0;
    arsenal_acquire();
    for (index = 0; index < arsenal_request_count; index++) {
        struct arsenal_request *request = &arsenal_requests[index];
        if (!strcmp(request->logical, logical_map) && !strcmp(request->base_sha256, base_sha256_hex) && !strcmp(request->expected_sha256, expected)) break;
    }
    if (index == arsenal_request_count) {
        if (index == MAX_MAPS) {
            /* Request identities also include the offered revision. Evict
               completed/failed query state rather than exhausting the queue
               after visiting many hosts. Pending worker indices stay stable;
               verified files themselves are discovered by engine preflight. */
            for (index = 0; index < arsenal_request_count; index++)
                if (!arsenal_requests[index].queued && arsenal_requests[index].status != 2) break;
            if (index == MAX_MAPS) { arsenal_release(); return -1; }
        } else arsenal_request_count++;
        struct arsenal_request *request = &arsenal_requests[index];
        memset(request, 0, sizeof(*request));
        strcpy(request->logical, logical_map); strcpy(request->base_sha256, base_sha256_hex); strcpy(request->expected_sha256, expected);
    }
    struct arsenal_request *request = &arsenal_requests[index];
    if (request->status == 1 && (path_kind(request->cache_path) != 1 || path_kind(request->manifest_path) != 1)) request->status = 0;
    status = request->status;
    if (status == -1) request->status = 0; /* One failure observation; a later user retry can reschedule. */
    else if (!status) {
        request->status = status = 2; request->queued = 1;
        if (!arsenal_worker_running) { arsenal_worker_running = 1; start = 1; }
    }
    arsenal_release();
    if (start) {
        SDL_Thread *thread = SDL_CreateThread(arsenal_worker, "Fiesta weapons", NULL);
        if (thread) SDL_DetachThread(thread);
        else {
            arsenal_acquire(); arsenal_worker_running = 0;
            for (index = 0; index < arsenal_request_count; index++) if (arsenal_requests[index].queued) {
                arsenal_requests[index].queued = 0; arsenal_requests[index].status = -1;
            }
            arsenal_release(); return -1;
        }
    }
    return status;
}
