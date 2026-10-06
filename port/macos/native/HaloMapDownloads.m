#import "HaloMapDownloads.h"
#include "../../linux/include/halo_expanded_cache.h"
#include <CommonCrypto/CommonDigest.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>

static HaloMapDownloads *hostDownloads;
static NSError *downloadError(NSString *message) {
    return [NSError errorWithDomain:@"HaloMapDownloads" code:1 userInfo:@{NSLocalizedDescriptionKey:message}];
}
static NSString *origin(NSURL *url) {
    if (![url.scheme.lowercaseString isEqualToString:@"https"] || !url.host.length || url.user || url.password) return nil;
    return [NSString stringWithFormat:@"https://%@%@", url.host.lowercaseString,
            url.port && url.port.integerValue != 443 ? [@":" stringByAppendingString:url.port.stringValue] : @""];
}
static BOOL allowedURL(NSURL *url, NSDictionary *config) {
    NSString *value = origin(url);
    if (!value || url.fragment) return NO;
    for (id allowed in config[@"allowed_origins"]) {
        if ([allowed isKindOfClass:NSString.class] && [value isEqualToString:allowed]) return YES;
    }
    return NO;
}
static BOOL numberInRange(id value, unsigned long long maximum) {
    return [value isKindOfClass:NSNumber.class] && strcmp([value objCType], @encode(BOOL)) &&
        [value doubleValue] >= 1 && [value doubleValue] <= maximum &&
        [value doubleValue] == [value unsignedLongLongValue];
}
static BOOL mapNameIsValid(NSString *name) {
    if (![name isKindOfClass:NSString.class] || name.length < 1 || name.length > 31) return NO;
    NSCharacterSet *letters = [NSCharacterSet characterSetWithCharactersInString:@"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_ -"];
    if ([name rangeOfCharacterFromSet:letters.invertedSet].location != NSNotFound) return NO;
    static NSSet *reserved;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ reserved = [NSSet setWithArray:@[@"ui", @"a10", @"a30", @"a50", @"b30", @"b40", @"c10", @"c20", @"c40", @"d20", @"d40",
        @"beavercreek", @"sidewinder", @"damnation", @"ratrace", @"prisoner", @"hangemhigh", @"chillout", @"carousel", @"boardingaction", @"bloodgulch", @"wizard", @"putput", @"longest"]]; });
    return ![reserved containsObject:name.lowercaseString];
}
static BOOL hashIsValid(id hash) {
    return [hash isKindOfClass:NSString.class] && [hash length] == 64 &&
        [hash rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"].invertedSet].location == NSNotFound;
}
BOOL HaloDownloadConfigurationIsValid(NSDictionary *config) {
    if (![config isKindOfClass:NSDictionary.class] || ![config[@"schema_version"] isEqual:@1] ||
        ![config[@"profile"] isEqual:@"stock-xbox-ntsc"] || ![config[@"cache_build"] isEqual:@"01.10.12.2276"] ||
        ![config[@"allowed_origins"] isKindOfClass:NSArray.class] ||
        !numberInRange(config[@"max_catalog_bytes"], 1048576) || !numberInRange(config[@"max_map_bytes"], 134217728) ||
        !numberInRange(config[@"max_cache_bytes"], 134217728) || !numberInRange(config[@"max_tag_bytes"], 23068672) ||
        !numberInRange(config[@"max_maps"], 115)) return NO;
    id catalog = config[@"catalog_url"], base = config[@"objects_base_url"], arsenal = config[@"arsenal_catalog_url"];
    if (!catalog || catalog == NSNull.null) return (!base || base == NSNull.null) &&
        (!arsenal || arsenal == NSNull.null) && [config[@"allowed_origins"] count] == 0;
    if (![catalog isKindOfClass:NSString.class] || ![base isKindOfClass:NSString.class]) return NO;
    NSURL *catalogURL = [NSURL URLWithString:catalog], *baseURL = [NSURL URLWithString:base];
    NSURL *arsenalURL = [arsenal isKindOfClass:NSString.class] ? [NSURL URLWithString:arsenal] : nil;
    return allowedURL(catalogURL, config) && allowedURL(baseURL, config) && !catalogURL.query && !baseURL.query &&
        (!arsenal || arsenal == NSNull.null || (arsenalURL && allowedURL(arsenalURL, config) && !arsenalURL.query));
}
NSDictionary *HaloValidateMapCatalog(NSData *data, NSDictionary *config, NSError **error) {
    if (!HaloDownloadConfigurationIsValid(config) || data.length > [config[@"max_catalog_bytes"] unsignedLongLongValue]) {
        if (error) *error = downloadError(@"The map catalog exceeds this build's limits.");
        return nil;
    }
    id catalog = [NSJSONSerialization JSONObjectWithData:data options:0 error:error];
    if (![catalog isKindOfClass:NSDictionary.class] || ![catalog[@"schema_version"] isEqual:@1] ||
        ![catalog[@"profile"] isEqual:config[@"profile"]] || ![catalog[@"maps"] isKindOfClass:NSArray.class] ||
        [catalog[@"maps"] count] > [config[@"max_maps"] unsignedIntegerValue]) {
        if (error) *error = downloadError(@"The map catalog is incompatible with this build.");
        return nil;
    }
    NSMutableDictionary *entries = [NSMutableDictionary dictionary];
    for (id entry in catalog[@"maps"]) {
        NSString *name = [entry isKindOfClass:NSDictionary.class] ? entry[@"id"] : nil;
        BOOL valid = mapNameIsValid(name) && [name isEqual:name.lowercaseString] && hashIsValid(entry[@"sha256"]) && !entries[name.lowercaseString] &&
            numberInRange(entry[@"file_bytes"], [config[@"max_map_bytes"] unsignedLongLongValue]) &&
            [entry[@"file_bytes"] unsignedLongLongValue] >= 2048 && [entry[@"cache_version"] isEqual:@5] &&
            [entry[@"cache_build"] isEqual:config[@"cache_build"]] && [entry[@"scenario_type"] isEqual:@1];
        NSString *key = valid ? [NSString stringWithFormat:@"maps/sha256/%@/%@.map", entry[@"sha256"], name] : nil;
        if (!valid || ![entry[@"object_key"] isEqual:key] ||
            (entry[@"prefetch"] && ![entry[@"prefetch"] isKindOfClass:NSNumber.class])) {
            if (error) *error = downloadError(@"The map catalog contains an unsafe, duplicate or unsupported map.");
            return nil;
        }
        entries[name.lowercaseString] = entry;
    }
    return entries;
}
static uint32_t little32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
BOOL HaloVerifyDownloadedMap(NSURL *file, NSDictionary *entry, NSDictionary *config, NSError **error) {
    int descriptor = open(file.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    struct stat info;
    unsigned char header[2048];
    BOOL valid = HaloDownloadConfigurationIsValid(config) && descriptor >= 0 && !fstat(descriptor, &info) && S_ISREG(info.st_mode) &&
        [entry[@"file_bytes"] unsignedLongLongValue] <= [config[@"max_map_bytes"] unsignedLongLongValue] &&
        info.st_size >= 0 && (unsigned long long)info.st_size == [entry[@"file_bytes"] unsignedLongLongValue] && read(descriptor, header, sizeof(header)) == sizeof(header);
    if (valid) {
        const unsigned char *nameEnd = memchr(header + 32, 0, 32), *buildEnd = memchr(header + 64, 0, 32);
        NSString *name = nameEnd ? [[NSString alloc] initWithBytes:header + 32 length:nameEnd - header - 32 encoding:NSASCIIStringEncoding] : nil;
        NSString *build = buildEnd ? [[NSString alloc] initWithBytes:header + 64 length:buildEnd - header - 64 encoding:NSASCIIStringEncoding] : nil;
        uint32_t declared = little32(header + 8), tagOffset = little32(header + 16), tagSize = little32(header + 20);
        valid = !memcmp(header, "daeh", 4) && !memcmp(header + 2044, "toof", 4) && little32(header + 4) == 5 &&
            header[96] == 1 && header[97] == 0 && [name.lowercaseString isEqual:[entry[@"id"] lowercaseString]] &&
            [build isEqual:entry[@"cache_build"]] && declared >= 2048 && declared <= [config[@"max_cache_bytes"] unsignedLongLongValue] &&
            tagSize <= [config[@"max_tag_bytes"] unsignedLongLongValue] &&
            tagOffset >= 2048 && (uint64_t)tagOffset + tagSize <= declared;
        /* v5 caches can be compressed; declared bytes describe decompressed
           cache size. The catalog's transfer length and SHA authenticate the
           exact complete file; do not mistake transfer length for cache size. */
    }
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    if (valid) {
        CC_SHA256_Update(&context, header, sizeof(header));
        unsigned char bytes[65536];
        ssize_t count;
        while ((count = read(descriptor, bytes, sizeof(bytes))) > 0) CC_SHA256_Update(&context, bytes, (CC_LONG)count);
        valid = count == 0;
        unsigned char digest[CC_SHA256_DIGEST_LENGTH];
        CC_SHA256_Final(digest, &context);
        NSMutableString *hash = [NSMutableString string];
        for (unsigned i = 0; i < sizeof(digest); i++) [hash appendFormat:@"%02x", digest[i]];
        valid = valid && [hash isEqual:entry[@"sha256"]];
    }
    if (descriptor >= 0) close(descriptor);
    if (!valid && error) *error = downloadError(@"The downloaded map failed its size, SHA-256 or Xbox v5 compatibility check.");
    return valid;
}

@interface HaloMapTransfer : NSObject
@property(nonatomic) BOOL catalog;
@property(nonatomic) BOOL accepted;
@property(nonatomic, strong) NSDictionary *entry;
@property(nonatomic, strong) NSMutableData *data;
@property(nonatomic, strong) NSURL *partial;
@property(nonatomic) int descriptor;
@property(nonatomic) unsigned long long received;
@property(nonatomic, strong) NSError *failure;
@property(nonatomic, strong) NSURLSessionTask *task;
@property(nonatomic) BOOL cancelled;
@end
@implementation HaloMapTransfer
@end

/* Arsenal metadata intentionally has a narrower JSON grammar than application
   preferences: ASCII strings, unsigned integers, objects and arrays only.
   Parsing here rejects duplicate keys before Foundation can collapse them. */
typedef struct { const unsigned char *p, *end; unsigned depth; BOOL valid; } ArsenalJSON;
static void arsenalSpace(ArsenalJSON *r) {
    while (r->p < r->end && (*r->p == ' ' || *r->p == '\n' || *r->p == '\r' || *r->p == '\t')) r->p++;
}
static NSString *arsenalString(ArsenalJSON *r) {
    if (r->p == r->end || *r->p++ != '"') { r->valid = NO; return nil; }
    const unsigned char *start = r->p;
    while (r->p < r->end && *r->p != '"') {
        if (*r->p < 32 || *r->p > 126 || *r->p == '\\' || r->p - start >= 256) { r->valid = NO; return nil; }
        r->p++;
    }
    if (r->p == r->end) { r->valid = NO; return nil; }
    NSString *value = [[NSString alloc] initWithBytes:start length:r->p - start encoding:NSASCIIStringEncoding];
    r->p++; return value;
}
static id arsenalValue(ArsenalJSON *r) {
    arsenalSpace(r);
    if (!r->valid || r->p == r->end || r->depth >= 6) { r->valid = NO; return nil; }
    if (*r->p == '"') return arsenalString(r);
    if (*r->p >= '0' && *r->p <= '9') {
        uint64_t value = 0; const unsigned char *start = r->p;
        do {
            value = value * 10 + (*r->p++ - '0');
            if (value > 2147483648ULL) { r->valid = NO; return nil; }
        } while (r->p < r->end && *r->p >= '0' && *r->p <= '9');
        if (r->p - start > 1 && *start == '0') { r->valid = NO; return nil; }
        return @(value);
    }
    unsigned char opener = *r->p++, closer = opener == '{' ? '}' : ']';
    if (opener != '{' && opener != '[') { r->valid = NO; return nil; }
    r->depth++;
    NSMutableDictionary *object = opener == '{' ? [NSMutableDictionary dictionary] : nil;
    NSMutableArray *array = opener == '[' ? [NSMutableArray array] : nil;
    arsenalSpace(r);
    if (r->p < r->end && *r->p == closer) { r->p++; r->depth--; return object ? (id)object : (id)array; }
    while (r->valid && r->p < r->end) {
        NSString *key = nil;
        if (object) {
            key = arsenalString(r); arsenalSpace(r);
            if (!key || object[key] || object.count >= 16 || r->p == r->end || *r->p++ != ':') { r->valid = NO; break; }
        }
        id value = arsenalValue(r);
        if (!value) break;
        if (object) object[key] = value;
        else { if (array.count >= 115) { r->valid = NO; break; } [array addObject:value]; }
        arsenalSpace(r);
        if (r->p == r->end) break;
        unsigned char separator = *r->p++;
        if (separator == closer) { r->depth--; return object ? (id)object : (id)array; }
        if (separator != ',') break;
        arsenalSpace(r);
    }
    r->valid = NO; return nil;
}
static NSDictionary *arsenalObject(NSData *data, NSUInteger maximum) {
    if (!data.length || data.length > maximum) return nil;
    ArsenalJSON reader = { data.bytes, (const unsigned char *)data.bytes + data.length, 0, YES };
    id result = arsenalValue(&reader); arsenalSpace(&reader);
    return reader.valid && reader.p == reader.end && [result isKindOfClass:NSDictionary.class] ? result : nil;
}
static BOOL arsenalFields(NSDictionary *object, NSArray *fields) {
    return [object isKindOfClass:NSDictionary.class] &&
        [[NSSet setWithArray:object.allKeys] isEqualToSet:[NSSet setWithArray:fields]];
}
static BOOL arsenalLogicalName(NSString *name) {
    if (![name isKindOfClass:NSString.class] || name.length < 1 || name.length > 31 ||
        [name rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyz0123456789_ -"].invertedSet].location != NSNotFound ||
        [name hasSuffix:@" "] || [[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyz0123456789"]
            characterIsMember:[name characterAtIndex:0]] == NO) return NO;
    static NSSet *reserved; static dispatch_once_t once;
    dispatch_once(&once, ^{
        reserved = [NSSet setWithArray:@[@"ui", @"a10", @"a30", @"a50", @"b30", @"b40", @"c10", @"c20", @"c40", @"d20", @"d40",
            @"con", @"prn", @"aux", @"nul", @"com1", @"com2", @"com3", @"com4", @"com5", @"com6", @"com7", @"com8", @"com9",
            @"lpt1", @"lpt2", @"lpt3", @"lpt4", @"lpt5", @"lpt6", @"lpt7", @"lpt8", @"lpt9"]];
    });
    return ![reserved containsObject:name];
}
static NSString *arsenalHash(NSData *bytes) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(bytes.bytes, (CC_LONG)bytes.length, digest);
    NSMutableString *result = [NSMutableString string];
    for (unsigned i = 0; i < sizeof(digest); i++) [result appendFormat:@"%02x", digest[i]];
    return result;
}
static NSString *arsenalPhysicalName(NSString *logical) {
    if (!arsenalLogicalName(logical)) return nil;
    return logical.length <= 23 ? [@"_fiesta_" stringByAppendingString:logical] :
        [@"_fiestah_" stringByAppendingString:[arsenalHash([logical dataUsingEncoding:NSASCIIStringEncoding]) substringToIndex:16]];
}
static NSString *arsenalCatalogKey(NSString *name, NSString *base) {
    return [NSString stringWithFormat:@"%@|%@", name, base];
}
static BOOL arsenalSizes(NSDictionary *entry, NSDictionary *config) {
    return numberInRange(entry[@"cache_file_bytes"], [config[@"max_map_bytes"] unsignedLongLongValue]) &&
        [entry[@"cache_file_bytes"] unsignedLongLongValue] >= 2048 &&
        numberInRange(entry[@"cache_declared_bytes"], [config[@"max_cache_bytes"] unsignedLongLongValue]) &&
        [entry[@"cache_declared_bytes"] unsignedLongLongValue] >= 2048;
}
static NSDictionary *arsenalManifest(NSData *data, NSDictionary *config) {
    NSDictionary *entry = arsenalObject(data, 4096);
    return arsenalFields(entry, @[@"schema_version", @"generation", @"logical_map", @"physical_map",
        @"base_sha256", @"cache_sha256", @"weapon_list_sha256", @"cache_file_bytes", @"cache_declared_bytes"]) &&
        [entry[@"schema_version"] isEqual:@1] && [entry[@"generation"] isEqual:@(HALO_EXPANDED_CACHE_GENERATION)] &&
        [entry[@"weapon_list_sha256"] isEqual:@HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256] &&
        [entry[@"physical_map"] isEqual:arsenalPhysicalName(entry[@"logical_map"])] &&
        hashIsValid(entry[@"base_sha256"]) && hashIsValid(entry[@"cache_sha256"]) && arsenalSizes(entry, config) ? entry : nil;
}
NSDictionary *HaloValidateArsenalCatalog(NSData *data, NSDictionary *config, NSError **error) {
    NSDictionary *catalog = HaloDownloadConfigurationIsValid(config) ?
        arsenalObject(data, [config[@"max_catalog_bytes"] unsignedIntegerValue]) : nil;
    BOOL valid = arsenalFields(catalog, @[@"schema_version", @"profile", @"generation", @"weapon_list_sha256", @"arsenals"]) &&
        [catalog[@"schema_version"] isEqual:@1] && [catalog[@"generation"] isEqual:@(HALO_EXPANDED_CACHE_GENERATION)] &&
        [catalog[@"profile"] isEqual:@"fiesta-arsenal-v1"] &&
        [catalog[@"weapon_list_sha256"] isEqual:@HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256] &&
        [catalog[@"arsenals"] isKindOfClass:NSArray.class] &&
        [catalog[@"arsenals"] count] > 0 &&
        [catalog[@"arsenals"] count] <= [config[@"max_maps"] unsignedIntegerValue];
    NSMutableDictionary *entries = [NSMutableDictionary dictionary]; uint64_t total = data.length;
    for (NSDictionary *entry in valid ? catalog[@"arsenals"] : @[]) {
        if (!arsenalFields(entry, @[@"logical_map", @"physical_map", @"base_sha256", @"cache_sha256",
            @"cache_file_bytes", @"cache_declared_bytes", @"manifest_sha256", @"manifest_bytes",
            @"cache_object_key", @"manifest_object_key"]) ||
            ![entry[@"physical_map"] isEqual:arsenalPhysicalName(entry[@"logical_map"])] ||
            !hashIsValid(entry[@"base_sha256"]) || !hashIsValid(entry[@"cache_sha256"]) ||
            !hashIsValid(entry[@"manifest_sha256"]) || !arsenalSizes(entry, config) ||
            !numberInRange(entry[@"manifest_bytes"], 4096) ||
            ![entry[@"cache_object_key"] isEqual:[NSString stringWithFormat:@"arsenals/v1/sha256/%@/%@.map", entry[@"cache_sha256"], entry[@"physical_map"]]] ||
            ![entry[@"manifest_object_key"] isEqual:[NSString stringWithFormat:@"arsenals/v1/sha256/%@/%@.json", entry[@"manifest_sha256"], entry[@"physical_map"]]]) { valid = NO; break; }
        NSString *key = arsenalCatalogKey(entry[@"logical_map"], entry[@"base_sha256"]);
        total += [entry[@"cache_file_bytes"] unsignedLongLongValue] + [entry[@"manifest_bytes"] unsignedLongLongValue];
        if (entries[key] || total > 2147483648ULL) { valid = NO; break; }
        entries[key] = entry;
    }
    if (!valid && error) *error = downloadError(@"The Fiesta arsenal catalog is unsafe or incompatible with this build.");
    return valid ? entries : nil;
}
static BOOL arsenalStatSame(struct stat *a, struct stat *b) {
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_size == b->st_size &&
        a->st_mtimespec.tv_sec == b->st_mtimespec.tv_sec && a->st_mtimespec.tv_nsec == b->st_mtimespec.tv_nsec &&
        a->st_ctimespec.tv_sec == b->st_ctimespec.tv_sec && a->st_ctimespec.tv_nsec == b->st_ctimespec.tv_nsec;
}
static NSData *arsenalReadDescriptor(int fd, NSUInteger maximum) {
    struct stat before, after; NSMutableData *data = nil;
    if (fd >= 0 && !fstat(fd, &before) && S_ISREG(before.st_mode) && before.st_size > 0 &&
        (uint64_t)before.st_size <= maximum) {
        data = [NSMutableData dataWithLength:(NSUInteger)before.st_size]; NSUInteger offset = 0;
        while (offset < data.length) {
            ssize_t count = read(fd, (unsigned char *)data.mutableBytes + offset, data.length - offset);
            if (count <= 0) { data = nil; break; } offset += count;
        }
        unsigned char extra;
        if (data && (read(fd, &extra, 1) != 0 || fstat(fd, &after) || !arsenalStatSame(&before, &after))) data = nil;
    }
    return data;
}
static NSData *arsenalReadFile(NSURL *url, NSUInteger maximum) {
    int fd = open(url.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    NSData *data = arsenalReadDescriptor(fd, maximum);
    if (fd >= 0) close(fd); return data;
}
static BOOL arsenalVerifyDescriptor(int fd, NSDictionary *entry, NSDictionary *config) {
    /* Authenticate one descriptor, including exact physical header identity and
       declared size, and reject a file edited while its digest was computed. */
    struct stat before, after; unsigned char header[2048];
    BOOL valid = fd >= 0 && !fstat(fd, &before) && S_ISREG(before.st_mode) &&
        before.st_size >= 2048 && (uint64_t)before.st_size == [entry[@"cache_file_bytes"] unsignedLongLongValue] &&
        read(fd, header, sizeof(header)) == sizeof(header);
    if (valid) {
        const unsigned char *nameEnd = memchr(header + 32, 0, 32), *buildEnd = memchr(header + 64, 0, 32);
        NSString *name = nameEnd ? [[NSString alloc] initWithBytes:header + 32 length:nameEnd - header - 32 encoding:NSASCIIStringEncoding] : nil;
        NSString *build = buildEnd ? [[NSString alloc] initWithBytes:header + 64 length:buildEnd - header - 64 encoding:NSASCIIStringEncoding] : nil;
        uint32_t declared = little32(header + 8), tagOffset = little32(header + 16), tagSize = little32(header + 20);
        valid = arsenalSizes(entry, config) && !memcmp(header, "daeh", 4) && !memcmp(header + 2044, "toof", 4) &&
            little32(header + 4) == 5 && header[96] == 1 && header[97] == 0 &&
            [name isEqual:entry[@"physical_map"]] && [build isEqual:config[@"cache_build"]] &&
            declared == [entry[@"cache_declared_bytes"] unsignedLongLongValue] &&
            tagSize <= [config[@"max_tag_bytes"] unsignedLongLongValue] && tagOffset >= 2048 &&
            (uint64_t)tagOffset + tagSize <= declared;
    }
    CC_SHA256_CTX context; CC_SHA256_Init(&context);
    if (valid) {
        CC_SHA256_Update(&context, header, sizeof(header)); unsigned char bytes[65536]; ssize_t count; uint64_t total = 2048;
        while ((count = read(fd, bytes, sizeof(bytes))) > 0) {
            total += count;
            if (total > (uint64_t)before.st_size) { valid = NO; break; }
            CC_SHA256_Update(&context, bytes, (CC_LONG)count);
        }
        unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_Final(digest, &context);
        NSMutableString *hash = [NSMutableString string];
        for (unsigned i = 0; i < sizeof(digest); i++) [hash appendFormat:@"%02x", digest[i]];
        valid = valid && count == 0 && total == (uint64_t)before.st_size && !fstat(fd, &after) &&
            arsenalStatSame(&before, &after) && [hash isEqual:entry[@"cache_sha256"]];
    }
    return valid;
}
static BOOL arsenalVerifyCache(NSURL *file, NSDictionary *entry, NSDictionary *config) {
    int fd = open(file.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    BOOL valid = arsenalVerifyDescriptor(fd, entry, config);
    if (fd >= 0) close(fd); return valid;
}
static BOOL arsenalManifestMatches(NSDictionary *manifest, NSDictionary *entry) {
    for (NSString *key in @[@"logical_map", @"physical_map", @"base_sha256", @"cache_sha256", @"cache_file_bytes", @"cache_declared_bytes"])
        if (![manifest[key] isEqual:entry[key]]) return NO;
    return YES;
}
/* Separate serial queue/session keeps on-demand arsenals out of the existing
   community-map prefetch queue. No engine callback waits for disk or HTTP. */
@interface HaloArsenalDownloads : NSObject <NSURLSessionDataDelegate>
@property(nonatomic, copy) void (^statusChanged)(void);
@property(nonatomic, readonly) NSString *statusText;
- (instancetype)initWithMaps:(NSURL *)maps library:(NSURL *)library partials:(NSURL *)partials
    configuration:(NSDictionary *)config session:(NSURLSessionConfiguration *)session;
- (void)setEnabled:(BOOL)enabled compatible:(BOOL)compatible;
- (int)request:(NSString *)logical base:(NSString *)base expected:(NSString *)expected;
- (void)retry;
- (void)cancel;
@end

@implementation HaloArsenalDownloads {
    NSURL *_maps, *_library, *_partials, *_directory, *_stage, *_cachedCatalog;
    NSDictionary *_configuration, *_entries, *_activeQuery, *_activeEntry;
    NSURLSession *_session; dispatch_queue_t _work;
    NSMutableDictionary<NSString *, NSDictionary *> *_queries;
    NSMutableDictionary<NSString *, NSNumber *> *_states;
    NSMutableOrderedSet *_pending;
    HaloMapTransfer *_transfer;
    NSString *_activeKey, *_statusText;
    BOOL _enabled, _compatible, _cancelled, _catalogLoaded, _catalogFetched, _catalogFailed, _retryCatalog;
}
- (instancetype)initWithMaps:(NSURL *)maps library:(NSURL *)library partials:(NSURL *)partials
    configuration:(NSDictionary *)config session:(NSURLSessionConfiguration *)session {
    if ((self = [super init])) {
        _maps = maps; _library = library; _partials = partials; _configuration = [config copy];
        _directory = [maps URLByAppendingPathComponent:@"arsenal/v1" isDirectory:YES];
        NSString *url = [config[@"arsenal_catalog_url"] isKindOfClass:NSString.class] ? config[@"arsenal_catalog_url"] : @"";
        _cachedCatalog = [library URLByAppendingPathComponent:[NSString stringWithFormat:@"arsenal-catalog-%@.json", arsenalHash([url dataUsingEncoding:NSASCIIStringEncoding])]];
        _work = dispatch_queue_create("com.pfista.halo.arsenals", DISPATCH_QUEUE_SERIAL);
        _queries = [NSMutableDictionary dictionary]; _states = [NSMutableDictionary dictionary];
        _pending = [NSMutableOrderedSet orderedSet]; _entries = @{}; _statusText = @"";
        NSOperationQueue *delegates = [[NSOperationQueue alloc] init]; delegates.maxConcurrentOperationCount = 1;
        NSURLSessionConfiguration *configuration = [session copy] ?: NSURLSessionConfiguration.ephemeralSessionConfiguration;
        configuration.timeoutIntervalForRequest = 30; configuration.timeoutIntervalForResource = 600; configuration.URLCache = nil;
        _session = [NSURLSession sessionWithConfiguration:configuration delegate:self delegateQueue:delegates];
    }
    return self;
}
- (NSString *)statusText { @synchronized(self) { return _statusText; } }
- (void)status:(NSString *)text {
    @synchronized(self) { _statusText = [text copy]; }
    dispatch_async(dispatch_get_main_queue(), ^{ if (self.statusChanged) self.statusChanged(); });
}
- (void)setEnabled:(BOOL)enabled compatible:(BOOL)compatible {
    @synchronized(self) { _enabled = enabled; _compatible = compatible; }
}
- (BOOL)networkAllowed {
    @synchronized(self) {
        return _enabled && _compatible && !_cancelled && HaloDownloadConfigurationIsValid(_configuration) &&
            [_configuration[@"arsenal_catalog_url"] isKindOfClass:NSString.class];
    }
}
- (int)request:(NSString *)logical base:(NSString *)base expected:(NSString *)expected {
    if (!arsenalLogicalName(logical) || !hashIsValid(base) || (expected.length && !hashIsValid(expected)))
        return HALO_MAP_DOWNLOAD_UNAVAILABLE;
    NSString *key = [NSString stringWithFormat:@"%@|%@|%@", logical, base, expected ?: @""];
    @synchronized(self) {
        if (!_compatible || !HaloDownloadConfigurationIsValid(_configuration)) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
        NSNumber *state = _states[key];
        if (state) return state.intValue;
        /* Cancellation stops HTTP, but must not prevent recognition of a
           previously installed complete local pair on a new request. */
        if (_queries.count >= 345) {
            NSString *discard = nil;
            for (NSString *old in [_queries.allKeys sortedArrayUsingSelector:@selector(compare:)])
                if (_states[old].intValue != HALO_MAP_DOWNLOAD_PENDING) { discard = old; break; }
            if (!discard) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
            [_queries removeObjectForKey:discard]; [_states removeObjectForKey:discard];
        }
        _queries[key] = @{@"logical_map":logical, @"base_sha256":base, @"expected":expected ?: @""};
        _states[key] = @(HALO_MAP_DOWNLOAD_PENDING);
        dispatch_async(_work, ^{ [self->_pending addObject:key]; [self next]; });
    }
    return HALO_MAP_DOWNLOAD_PENDING;
}
- (void)finish:(int)state message:(NSString *)message {
    @synchronized(self) { if (_activeKey) _states[_activeKey] = @(state); }
    if (message.length) [self status:message];
    _activeKey = nil; _activeQuery = nil; _activeEntry = nil;
    if (_stage) {
        unlink([_stage URLByAppendingPathComponent:@"cache.map"].fileSystemRepresentation);
        unlink([_stage URLByAppendingPathComponent:@"manifest.json"].fileSystemRepresentation);
        rmdir(_stage.fileSystemRepresentation); _stage = nil;
    }
    [self next];
}
- (BOOL)directories:(BOOL)create error:(NSError **)error {
    NSArray *directories = @[_library, _maps, [_maps URLByAppendingPathComponent:@"arsenal" isDirectory:YES], _directory];
    if (create) directories = [directories arrayByAddingObject:_partials];
    for (NSURL *directory in directories) {
        struct stat info;
        if (!lstat(directory.fileSystemRepresentation, &info)) {
            if (S_ISDIR(info.st_mode)) continue;
        } else if (errno == ENOENT && !create) return NO;
        else if (errno == ENOENT && create &&
            [NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:error]) continue;
        if (error && !*error) *error = downloadError(@"The Fiesta arsenal folder contains an unsafe path or cannot be created.");
        return NO;
    }
    return YES;
}
- (NSDictionary *)localPair:(NSError **)error {
    if (![self directories:NO error:error]) return nil;
    NSString *physical = arsenalPhysicalName(_activeQuery[@"logical_map"]);
    NSURL *map = [_directory URLByAppendingPathComponent:[physical stringByAppendingPathExtension:@"map"]];
    NSURL *json = [_directory URLByAppendingPathComponent:[physical stringByAppendingPathExtension:@"json"]];
    struct stat mapInfo, jsonInfo;
    BOOL mapExists = !lstat(map.fileSystemRepresentation, &mapInfo), jsonExists = !lstat(json.fileSystemRepresentation, &jsonInfo);
    if (!mapExists && !jsonExists) return nil;
    /* Matching single halves can be completed after interruption. Every
       different or unsafe existing file is preserved by installPair below. */
    if ((mapExists && !S_ISREG(mapInfo.st_mode)) || (jsonExists && !S_ISREG(jsonInfo.st_mode))) {
        if (error) *error = downloadError(@"An existing Fiesta arsenal path is a link or non-file. It was preserved."); return nil;
    }
    if (!mapExists || !jsonExists) return nil;
    NSData *bytes = arsenalReadFile(json, 4096); NSDictionary *manifest = arsenalManifest(bytes, _configuration);
    if (!manifest || ![manifest[@"logical_map"] isEqual:_activeQuery[@"logical_map"]] ||
        ![manifest[@"base_sha256"] isEqual:_activeQuery[@"base_sha256"]] ||
        ([_activeQuery[@"expected"] length] && ![manifest[@"cache_sha256"] isEqual:_activeQuery[@"expected"]]) ||
        !arsenalVerifyCache(map, manifest, _configuration)) {
        if (error) *error = downloadError(@"An existing Fiesta arsenal differs from this request or failed verification. Existing files were preserved."); return nil;
    }
    return manifest;
}
- (void)next {
    if (_transfer || _activeKey) return;
    NSString *key = _pending.firstObject; if (!key) return;
    [_pending removeObject:key];
    @synchronized(self) { _activeKey = key; _activeQuery = _queries[key]; }
    NSError *error = nil;
    if ([self localPair:&error]) {
        [self finish:HALO_MAP_DOWNLOAD_READY message:[NSString stringWithFormat:@"%@ Fiesta arsenal is ready.", _activeQuery[@"logical_map"]]]; return;
    }
    if (error) { [self finish:HALO_MAP_DOWNLOAD_FAILED message:error.localizedDescription]; return; }
    if (![self networkAllowed]) {
        [self finish:HALO_MAP_DOWNLOAD_UNAVAILABLE message:@"Enable community downloads to obtain the requested Fiesta arsenal. Use Check Maps to retry."]; return;
    }
    if (![self directories:YES error:&error]) { [self finish:HALO_MAP_DOWNLOAD_FAILED message:error.localizedDescription]; return; }
    if (!_catalogLoaded) {
        _catalogLoaded = YES;
        NSData *bytes = arsenalReadFile(_cachedCatalog, [_configuration[@"max_catalog_bytes"] unsignedIntegerValue]);
        NSDictionary *entries = bytes ? HaloValidateArsenalCatalog(bytes, _configuration, nil) : nil;
        if (entries) _entries = entries;
    }
    if (!_catalogFetched || _retryCatalog) {
        _retryCatalog = NO; _catalogFetched = YES;
        [self fetch:_configuration[@"arsenal_catalog_url"] catalog:YES manifest:NO]; return;
    }
    if (_catalogFailed) { [self finish:HALO_MAP_DOWNLOAD_FAILED message:@"The Fiesta catalog is unavailable. Use Check Maps to retry."]; return; }
    NSDictionary *entry = _entries[arsenalCatalogKey(_activeQuery[@"logical_map"], _activeQuery[@"base_sha256"])];
    if (entry && (![_activeQuery[@"expected"] length] || [_activeQuery[@"expected"] isEqual:entry[@"cache_sha256"]])) {
        _activeEntry = entry;
        NSNumber *capacity = nil;
        [_directory getResourceValue:&capacity forKey:NSURLVolumeAvailableCapacityKey error:nil];
        if (capacity && capacity.unsignedLongLongValue < [entry[@"cache_file_bytes"] unsignedLongLongValue] + 16781312ULL) {
            [self finish:HALO_MAP_DOWNLOAD_FAILED message:@"Not enough disk space for this Fiesta arsenal. Use Check Maps to retry."]; return;
        }
        _stage = [_partials URLByAppendingPathComponent:[@".fiesta-" stringByAppendingString:NSUUID.UUID.UUIDString] isDirectory:YES];
        if (mkdir(_stage.fileSystemRepresentation, 0700)) { [self finish:HALO_MAP_DOWNLOAD_FAILED message:@"Could not create private Fiesta download staging."]; return; }
        [self fetch:entry[@"manifest_object_key"] catalog:NO manifest:YES]; return;
    }
    [self finish:HALO_MAP_DOWNLOAD_UNAVAILABLE message:@"No approved Fiesta arsenal matches this map, original cache and host revision."];
}
- (void)fetch:(NSString *)key catalog:(BOOL)catalog manifest:(BOOL)manifest {
    NSURL *url = catalog ? [NSURL URLWithString:key] : [[NSURL URLWithString:_configuration[@"objects_base_url"]] URLByAppendingPathComponent:key];
    if (!allowedURL(url, _configuration) || url.query) {
        [self finish:HALO_MAP_DOWNLOAD_FAILED message:@"The Fiesta download URL is not approved."]; return;
    }
    HaloMapTransfer *transfer = [[HaloMapTransfer alloc] init]; transfer.catalog = catalog;
    transfer.entry = _activeEntry; transfer.descriptor = -1;
    if (catalog || manifest) transfer.data = [NSMutableData data];
    else {
        transfer.partial = [_stage URLByAppendingPathComponent:@"cache.map"];
        transfer.descriptor = open(transfer.partial.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
        if (transfer.descriptor < 0) { [self finish:HALO_MAP_DOWNLOAD_FAILED message:@"Could not stage the Fiesta cache."]; return; }
    }
    _transfer = transfer; transfer.task = [_session dataTaskWithURL:url];
    [self status:[NSString stringWithFormat:@"Downloading %@ Fiesta %@…", _activeQuery[@"logical_map"], catalog ? @"catalog" : manifest ? @"manifest" : @"arsenal"]];
    [transfer.task resume];
}
- (void)retry {
    dispatch_async(_work, ^{
        @synchronized(self) {
            self->_cancelled = NO;
            /* An explicit check also invalidates READY memos: files may have
               been removed or edited since the last worker verification.
               Existing pairs are checked locally before considering HTTP. */
            for (NSString *key in self->_queries) {
                if ([key isEqual:self->_activeKey] && self->_transfer && !self->_transfer.cancelled) continue;
                self->_states[key] = @(HALO_MAP_DOWNLOAD_PENDING); [self->_pending addObject:key];
            }
        }
        self->_retryCatalog = YES;
        /* Do not fetch anything if no arsenal has ever been requested. */
        [self next];
    });
}
- (void)cancel {
    /* The consent/cancel gate changes immediately, even when the worker is
       hashing a large staged cache. Publication rechecks it after verification. */
    @synchronized(self) { _cancelled = YES; }
    dispatch_async(_work, ^{
        @synchronized(self) {
            self->_cancelled = YES;
            for (NSString *key in self->_states.allKeys) if (self->_states[key].intValue != HALO_MAP_DOWNLOAD_READY)
                self->_states[key] = @(HALO_MAP_DOWNLOAD_UNAVAILABLE);
        }
        [self->_pending removeAllObjects];
        self->_retryCatalog = NO;
        if (self->_transfer) { self->_transfer.cancelled = YES; [self->_transfer.task cancel]; }
        if (self->_queries.count) [self status:@"Fiesta downloads cancelled. Use Check Maps to retry."];
    });
}
- (BOOL)installPair:(NSError **)error {
    if (![self directories:NO error:error] || ![self networkAllowed]) return NO;
    NSURL *map = [_stage URLByAppendingPathComponent:@"cache.map"], *json = [_stage URLByAppendingPathComponent:@"manifest.json"];
    NSData *manifestBytes = arsenalReadFile(json, 4096); NSDictionary *manifest = arsenalManifest(manifestBytes, _configuration);
    if (!manifest || !arsenalManifestMatches(manifest, _activeEntry) ||
        manifestBytes.length != [_activeEntry[@"manifest_bytes"] unsignedIntegerValue] ||
        ![arsenalHash(manifestBytes) isEqual:_activeEntry[@"manifest_sha256"]] || !arsenalVerifyCache(map, _activeEntry, _configuration)) {
        if (error) *error = downloadError(@"The Fiesta pair failed its manifest, SHA-256, size or Xbox cache check."); return NO;
    }
    NSString *physical = _activeEntry[@"physical_map"];
    int directory = open(_directory.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    if (directory < 0) { if (error) *error = downloadError(@"The Fiesta destination directory is unsafe."); return NO; }
    NSArray *sources = @[map, json];
    NSArray *names = @[[physical stringByAppendingPathExtension:@"map"], [physical stringByAppendingPathExtension:@"json"]];
    BOOL valid = [self networkAllowed]; BOOL created[2] = {NO, NO}; struct stat owned[2];
    for (unsigned i = 0; i < 2 && valid; i++) {
        NSURL *source = sources[i]; NSString *name = names[i];
        struct stat existing;
        if (fstatat(directory, name.fileSystemRepresentation, &existing, AT_SYMLINK_NOFOLLOW)) {
            if (errno != ENOENT || linkat(AT_FDCWD, source.fileSystemRepresentation, directory, name.fileSystemRepresentation, 0)) { valid = NO; break; }
            created[i] = YES;
            /* Record the source inode, so rollback cannot erase a replacement
               created by somebody else after our exclusive link. */
            if (lstat(source.fileSystemRepresentation, &owned[i])) { valid = NO; break; }
        } else {
            /* Inspect through the held directory, preventing a changed parent
               path from redirecting collision checks. Never overwrite leaves. */
            int fd = openat(directory, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
            struct stat opened; valid = fd >= 0 && !fstat(fd, &opened) && S_ISREG(opened.st_mode) &&
                opened.st_dev == existing.st_dev && opened.st_ino == existing.st_ino;
            valid = valid && (i == 0 ? arsenalVerifyDescriptor(fd, _activeEntry, _configuration) :
                [arsenalReadDescriptor(fd, 4096) isEqual:manifestBytes]);
            if (fd >= 0) close(fd);
        }
    }
    /* Reopen both published leaves through the held directory. A complete
       authenticated pair, rather than the first successful link, is READY. */
    for (unsigned i = 0; i < 2 && valid; i++) {
        int fd = openat(directory, [names[i] fileSystemRepresentation], O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
        valid = i == 0 ? arsenalVerifyDescriptor(fd, _activeEntry, _configuration) :
            [arsenalReadDescriptor(fd, 4096) isEqual:manifestBytes];
        if (fd >= 0) close(fd);
    }
    if (valid && ![self networkAllowed]) valid = NO;
    if (valid) {
        struct stat held, named;
        valid = !fstat(directory, &held) && !lstat(_directory.fileSystemRepresentation, &named) &&
            S_ISDIR(named.st_mode) && held.st_dev == named.st_dev && held.st_ino == named.st_ino && !fsync(directory);
    }
    if (!valid) for (unsigned i = 0; i < 2; i++) if (created[i]) {
        struct stat current;
        if (!fstatat(directory, [names[i] fileSystemRepresentation], &current, AT_SYMLINK_NOFOLLOW) &&
            current.st_dev == owned[i].st_dev && current.st_ino == owned[i].st_ino)
            unlinkat(directory, [names[i] fileSystemRepresentation], 0);
    }
    close(directory);
    if (!valid && error) *error = downloadError(@"A conflicting Fiesta destination was preserved; no complete pair was installed.");
    return valid;
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task willPerformHTTPRedirection:(NSHTTPURLResponse *)response
    newRequest:(NSURLRequest *)request completionHandler:(void (^)(NSURLRequest *))completion {
    (void)session; (void)task; (void)response;
    completion(allowedURL(request.URL, _configuration) && !request.URL.query ? request : nil);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveResponse:(NSURLResponse *)response
    completionHandler:(void (^)(NSURLSessionResponseDisposition))completion {
    (void)session;
    dispatch_async(_work, ^{
        HaloMapTransfer *transfer = self->_transfer;
        if (!transfer || transfer.task != task || transfer.cancelled) { completion(NSURLSessionResponseCancel); return; }
        unsigned long long limit = transfer.catalog ? [self->_configuration[@"max_catalog_bytes"] unsignedLongLongValue] :
            [transfer.entry[transfer.data ? @"manifest_bytes" : @"cache_file_bytes"] unsignedLongLongValue];
        BOOL valid = [response isKindOfClass:NSHTTPURLResponse.class] && [(NSHTTPURLResponse *)response statusCode] == 200 &&
            allowedURL(response.URL, self->_configuration) && !response.URL.query &&
            (response.expectedContentLength < 0 || (uint64_t)response.expectedContentLength <= limit) && [self networkAllowed];
        transfer.accepted = valid;
        if (!valid) transfer.failure = downloadError(@"The Fiesta server response failed its origin, status or size check.");
        completion(valid ? NSURLSessionResponseAllow : NSURLSessionResponseCancel);
    });
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    dispatch_async(_work, ^{
        HaloMapTransfer *transfer = self->_transfer; if (!transfer || transfer.task != task || !transfer.accepted || transfer.cancelled) return;
        unsigned long long limit = transfer.catalog ? [self->_configuration[@"max_catalog_bytes"] unsignedLongLongValue] :
            [transfer.entry[transfer.data ? @"manifest_bytes" : @"cache_file_bytes"] unsignedLongLongValue];
        if (data.length > limit - transfer.received || ![self networkAllowed]) {
            transfer.failure = downloadError(@"The Fiesta transfer exceeded its approved size or downloads were disabled."); [task cancel]; return;
        }
        if (transfer.data) [transfer.data appendData:data];
        else {
            NSUInteger offset = 0;
            while (offset < data.length) {
                ssize_t count = write(transfer.descriptor, (const unsigned char *)data.bytes + offset, data.length - offset);
                if (count <= 0) { transfer.failure = downloadError(@"The Fiesta cache could not be written."); [task cancel]; return; }
                offset += count;
            }
        }
        transfer.received += data.length;
        if (!transfer.catalog && !transfer.data) [self status:[NSString stringWithFormat:@"Downloading %@ Fiesta arsenal: %.1f / %.1f MB",
            self->_activeQuery[@"logical_map"], transfer.received / 1048576.0, limit / 1048576.0]];
    });
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)networkError {
    (void)session;
    dispatch_async(_work, ^{
        HaloMapTransfer *transfer = self->_transfer; if (!transfer || transfer.task != task) return;
        self->_transfer = nil;
        NSError *error = transfer.failure ?: networkError;
        if (transfer.descriptor >= 0) {
            if (fsync(transfer.descriptor) && !error) error = downloadError(@"The Fiesta cache could not be saved.");
            close(transfer.descriptor);
        }
        if (transfer.cancelled) {
            /* Retry may already have requeued the cancelled request. Preserve
               that PENDING state instead of undoing the explicit retry. */
            NSString *key = self->_activeKey;
            BOOL requeued = [self->_pending containsObject:key];
            [self finish:requeued ? HALO_MAP_DOWNLOAD_PENDING : HALO_MAP_DOWNLOAD_UNAVAILABLE message:nil]; return;
        }
        if (!error && !transfer.accepted) error = downloadError(@"The Fiesta transfer was not accepted.");
        if (!error && transfer.catalog) {
            NSDictionary *entries = HaloValidateArsenalCatalog(transfer.data, self->_configuration, &error);
            if (entries) {
                struct stat info;
                BOOL safe = lstat(self->_cachedCatalog.fileSystemRepresentation, &info) ? errno == ENOENT : S_ISREG(info.st_mode);
                if (!safe || ![transfer.data writeToURL:self->_cachedCatalog options:NSDataWritingAtomic error:&error]) {
                    if (!error) error = downloadError(@"The cached Fiesta catalog path is unsafe.");
                } else {
                    self->_catalogFailed = NO;
                    self->_entries = entries;
                    NSString *key = self->_activeKey; self->_activeKey = nil; self->_activeQuery = nil;
                    [self->_pending insertObject:key atIndex:0]; [self next]; return;
                }
            }
        } else if (!error && transfer.data) {
            NSDictionary *manifest = arsenalManifest(transfer.data, self->_configuration);
            if (transfer.data.length != [self->_activeEntry[@"manifest_bytes"] unsignedIntegerValue] ||
                ![arsenalHash(transfer.data) isEqual:self->_activeEntry[@"manifest_sha256"]] ||
                !manifest || !arsenalManifestMatches(manifest, self->_activeEntry)) error = downloadError(@"The Fiesta manifest failed verification.");
            else {
                NSURL *json = [self->_stage URLByAppendingPathComponent:@"manifest.json"];
                int fd = open(json.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
                BOOL saved = fd >= 0; NSUInteger offset = 0;
                while (saved && offset < transfer.data.length) {
                    ssize_t count = write(fd, (const unsigned char *)transfer.data.bytes + offset, transfer.data.length - offset);
                    if (count <= 0) saved = NO; else offset += count;
                }
                if (saved && fsync(fd)) saved = NO;
                if (fd >= 0) close(fd);
                if (!saved) error = downloadError(@"The Fiesta manifest could not be staged.");
                else { [self fetch:self->_activeEntry[@"cache_object_key"] catalog:NO manifest:NO]; return; }
            }
        } else if (!error && [self installPair:&error]) {
            [self finish:HALO_MAP_DOWNLOAD_READY message:[NSString stringWithFormat:@"%@ Fiesta arsenal is ready.", self->_activeQuery[@"logical_map"]]]; return;
        }
        if (transfer.catalog) self->_catalogFailed = YES;
        [self finish:HALO_MAP_DOWNLOAD_FAILED message:[NSString stringWithFormat:@"Fiesta download failed: %@ Use Check Maps to retry.", error.localizedDescription ?: @"verification failed"]];
    });
}
@end

@implementation HaloMapDownloads {
    NSURL *_support, *_library, *_partials;
    NSDictionary *_configuration;
    NSURLSession *_session;
    dispatch_queue_t _work;
    NSMutableDictionary<NSNumber *, HaloMapTransfer *> *_transfers;
    NSDictionary<NSString *, NSDictionary *> *_entries;
    NSDictionary<NSString *, NSDictionary *> *_localEntries;
    NSMutableDictionary<NSString *, NSNumber *> *_states;
    NSMutableDictionary<NSString *, NSString *> *_failures;
    NSMutableOrderedSet<NSString *> *_requests;
    BOOL _catalogPending, _catalogFailed, _refreshRequested, _initializing, _mapPending, _enabled, _configured, _cancelled, _compatibleData;
    NSString *_statusText;
    HaloArsenalDownloads *_arsenalDownloads;
}
- (instancetype)initWithSupportDirectory:(NSURL *)support configuration:(NSDictionary *)config
                    sessionConfiguration:(NSURLSessionConfiguration *)sessionConfiguration {
    if ((self = [super init])) {
        _support = support.URLByStandardizingPath.URLByResolvingSymlinksInPath;
        _library = [_support URLByAppendingPathComponent:@"Community Maps" isDirectory:YES];
        _mapsDirectory = [_library URLByAppendingPathComponent:@"maps" isDirectory:YES];
        _partials = [_library URLByAppendingPathComponent:@"Downloads" isDirectory:YES];
        _configuration = [config copy];
        _configured = HaloDownloadConfigurationIsValid(config) && [config[@"catalog_url"] isKindOfClass:NSString.class];
        _statusText = _configured ? @"Community downloads are off." : @"Map hosting is not configured for this build.";
        _work = dispatch_queue_create("com.pfista.halo.maps", DISPATCH_QUEUE_SERIAL);
        _states = [NSMutableDictionary dictionary];
        _failures = [NSMutableDictionary dictionary];
        _transfers = [NSMutableDictionary dictionary];
        _requests = [NSMutableOrderedSet orderedSet];
        _entries = @{};
        _localEntries = @{};
        NSOperationQueue *delegates = [[NSOperationQueue alloc] init];
        delegates.maxConcurrentOperationCount = 1;
        NSURLSessionConfiguration *session = sessionConfiguration ?: NSURLSessionConfiguration.ephemeralSessionConfiguration;
        session.timeoutIntervalForRequest = 30;
        session.timeoutIntervalForResource = 600;
        session.URLCache = nil;
        _session = [NSURLSession sessionWithConfiguration:session delegate:self delegateQueue:delegates];
        _arsenalDownloads = [[HaloArsenalDownloads alloc] initWithMaps:_mapsDirectory library:_library partials:_partials
            configuration:_configuration session:sessionConfiguration];
        __weak HaloMapDownloads *weakSelf = self;
        _arsenalDownloads.statusChanged = ^{
            HaloMapDownloads *manager = weakSelf;
            if (manager.statusChanged) manager.statusChanged();
        };
    }
    return self;
}
- (BOOL)configured { return _configured; }
- (BOOL)enabled { @synchronized(self) { return _enabled; } }
- (BOOL)compatibleData { @synchronized(self) { return _compatibleData; } }
- (NSString *)statusText {
    NSString *community;
    @synchronized(self) {
        NSString *key = [[_failures.allKeys sortedArrayUsingSelector:@selector(compare:)] firstObject];
        NSString *failure = key ? _failures[key] : nil;
        community = failure && ![_statusText containsString:failure]
            ? [NSString stringWithFormat:@"%@\n%@", failure, _statusText] : _statusText;
    }
    NSString *arsenal = _arsenalDownloads.statusText;
    return arsenal.length ? [NSString stringWithFormat:@"%@\n%@", community, arsenal] : community;
}
- (void)status:(NSString *)text {
    @synchronized(self) { _statusText = [text copy]; }
    dispatch_async(dispatch_get_main_queue(), ^{ if (self.statusChanged) self.statusChanged(); });
}
- (void)activateForHost { hostDownloads = self; }
- (void)setGameDataRoot:(NSURL *)root {
    /* Called before the engine starts. Changing the next-launch preference
       never switches the current session's content profile. */
    NSURL *maps = nil, *ui = nil;
    for (NSURL *file in [NSFileManager.defaultManager contentsOfDirectoryAtURL:root includingPropertiesForKeys:nil options:0 error:nil])
        if ([file.lastPathComponent.lowercaseString isEqual:@"maps"]) maps = file;
    for (NSURL *file in maps ? [NSFileManager.defaultManager contentsOfDirectoryAtURL:maps includingPropertiesForKeys:nil options:0 error:nil] : @[])
        if ([file.lastPathComponent.lowercaseString isEqual:@"ui.map"]) ui = file;
    NSFileHandle *file = [NSFileHandle fileHandleForReadingFromURL:ui error:nil];
    NSData *header = [file readDataUpToLength:2048 error:nil];
    [file closeFile];
    NSString *build = nil;
    if (header.length == 2048) {
        const unsigned char *bytes = header.bytes, *end = memchr(bytes + 64, 0, 32);
        if (end) build = [[NSString alloc] initWithBytes:bytes + 64 length:end - bytes - 64 encoding:NSASCIIStringEncoding];
    }
    @synchronized(self) { _compatibleData = [build isEqual:_configuration[@"cache_build"]]; }
    [_arsenalDownloads setEnabled:self.enabled compatible:self.compatibleData];
    if (!self.compatibleData && _configured) [self status:@"This map collection needs original Xbox NTSC 2276 game data. Your current maps stay unchanged."];
}
- (BOOL)prepareDirectories:(NSError **)error {
    for (NSURL *directory in @[_library, _mapsDirectory, _partials]) {
        struct stat info;
        if (!lstat(directory.fileSystemRepresentation, &info) && !S_ISDIR(info.st_mode)) {
            if (error) *error = downloadError(@"The managed map folder contains a link or file where a directory is required.");
            return NO;
        }
        if (![NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:YES attributes:nil error:error]) return NO;
    }
    return YES;
}
- (void)startEnabled:(BOOL)enabled {
    @synchronized(self) { _enabled = enabled; _initializing = self.compatibleData; }
    [_arsenalDownloads setEnabled:enabled compatible:self.compatibleData];
    dispatch_async(_work, ^{
        if (!HaloDownloadConfigurationIsValid(self->_configuration) || !self.compatibleData) { @synchronized(self) { self->_initializing = NO; } return; }
        NSError *error = nil;
        if (![self prepareDirectories:&error]) {
            @synchronized(self) { self->_initializing = NO; self->_catalogFailed = YES; }
            [self status:error.localizedDescription]; return;
        }
        [self loadLocalMaps];
        NSURL *cached = [self->_library URLByAppendingPathComponent:@"catalog.json"];
        NSData *bytes = [NSData dataWithContentsOfURL:cached options:NSDataReadingMappedIfSafe error:nil];
        if (bytes) {
            NSDictionary *record = [NSJSONSerialization JSONObjectWithData:bytes options:0 error:nil];
            if ([record isKindOfClass:NSDictionary.class] && [record[@"catalog_url"] isEqual:self->_configuration[@"catalog_url"]]) {
                NSData *catalog = [NSJSONSerialization dataWithJSONObject:record[@"catalog"] ?: @{} options:0 error:nil];
                NSDictionary *entries = HaloValidateMapCatalog(catalog, self->_configuration, nil);
                if (entries) [self acceptCatalog:entries];
            }
        }
        if (self.enabled && self->_configured) [self fetchCatalog];
        @synchronized(self) { self->_initializing = NO; }
    });
}
- (void)setDownloadsEnabled:(BOOL)enabled {
    @synchronized(self) { _enabled = enabled; }
    [_arsenalDownloads setEnabled:enabled compatible:self.compatibleData];
    if (enabled) [self checkForMaps];
    else [self cancelDownloads];
}
- (void)checkForMaps {
    [_arsenalDownloads retry];
    dispatch_async(_work, ^{
        @synchronized(self) {
            self->_cancelled = NO; self->_catalogFailed = NO;
            [self->_failures removeObjectForKey:@"_catalog"];
        }
        if (!self->_configured) { [self status:@"Map hosting is not configured for this build."]; return; }
        if (!self.compatibleData) { [self status:@"This map collection requires Xbox NTSC 2276 game data."]; return; }
        if (!self.enabled) { [self status:@"Enable community downloads to check for maps."]; return; }
        @synchronized(self) {
            for (NSString *name in self->_states.allKeys) if (self->_states[name].intValue == HALO_MAP_DOWNLOAD_FAILED) {
                [self->_states removeObjectForKey:name];
                [self->_failures removeObjectForKey:name];
                [self->_requests addObject:name];
            }
        }
        if (self->_catalogPending) self->_refreshRequested = YES;
        else [self fetchCatalog];
    });
}
- (void)cancelDownloads {
    [_arsenalDownloads cancel];
    dispatch_async(_work, ^{
        @synchronized(self) {
            self->_cancelled = YES; self->_catalogFailed = NO;
            [self->_failures removeAllObjects];
        }
        self->_refreshRequested = NO;
        for (HaloMapTransfer *transfer in self->_transfers.allValues) { transfer.cancelled = YES; [transfer.task cancel]; }
        [self->_requests removeAllObjects];
        @synchronized(self) {
            for (NSString *name in self->_states.allKeys) if (self->_states[name].intValue != HALO_MAP_DOWNLOAD_READY)
                [self->_states removeObjectForKey:name];
        }
        [self status:@"Map downloads cancelled. Use Check Maps to retry."];
    });
}
- (int)requestMap:(NSString *)name {
    return [self requestMap:name prioritize:YES];
}
- (int)requestArsenal:(NSString *)name baseSHA256:(NSString *)base expectedSHA256:(NSString *)expected {
    return [_arsenalDownloads request:name base:base expected:expected];
}
- (int)requestMap:(NSString *)name prioritize:(BOOL)prioritize {
    if (!mapNameIsValid(name) || !self.compatibleData) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
    NSString *key = name.lowercaseString;
    BOOL enqueue = NO;
    @synchronized(self) {
        NSNumber *state = _states[key];
        if (state.intValue == HALO_MAP_DOWNLOAD_READY) return HALO_MAP_DOWNLOAD_READY;
        if (_initializing) return HALO_MAP_DOWNLOAD_PENDING;
        if (_cancelled) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
        if (_localEntries[key]) return state ? state.intValue : HALO_MAP_DOWNLOAD_FAILED;
        if (!_enabled || !_configured || _cancelled) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
        if (state && (state.intValue != HALO_MAP_DOWNLOAD_PENDING || !prioritize)) return state.intValue;
        if (!state) {
            if (!_entries[key]) return _catalogPending || _initializing ? HALO_MAP_DOWNLOAD_PENDING :
                _catalogFailed ? HALO_MAP_DOWNLOAD_FAILED : HALO_MAP_DOWNLOAD_UNAVAILABLE;
            _states[key] = @(HALO_MAP_DOWNLOAD_PENDING);
            enqueue = YES;
        }
    }
    dispatch_async(_work, ^{
        if (enqueue) [self->_requests addObject:key];
        // A join request moves ahead of bulk downloads without restarting the
        // active transfer (which is no longer in the pending ordered set).
        if (prioritize && [self->_requests containsObject:key]) {
            [self->_requests removeObject:key];
            [self->_requests insertObject:key atIndex:0];
        }
        [self nextMap];
    });
    return HALO_MAP_DOWNLOAD_PENDING;
}
- (void)acceptCatalog:(NSDictionary *)entries {
    NSMutableDictionary *combined = [entries mutableCopy];
    [combined addEntriesFromDictionary:_localEntries];
    entries = combined;
    @synchronized(self) {
        _entries = entries;
        for (NSString *name in _states.allKeys) {
            if (!entries[name] || _states[name].intValue == HALO_MAP_DOWNLOAD_READY) {
                [_states removeObjectForKey:name]; [_failures removeObjectForKey:name];
            }
        }
    }
    for (NSString *name in entries) {
        NSDictionary *entry = entries[name];
        NSURL *file = [_mapsDirectory URLByAppendingPathComponent:[entry[@"id"] stringByAppendingPathExtension:@"map"]];
        struct stat info;
        if (!lstat(file.fileSystemRepresentation, &info)) {
            NSError *error = nil;
            BOOL valid = HaloVerifyDownloadedMap(file, entry, _configuration, &error);
            NSString *message = [NSString stringWithFormat:@"%@ conflicts with an existing map. Keep that file or move it manually before retrying.", entry[@"id"]];
            @synchronized(self) {
                _states[name] = @(valid ? HALO_MAP_DOWNLOAD_READY : HALO_MAP_DOWNLOAD_FAILED);
                if (valid) [_failures removeObjectForKey:name]; else _failures[name] = message;
            }
            if (!valid) [self status:message];
        } else if ([entry[@"local"] boolValue]) {
            NSString *message = [NSString stringWithFormat:@"%@ is missing. Re-import its community package, or cancel downloads to stop waiting.", name];
            @synchronized(self) { _states[name] = @(HALO_MAP_DOWNLOAD_FAILED); _failures[name] = message; }
            [self status:message];
        }
        // Enabled launches fetch the whole approved collection. READY maps
        // and conflicts above still preserve existing bytes.
        if (self.enabled) [self requestMap:name prioritize:NO];
    }
}
- (NSDictionary *)localEntry:(NSDictionary *)manifest {
    if (![manifest isKindOfClass:NSDictionary.class]) return nil;
    NSString *name = manifest[@"id"];
    NSDictionary *output = manifest[@"output"];
    if (!mapNameIsValid(name) || ![name isEqual:name.lowercaseString] ||
        ![manifest[@"profile"] isEqual:_configuration[@"profile"]] ||
        ![manifest[@"cache_build"] isEqual:_configuration[@"cache_build"]] ||
        ![output isKindOfClass:NSDictionary.class] || !hashIsValid(output[@"sha256"]) ||
        !numberInRange(output[@"size"], [_configuration[@"max_map_bytes"] unsignedLongLongValue])) return nil;
    return @{@"id":name, @"sha256":output[@"sha256"], @"file_bytes":output[@"size"], @"local":@YES,
             @"cache_build":manifest[@"cache_build"]};
}
- (void)loadLocalMaps {
    NSURL *receipt = [_library URLByAppendingPathComponent:@"local-maps.json"];
    int descriptor = open(receipt.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    struct stat info;
    if (descriptor < 0) return;
    BOOL bounded = !fstat(descriptor, &info) && S_ISREG(info.st_mode) && info.st_size > 0 && info.st_size <= 1048576;
    NSFileHandle *file = [[NSFileHandle alloc] initWithFileDescriptor:descriptor closeOnDealloc:YES];
    NSData *bytes = bounded ? [file readDataUpToLength:1048577 error:nil] : nil;
    [file closeFile];
    if (!bounded || bytes.length != (NSUInteger)info.st_size) return;
    id record = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:nil] : nil;
    if (![record isKindOfClass:NSDictionary.class] || ![record[@"version"] isEqual:@1] ||
        ![record[@"maps"] isKindOfClass:NSArray.class] || [record[@"maps"] count] > 512) return;
    NSMutableDictionary *valid = [NSMutableDictionary dictionary];
    for (id manifest in record[@"maps"]) {
        NSDictionary *entry = [self localEntry:manifest];
        if (!entry || valid[entry[@"id"]]) continue;
        NSURL *map = [_mapsDirectory URLByAppendingPathComponent:[entry[@"id"] stringByAppendingPathExtension:@"map"]];
        if (HaloVerifyDownloadedMap(map, entry, _configuration, nil)) valid[entry[@"id"]] = entry;
    }
    @synchronized(self) { _localEntries = valid; }
    [self acceptCatalog:@{}];
    if (valid.count) [self status:[NSString stringWithFormat:@"%lu locally rebuilt maps are available offline.", (unsigned long)valid.count]];
}
- (void)registerAssembledMap:(NSURL *)file manifest:(NSDictionary *)manifest
                 completion:(void (^)(NSError *))completion {
    dispatch_async(_work, ^{
        NSError *error = nil;
        NSDictionary *entry = [self localEntry:manifest];
        NSURL *expected = entry ? [self->_mapsDirectory URLByAppendingPathComponent:[entry[@"id"] stringByAppendingPathExtension:@"map"]] : nil;
        if (!self.compatibleData || !entry || ![file.URLByStandardizingPath.path isEqual:expected.path] ||
            ![self prepareDirectories:&error] || !HaloVerifyDownloadedMap(file, entry, self->_configuration, &error))
            error = error ?: downloadError(@"The reconstructed map could not be registered with this game-data profile.");
        if (!error) {
            NSMutableDictionary *local = [self->_localEntries mutableCopy];
            local[entry[@"id"]] = entry;
            if (local.count > 512) error = downloadError(@"The local map library has reached its limit.");
            NSMutableArray *maps = [NSMutableArray array];
            for (NSString *name in [local.allKeys sortedArrayUsingSelector:@selector(compare:)]) {
                NSDictionary *item = local[name];
                [maps addObject:@{@"id":name, @"profile":self->_configuration[@"profile"], @"cache_build":item[@"cache_build"],
                    @"output":@{@"size":item[@"file_bytes"], @"sha256":item[@"sha256"]}}];
            }
            NSURL *receipt = [self->_library URLByAppendingPathComponent:@"local-maps.json"];
            struct stat info;
            if (!error && !lstat(receipt.fileSystemRepresentation, &info) && !S_ISREG(info.st_mode))
                error = downloadError(@"The local map receipt is a link or directory. Existing files were preserved.");
            NSData *bytes = !error ? [NSJSONSerialization dataWithJSONObject:@{@"version":@1, @"maps":maps} options:0 error:&error] : nil;
            if (bytes && ![bytes writeToURL:receipt options:NSDataWritingAtomic error:&error]) bytes = nil;
            if (!error) {
                @synchronized(self) {
                    self->_localEntries = local;
                    NSMutableDictionary *all = [self->_entries mutableCopy];
                    all[entry[@"id"]] = entry; self->_entries = all;
                    self->_states[entry[@"id"]] = @(HALO_MAP_DOWNLOAD_READY);
                    [self->_failures removeObjectForKey:entry[@"id"]];
                }
                [self->_requests removeObject:entry[@"id"]];
                for (HaloMapTransfer *transfer in self->_transfers.allValues)
                    if (!transfer.catalog && [transfer.entry[@"id"] isEqual:entry[@"id"]]) {
                        transfer.cancelled = YES; [transfer.task cancel];
                    }
                [self status:[NSString stringWithFormat:@"%@ is ready to play and available offline.", entry[@"id"]]];
            }
        }
        dispatch_async(dispatch_get_main_queue(), ^{ if (completion) completion(error); });
    });
}
- (void)fetchCatalog {
    if (_catalogPending || _cancelled || !self.enabled) return;
    NSError *error = nil;
    if (![self prepareDirectories:&error]) {
        @synchronized(self) { _catalogFailed = YES; }
        [self status:error.localizedDescription]; return;
    }
    @synchronized(self) { _catalogPending = YES; }
    [self status:@"Checking approved community maps…"];
    HaloMapTransfer *transfer = [[HaloMapTransfer alloc] init];
    transfer.catalog = YES;
    transfer.descriptor = -1;
    transfer.data = [NSMutableData data];
    NSURLSessionDataTask *task = [_session dataTaskWithURL:[NSURL URLWithString:_configuration[@"catalog_url"]]];
    transfer.task = task;
    _transfers[@(task.taskIdentifier)] = transfer;
    [task resume];
}
- (void)nextMap {
    if (_mapPending || _catalogPending || _cancelled || !self.enabled) return;
    NSString *name = _requests.firstObject;
    if (!name) return;
    [_requests removeObject:name];
    NSDictionary *entry = _entries[name];
    if ([entry[@"local"] boolValue]) { [self nextMap]; return; }
    if (!entry) {
        @synchronized(self) { [_states removeObjectForKey:name]; }
        [self nextMap]; return;
    }
    @synchronized(self) { if (_states[name].intValue == HALO_MAP_DOWNLOAD_READY) { [self nextMap]; return; } }
    NSError *error = nil;
    if (![self prepareDirectories:&error]) { [self failMap:name message:error.localizedDescription]; return; }
    NSURL *destination = [_mapsDirectory URLByAppendingPathComponent:[entry[@"id"] stringByAppendingPathExtension:@"map"]];
    struct stat info;
    if (!lstat(destination.fileSystemRepresentation, &info)) {
        if (HaloVerifyDownloadedMap(destination, entry, _configuration, &error)) {
            @synchronized(self) { _states[name] = @(HALO_MAP_DOWNLOAD_READY); }
            [self nextMap]; return;
        }
        [self failMap:name message:@"An existing map has different bytes. It was left unchanged; move it manually before retrying."]; return;
    }
    NSNumber *free = nil;
    [_library getResourceValue:&free forKey:NSURLVolumeAvailableCapacityKey error:nil];
    if (free && free.unsignedLongLongValue < [entry[@"file_bytes"] unsignedLongLongValue] + 1048576) {
        [self failMap:name message:@"There is not enough free space to download this map."]; return;
    }
    HaloMapTransfer *transfer = [[HaloMapTransfer alloc] init];
    transfer.entry = entry;
    transfer.partial = [_partials URLByAppendingPathComponent:[NSString stringWithFormat:@"%@-%@.partial", entry[@"sha256"], NSUUID.UUID.UUIDString]];
    transfer.descriptor = open(transfer.partial.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (transfer.descriptor < 0) { [self failMap:name message:@"The download staging file could not be created."]; return; }
    NSURL *url = [[NSURL URLWithString:_configuration[@"objects_base_url"]] URLByAppendingPathComponent:entry[@"object_key"]];
    if (!allowedURL(url, _configuration)) { close(transfer.descriptor); unlink(transfer.partial.fileSystemRepresentation); [self failMap:name message:@"The map URL is not an approved HTTPS origin."]; return; }
    _mapPending = YES;
    @synchronized(self) { _states[name] = @(HALO_MAP_DOWNLOAD_PENDING); }
    [self status:[NSString stringWithFormat:@"Downloading %@…", entry[@"id"]]];
    NSURLSessionDataTask *task = [_session dataTaskWithURL:url];
    transfer.task = task;
    _transfers[@(task.taskIdentifier)] = transfer;
    [task resume];
}
- (void)failMap:(NSString *)name message:(NSString *)message {
    NSString *failure = [NSString stringWithFormat:@"%@: %@ Use Check Maps to retry.", name, message];
    @synchronized(self) {
        if (_localEntries[name] && _states[name].intValue == HALO_MAP_DOWNLOAD_READY) { [self nextMap]; return; }
        _states[name] = @(HALO_MAP_DOWNLOAD_FAILED); _failures[name] = failure;
    }
    [self status:failure];
    [self nextMap];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completion {
    (void)session; (void)task; (void)response;
    completion(allowedURL(request.URL, _configuration) ? request : nil);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveResponse:(NSURLResponse *)response
 completionHandler:(void (^)(NSURLSessionResponseDisposition))completion {
    (void)session;
    dispatch_async(_work, ^{
        HaloMapTransfer *transfer = self->_transfers[@(task.taskIdentifier)];
        unsigned long long limit = transfer.catalog ? [self->_configuration[@"max_catalog_bytes"] unsignedLongLongValue] : [transfer.entry[@"file_bytes"] unsignedLongLongValue];
        transfer.accepted = [response isKindOfClass:NSHTTPURLResponse.class] && ((NSHTTPURLResponse *)response).statusCode == 200 &&
            allowedURL(response.URL, self->_configuration) && (response.expectedContentLength < 0 || (unsigned long long)response.expectedContentLength <= limit);
        if (!transfer.accepted) transfer.failure = downloadError(@"The server returned an unexpected response or file size.");
        completion(transfer.accepted ? NSURLSessionResponseAllow : NSURLSessionResponseCancel);
    });
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    dispatch_async(_work, ^{
        HaloMapTransfer *transfer = self->_transfers[@(task.taskIdentifier)];
        if (!transfer || transfer.failure) return;
        unsigned long long limit = transfer.catalog ? [self->_configuration[@"max_catalog_bytes"] unsignedLongLongValue] : [transfer.entry[@"file_bytes"] unsignedLongLongValue];
        if (data.length > limit - transfer.received) { transfer.failure = downloadError(@"The server sent more bytes than the approved file size."); [task cancel]; return; }
        if (transfer.catalog) [transfer.data appendData:data];
        else {
            const char *bytes = data.bytes;
            NSUInteger offset = 0;
            while (offset < data.length) {
                ssize_t written = write(transfer.descriptor, bytes + offset, data.length - offset);
                if (written <= 0) { transfer.failure = downloadError(@"The map could not be written. Check free space."); [task cancel]; return; }
                offset += (NSUInteger)written;
            }
        }
        transfer.received += data.length;
        if (!transfer.catalog) [self status:[NSString stringWithFormat:@"%@ — %llu of %llu MB", transfer.entry[@"id"], transfer.received >> 20, limit >> 20]];
    });
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)networkError {
    (void)session;
    dispatch_async(_work, ^{
        HaloMapTransfer *transfer = self->_transfers[@(task.taskIdentifier)];
        if (!transfer) return;
        [self->_transfers removeObjectForKey:@(task.taskIdentifier)];
        NSError *error = transfer.cancelled ? downloadError(@"Download cancelled.") : transfer.failure ?: networkError;
        if (transfer.catalog) {
            @synchronized(self) { self->_catalogPending = NO; }
            NSDictionary *entries = !error && transfer.accepted ? HaloValidateMapCatalog(transfer.data, self->_configuration, &error) : nil;
            if (entries) {
                NSDictionary *catalog = [NSJSONSerialization JSONObjectWithData:transfer.data options:0 error:nil];
                NSData *cached = [NSJSONSerialization dataWithJSONObject:@{@"catalog_url":self->_configuration[@"catalog_url"], @"catalog":catalog} options:0 error:&error];
                if (cached && [cached writeToURL:[self->_library URLByAppendingPathComponent:@"catalog.json"] options:NSDataWritingAtomic error:&error]) {
                    @synchronized(self) { self->_catalogFailed = NO; [self->_failures removeObjectForKey:@"_catalog"]; }
                    [self acceptCatalog:entries];
                    [self status:[NSString stringWithFormat:@"%lu approved maps available. Missing maps download when needed.", (unsigned long)entries.count]];
                }
            }
            if (error && !transfer.cancelled) {
                NSString *failure = [@"Map catalog unavailable: " stringByAppendingString:error.localizedDescription];
                @synchronized(self) { self->_catalogFailed = YES; self->_failures[@"_catalog"] = failure; }
                [self status:failure];
            }
        } else {
            self->_mapPending = NO;
            if (transfer.descriptor >= 0) {
                if (fsync(transfer.descriptor) && !error) error = downloadError(@"The map could not be saved to disk.");
                close(transfer.descriptor);
            }
            NSString *name = [transfer.entry[@"id"] lowercaseString];
            if (!error && ![self->_entries[name][@"sha256"] isEqual:transfer.entry[@"sha256"]])
                error = downloadError(@"The approved map revision changed during download. Retry with the current catalog.");
            if (!error && transfer.accepted && HaloVerifyDownloadedMap(transfer.partial, transfer.entry, self->_configuration, &error)) {
                NSURL *destination = [self->_mapsDirectory URLByAppendingPathComponent:[transfer.entry[@"id"] stringByAppendingPathExtension:@"map"]];
                /* link is atomic and exclusive; unlike rename it cannot replace
                   a file that appeared while the HTTP task was running. */
                if (!link(transfer.partial.fileSystemRepresentation, destination.fileSystemRepresentation) ||
                    HaloVerifyDownloadedMap(destination, transfer.entry, self->_configuration, nil)) {
                    @synchronized(self) { self->_states[name] = @(HALO_MAP_DOWNLOAD_READY); [self->_failures removeObjectForKey:name]; }
                    [self status:[NSString stringWithFormat:@"%@ is ready.", transfer.entry[@"id"]]];
                } else error = downloadError(@"The destination already exists or could not be created. Existing files were preserved.");
            }
            if (transfer.partial) unlink(transfer.partial.fileSystemRepresentation);
            if (error && !transfer.cancelled) [self failMap:name message:error.localizedDescription];
        }
        if (transfer.catalog && self->_refreshRequested && self.enabled && !self->_cancelled) {
            self->_refreshRequested = NO;
            [self fetchCatalog];
        }
        [self nextMap];
    });
}
@end

int halo_map_download_directory(char *out, size_t capacity) {
    if (!out || !capacity || !hostDownloads || !hostDownloads.compatibleData) return 0;
    return [hostDownloads.mapsDirectory.path getCString:out maxLength:capacity encoding:NSUTF8StringEncoding] ? 1 : 0;
}
int halo_map_download_request(const char *map_name) {
    if (!hostDownloads || !map_name) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
    NSString *name = [[NSString alloc] initWithBytes:map_name length:strnlen(map_name, 32) encoding:NSASCIIStringEncoding];
    return [hostDownloads requestMap:name];
}
int halo_arsenal_download_request(const char *logical_map, const char *base_sha256_hex, const char *cache_sha256_hex) {
    if (!hostDownloads || !logical_map || !base_sha256_hex) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
    NSString *name = [[NSString alloc] initWithBytes:logical_map length:strnlen(logical_map, 32) encoding:NSASCIIStringEncoding];
    NSString *base = [[NSString alloc] initWithBytes:base_sha256_hex length:strnlen(base_sha256_hex, 65) encoding:NSASCIIStringEncoding];
    NSString *expected = cache_sha256_hex ? [[NSString alloc] initWithBytes:cache_sha256_hex length:strnlen(cache_sha256_hex, 65) encoding:NSASCIIStringEncoding] : @"";
    if (!expected) return HALO_MAP_DOWNLOAD_UNAVAILABLE;
    return [hostDownloads requestArsenal:name baseSHA256:base expectedSHA256:expected];
}
