/* Synthetic Xbox headers and an NSURLProtocol HTTPS fixture; no game assets,
   credentials or external network are used. */
#import <Foundation/Foundation.h>
#import "HaloMapDownloads.h"
#include <CommonCrypto/CommonDigest.h>
#include <assert.h>
#include "../../linux/include/halo_expanded_cache.h"

static NSMutableDictionary<NSString *, NSData *> *responses;
static unsigned requests;
@class FixtureHTTPS;
static BOOL holdMapResponses;
static NSMutableArray<FixtureHTTPS *> *heldMapResponses;
static NSMutableArray<NSString *> *requestPaths;
@interface FixtureHTTPS : NSURLProtocol
@property(nonatomic) BOOL stopped;
@property(nonatomic, strong) NSData *responseBytes;
- (void)finishLoading;
@end
@implementation FixtureHTTPS
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return [request.URL.host isEqual:@"maps.test"]; }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    @synchronized(FixtureHTTPS.class) {
        self.responseBytes = responses[self.request.URL.path]; requests++;
        [requestPaths addObject:self.request.URL.path];
        if (holdMapResponses && [self.request.URL.path hasSuffix:@".map"]) {
            [heldMapResponses addObject:self]; return;
        }
    }
    [self finishLoading];
}
- (void)finishLoading {
    NSData *bytes = self.responseBytes;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_MSEC), dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        @synchronized(self) {
            if (self.stopped) return;
            NSDictionary *headers = @{@"Content-Length":@(bytes.length).stringValue};
            NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:self.request.URL statusCode:bytes ? 200 : 404 HTTPVersion:@"HTTP/1.1" headerFields:headers];
            [self.client URLProtocol:self didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
            if (bytes) [self.client URLProtocol:self didLoadData:bytes];
            [self.client URLProtocolDidFinishLoading:self];
        }
    });
}
- (void)stopLoading { @synchronized(self) { self.stopped = YES; } }
@end

static void releaseMapResponse(void) {
    FixtureHTTPS *response;
    @synchronized(FixtureHTTPS.class) {
        assert(heldMapResponses.count == 1);
        response = heldMapResponses.firstObject;
        [heldMapResponses removeObjectAtIndex:0];
    }
    [response finishLoading];
}

