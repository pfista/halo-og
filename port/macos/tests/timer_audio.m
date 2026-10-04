/* In-process HTTPS fixtures and generated PCM samples. No recordings,
   credentials or external network are needed for these checks. */
#import "HaloTimerAudio.h"
#include <CommonCrypto/CommonDigest.h>
#include <assert.h>

static NSMutableDictionary *responses;
static NSMutableArray<NSString *> *requestPaths;
static NSUInteger requests;
static BOOL holdRecordings;
static NSMutableArray *held;

@interface TimerFixtureHTTPS : NSURLProtocol
@property(nonatomic) BOOL stopped;
@property(nonatomic, strong) NSDictionary *fixture;
- (void)finishLoading;
@end
@implementation TimerFixtureHTTPS
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { (void)request; return YES; }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    assert([self.request.URL.scheme isEqual:@"https"]);
    assert([self.request.URL.host isEqual:@"dl.oghalo.com"]);
    assert(!self.request.URL.query && !self.request.URL.fragment);
    assert([[self.request valueForHTTPHeaderField:@"Accept-Encoding"] isEqual:@"identity"]);
    @synchronized(TimerFixtureHTTPS.class) {
        requests++;
        [requestPaths addObject:self.request.URL.path];
        self.fixture = responses[self.request.URL.path];
        if (holdRecordings && [self.request.URL.path hasSuffix:@".wav"]) { [held addObject:self]; return; }
    }
    [self finishLoading];
}
- (void)finishLoading {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_MSEC), dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        @synchronized(self) {
            if (self.stopped) return;
            NSData *data = self.fixture[@"data"];
            NSDictionary *headers = self.fixture[@"headers"] ?: @{@"Content-Length":@(data.length).stringValue};
            NSInteger status = self.fixture[@"status"] ? [self.fixture[@"status"] integerValue] : (data ? 200 : 404);
            NSURL *url = self.fixture[@"url"] ?: self.request.URL;
            NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:url statusCode:status HTTPVersion:@"HTTP/1.1" headerFields:headers];
            [self.client URLProtocol:self didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
            if (data) [self.client URLProtocol:self didLoadData:data];
            [self.client URLProtocolDidFinishLoading:self];
        }
    });
}
- (void)stopLoading { @synchronized(self) { self.stopped = YES; } }
@end

static NSString *hash(NSData *data) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *result = [NSMutableString string];
    for (unsigned i = 0; i < sizeof(digest); i++) [result appendFormat:@"%02x", digest[i]];
    return result;
}
static NSData *wav(void) {
    NSMutableData *data = [NSMutableData dataWithLength:172]; // 64 mono frames.
    unsigned char *p = data.mutableBytes;
    memcpy(p, "RIFF", 4); memcpy(p + 8, "WAVEfmt ", 8); memcpy(p + 36, "data", 4);
    uint32_t riff = 164, fmt = 16, rate = 22050, byteRate = 44100, bytes = 128;
    uint16_t pcm = 1, channels = 1, align = 2, bits = 16;
    memcpy(p + 4, &riff, 4); memcpy(p + 16, &fmt, 4); memcpy(p + 20, &pcm, 2);
    memcpy(p + 22, &channels, 2); memcpy(p + 24, &rate, 4); memcpy(p + 28, &byteRate, 4);
    memcpy(p + 32, &align, 2); memcpy(p + 34, &bits, 2); memcpy(p + 40, &bytes, 4);
    for (unsigned i = 44; i < data.length; i++) p[i] = (unsigned char)i;
    return data;
}
static NSMutableArray *entries(NSData *data) {
    NSMutableArray *entries = [NSMutableArray array];
    for (NSString *cue in HaloTimerAudioCues()) {
        NSString *sha = hash(data);
        [entries addObject:[@{@"cue":cue, @"file_bytes":@(data.length), @"sha256":sha,
            @"object_key":[NSString stringWithFormat:@"audio/timer/sha256/%@/%@.wav", sha, cue]} mutableCopy]];
    }
    return entries;
}
static NSData *manifest(NSArray *files) {
    return [NSJSONSerialization dataWithJSONObject:@{@"schema_version":@1, @"pack_id":@"performance-timer-v1", @"files":files} options:0 error:nil];
}
static void fixtures(NSArray *files, NSData *data) {
    responses = [NSMutableDictionary dictionaryWithObject:@{@"data":manifest(files)} forKey:@"/audio/timer/v1/current.json"];
    for (NSDictionary *entry in files) responses[[@"/" stringByAppendingString:entry[@"object_key"]]] = @{@"data":data};
    holdRecordings = NO;
    held = [NSMutableArray array];
}
static void waitAt(unsigned line, BOOL (^predicate)(void)) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5];
    while (!predicate() && deadline.timeIntervalSinceNow > 0)
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
    if (!predicate()) { fprintf(stderr, "timer_audio.m:%u timed out; last request %s\n", line, requestPaths.lastObject.UTF8String); assert(predicate()); }
}
#define waitFor(predicate) waitAt(__LINE__, predicate)
static NSURL *folder(NSURL *root, NSString *name) {
    NSURL *url = [root URLByAppendingPathComponent:name isDirectory:YES];
    assert([NSFileManager.defaultManager createDirectoryAtURL:url withIntermediateDirectories:YES attributes:nil error:nil]);
    return url;
}
static HaloTimerAudio *manager(NSURL *root, NSString *name) {
    NSURLSessionConfiguration *session = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    session.protocolClasses = @[TimerFixtureHTTPS.class];
    return [[HaloTimerAudio alloc] initWithSupportDirectory:folder(root, name) sessionConfiguration:session];
}
static void download(HaloTimerAudio *manager) {
    NSUInteger before = requests;
    [manager downloadRecordings];
    waitFor(^BOOL{ return requests > before; });
    waitFor(^BOOL{ return !manager.downloading; });
}
static void noPackOrStage(NSURL *support) {
    NSURL *sounds = [support URLByAppendingPathComponent:@"sounds" isDirectory:YES];
    for (NSString *name in [NSFileManager.defaultManager contentsOfDirectoryAtPath:sounds.path error:nil])
        assert(![name isEqual:@"performance"] && ![name hasPrefix:@".performance-download-"]);
}

