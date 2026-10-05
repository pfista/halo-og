/* Authored metadata and in-process HTTPS responses; no external network,
   GitHub token, executable downloads, user preferences or game assets. */
#import <Foundation/Foundation.h>
#import "HaloReleaseUpdates.h"
#include "release_discovery.h"
#include <assert.h>

static NSDictionary *fixtureResponse;
static unsigned requests;
static unsigned callbacks;

@interface FixtureReleaseHTTPS : NSURLProtocol
@property(nonatomic) BOOL stopped;
@end
@implementation FixtureReleaseHTTPS
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return [request.URL.host isEqualToString:@"api.github.com"]; }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    NSDictionary *fixture;
    @synchronized(FixtureReleaseHTTPS.class) { requests++; fixture = [fixtureResponse copy]; }
    assert([self.request.URL.absoluteString isEqualToString:@HALO_RELEASE_DISCOVERY_URL]);
    assert([[self.request valueForHTTPHeaderField:@"User-Agent"] isEqualToString:@"Halo-OG-release-check"]);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 50 * NSEC_PER_MSEC), dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        @synchronized(self) {
            if (self.stopped) return;
            if ([fixture[@"offline"] boolValue]) {
                [self.client URLProtocol:self didFailWithError:[NSError errorWithDomain:NSURLErrorDomain
                    code:NSURLErrorNotConnectedToInternet userInfo:nil]];
                return;
            }
            NSData *bytes = fixture[@"bytes"] ?: [NSData data];
            NSMutableDictionary *headers = [@{@"Content-Type":fixture[@"mime"] ?: @"application/json"} mutableCopy];
            NSNumber *declared = fixture[@"length"];
            if (declared) headers[@"Content-Length"] = declared.stringValue;
            NSURL *url = fixture[@"url"] ? [NSURL URLWithString:fixture[@"url"]] : self.request.URL;
            NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:url
                statusCode:fixture[@"status"] ? [fixture[@"status"] integerValue] : 200
                HTTPVersion:@"HTTP/1.1" headerFields:headers];
            [self.client URLProtocol:self didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
            NSUInteger chunk = fixture[@"chunk"] ? [fixture[@"chunk"] unsignedIntegerValue] : MAX(bytes.length, 1u);
            for (NSUInteger offset = 0; offset < bytes.length; offset += chunk) {
                if (self.stopped) return;
                [self.client URLProtocol:self didLoadData:[bytes subdataWithRange:NSMakeRange(offset, MIN(chunk, bytes.length - offset))]];
            }
            [self.client URLProtocolDidFinishLoading:self];
        }
    });
}
- (void)stopLoading { @synchronized(self) { self.stopped = YES; } }
@end

