/* Synthetic Xbox headers and an NSURLProtocol HTTPS fixture; no game assets,
   credentials or external network are used. */
#import <Foundation/Foundation.h>
#import "HaloMapDownloads.h"
#import "HaloMapPackages.h"
#include <CommonCrypto/CommonDigest.h>
#include <assert.h>
#include <sys/stat.h>

static NSMutableDictionary<NSString *, NSData *> *responses;
static unsigned requests;
@interface FixtureHTTPS : NSURLProtocol
@property(nonatomic) BOOL stopped;
@end
@implementation FixtureHTTPS
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return [request.URL.host isEqual:@"maps.test"]; }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    NSData *bytes;
    @synchronized(FixtureHTTPS.class) { bytes = responses[self.request.URL.path]; requests++; }
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
static NSData *packageBytes;
static NSDictionary *entry(NSString *name, NSData *bytes) {
    NSString *sha = hash(bytes);
    return @{@"id":name, @"sha256":sha, @"file_bytes":@(bytes.length), @"cache_version":@5,
        @"cache_build":@"01.10.12.2276", @"scenario_type":@1,
        @"package_sha256":hash(packageBytes), @"package_bytes":@(packageBytes.length), @"prefetch":@NO,
        @"object_key":[NSString stringWithFormat:@"packages/sha256/%@/%@.mapog", hash(packageBytes), name]};
}
static NSData *catalog(NSArray *maps) {
    return [NSJSONSerialization dataWithJSONObject:@{@"schema_version":@2, @"profile":@"stock-xbox-ntsc", @"maps":maps} options:0 error:nil];
}
static void waitFor(BOOL (^predicate)(void)) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:10];
    while (!predicate() && until.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    assert(predicate());
}
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