/* Only the explicit --live runner option selects production NSURLSession.
   Preserve its fresh download folder for independent inspection afterwards. */
static int liveDownload(NSURL *support) {
    assert(![NSFileManager.defaultManager contentsOfDirectoryAtPath:support.path error:nil].count);
    HaloTimerAudio *audio = [[HaloTimerAudio alloc] initWithSupportDirectory:support sessionConfiguration:nil];
    NSString *initialStatus = audio.statusText;
    [audio downloadRecordings];
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:180];
    BOOL started = NO;
    while (deadline.timeIntervalSinceNow > 0) {
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
        if (audio.downloading) started = YES;
        if (!audio.downloading && (started || ![audio.statusText isEqual:initialStatus])) break;
    }
    if (!audio.installed || audio.downloading) {
        fprintf(stderr, "Live Timer Audio download failed: %s\n", audio.statusText.UTF8String);
        [audio cancelDownloads];
        waitFor(^BOOL{ return !audio.downloading; });
        return 1;
    }
    NSURL *pack = [support URLByAppendingPathComponent:@"sounds/performance" isDirectory:YES];
    NSDictionary *files = HaloValidateTimerAudioManifest([NSData dataWithContentsOfURL:[pack URLByAppendingPathComponent:@"download-manifest.json"]]);
    assert(files.count == 46);
    unsigned long long bytes = 0;
    for (NSString *cue in HaloTimerAudioCues()) {
        NSData *data = [NSData dataWithContentsOfURL:[pack URLByAppendingPathComponent:[cue stringByAppendingPathExtension:@"wav"]]];
        assert(HaloTimerAudioWAVIsValid(data) && [hash(data) isEqual:files[cue][@"sha256"]]);
        assert(data.length == [files[cue][@"file_bytes"] unsignedLongLongValue]);
        bytes += data.length;
    }
    printf("Production native HTTPS verified 46 recordings, %llu bytes; saved at %s\n", bytes, pack.path.UTF8String);
    return 0;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        assert(argc == 2 || (argc == 3 && !strcmp(argv[2], "--live")));
        NSURL *root = [NSURL fileURLWithPath:@(argv[1]) isDirectory:YES];
        if (argc == 3) return liveDownload(root);
        requestPaths = [NSMutableArray array];
        NSData *audio = wav();
        NSMutableArray *files = entries(audio);
        assert(HaloTimerAudioCues().count == 46);
        assert(HaloTimerAudioWAVIsValid(audio));
        assert(HaloValidateTimerAudioManifest(manifest(files)).count == 46);
        assert(!HaloValidateTimerAudioManifest([@"malformed" dataUsingEncoding:NSUTF8StringEncoding]));
        assert(!HaloValidateTimerAudioManifest(manifest([files subarrayWithRange:NSMakeRange(0, 45)])));
        for (NSDictionary *change in @[@{@"cue":@"../unsafe"}, @{@"cue":@"TimerBeep"}, @{@"file_bytes":@YES},
            @{@"file_bytes":@1048577}, @{@"file_bytes":@45}, @{@"file_bytes":@172.5}, @{@"sha256":@"wrong"},
            @{@"object_key":@"../timerbeep.wav"}, @{@"unexpected":@1}]) {
            NSMutableArray *bad = entries(audio); [bad[0] addEntriesFromDictionary:change];
            assert(!HaloValidateTimerAudioManifest(manifest(bad)));
        }
        NSMutableArray *duplicates = entries(audio); duplicates[45] = duplicates[0];
        assert(!HaloValidateTimerAudioManifest(manifest(duplicates)));
        NSMutableArray *tooLarge = entries(audio);
        for (NSMutableDictionary *entry in tooLarge) entry[@"file_bytes"] = @1048576;
        assert(!HaloValidateTimerAudioManifest(manifest(tooLarge)));
        NSMutableDictionary *wrongSchema = [@{@"schema_version":@YES, @"pack_id":@"performance-timer-v1", @"files":files} mutableCopy];
        assert(!HaloValidateTimerAudioManifest([NSJSONSerialization dataWithJSONObject:wrongSchema options:0 error:nil]));
        wrongSchema[@"schema_version"] = @1; wrongSchema[@"pack_id"] = @"other";
        assert(!HaloValidateTimerAudioManifest([NSJSONSerialization dataWithJSONObject:wrongSchema options:0 error:nil]));
        NSString *validJSON = [[NSString alloc] initWithData:manifest(files) encoding:NSUTF8StringEncoding];
        NSString *floatSchema = [validJSON stringByReplacingOccurrencesOfString:@"\"schema_version\":1" withString:@"\"schema_version\":1.0"];
        NSString *floatBytes = [validJSON stringByReplacingOccurrencesOfString:@"\"file_bytes\":172" withString:@"\"file_bytes\":172.0"];
        assert(!HaloValidateTimerAudioManifest([floatSchema dataUsingEncoding:NSUTF8StringEncoding]));
        assert(!HaloValidateTimerAudioManifest([floatBytes dataUsingEncoding:NSUTF8StringEncoding]));
        NSMutableData *invalidAudio = [audio mutableCopy]; ((unsigned char *)invalidAudio.mutableBytes)[20] = 3;
        assert(!HaloTimerAudioWAVIsValid(invalidAudio));
        for (unsigned offset = 16; offset <= 40; offset += 4) {
            NSMutableData *bad = [audio mutableCopy]; ((unsigned char *)bad.mutableBytes)[offset] ^= 0xff;
            assert(!HaloTimerAudioWAVIsValid(bad));
        }
        assert(!HaloTimerAudioWAVIsValid([audio subdataWithRange:NSMakeRange(0, 171)]));

        fixtures(files, audio);
        HaloTimerAudio *success = manager(root, @"success");
        assert(!success.installed && !success.downloading && requests == 0);
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        assert(requests == 0); // Initialization never opts into HTTP.
        __block unsigned updates = 0;
        success.statusChanged = ^{ updates++; };
        download(success);
        assert(success.installed && requests == 47 && updates);
        NSURL *pack = [[root URLByAppendingPathComponent:@"success/sounds" isDirectory:YES] URLByAppendingPathComponent:@"performance" isDirectory:YES];
        for (NSString *cue in HaloTimerAudioCues()) assert([[NSData dataWithContentsOfURL:[pack URLByAppendingPathComponent:[cue stringByAppendingPathExtension:@"wav"]]] isEqual:audio]);
        assert([NSFileManager.defaultManager fileExistsAtPath:[pack URLByAppendingPathComponent:@"download-manifest.json"].path]);
        NSUInteger priorRequests = requests;
        HaloTimerAudio *offline = manager(root, @"success");
        assert(offline.installed);
        [offline downloadRecordings];
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        assert(requests == priorRequests && !offline.downloading);

        // The last recording fails after 45 valid clips have been staged.
        fixtures(files, audio);
        NSString *last = [@"/" stringByAppendingString:files.lastObject[@"object_key"]];
        NSMutableData *corrupt = [audio mutableCopy]; ((unsigned char *)corrupt.mutableBytes)[100] ^= 1;
        responses[last] = @{@"data":corrupt};
        HaloTimerAudio *atomicFailure = manager(root, @"atomic-failure");
        download(atomicFailure); assert(!atomicFailure.installed);
        noPackOrStage([root URLByAppendingPathComponent:@"atomic-failure"]);
        fixtures(files, audio); download(atomicFailure); assert(atomicFailure.installed); // A failed pack can retry.

        // A missing file, malformed but correctly hashed audio, bad hash, and
        // unsupported transfer encodings all refuse complete-pack activation.
        for (NSString *kind in @[@"missing", @"pcm", @"hash", @"gzip", @"redirect", @"short-length", @"foreign-origin", @"overflow"]) {
            NSMutableArray *caseFiles = entries([kind isEqual:@"pcm"] ? invalidAudio : audio);
            if ([kind isEqual:@"hash"]) {
                NSString *zeros = [@"" stringByPaddingToLength:64 withString:@"0" startingAtIndex:0];
                caseFiles[0][@"sha256"] = zeros;
                caseFiles[0][@"object_key"] = [NSString stringWithFormat:@"audio/timer/sha256/%@/timerbeep.wav", zeros];
            }
            fixtures(caseFiles, [kind isEqual:@"pcm"] ? invalidAudio : audio);
            NSString *key = [@"/" stringByAppendingString:caseFiles[0][@"object_key"]];
            if ([kind isEqual:@"missing"]) [responses removeObjectForKey:key];
            if ([kind isEqual:@"gzip"]) responses[key] = @{@"data":audio, @"headers":@{@"Content-Encoding":@"gzip", @"Content-Length":@(audio.length).stringValue}};
            if ([kind isEqual:@"redirect"]) responses[key] = @{@"data":audio, @"status":@302, @"headers":@{@"Location":@"https://evil.test/clip.wav"}};
            if ([kind isEqual:@"short-length"]) responses[key] = @{@"data":audio, @"headers":@{@"Content-Length":@"100"}};
            if ([kind isEqual:@"foreign-origin"]) responses[key] = @{@"data":audio, @"url":[NSURL URLWithString:@"https://evil.test/clip.wav"]};
            if ([kind isEqual:@"overflow"]) {
                NSMutableData *tooMany = [audio mutableCopy]; [tooMany appendBytes:"xx" length:2];
                responses[key] = @{@"data":tooMany, @"headers":@{}};
            }
            HaloTimerAudio *failure = manager(root, kind);
            download(failure); assert(!failure.installed);
            noPackOrStage([root URLByAppendingPathComponent:kind]);
        }
        fixtures(files, audio);
        responses[@"/audio/timer/v1/current.json"] = @{@"data":[NSMutableData dataWithLength:65537], @"headers":@{}};
        HaloTimerAudio *oversizeManifest = manager(root, @"oversize-manifest");
        download(oversizeManifest); assert(!oversizeManifest.installed); noPackOrStage([root URLByAppendingPathComponent:@"oversize-manifest"]);
        fixtures(files, audio);
        responses[@"/audio/timer/v1/current.json"] = @{@"data":manifest(duplicates)};
        HaloTimerAudio *badManifest = manager(root, @"duplicate-manifest");
        download(badManifest); assert(!badManifest.installed); noPackOrStage([root URLByAppendingPathComponent:@"duplicate-manifest"]);

        // Any existing partial/user pack, file or link is preserved before HTTP.
        NSURL *preserved = folder(root, @"preserved"), *userPack = folder(preserved, @"sounds/performance");
        NSURL *sentinel = [userPack URLByAppendingPathComponent:@"timerbeep.wav"];
        NSData *userBytes = [@"user recording" dataUsingEncoding:NSUTF8StringEncoding];
        assert([userBytes writeToURL:sentinel atomically:YES]);
        HaloTimerAudio *existing = manager(root, @"preserved");
        priorRequests = requests; [existing downloadRecordings];
        waitFor(^BOOL{ return [existing.statusText containsString:@"preserved"] && !existing.downloading; });
        assert(requests == priorRequests && [[NSData dataWithContentsOfURL:sentinel] isEqual:userBytes]);
        NSURL *linkRoot = folder(root, @"link"), *elsewhere = folder(root, @"elsewhere");
        assert([NSFileManager.defaultManager createSymbolicLinkAtURL:[linkRoot URLByAppendingPathComponent:@"sounds"] withDestinationURL:elsewhere error:nil]);
        HaloTimerAudio *linked = manager(root, @"link"); [linked downloadRecordings];
        waitFor(^BOOL{ return [linked.statusText containsString:@"preserved"] && !linked.downloading; });
        assert(requests == priorRequests && ![NSFileManager.defaultManager contentsOfDirectoryAtPath:elsewhere.path error:nil].count);
        NSURL *fileRoot = folder(root, @"existing-file"), *fileSounds = folder(fileRoot, @"sounds");
        NSURL *existingFile = [fileSounds URLByAppendingPathComponent:@"performance"];
        assert([userBytes writeToURL:existingFile atomically:YES]);
        HaloTimerAudio *fileDestination = manager(root, @"existing-file"); [fileDestination downloadRecordings];
        waitFor(^BOOL{ return [fileDestination.statusText containsString:@"preserved"] && !fileDestination.downloading; });
        assert(requests == priorRequests && [[NSData dataWithContentsOfURL:existingFile] isEqual:userBytes]);

        fixtures(files, audio); holdRecordings = YES;
        HaloTimerAudio *cancelled = manager(root, @"cancelled"); [cancelled downloadRecordings];
        waitFor(^BOOL{ @synchronized(TimerFixtureHTTPS.class) { return held.count == 1; } });
        assert(cancelled.downloading && !cancelled.installed);
        assert(![NSFileManager.defaultManager fileExistsAtPath:[root URLByAppendingPathComponent:@"cancelled/sounds/performance"].path]);
        [cancelled cancelDownloads]; waitFor(^BOOL{ return !cancelled.downloading; });
        assert(!cancelled.installed); noPackOrStage([root URLByAppendingPathComponent:@"cancelled"]);

        fixtures(files, audio); holdRecordings = YES;
        HaloTimerAudio *raced = manager(root, @"raced"); [raced downloadRecordings];
        waitFor(^BOOL{ @synchronized(TimerFixtureHTTPS.class) { return held.count == 1; } });
        NSURL *racedPack = folder([root URLByAppendingPathComponent:@"raced"], @"sounds/performance");
        NSURL *racedSentinel = [racedPack URLByAppendingPathComponent:@"keep.txt"];
        assert([userBytes writeToURL:racedSentinel atomically:YES]);
        TimerFixtureHTTPS *waiting; @synchronized(TimerFixtureHTTPS.class) { waiting = held.firstObject; holdRecordings = NO; }
        [waiting finishLoading]; waitFor(^BOOL{ return !raced.downloading; });
        assert(!raced.installed && [[NSData dataWithContentsOfURL:racedSentinel] isEqual:userBytes]);
        assert([NSFileManager.defaultManager contentsOfDirectoryAtPath:racedPack.path error:nil].count == 1);
        for (NSString *name in [NSFileManager.defaultManager contentsOfDirectoryAtPath:[root URLByAppendingPathComponent:@"raced/sounds"].path error:nil]) assert(![name hasPrefix:@".performance-download-"]);

        __block BOOL redirectRejected = NO;
        NSURLSession *unusedSession = [NSURLSession sessionWithConfiguration:NSURLSessionConfiguration.ephemeralSessionConfiguration];
        NSURL *redirectURL = [NSURL URLWithString:@"https://dl.oghalo.com/audio/timer/v1/current.json"];
        NSURLSessionTask *unusedTask = [unusedSession dataTaskWithURL:redirectURL];
        NSHTTPURLResponse *redirect = [[NSHTTPURLResponse alloc] initWithURL:redirectURL statusCode:302 HTTPVersion:@"HTTP/1.1" headerFields:@{@"Location":redirectURL.absoluteString}];
        [(id<NSURLSessionTaskDelegate>)success URLSession:unusedSession task:unusedTask willPerformHTTPRedirection:redirect
            newRequest:[NSURLRequest requestWithURL:redirectURL]
            completionHandler:^(NSURLRequest *request) { redirectRejected = request == nil; }];
        assert(redirectRejected);
        [unusedSession invalidateAndCancel];
        puts("Timer Audio HTTPS, manifest, PCM, cancellation and atomic preservation fixtures passed.");
    }
    return 0;
}