static NSString *sha(NSString *digit) {
    return [@"" stringByPaddingToLength:40 withString:digit startingAtIndex:0];
}
static NSDictionary *release(NSString *tag, NSString *source, NSString *date, NSString *published) {
    NSMutableArray *assets = [NSMutableArray array];
    for (NSString *name in @[@"Halo-OG-macos-arm64.dmg", @"SHA256SUMS", @"provenance.json"])
        [assets addObject:@{@"name":name, @"state":@"uploaded", @"browser_download_url":
            [NSString stringWithFormat:@"https://github.com/pfista/halo-og/releases/download/%@/%@", tag, name]}];
    return @{@"tag_name":tag, @"created_at":date, @"published_at":published, @"draft":@NO,
        @"prerelease":@YES, @"body":[NSString stringWithFormat:@"Build from [source](https://github.com/pfista/halo-og/commit/%@).", source],
        @"assets":assets};
}
static NSData *metadata(NSArray *releases) {
    return [NSJSONSerialization dataWithJSONObject:releases options:0 error:nil];
}
static void respond(NSDictionary *response) {
    @synchronized(FixtureReleaseHTTPS.class) { fixtureResponse = response; }
}
static void waitFor(BOOL (^predicate)(void)) {
    NSDate *end = [NSDate dateWithTimeIntervalSinceNow:5];
    while (!predicate() && end.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    assert(predicate());
}
static HaloReleaseUpdates *manager(NSString *source, NSString *date) {
    NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.protocolClasses = @[FixtureReleaseHTTPS.class];
    HaloReleaseUpdates *updates = [[HaloReleaseUpdates alloc] initWithSourceSHA:source sourceDate:date
                                                       sessionConfiguration:configuration];
    updates.statusChanged = ^{ assert(NSThread.isMainThread); callbacks++; };
    return updates;
}
static void check(HaloReleaseUpdates *updates, NSDictionary *response) {
    unsigned before = callbacks;
    respond(response);
    [updates checkForUpdates];
    waitFor(^BOOL { return !updates.checking && callbacks > before; });
}

int main(void) {
    @autoreleasepool {
        NSString *current = sha(@"1"), *date = @"2026-10-04T00:00:00Z";
        NSDictionary *newer = release(@"test-new", sha(@"3"), @"2026-10-05T00:00:00Z", @"2026-10-06T00:00:00Z");
        NSDictionary *older = release(@"test-old", sha(@"2"), @"2026-10-03T00:00:00Z", @"2026-10-07T00:00:00Z");
        NSDictionary *same = release(@"test-repack", current, @"2026-10-05T00:00:00Z", @"2026-10-07T00:00:00Z");

        // Unknown, dirty and invalid identities never start an automatic check.
        for (NSArray *identity in @[@[@"unknown", date], @[[current stringByAppendingString:@" (local changes)"], date],
            @[current, @"unknown"], @[current, @"2026-02-30T00:00:00Z"], @[current, @"2026-10-04T00:00:00+00:00"]]) {
            HaloReleaseUpdates *local = manager(identity[0], identity[1]);
            unsigned before = requests;
            assert(!local.automaticChecksAvailable && !local.updateAvailable);
            assert([local.downloadURL.absoluteString isEqualToString:@"https://github.com/pfista/halo-og/releases"]);
            [local checkForUpdates];
            assert(!local.checking && requests == before && !local.updateAvailable);
        }
        HaloReleaseUpdates *updates = manager(current, date);
        assert(updates.automaticChecksAvailable);

        // Requesting metadata returns immediately and coalesces repeated checks.
        respond(@{@"bytes":metadata(@[older, same, newer])});
        unsigned before = requests;
        NSDate *start = NSDate.date;
        [updates checkForUpdates];
        for (unsigned i = 0; i < 10; i++) [updates checkForUpdates];
        assert(-start.timeIntervalSinceNow < 0.03 && updates.checking);
        waitFor(^BOOL { return !updates.checking; });
        assert(requests == before + 1 && updates.updateAvailable);
        assert([updates.downloadURL.absoluteString isEqualToString:
            @"https://github.com/pfista/halo-og/releases/download/test-new/Halo-OG-macos-arm64.dmg"]);
        assert([updates.statusText containsString:@"test-new"]);
        check(updates, @{@"bytes":metadata(@[newer, same, older])});
        assert(updates.updateAvailable && [updates.statusText containsString:@"test-new"]);

        // A repack of this SHA or a later publication of older source is not new.
        check(updates, @{@"bytes":metadata(@[same, older])});
        assert(!updates.updateAvailable && !updates.downloadURL && [updates.statusText containsString:@"No newer"]);
        check(updates, @{@"bytes":metadata(@[])});
        assert(!updates.updateAvailable);
        NSMutableDictionary *incomplete = [newer mutableCopy]; incomplete[@"assets"] = @[];
        check(updates, @{@"bytes":metadata(@[incomplete])}); assert(!updates.updateAvailable);
        NSMutableDictionary *badAsset = [newer mutableCopy];
        NSMutableArray *assets = [newer[@"assets"] mutableCopy];
        NSMutableDictionary *asset = [assets[0] mutableCopy]; asset[@"browser_download_url"] = @"https://example.test/installer.dmg";
        assets[0] = asset; badAsset[@"assets"] = assets;
        check(updates, @{@"bytes":metadata(@[badAsset])}); assert(!updates.updateAvailable);

        for (NSDictionary *failure in @[@{@"offline":@YES}, @{@"status":@403, @"bytes":metadata(@[newer])},
            @{@"mime":@"text/html", @"bytes":metadata(@[newer])},
            @{@"url":@"http://api.github.com/repos/pfista/halo-og/releases?per_page=5", @"bytes":metadata(@[newer])},
            @{@"bytes":[@"[{ broken" dataUsingEncoding:NSUTF8StringEncoding]},
            @{@"bytes":[@"{}" dataUsingEncoding:NSUTF8StringEncoding]}]) {
            check(updates, failure);
            assert(!updates.updateAvailable && !updates.checking);
            assert([updates.downloadURL.absoluteString isEqualToString:@"https://github.com/pfista/halo-og/releases"]);
        }

        // Reject declared oversized bodies before parsing and bound chunked data.
        check(updates, @{@"length":@(HALO_RELEASE_DISCOVERY_BYTES + 1), @"bytes":metadata(@[newer])});
        assert(!updates.updateAvailable && [updates.statusText containsString:@"limit"]);
        NSMutableData *bounded = [metadata(@[newer]) mutableCopy];
        NSUInteger originalLength = bounded.length;
        bounded.length = HALO_RELEASE_DISCOVERY_BYTES;
        memset((unsigned char *)bounded.mutableBytes + originalLength, ' ', bounded.length - originalLength);
        check(updates, @{@"length":@(bounded.length), @"bytes":bounded, @"chunk":@4096});
        assert(updates.updateAvailable); // Exact cap remains valid.
        [bounded appendBytes:" " length:1];
        check(updates, @{@"bytes":bounded, @"chunk":@4096});
        assert(!updates.updateAvailable && [updates.statusText containsString:@"limit"]);
        check(updates, @{@"bytes":metadata(@[newer])}); assert(updates.updateAvailable); // Retry after failure.
        puts("Native Mac release discovery fixtures passed");
    }
    return 0;
}