int main(int argc, const char **argv) {
    @autoreleasepool {
        assert(argc == 3);
        NSURL *root = [NSURL fileURLWithPath:@(argv[1]) isDirectory:YES];
        NSDictionary *unconfigured = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])] options:0 error:nil];
        assert(HaloDownloadConfigurationIsValid(unconfigured));
        NSMutableDictionary *config = [unconfigured mutableCopy];
        config[@"catalog_url"] = @"https://maps.test/catalog.json";
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
        packageBytes = [NSData dataWithContentsOfURL:[root URLByAppendingPathComponent:@"downrush.mapog"]];
        assert(packageBytes.length);
        // Legacy local inspection and the compressed wrapper share the exact
        // same inner whole-asset manifest. No game or user files are created.
        NSError *inspectionError = nil;
        NSDictionary *plainManifest = HaloInspectCommunityPackage([root URLByAppendingPathComponent:@"downrush.hogpkg"], &inspectionError);
        NSDictionary *wrappedManifest = HaloInspectCommunityPackage([root URLByAppendingPathComponent:@"downrush.mapog"], &inspectionError);
        if (!wrappedManifest) fprintf(stderr, "Compressed fixture rejected: %s\n", inspectionError.localizedDescription.UTF8String);
        assert(plainManifest && [plainManifest isEqual:wrappedManifest]);
        for (NSString *name in @[@"trailing",@"truncated",@"wrong-sha",@"overlimit",@"bomb",@"dictionary",@"tampered"]) {
            assert(!HaloInspectCommunityPackage([root URLByAppendingPathComponent:[name stringByAppendingString:@".mapog"]], &inspectionError));
            assert(inspectionError);
        }
        NSData *map = fixtureMap(@"downrush", @"01.10.12.2276");
        assert([map isEqual:[NSData dataWithContentsOfURL:[root URLByAppendingPathComponent:@"downrush.map"]]]);
        NSDictionary *approved = entry(@"downrush", map);
        NSError *error = nil;
        // Special files must fail without waiting for a FIFO writer. A blocking
        // open would stall both manual inspection and the serial download work.
        NSURL *fifo = [root URLByAppendingPathComponent:@"special-file.mapog"];
        assert(mkfifo(fifo.fileSystemRepresentation, 0600) == 0);
        NSDate *beforeFIFO = NSDate.date;
        assert(!HaloInspectCommunityPackage(fifo, &error));
        assert(!HaloVerifyDownloadedPackage(fifo, approved, config, &error));
        assert(!HaloVerifyDownloadedMap(fifo, approved, config, &error));
        assert(-beforeFIFO.timeIntervalSinceNow < 1);
        NSDictionary *validEntries = HaloValidateMapCatalog(catalog(@[approved]), config, &error);
        if (!validEntries) fprintf(stderr, "Valid package catalog rejected: %s\n", error.localizedDescription.UTF8String);
        assert(validEntries.count == 1);
        for (NSString *name in @[@"ui", @"a10", @"bloodgulch", @"_unsafe", @"-unsafe", @"../unsafe", @"bad/name", @"bad\\name"]) {
            assert(!HaloValidateMapCatalog(catalog(@[entry(name, map)]), config, &error));
        }
        assert(!HaloValidateMapCatalog(catalog(@[approved, approved]), config, &error));
        assert(!HaloValidateMapCatalog(catalog(@[entry(@"DownRush", map)]), config, &error));
        assert(!HaloValidateMapCatalog(catalog(@[@3]), config, &error));
        for (NSDictionary *replacement in @[@{@"cache_version":@7}, @{ @"scenario_type":@YES}, @{@"cache_build":@"01.01.14.2342"},
            @{@"file_bytes":@134217729}, @{ @"package_bytes":@268435457}, @{ @"package_bytes":@YES},
            @{ @"prefetch":@1}, @{ @"package_sha256":@"wrong"}, @{@"object_key":@"../downrush.map"}, @{@"sha256":@"wrong"}]) {
            NSMutableDictionary *bad = [approved mutableCopy]; [bad addEntriesFromDictionary:replacement];
            assert(!HaloValidateMapCatalog(catalog(@[bad]), config, &error));
        }
        // Legacy catalogs containing complete compiled maps are no longer
        // eligible network content, even if their map identity is valid.
        NSData *legacy = [NSJSONSerialization dataWithJSONObject:@{@"schema_version":@1, @"profile":@"stock-xbox-ntsc", @"maps":@[approved]} options:0 error:nil];
        assert(!HaloValidateMapCatalog(legacy, config, &error));
        NSData *duplicateJSON = [@"{\"schema_version\":2,\"schema_version\":2,\"profile\":\"stock-xbox-ntsc\",\"maps\":[]}" dataUsingEncoding:NSUTF8StringEncoding];
        assert(!HaloValidateMapCatalog(duplicateJSON, config, &error));
        NSString *validJSON = [[NSString alloc] initWithData:catalog(@[approved]) encoding:NSUTF8StringEncoding];
        for (NSString *key in @[@"schema_version",@"cache_version",@"scenario_type",@"file_bytes",@"package_bytes"]) {
            NSNumber *value = [key isEqual:@"schema_version"] ? @2 : approved[key];
            NSString *field = [NSString stringWithFormat:@"\"%@\":%@", key, value];
            assert([validJSON containsString:field]);
            NSString *floating = [validJSON stringByReplacingOccurrencesOfString:field withString:[field stringByAppendingString:@".0"]];
            assert(!HaloValidateMapCatalog([floating dataUsingEncoding:NSUTF8StringEncoding], config, &error));
        }
        NSMutableDictionary *booleanSchema = [config mutableCopy]; booleanSchema[@"schema_version"] = @YES;
        assert(!HaloDownloadConfigurationIsValid(booleanSchema));
        NSURL *package = [root URLByAppendingPathComponent:@"received.mapog"];
        assert([packageBytes writeToURL:package atomically:YES]);
        assert(HaloVerifyDownloadedPackage(package, approved, config, &error));
        NSMutableDictionary *packageLimit = [config mutableCopy]; packageLimit[@"max_package_bytes"] = @18;
        assert(!HaloVerifyDownloadedPackage(package, approved, packageLimit, &error));
        NSMutableData *alteredPackage = [packageBytes mutableCopy];
        ((unsigned char *)alteredPackage.mutableBytes)[alteredPackage.length - 1] ^= 1;
        assert([alteredPackage writeToURL:package atomically:YES]);
        assert(!HaloVerifyDownloadedPackage(package, approved, config, &error));
        assert([[packageBytes subdataWithRange:NSMakeRange(0, packageBytes.length - 1)] writeToURL:package atomically:YES]);
        assert(!HaloVerifyDownloadedPackage(package, approved, config, &error));
        NSURL *packageLink = [root URLByAppendingPathComponent:@"linked.mapog"];
        assert([NSFileManager.defaultManager createSymbolicLinkAtURL:packageLink withDestinationURL:package error:nil]);
        assert(!HaloVerifyDownloadedPackage(packageLink, approved, config, &error));
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

        NSURL *game = [root URLByAppendingPathComponent:@"game" isDirectory:YES];
        responses = [@{@"/catalog.json":catalog(@[approved]),
            [@"/" stringByAppendingString:approved[@"object_key"]]:packageBytes} mutableCopy];
        HaloMapDownloads *disabled = manager(folder(root, @"disabled"), game, config);
        [disabled startEnabled:NO];
        waitFor(^BOOL{ return [disabled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
        assert(requests == 0);

        NSURL *specialSupport = folder(root, @"special-metadata");
        NSURL *specialLibrary = folder(specialSupport, @"Community Maps");
        for (NSString *name in @[@"catalog.json", @"local-maps.json"])
            assert(mkfifo([specialLibrary URLByAppendingPathComponent:name].fileSystemRepresentation, 0600) == 0);
        HaloMapDownloads *specialMetadata = manager(specialSupport, game, config);
        [specialMetadata startEnabled:NO];
        waitFor(^BOOL{ return [specialMetadata requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
        assert(requests == 0);

        // The fixed fixture bundle's helper record has the same regular-file
        // restriction. Preserve and restore it after this isolated failure.
        NSURL *toolsRecord = [NSBundle.mainBundle.resourceURL URLByAppendingPathComponent:@"ContentTools.json"];
        NSURL *savedRecord = [toolsRecord URLByAppendingPathExtension:@"saved"];
        assert([NSFileManager.defaultManager moveItemAtURL:toolsRecord toURL:savedRecord error:nil]);
        assert(mkfifo(toolsRecord.fileSystemRepresentation, 0600) == 0);
        HaloMapDownloads *specialRecord = manager(folder(root, @"special-helper-record"), game, config);
        [specialRecord startEnabled:YES];
        waitFor(^BOOL{ return [specialRecord.statusText containsString:@"approved maps available"]; });
        assert([specialRecord requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [specialRecord requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert(![NSFileManager.defaultManager fileExistsAtPath:[specialRecord.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
        [specialRecord setDownloadsEnabled:NO];
        assert([NSFileManager.defaultManager removeItemAtURL:toolsRecord error:nil]);
        assert([NSFileManager.defaultManager moveItemAtURL:savedRecord toURL:toolsRecord error:nil]);

        HaloMapDownloads *downloads = manager(folder(root, @"support"), game, config);
        downloads.statusChanged = ^{ assert(NSThread.isMainThread); };
        [downloads activateForHost];
        [downloads startEnabled:YES];
        assert(halo_map_download_request("downrush") == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [downloads.statusText containsString:@"approved maps available"]; });
        assert([downloads requestMap:@"unknown"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert([downloads requestMap:@"ui"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert([downloads requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
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
        NSMutableDictionary *noHosting = [config mutableCopy];
        noHosting[@"catalog_url"] = NSNull.null; noHosting[@"objects_base_url"] = NSNull.null;
        noHosting[@"allowed_origins"] = @[];
        assert(HaloDownloadConfigurationIsValid(noHosting));
        HaloMapDownloads *localOnly = manager(folder(root, @"support"), game, noHosting);
        [localOnly startEnabled:NO];
        waitFor(^BOOL{ return [localOnly requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        assert(requests == afterDownload && !localOnly.configured);

        // Launch prefetch installs the map before any requestMap call.
        NSMutableDictionary *prefetchedEntry = [approved mutableCopy]; prefetchedEntry[@"prefetch"] = @YES;
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[prefetchedEntry]); }
        HaloMapDownloads *prefetch = manager(folder(root, @"prefetch"), game, config);
        [prefetch startEnabled:YES];
        NSURL *prefetchedMap = [prefetch.mapsDirectory URLByAppendingPathComponent:@"downrush.map"];
        waitFor(^BOOL{ return [NSFileManager.defaultManager fileExistsAtPath:prefetchedMap.path]; });
        waitFor(^BOOL{ return [prefetch requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        assert([[NSData dataWithContentsOfURL:prefetchedMap] isEqual:map]);
        [prefetch setDownloadsEnabled:NO];
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[approved]); }

        // Revalidation clears stale ready state when installed bytes disappear.
        assert([NSFileManager.defaultManager removeItemAtURL:installed error:nil]);
        [offline setDownloadsEnabled:YES];
        waitFor(^BOOL{ return [offline.statusText containsString:@"approved maps available"]; });
        waitFor(^BOOL{ return [offline requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert([offline.statusText containsString:@"Re-import"]);
        [offline cancelDownloads];
        waitFor(^BOOL{ return [offline requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE; });
        // A local reconstruction receipt requires an explicit re-import when
        // its bytes are removed; catalog refresh must not erase that authority.
        assert([map writeToURL:installed atomically:YES]);
        [offline setDownloadsEnabled:NO];

        HaloMapDownloads *collision = manager(folder(root, @"collision"), game, config);
        folder(folder(root, @"collision/Community Maps"), @"maps");
        NSURL *existing = [collision.mapsDirectory URLByAppendingPathComponent:@"downrush.map"];
        NSData *personal = [@"user file" dataUsingEncoding:NSUTF8StringEncoding];
        assert([personal writeToURL:existing atomically:YES]);
        [collision startEnabled:YES];
        waitFor(^BOOL{ return [collision requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        waitFor(^BOOL{ return [collision.statusText containsString:@"approved maps available"]; });
        assert([collision.statusText containsString:@"existing map"]);
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
        // Package output identity must match the catalog before helper execution.
        @synchronized(FixtureHTTPS.class) {
            responses[@"/catalog.json"] = catalog(@[wrongEntry]);
            responses[[@"/" stringByAppendingString:wrongEntry[@"object_key"]]] = packageBytes;
        }
        HaloMapDownloads *invalid = manager(folder(root, @"invalid"), game, config);
        [invalid startEnabled:YES];
        waitFor(^BOOL{ return [invalid.statusText containsString:@"approved maps available"]; });
        assert([invalid requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [invalid requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert(![NSFileManager.defaultManager fileExistsAtPath:[invalid.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
        assert([NSFileManager.defaultManager contentsOfDirectoryAtPath:[invalid.mapsDirectory.URLByDeletingLastPathComponent.path stringByAppendingPathComponent:@"Downloads"] error:nil].count == 0);
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[approved]); }
        [invalid checkForMaps];
        waitFor(^BOOL{ return [invalid requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });

        // A short HTTPS package cannot publish partial output. An exact-byte
        // transfer can also fail when the selected original base differs.
        @synchronized(FixtureHTTPS.class) {
            responses[[@"/" stringByAppendingString:approved[@"object_key"]]] = [packageBytes subdataWithRange:NSMakeRange(0, packageBytes.length - 1)];
        }
        HaloMapDownloads *truncated = manager(folder(root, @"truncated"), game, config);
        [truncated startEnabled:YES];
        waitFor(^BOOL{ return [truncated.statusText containsString:@"approved maps available"]; });
        [truncated requestMap:@"downrush"];
        waitFor(^BOOL{ return [truncated requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert(![NSFileManager.defaultManager fileExistsAtPath:[truncated.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
        assert([NSFileManager.defaultManager contentsOfDirectoryAtPath:[truncated.mapsDirectory.URLByDeletingLastPathComponent.path stringByAppendingPathComponent:@"Downloads"] error:nil].count == 0);
        @synchronized(FixtureHTTPS.class) { responses[[@"/" stringByAppendingString:approved[@"object_key"]]] = packageBytes; }
        NSURL *wrongStock = [root URLByAppendingPathComponent:@"wrong-stock"];
        assert([NSFileManager.defaultManager copyItemAtURL:game toURL:wrongStock error:nil]);
        NSURL *originalA10 = [wrongStock URLByAppendingPathComponent:@"maps/a10.map"];
        NSMutableData *badBase = [[NSData dataWithContentsOfURL:originalA10] mutableCopy];
        ((unsigned char *)badBase.mutableBytes)[2500] ^= 1;
        assert([badBase writeToURL:originalA10 atomically:YES]);
        HaloMapDownloads *wrongBase = manager(folder(root, @"wrong-base-support"), wrongStock, config);
        [wrongBase startEnabled:YES];
        waitFor(^BOOL{ return [wrongBase.statusText containsString:@"approved maps available"]; });
        [wrongBase requestMap:@"downrush"];
        waitFor(^BOOL{ return [wrongBase requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert([[NSData dataWithContentsOfURL:originalA10] isEqual:badBase]);
        assert(![NSFileManager.defaultManager fileExistsAtPath:[wrongBase.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
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
        [cancelled startEnabled:YES];
        waitFor(^BOOL{ return [cancelled.statusText containsString:@"approved maps available"]; });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        [cancelled cancelDownloads];
        waitFor(^BOOL{ return [cancelled.statusText containsString:@"cancelled"]; });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        assert(![NSFileManager.defaultManager fileExistsAtPath:[cancelled.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);
        [cancelled checkForMaps];
        waitFor(^BOOL{ return [cancelled.statusText containsString:@"approved maps available"]; });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });

        // Cancel releases the guest wait immediately, even while the serial
        // worker runs a fixed native helper. A completed verified map is kept.
        HaloMapDownloads *assemblyCancel = manager(folder(root, @"assembly-cancel"), game, config);
        [assemblyCancel startEnabled:YES];
        waitFor(^BOOL{ return [assemblyCancel.statusText containsString:@"approved maps available"]; });
        [assemblyCancel requestMap:@"downrush"];
        waitFor(^BOOL{ return [assemblyCancel.statusText containsString:@"Rebuilding the community map"]; });
        [assemblyCancel cancelDownloads];
        assert([assemblyCancel requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        waitFor(^BOOL{ return [assemblyCancel.statusText containsString:@"cancelled"]; });
        assert([assemblyCancel requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY);

        // A verified local reconstruction receipt remains authoritative even
        // when a later network catalog omits this map.
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[]); }
        [cancelled checkForMaps];
        waitFor(^BOOL{ return [cancelled.statusText containsString:@"0 approved maps available"]; });
        assert([cancelled requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY);
        assert([NSFileManager.defaultManager fileExistsAtPath:[cancelled.mapsDirectory URLByAppendingPathComponent:@"downrush.map"].path]);

        // An HTTP error leaves the missing-map hook in FAILED until a retry.
        @synchronized(FixtureHTTPS.class) { [responses removeObjectForKey:@"/catalog.json"]; }
        HaloMapDownloads *failedCatalog = manager(folder(root, @"catalog-failure"), game, config);
        [failedCatalog startEnabled:YES];
        assert([failedCatalog requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [failedCatalog requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_FAILED; });
        assert([failedCatalog.statusText containsString:@"catalog unavailable"]);
        @synchronized(FixtureHTTPS.class) { responses[@"/catalog.json"] = catalog(@[approved]); }
        [failedCatalog checkForMaps];
        waitFor(^BOOL{ return [failedCatalog.statusText containsString:@"approved maps available"]; });
        assert(![failedCatalog.statusText containsString:@"catalog unavailable"]);
        assert([failedCatalog requestMap:@"unknown"] == HALO_MAP_DOWNLOAD_UNAVAILABLE);
        // Immediate cancel/retry while catalog completion is still queued must
        // schedule a fresh check rather than losing the retry to pending state.
        HaloMapDownloads *rapidRetry = manager(folder(root, @"rapid-retry"), game, config);
        [rapidRetry startEnabled:YES];
        [rapidRetry cancelDownloads];
        [rapidRetry checkForMaps];
        waitFor(^BOOL{ return [rapidRetry.statusText containsString:@"approved maps available"]; });
        assert([rapidRetry requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_PENDING);
        waitFor(^BOOL{ return [rapidRetry requestMap:@"downrush"] == HALO_MAP_DOWNLOAD_READY; });
        puts("Native package HTTPS fixtures: opt-in, async package/assembly/ready, catalog bounds, package/output SHA checks, atomic install, offline reuse, collision preservation, retry and PAL gating passed");
    }
    return 0;
}