static NSData *fixtureMap(NSString *name, NSString *build) {
    NSMutableData *bytes = [NSMutableData dataWithLength:4096];
    unsigned char *p = bytes.mutableBytes;
    memcpy(p, "daeh", 4);
    uint32_t version = 5, declared = 4096, offset = 2048, size = 128;
    memcpy(p + 4, &version, 4); memcpy(p + 8, &declared, 4);
    memcpy(p + 16, &offset, 4); memcpy(p + 20, &size, 4);
    memcpy(p + 32, name.UTF8String, name.length); memcpy(p + 64, build.UTF8String, build.length);
    p[96] = 1; memcpy(p + 2044, "toof", 4);
    for (NSUInteger i = 2048; i < bytes.length; i++) p[i] = (unsigned char)i;
    return bytes;
}
static NSString *hash(NSData *bytes) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(bytes.bytes, (CC_LONG)bytes.length, digest);
    NSMutableString *result = [NSMutableString string];
    for (unsigned i = 0; i < sizeof(digest); i++) [result appendFormat:@"%02x", digest[i]];
    return result;
}
static NSDictionary *entry(NSString *name, NSData *bytes) {
    NSString *sha = hash(bytes);
    return @{@"id":name, @"sha256":sha, @"file_bytes":@(bytes.length), @"cache_version":@5,
        @"cache_build":@"01.10.12.2276", @"scenario_type":@1,
        @"object_key":[NSString stringWithFormat:@"maps/sha256/%@/%@.map", sha, name]};
}
static NSData *catalog(NSArray *maps) {
    return [NSJSONSerialization dataWithJSONObject:@{@"schema_version":@1, @"profile":@"stock-xbox-ntsc", @"maps":maps} options:0 error:nil];
}
static void waitForAtLine(unsigned line, BOOL (^predicate)(void)) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:5];
    while (!predicate() && until.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    if (!predicate()) {
        @synchronized(FixtureHTTPS.class) {
            fprintf(stderr, "Timed out waiting at map_downloads.m:%u after %u fixture requests; last path: %s\n",
                line, requests, requestPaths.lastObject.UTF8String ?: "(none)");
        }
        assert(predicate());
    }
}
#define waitFor(predicate) waitForAtLine(__LINE__, predicate)
static NSURL *folder(NSURL *root, NSString *name) {
    NSURL *result = [root URLByAppendingPathComponent:name isDirectory:YES];
    assert([NSFileManager.defaultManager createDirectoryAtURL:result withIntermediateDirectories:YES attributes:nil error:nil]);
    return result;
}
static HaloMapDownloads *manager(NSURL *support, NSURL *data, NSDictionary *config) {
    NSURLSessionConfiguration *session = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    session.protocolClasses = @[FixtureHTTPS.class];
    HaloMapDownloads *downloads = [[HaloMapDownloads alloc] initWithSupportDirectory:support configuration:config sessionConfiguration:session];
    [downloads setGameDataRoot:data];
    return downloads;
}
static NSData *arsenalJSON(id value) {
    return [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingWithoutEscapingSlashes error:nil];
}
static NSString *arsenalPhysical(NSString *logical) {
    return logical.length <= 23 ? [@"_fiesta_" stringByAppendingString:logical] :
        [@"_fiestah_" stringByAppendingString:[hash([logical dataUsingEncoding:NSASCIIStringEncoding]) substringToIndex:16]];
}
static NSDictionary *arsenalEntry(NSString *name, NSString *base, NSData *cache, NSData **manifestData) {
    NSString *physical = arsenalPhysical(name), *cacheSHA = hash(cache);
    NSDictionary *manifest = @{@"schema_version":@1, @"generation":@1, @"logical_map":name, @"physical_map":physical,
        @"base_sha256":base, @"cache_sha256":cacheSHA, @"weapon_list_sha256":@HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256,
        @"cache_file_bytes":@(cache.length), @"cache_declared_bytes":@4096};
    NSData *bytes = arsenalJSON(manifest);
    if (manifestData) *manifestData = bytes;
    return @{@"logical_map":name, @"physical_map":physical, @"base_sha256":base, @"cache_sha256":cacheSHA,
        @"cache_file_bytes":@(cache.length), @"cache_declared_bytes":@4096, @"manifest_sha256":hash(bytes), @"manifest_bytes":@(bytes.length),
        @"cache_object_key":[NSString stringWithFormat:@"arsenals/v1/sha256/%@/%@.map", cacheSHA, physical],
        @"manifest_object_key":[NSString stringWithFormat:@"arsenals/v1/sha256/%@/%@.json", hash(bytes), physical]};
}
static NSData *arsenalCatalog(NSArray *entries) {
    return arsenalJSON(@{@"schema_version":@1, @"profile":@"fiesta-arsenal-v1", @"generation":@1,
        @"weapon_list_sha256":@HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256, @"arsenals":entries});
}
static void serveArsenal(NSDictionary *entry, NSData *cache, NSData *manifest) {
    @synchronized(FixtureHTTPS.class) {
        responses[[@"/" stringByAppendingString:entry[@"cache_object_key"]]] = cache;
        responses[[@"/" stringByAppendingString:entry[@"manifest_object_key"]]] = manifest;
    }
}
static NSURL *pairDirectory(HaloMapDownloads *downloads) { return folder(downloads.mapsDirectory, @"arsenal/v1"); }
static void installFixturePair(HaloMapDownloads *downloads, NSDictionary *entry, NSData *cache, NSData *manifest) {
    NSURL *directory = pairDirectory(downloads); NSString *physical = entry[@"physical_map"];
    assert([cache writeToURL:[directory URLByAppendingPathComponent:[physical stringByAppendingPathExtension:@"map"]] atomically:YES]);
    assert([manifest writeToURL:[directory URLByAppendingPathComponent:[physical stringByAppendingPathExtension:@"json"]] atomically:YES]);
}
static int requestArsenal(HaloMapDownloads *downloads, NSDictionary *entry, NSString *expected) {
    return [downloads requestArsenal:entry[@"logical_map"] baseSHA256:entry[@"base_sha256"] expectedSHA256:expected];
}
static void testArsenals(NSURL *root, NSURL *game, NSDictionary *config) {
    NSString *base = hash([@"original prisoner revision" dataUsingEncoding:NSASCIIStringEncoding]);
    NSData *cache = fixtureMap(@"_fiesta_prisoner", @"01.10.12.2276"), *manifest;
    NSDictionary *approved = arsenalEntry(@"prisoner", base, cache, &manifest);
    NSData *otherCache = fixtureMap(@"_fiesta_bloodgulch", @"01.10.12.2276"), *otherManifest;
    NSDictionary *other = arsenalEntry(@"bloodgulch", base, otherCache, &otherManifest);
    NSError *error = nil;
    assert(HaloValidateArsenalCatalog(arsenalCatalog(@[approved, other]), config, &error).count == 2);
    assert(!HaloValidateArsenalCatalog(arsenalCatalog(@[]), config, &error));
    assert(!HaloValidateArsenalCatalog(arsenalCatalog(@[approved, approved]), config, &error));
    NSMutableDictionary *revision = [approved mutableCopy]; revision[@"base_sha256"] = hash(cache);
    assert(HaloValidateArsenalCatalog(arsenalCatalog(@[approved, revision]), config, &error).count == 2);
    for (NSDictionary *replacement in @[@{@"physical_map":@"prisoner"}, @{@"cache_file_bytes":@YES}, @{@"manifest_bytes":@4097},
        @{@"cache_declared_bytes":@134217729}, @{@"base_sha256":@"bad"}, @{@"extra":@1},
        @{@"cache_object_key":@"../unsafe"}, @{@"manifest_object_key":@"https://maps.test/unsafe"}]) {
        NSMutableDictionary *bad = [approved mutableCopy]; [bad addEntriesFromDictionary:replacement];
        assert(!HaloValidateArsenalCatalog(arsenalCatalog(@[bad]), config, &error));
    }
    for (NSString *name in @[@"_private", @"prisoner ", @"ui", @"a10", @"nul", @"com1", @"../bad", @"Prisoner"]) {
        NSMutableDictionary *bad = [approved mutableCopy]; bad[@"logical_map"] = name;
        bad[@"physical_map"] = arsenalPhysical(name);
        assert(!HaloValidateArsenalCatalog(arsenalCatalog(@[bad]), config, &error));
    }
    NSString *longName = @"a123456789012345678901234567890";
    NSData *longCache = fixtureMap(arsenalPhysical(longName), @"01.10.12.2276");
    assert(HaloValidateArsenalCatalog(arsenalCatalog(@[arsenalEntry(longName, base, longCache, NULL)]), config, &error));
    NSString *json = [[NSString alloc] initWithData:arsenalCatalog(@[approved]) encoding:NSASCIIStringEncoding];
    for (NSString *bad in @[[json stringByReplacingOccurrencesOfString:@"\"schema_version\":1" withString:@"\"schema_version\":1,\"schema_version\":1"],
        [json stringByReplacingOccurrencesOfString:@"\"generation\":1" withString:@"\"generation\":true"],
        [json stringByReplacingOccurrencesOfString:@"4096" withString:@"4096.0"], [json stringByAppendingString:@"{}"],
        [json stringByReplacingOccurrencesOfString:@"fiesta-arsenal-v1" withString:@"fiesta-arsenal-v2"],
        [json stringByReplacingOccurrencesOfString:@"prisoner" withString:@"pris\\u006fner"]]) {
        assert(!HaloValidateArsenalCatalog([bad dataUsingEncoding:NSASCIIStringEncoding], config, &error));
    }
    NSMutableArray *overBudget = [NSMutableArray array];
    for (unsigned i = 0; i < 17; i++) {
        NSMutableDictionary *large = [approved mutableCopy]; large[@"base_sha256"] = hash([@(i).stringValue dataUsingEncoding:NSASCIIStringEncoding]);
        large[@"cache_file_bytes"] = @134217728; [overBudget addObject:large];
    }
    assert(!HaloValidateArsenalCatalog(arsenalCatalog(overBudget), config, &error));
    @synchronized(FixtureHTTPS.class) {
        responses[@"/catalog.json"] = catalog(@[]);
        responses[@"/arsenals.json"] = arsenalCatalog(@[approved, other]);
    }
    serveArsenal(approved, cache, manifest); serveArsenal(other, otherCache, otherManifest);

    // Missing local pair is checked off-thread, even with downloads disabled.
    unsigned before = requests;
    HaloMapDownloads *offline = manager(folder(root, @"arsenal-offline"), game, config);
    [offline startEnabled:NO];
    assert(requestArsenal(offline, approved, nil) == HALO_MAP_DOWNLOAD_PENDING);
    waitFor(^BOOL{ return requestArsenal(offline, approved, nil) == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
    assert(requests == before);
    // Predownloaded pairs need neither catalog history nor HTTP consent.
    installFixturePair(offline, approved, cache, manifest);
    [offline checkForMaps];
    waitFor(^BOOL{ return requestArsenal(offline, approved, nil) == HALO_MAP_DOWNLOAD_READY; });
    assert(requests == before);
    [offline activateForHost];
    assert(halo_arsenal_download_request("prisoner", base.UTF8String, NULL) == HALO_MAP_DOWNLOAD_READY);
    assert(halo_arsenal_download_request("prisoner", "invalid", NULL) == HALO_MAP_DOWNLOAD_UNAVAILABLE);
    assert(requestArsenal(offline, approved, approved[@"cache_sha256"]) == HALO_MAP_DOWNLOAD_PENDING);
    waitFor(^BOOL{ return requestArsenal(offline, approved, approved[@"cache_sha256"]) == HALO_MAP_DOWNLOAD_READY; });
    assert(requests == before);

    HaloMapDownloads *onDemand = manager(folder(root, @"arsenal-demand"), game, config);
    [onDemand startEnabled:YES];
    waitFor(^BOOL{ return [onDemand.statusText containsString:@"0 approved maps available"]; });
    before = requests;
    holdMapResponses = YES;
    assert(requestArsenal(onDemand, approved, approved[@"cache_sha256"]) == HALO_MAP_DOWNLOAD_PENDING);
    waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
    assert(requests == before + 3); // catalog, requested manifest, requested cache
    assert(requestArsenal(onDemand, approved, approved[@"cache_sha256"]) == HALO_MAP_DOWNLOAD_PENDING);
    NSURL *destination = [onDemand.mapsDirectory URLByAppendingPathComponent:@"arsenal/v1/_fiesta_prisoner.map"];
    assert(![NSFileManager.defaultManager fileExistsAtPath:destination.path]);
    assert(![NSFileManager.defaultManager fileExistsAtPath:[onDemand.mapsDirectory URLByAppendingPathComponent:@"arsenal/v1/_fiesta_bloodgulch.map"].path]);
    releaseMapResponse();
    waitFor(^BOOL{ return requestArsenal(onDemand, approved, approved[@"cache_sha256"]) == HALO_MAP_DOWNLOAD_READY; });
    holdMapResponses = NO;
    [onDemand setDownloadsEnabled:NO];
    assert(requestArsenal(onDemand, approved, approved[@"cache_sha256"]) == HALO_MAP_DOWNLOAD_READY);
    HaloMapDownloads *freshOffline = manager(folder(root, @"arsenal-demand"), game, config);
    [freshOffline startEnabled:NO];
    before = requests;
    waitFor(^BOOL{ return requestArsenal(freshOffline, approved, nil) == HALO_MAP_DOWNLOAD_READY; });
    assert(requests == before);
    // Check Maps invalidates a READY memo if its pair was manually removed.
    NSURL *readyDirectory = pairDirectory(freshOffline);
    assert([NSFileManager.defaultManager removeItemAtURL:[readyDirectory URLByAppendingPathComponent:@"_fiesta_prisoner.map"] error:nil]);
    assert([NSFileManager.defaultManager removeItemAtURL:[readyDirectory URLByAppendingPathComponent:@"_fiesta_prisoner.json"] error:nil]);
    [freshOffline checkForMaps];
    waitFor(^BOOL{ return requestArsenal(freshOffline, approved, nil) == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
    assert(requests == before); // disabled revalidation did not contact HTTP
    [freshOffline setDownloadsEnabled:YES];
    waitFor(^BOOL{ return requestArsenal(freshOffline, approved, nil) == HALO_MAP_DOWNLOAD_READY; });
    assert([[NSData dataWithContentsOfURL:[readyDirectory URLByAppendingPathComponent:@"_fiesta_prisoner.map"]] isEqual:cache]);

    // Different complete installs and symlink leaves are never overwritten.
    HaloMapDownloads *conflict = manager(folder(root, @"arsenal-conflict"), game, config);
    installFixturePair(conflict, approved, cache, manifest);
    [conflict startEnabled:YES];
    waitFor(^BOOL{ return [conflict.statusText containsString:@"0 approved maps available"]; });
    before = requests;
    waitFor(^BOOL{ return requestArsenal(conflict, approved, hash(manifest)) == HALO_MAP_DOWNLOAD_FAILED; });
    assert(requests == before);
    assert([[NSData dataWithContentsOfURL:[pairDirectory(conflict) URLByAppendingPathComponent:@"_fiesta_prisoner.map"]] isEqual:cache]);
    HaloMapDownloads *linked = manager(folder(root, @"arsenal-link"), game, config);
    NSURL *linkedMap = [pairDirectory(linked) URLByAppendingPathComponent:@"_fiesta_prisoner.map"];
    NSURL *victim = [root URLByAppendingPathComponent:@"arsenal-link-target"];
    assert([cache writeToURL:victim atomically:YES]);
    assert([NSFileManager.defaultManager createSymbolicLinkAtURL:linkedMap withDestinationURL:victim error:nil]);
    [linked startEnabled:NO];
    waitFor(^BOOL{ return requestArsenal(linked, approved, nil) == HALO_MAP_DOWNLOAD_FAILED; });
    assert([[NSData dataWithContentsOfURL:victim] isEqual:cache]);

    // A matching interrupted half is completed only after full verification.
    HaloMapDownloads *half = manager(folder(root, @"arsenal-half"), game, config);
    assert([cache writeToURL:[pairDirectory(half) URLByAppendingPathComponent:@"_fiesta_prisoner.map"] atomically:YES]);
    [half startEnabled:YES];
    waitFor(^BOOL{ return requestArsenal(half, approved, nil) == HALO_MAP_DOWNLOAD_READY; });
    assert([[NSData dataWithContentsOfURL:[pairDirectory(half) URLByAppendingPathComponent:@"_fiesta_prisoner.json"]] isEqual:manifest]);

    HaloMapDownloads *cancelled = manager(folder(root, @"arsenal-cancel"), game, config);
    [cancelled startEnabled:YES];
    waitFor(^BOOL{ return [cancelled.statusText containsString:@"0 approved maps available"]; });
    holdMapResponses = YES;
    assert(requestArsenal(cancelled, approved, nil) == HALO_MAP_DOWNLOAD_PENDING);
    waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
    [cancelled cancelDownloads];
    waitFor(^BOOL{ return [cancelled.statusText containsString:@"Fiesta downloads cancelled"]; });
    assert(requestArsenal(cancelled, approved, nil) == HALO_MAP_DOWNLOAD_UNAVAILABLE);
    releaseMapResponse();
    [cancelled checkForMaps];
    waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
    assert(requestArsenal(cancelled, approved, nil) == HALO_MAP_DOWNLOAD_PENDING);
    releaseMapResponse();
    waitFor(^BOOL{ return requestArsenal(cancelled, approved, nil) == HALO_MAP_DOWNLOAD_READY; });
    holdMapResponses = NO;

    // An authenticated manifest cannot authorize a truncated/tampered cache.
    NSMutableData *tampered = [cache mutableCopy]; ((unsigned char *)tampered.mutableBytes)[3000] ^= 1;
    serveArsenal(approved, tampered, manifest);
    HaloMapDownloads *corrupt = manager(folder(root, @"arsenal-corrupt"), game, config);
    [corrupt startEnabled:YES];
    waitFor(^BOOL{ return requestArsenal(corrupt, approved, nil) == HALO_MAP_DOWNLOAD_FAILED; });
    NSURL *corruptDirectory = pairDirectory(corrupt);
    assert(![NSFileManager.defaultManager fileExistsAtPath:[corruptDirectory URLByAppendingPathComponent:@"_fiesta_prisoner.map"].path]);
    assert(![NSFileManager.defaultManager fileExistsAtPath:[corruptDirectory URLByAppendingPathComponent:@"_fiesta_prisoner.json"].path]);
    serveArsenal(approved, cache, manifest);
    [corrupt checkForMaps];
    waitFor(^BOOL{ return requestArsenal(corrupt, approved, nil) == HALO_MAP_DOWNLOAD_READY; });

    // Authenticated file bytes still require exact physical/declared headers.
    NSMutableData *badDeclared = [cache mutableCopy]; uint32_t declared = 6000;
    memcpy((unsigned char *)badDeclared.mutableBytes + 8, &declared, 4);
    NSArray *badHeaders = @[fixtureMap(@"prisoner", @"01.10.12.2276"), badDeclared,
        fixtureMap(@"_fiesta_prisoner", @"01.01.14.2342")];
    unsigned index = 0;
    for (NSData *badCache in badHeaders) {
        NSData *badManifest;
        NSDictionary *badEntry = arsenalEntry(@"prisoner", base, badCache, &badManifest);
        @synchronized(FixtureHTTPS.class) { responses[@"/arsenals.json"] = arsenalCatalog(@[badEntry]); }
        serveArsenal(badEntry, badCache, badManifest);
        HaloMapDownloads *badHeader = manager(folder(root, [NSString stringWithFormat:@"arsenal-bad-header-%u", index++]), game, config);
        [badHeader startEnabled:YES];
        waitFor(^BOOL{ return requestArsenal(badHeader, badEntry, nil) == HALO_MAP_DOWNLOAD_FAILED; });
        assert(![NSFileManager.defaultManager fileExistsAtPath:[badHeader.mapsDirectory URLByAppendingPathComponent:@"arsenal/v1/_fiesta_prisoner.map"].path]);
    }
    NSMutableDictionary *wrongManifest = [[NSJSONSerialization JSONObjectWithData:manifest options:0 error:nil] mutableCopy];
    wrongManifest[@"base_sha256"] = hash(cache);
    NSData *wrongManifestBytes = arsenalJSON(wrongManifest);
    NSMutableDictionary *wrongManifestEntry = [approved mutableCopy];
    wrongManifestEntry[@"manifest_sha256"] = hash(wrongManifestBytes);
    wrongManifestEntry[@"manifest_bytes"] = @(wrongManifestBytes.length);
    wrongManifestEntry[@"manifest_object_key"] = [NSString stringWithFormat:@"arsenals/v1/sha256/%@/_fiesta_prisoner.json", hash(wrongManifestBytes)];
    @synchronized(FixtureHTTPS.class) { responses[@"/arsenals.json"] = arsenalCatalog(@[wrongManifestEntry]); }
    serveArsenal(wrongManifestEntry, cache, wrongManifestBytes);
    HaloMapDownloads *wrongPair = manager(folder(root, @"arsenal-manifest-mismatch"), game, config);
    [wrongPair startEnabled:YES];
    waitFor(^BOOL{ return [wrongPair.statusText containsString:@"0 approved maps available"]; });
    before = requests;
    waitFor(^BOOL{ return requestArsenal(wrongPair, approved, nil) == HALO_MAP_DOWNLOAD_FAILED; });
    assert(requests == before + 2); // catalog + rejected manifest, no cache transfer
    puts("Fiesta HTTPS fixtures: strict catalog/pin/identity/bounds, demand-only exact-SHA pairs, disabled offline reuse, partial completion, link/conflict preservation, cancellation and retry passed");
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        assert(argc == 3);
        NSURL *root = [NSURL fileURLWithPath:@(argv[1]) isDirectory:YES];
        NSDictionary *unconfigured = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])] options:0 error:nil];
        assert(HaloDownloadConfigurationIsValid(unconfigured));
        NSMutableDictionary *config = [unconfigured mutableCopy];
        config[@"catalog_url"] = @"https://maps.test/catalog.json";
        config[@"arsenal_catalog_url"] = @"https://maps.test/arsenals.json";
        config[@"objects_base_url"] = @"https://maps.test/";
        config[@"allowed_origins"] = @[@"https://maps.test"];
        assert(HaloDownloadConfigurationIsValid(config));
        NSMutableDictionary *badConfig = [config mutableCopy];
        badConfig[@"catalog_url"] = @"http://maps.test/catalog.json";
        assert(!HaloDownloadConfigurationIsValid(badConfig));
        badConfig[@"catalog_url"] = @"https://evil.test/catalog.json";
        assert(!HaloDownloadConfigurationIsValid(badConfig));
        badConfig[@"catalog_url"] = @"https://person:password@maps.test/catalog.json";
        assert(!HaloDownloadConfigurationIsValid(badConfig));
        badConfig = [config mutableCopy]; badConfig[@"arsenal_catalog_url"] = @"http://maps.test/arsenals.json";
        assert(!HaloDownloadConfigurationIsValid(badConfig));
        badConfig[@"arsenal_catalog_url"] = @"https://evil.test/arsenals.json";
        assert(!HaloDownloadConfigurationIsValid(badConfig));
        badConfig[@"arsenal_catalog_url"] = @"https://maps.test/arsenals.json?profile=other";
        assert(!HaloDownloadConfigurationIsValid(badConfig));
        NSData *map = fixtureMap(@"downrush", @"01.10.12.2276");
        NSDictionary *approved = entry(@"downrush", map);
        NSError *error = nil;
        assert(HaloValidateMapCatalog(catalog(@[approved]), config, &error).count == 1);
        for (NSString *name in @[@"ui", @"a10", @"bloodgulch", @"../unsafe", @"bad/name", @"bad\\name"]) {
            assert(!HaloValidateMapCatalog(catalog(@[entry(name, map)]), config, &error));
        }
        assert(!HaloValidateMapCatalog(catalog(@[approved, approved]), config, &error));
        assert(!HaloValidateMapCatalog(catalog(@[entry(@"DownRush", map)]), config, &error));
        assert(!HaloValidateMapCatalog(catalog(@[@3]), config, &error));
        for (NSDictionary *replacement in @[@{@"cache_version":@7}, @{@"cache_build":@"01.01.14.2342"},
            @{@"file_bytes":@134217729}, @{@"object_key":@"../downrush.map"}, @{@"sha256":@"wrong"}]) {
            NSMutableDictionary *bad = [approved mutableCopy]; [bad addEntriesFromDictionary:replacement];
            assert(!HaloValidateMapCatalog(catalog(@[bad]), config, &error));
        }
        NSURL *file = [root URLByAppendingPathComponent:@"map.map"];
        assert([map writeToURL:file atomically:YES]);
        assert(HaloVerifyDownloadedMap(file, approved, config, &error));
        NSMutableDictionary *lowerLimits = [config mutableCopy];
        lowerLimits[@"max_cache_bytes"] = @2048;
        assert(!HaloVerifyDownloadedMap(file, approved, lowerLimits, &error));
        lowerLimits[@"max_cache_bytes"] = @4096; lowerLimits[@"max_tag_bytes"] = @64;
        assert(!HaloVerifyDownloadedMap(file, approved, lowerLimits, &error));
        NSMutableData *tampered = [map mutableCopy]; ((unsigned char *)tampered.mutableBytes)[2500] ^= 1;
        assert([tampered writeToURL:file atomically:YES]); assert(!HaloVerifyDownloadedMap(file, approved, config, &error));
        NSData *wrongHeader = fixtureMap(@"atlas", @"01.10.12.2276");
        assert([wrongHeader writeToURL:file atomically:YES]);
        NSMutableDictionary *correctHashWrongName = [approved mutableCopy]; correctHashWrongName[@"sha256"] = hash(wrongHeader);
        assert(!HaloVerifyDownloadedMap(file, correctHashWrongName, config, &error));
        assert([[map subdataWithRange:NSMakeRange(0, 1000)] writeToURL:file atomically:YES]);
        assert(!HaloVerifyDownloadedMap(file, approved, config, &error));
        NSURL *linked = [root URLByAppendingPathComponent:@"link.map"];
        assert([NSFileManager.defaultManager createSymbolicLinkAtURL:linked withDestinationURL:file error:nil]);
        assert(!HaloVerifyDownloadedMap(linked, approved, config, &error));

        NSURL *game = folder(root, @"game"), *maps = folder(game, @"maps");
        assert([fixtureMap(@"ui", @"01.10.12.2276") writeToURL:[maps URLByAppendingPathComponent:@"ui.map"] atomically:YES]);
        responses = [@{@"/catalog.json":catalog(@[approved]),
            [@"/" stringByAppendingString:approved[@"object_key"]]:map} mutableCopy];
        requestPaths = [NSMutableArray array];
        heldMapResponses = [NSMutableArray array];
        HaloMapDownloads *disabled = manager(folder(root, @"disabled"), game, config);
        [disabled startEnabled:NO];
        waitFor(^BOOL{ return [disabled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
        assert(requests == 0);

        // All forty eligible maps download on launch without a guest/UI map
        // request, including entries explicitly opting out of legacy prefetch.
        NSMutableArray *launchEntries = [NSMutableArray array];
        for (unsigned i = 0; i < 40; i++) {
            NSString *name = [NSString stringWithFormat:@"fixture%02u", i];
            NSData *bytes = fixtureMap(name, @"01.10.12.2276");
            NSMutableDictionary *item = [entry(name, bytes) mutableCopy];
            if (i % 2 == 0) item[@"prefetch"] = @NO;
            [launchEntries addObject:item];
            responses[[@"/" stringByAppendingString:item[@"object_key"]]] = bytes;
        }
        responses[@"/catalog.json"] = catalog(launchEntries);
        HaloMapDownloads *launch = manager(folder(root, @"all-forty-launch"), game, config);
        [launch startEnabled:YES];
        waitFor(^BOOL{
            for (NSDictionary *item in launchEntries) {
                NSURL *mapFile = [launch.mapsDirectory URLByAppendingPathComponent:[item[@"id"] stringByAppendingPathExtension:@"map"]];
                if (![NSFileManager.defaultManager fileExistsAtPath:mapFile.path]) return NO;
            }
            return YES;
        });
        assert(requests == 41);
        for (NSDictionary *item in launchEntries) {
            NSURL *mapFile = [launch.mapsDirectory URLByAppendingPathComponent:[item[@"id"] stringByAppendingPathExtension:@"map"]];
            assert(HaloVerifyDownloadedMap(mapFile, item, config, &error));
            assert([launch requestMap:item[@"id"]] == HALO_MAP_DOWNLOAD_READY);
        }
        [launch setDownloadsEnabled:NO];

        // Hold the active bulk download, then append a newly approved map
        // behind the remaining queue. Repeated demand must make it next while
        // preserving the active transfer and downloading every map once.
        NSMutableArray *queueEntries = [NSMutableArray array];
        for (NSString *name in @[@"queueone", @"queuetwo", @"queuethree"]) {
            NSData *bytes = fixtureMap(name, @"01.10.12.2276");
            NSDictionary *item = entry(name, bytes);
            [queueEntries addObject:item];
            responses[[@"/" stringByAppendingString:item[@"object_key"]]] = bytes;
        }
        unsigned beforePriority = requests;
        NSUInteger firstPriorityPath = requestPaths.count;
        responses[@"/catalog.json"] = catalog(queueEntries);
        holdMapResponses = YES;
        HaloMapDownloads *priority = manager(folder(root, @"demand-priority"), game, config);
        [priority startEnabled:YES];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        NSString *active;
        @synchronized(FixtureHTTPS.class) { active = heldMapResponses.firstObject.request.URL.lastPathComponent.stringByDeletingPathExtension; }
        for (unsigned i = 0; i < 3; i++) assert([priority requestMap:active] == HALO_MAP_DOWNLOAD_PENDING);
        NSData *demandBytes = fixtureMap(@"queuedemand", @"01.10.12.2276");
        NSDictionary *demandEntry = entry(@"queuedemand", demandBytes);
        [queueEntries addObject:demandEntry];
        @synchronized(FixtureHTTPS.class) {
            responses[@"/catalog.json"] = catalog(queueEntries);
            responses[[@"/" stringByAppendingString:demandEntry[@"object_key"]]] = demandBytes;
        }
        [priority checkForMaps];
        waitFor(^BOOL{ return [priority requestMap:@"queuedemand"] == HALO_MAP_DOWNLOAD_PENDING &&
            [priority requestMap:@"unknown"] == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
        for (unsigned i = 0; i < 3; i++) assert([priority requestMap:@"queuedemand"] == HALO_MAP_DOWNLOAD_PENDING);
        releaseMapResponse();
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        @synchronized(FixtureHTTPS.class) {
            assert([heldMapResponses.firstObject.request.URL.lastPathComponent isEqual:@"queuedemand.map"]);
        }
        assert([priority requestMap:active] == HALO_MAP_DOWNLOAD_READY);
        releaseMapResponse();
        for (unsigned i = 0; i < 2; i++) {
            waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
            releaseMapResponse();
        }
        waitFor(^BOOL{
            for (NSDictionary *item in queueEntries)
                if (![NSFileManager.defaultManager fileExistsAtPath:[priority.mapsDirectory URLByAppendingPathComponent:[item[@"id"] stringByAppendingPathExtension:@"map"]].path]) return NO;
            return YES;
        });
        assert(requests - beforePriority == 6); // Two catalogs and four maps.
        for (NSDictionary *item in queueEntries) {
            NSURL *mapFile = [priority.mapsDirectory URLByAppendingPathComponent:[item[@"id"] stringByAppendingPathExtension:@"map"]];
            assert(HaloVerifyDownloadedMap(mapFile, item, config, &error));
            assert([priority requestMap:item[@"id"]] == HALO_MAP_DOWNLOAD_READY);
            NSString *path = [@"/" stringByAppendingString:item[@"object_key"]];
            unsigned count = 0;
            @synchronized(FixtureHTTPS.class) {
                for (NSUInteger i = firstPriorityPath; i < requestPaths.count; i++)
                    if ([requestPaths[i] isEqual:path]) count++;
            }
            assert(count == 1);
        }
        holdMapResponses = NO;
        [priority setDownloadsEnabled:NO];
        responses[@"/catalog.json"] = catalog(@[approved]);

        HaloMapDownloads *downloads = manager(folder(root, @"support"), game, config);
        [downloads activateForHost];
        // Catalog progress is transient when automatic downloads start. Hold
        // the map itself so PENDING assertions observe a durable transfer.
        holdMapResponses = YES;
        [downloads startEnabled:YES];
        assert(halo_map_download_request("downrush") == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert([downloads requestMap:@"unknown"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert([downloads requestMap:@"ui"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert([downloads requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        releaseMapResponse();
        waitFor(^BOOL{ return [downloads requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        NSURL *installed = [downloads.mapsDirectory URLByAppendingPathComponent:@"downrush.map"];
        assert([[NSData dataWithContentsOfURL:installed] isEqual:map]);
        char path[4096]; assert(halo_map_download_directory(path, sizeof(path)));
        assert([@(path) isEqual:downloads.mapsDirectory.path]);
        [downloads setDownloadsEnabled:NO];
        assert([downloads requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY);
        unsigned afterDownload = requests;
        HaloMapDownloads *offline = manager(folder(root, @"support"), game, config);
        [offline startEnabled:NO];
        waitFor(^BOOL{ return [offline requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        assert(requests == afterDownload);

        // Revalidation clears stale ready state when installed bytes disappear.
        assert([NSFileManager.defaultManager removeItemAtURL:installed error:nil]);
        [offline setDownloadsEnabled:YES];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert([offline requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        releaseMapResponse();
        waitFor(^BOOL{ return [offline requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        [offline setDownloadsEnabled:NO];
        holdMapResponses = NO;

        HaloMapDownloads *collision = manager(folder(root, @"collision"), game, config);
        folder(folder(root, @"collision/Community Maps"), @"maps");
        NSURL *existing = [collision.mapsDirectory URLByAppendingPathComponent:@"downrush.map"];
        NSData *personal = [@"user file" dataUsingEncoding:NSUTF8StringEncoding];
        assert([personal writeToURL:existing atomically:YES]);
        [collision startEnabled:YES];
        waitFor(^BOOL{ return [collision requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert([collision.statusText containsString:@"conflicts with an existing map"]);
        assert([[NSData dataWithContentsOfURL:existing] isEqual:personal]);
        [collision cancelDownloads];
        waitFor(^BOOL{ return [collision.statusText containsString:@"cancelled"]; });
        assert([collision requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        [collision checkForMaps];
        waitFor(^BOOL{ return [collision requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        [collision setDownloadsEnabled:NO];
        assert([collision requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);

        // A catalog-authenticated hash does not bypass the Xbox header checks.
        NSMutableDictionary *wrongEntry = [approved mutableCopy]; wrongEntry[@"sha256"] = hash(wrongHeader);
        wrongEntry[@"object_key"] = [NSString stringWithFormat:@"maps/sha256/%@/downrush.map", hash(wrongHeader)];
        @synchronized(FixtureHTTPS.class) {
            responses[@"/catalog.json"] = catalog(@[wrongEntry]);
            responses[[@"/" stringByAppendingString:wrongEntry[@"object_key"]]] = wrongHeader;
        }
        HaloMapDownloads *invalid = manager(folder(root, @"invalid"), game, config);
        holdMapResponses = YES;
        [invalid startEnabled:YES];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert([invalid requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        releaseMapResponse();
        waitFor(^BOOL{ return [invalid requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        holdMapResponses = NO;
        assert(![NSFileManager.defaultManager fileExistsAtPath:[invalid.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
        assert([NSFileManager.defaultManager contentsOfDirectoryAtPath:[invalid.mapsDirectory.URLByDeletingLastPathComponent.path stringByAppendingPathComponent:@"Downloads"] error:nil].count == 0);
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[approved]); }
        [invalid checkForMaps];
        waitFor(^BOOL{ return [invalid requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });

        NSURL *pal = folder(root, @"pal"), *palMaps = folder(pal, @"maps");
        assert([fixtureMap(@"ui", @"01.01.14.2342") writeToURL:[palMaps URLByAppendingPathComponent:@"ui.map"] atomically:YES]);
        HaloMapDownloads *incompatible = manager(folder(root, @"pal-support"), pal, config);
        [incompatible activateForHost]; [incompatible startEnabled:YES];
        assert(!incompatible.compatibleData && [incompatible requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert(!halo_map_download_directory(path, sizeof(path)));
        assert([incompatible.statusText containsString:@"NTSC 2276"]);
        NSURL *upper = folder(root, @"uppercase"), *upperMaps = folder(upper, @"MAPS");
        assert([fixtureMap(@"ui", @"01.10.12.2276") writeToURL:[upperMaps URLByAppendingPathComponent:@"UI.MAP"] atomically:YES]);
        HaloMapDownloads *uppercase = manager(folder(root, @"uppercase-support"), upper, config);
        assert(uppercase.compatibleData);

        HaloMapDownloads *cancelled = manager(folder(root, @"cancelled"), game, config);
        holdMapResponses = YES;
        [cancelled startEnabled:YES];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        [cancelled cancelDownloads];
        waitFor(^BOOL{ return [cancelled.statusText containsString:@"cancelled"]; });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert(![NSFileManager.defaultManager fileExistsAtPath:[cancelled.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
        releaseMapResponse();
        [cancelled checkForMaps];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        releaseMapResponse();
        waitFor(^BOOL{ return [cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        holdMapResponses = NO;

        // Removing catalog authority also removes the exported READY state.
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[]); }
        [cancelled checkForMaps];
        waitFor(^BOOL{ return [cancelled.statusText containsString:@"0 approved maps available"]; });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert([NSFileManager.defaultManager fileExistsAtPath:[cancelled.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);

        // An HTTP error leaves the missing-map hook in FAILED until a retry.
        @synchronized(FixtureHTTPS.class) { [responses removeObjectForKey:@"/catalog.json"]; }
        HaloMapDownloads *failedCatalog = manager(folder(root, @"catalog-failure"), game, config);
        [failedCatalog startEnabled:YES];
        assert([failedCatalog requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [failedCatalog requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert([failedCatalog.statusText containsString:@"catalog unavailable"]);
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[approved]); }
        holdMapResponses = YES;
        [failedCatalog checkForMaps];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert(![failedCatalog.statusText containsString:@"catalog unavailable"]);
        assert([failedCatalog requestMap:@"unknown"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        releaseMapResponse();
        waitFor(^BOOL{ return [failedCatalog requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        [failedCatalog setDownloadsEnabled:NO];
        // Immediate cancel/retry while catalog completion is still queued must
        // schedule a fresh check rather than losing the retry to pending state.
        HaloMapDownloads *rapidRetry = manager(folder(root, @"rapid-retry"), game, config);
        [rapidRetry startEnabled:YES];
        [rapidRetry cancelDownloads];
        [rapidRetry checkForMaps];
        waitFor(^BOOL{ @synchronized(FixtureHTTPS.class) { return heldMapResponses.count == 1; } });
        assert([rapidRetry requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        releaseMapResponse();
        waitFor(^BOOL{ return [rapidRetry requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        holdMapResponses = NO;
        testArsenals(root, game, config);
        puts("Native HTTPS fixtures: forty-map launch downloads despite prefetch=false, demand priority without duplicate transfers, disabled-network gating, async pending/ready, catalog bounds, SHA/header checks, atomic install, offline reuse, collision preservation, retry and PAL gating passed");
    }
    return 0;
}
