#import "HaloTimerAudio.h"
#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

static NSString *const manifestURL = @"https://dl.oghalo.com/audio/timer/v1/current.json";
enum { maximumManifestBytes = 65536, maximumFileBytes = 1048576, maximumPackBytes = 33554432 };

NSArray<NSString *> *HaloTimerAudioCues(void) {
    static NSArray *cues;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSMutableArray *names = [NSMutableArray arrayWithObjects:@"timerbeep", @"1_minute", nil];
        for (unsigned i = 2; i <= 30; i++) [names addObject:[NSString stringWithFormat:@"%u_minutes", i]];
        [names addObjectsFromArray:@[@"30_seconds_left", @"20_seconds"]];
        for (unsigned i = 10; i; i--) [names addObject:[NSString stringWithFormat:@"%u", i]];
        [names addObjectsFromArray:@[@"rocket", @"camo", @"overshield"]];
        cues = [names copy];
    });
    return cues;
}
static BOOL exactKeys(NSDictionary *object, NSArray *keys) {
    return [object isKindOfClass:NSDictionary.class] && object.count == keys.count &&
        [[NSSet setWithArray:object.allKeys] isEqualToSet:[NSSet setWithArray:keys]];
}
static BOOL integerInRange(id value, unsigned long long minimum, unsigned long long maximum) {
    return [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID() &&
        [value objCType][0] != 'f' && [value objCType][0] != 'd' &&
        [value doubleValue] >= minimum && [value doubleValue] <= maximum &&
        [value doubleValue] == [value unsignedLongLongValue];
}
static BOOL validHash(id value) {
    return [value isKindOfClass:NSString.class] && [value length] == 64 &&
        [value rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"].invertedSet].location == NSNotFound;
}
NSDictionary<NSString *, NSDictionary *> *HaloValidateTimerAudioManifest(NSData *data) {
    if (!data.length || data.length > maximumManifestBytes) return nil;
    id manifest = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    if (!exactKeys(manifest, @[@"schema_version", @"pack_id", @"files"]) ||
        !integerInRange(manifest[@"schema_version"], 1, 1) || ![manifest[@"pack_id"] isEqual:@"performance-timer-v1"] ||
        ![manifest[@"files"] isKindOfClass:NSArray.class] || [manifest[@"files"] count] != HaloTimerAudioCues().count) return nil;
    NSMutableDictionary *entries = [NSMutableDictionary dictionary];
    unsigned long long total = 0;
    for (id item in manifest[@"files"]) {
        if (!exactKeys(item, @[@"cue", @"file_bytes", @"sha256", @"object_key"])) return nil;
        NSString *cue = item[@"cue"];
        if (![cue isKindOfClass:NSString.class] || ![HaloTimerAudioCues() containsObject:cue] || entries[cue] ||
            !integerInRange(item[@"file_bytes"], 46, maximumFileBytes) || !validHash(item[@"sha256"])) return nil;
        NSString *key = [NSString stringWithFormat:@"audio/timer/sha256/%@/%@.wav", item[@"sha256"], cue];
        if (![item[@"object_key"] isEqual:key]) return nil;
        total += [item[@"file_bytes"] unsignedLongLongValue];
        if (total > maximumPackBytes) return nil;
        entries[cue] = item;
    }
    return entries;
}
static uint32_t little32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint16_t little16(const unsigned char *p) { return (uint16_t)p[0] | (uint16_t)p[1] << 8; }
BOOL HaloTimerAudioWAVIsValid(NSData *data) {
    if (data.length < 46 || data.length > maximumFileBytes) return NO;
    const unsigned char *p = data.bytes;
    unsigned channels = little16(p + 22), rate = little32(p + 24), align = little16(p + 32), bytes = little32(p + 40);
    return !memcmp(p, "RIFF", 4) && !memcmp(p + 8, "WAVEfmt ", 8) && little32(p + 16) == 16 &&
        little16(p + 20) == 1 && little16(p + 34) == 16 && !memcmp(p + 36, "data", 4) &&
        (channels == 1 || channels == 2) && (rate == 22050 || rate == 44100) && align == channels * 2 &&
        little32(p + 28) == rate * align && bytes && !(bytes % align) && bytes <= rate * align * 4 &&
        little32(p + 4) == bytes + 36 && data.length == (uint64_t)bytes + 44;
}
static NSString *sha256(NSData *data) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *hash = [NSMutableString string];
    for (unsigned i = 0; i < sizeof(digest); i++) [hash appendFormat:@"%02x", digest[i]];
    return hash;
}
static NSData *readClip(int directory, NSString *cue) {
    int file = openat(directory, [cue stringByAppendingPathExtension:@"wav"].fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    struct stat info;
    if (file < 0) return nil;
    NSData *result = nil;
    if (!fstat(file, &info) && S_ISREG(info.st_mode) && info.st_size >= 46 && info.st_size <= maximumFileBytes) {
        NSMutableData *bytes = [NSMutableData dataWithLength:(NSUInteger)info.st_size];
        NSUInteger offset = 0;
        while (offset < bytes.length) {
            ssize_t count = read(file, (char *)bytes.mutableBytes + offset, bytes.length - offset);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) break;
            offset += (NSUInteger)count;
        }
        unsigned char extra;
        if (offset == bytes.length && read(file, &extra, 1) == 0) result = bytes;
    }
    close(file);
    return result;
}
static BOOL completePack(int sounds) {
    int pack = sounds >= 0 ? openat(sounds, "performance", O_RDONLY | O_DIRECTORY | O_NOFOLLOW) : -1;
    if (pack < 0) return NO;
    BOOL complete = YES;
    for (NSString *cue in HaloTimerAudioCues()) if (!HaloTimerAudioWAVIsValid(readClip(pack, cue))) { complete = NO; break; }
    close(pack);
    return complete;
}
static BOOL installedAtURL(NSURL *support) {
    if (!support.isFileURL) return NO;
    int root = open(support.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    int sounds = root >= 0 ? openat(root, "sounds", O_RDONLY | O_DIRECTORY | O_NOFOLLOW) : -1;
    BOOL installed = completePack(sounds);
    if (sounds >= 0) close(sounds);
    if (root >= 0) close(root);
    return installed;
}
static BOOL allowedURL(NSURL *url) {
    return [url.scheme.lowercaseString isEqual:@"https"] && [url.host.lowercaseString isEqual:@"dl.oghalo.com"] &&
        (!url.port || url.port.integerValue == 443) && !url.user && !url.password && !url.query && !url.fragment;
}

@implementation HaloTimerAudio {
    NSURL *_support;
    NSURLSessionConfiguration *_configuration;
    NSURLSession *_session;
    NSURLSessionDataTask *_task;
    dispatch_queue_t _work;
    NSDictionary *_entries;
    NSData *_manifest;
    NSMutableData *_bytes;
    NSString *_stageName, *_failure, *_statusText;
    NSUInteger _index;
    int _sounds, _stage;
    BOOL _accepted, _downloading, _installed;
}
- (instancetype)initWithSupportDirectory:(NSURL *)support sessionConfiguration:(NSURLSessionConfiguration *)configuration {
    if ((self = [super init])) {
        _support = support.URLByStandardizingPath;
        _configuration = [configuration ?: NSURLSessionConfiguration.ephemeralSessionConfiguration copy];
        _configuration.timeoutIntervalForRequest = 30;
        _configuration.timeoutIntervalForResource = 180;
        _configuration.URLCache = nil;
        _configuration.HTTPCookieStorage = nil;
        _configuration.HTTPShouldSetCookies = NO;
        _work = dispatch_queue_create("com.pfista.halo.timer-audio", DISPATCH_QUEUE_SERIAL);
        _sounds = _stage = -1;
        _installed = installedAtURL(_support);
        _statusText = _installed ? @"The complete managed timer recording pack is installed." : @"The complete managed timer recording pack is not installed.";
    }
    return self;
}
- (BOOL)downloading { @synchronized(self) { return _downloading; } }
- (BOOL)installed { @synchronized(self) { return _installed; } }
- (NSString *)statusText { @synchronized(self) { return _statusText; } }
- (void)status:(NSString *)text {
    @synchronized(self) { _statusText = [text copy]; }
    dispatch_async(dispatch_get_main_queue(), ^{ if (self.statusChanged) self.statusChanged(); });
}
- (void)finish:(NSString *)message {
    [_task cancel]; _task = nil;
    [_session invalidateAndCancel]; _session = nil;
    if (_stage >= 0) {
        for (NSString *cue in HaloTimerAudioCues()) unlinkat(_stage, [cue stringByAppendingPathExtension:@"wav"].fileSystemRepresentation, 0);
        unlinkat(_stage, "download-manifest.json", 0);
        close(_stage); _stage = -1;
    }
    if (_sounds >= 0) {
        if (_stageName) unlinkat(_sounds, _stageName.fileSystemRepresentation, AT_REMOVEDIR);
        close(_sounds); _sounds = -1;
    }
    _stageName = nil; _entries = nil; _manifest = nil; _bytes = nil;
    @synchronized(self) { _downloading = NO; _installed = installedAtURL(_support); }
    [self status:message];
}
- (BOOL)prepareStage {
    NSFileManager *files = NSFileManager.defaultManager;
    if (!_support.isFileURL || ![files createDirectoryAtURL:_support withIntermediateDirectories:YES attributes:nil error:nil]) return NO;
    int root = open(_support.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    if (root < 0) return NO;
    BOOL made = !mkdirat(root, "sounds", 0755) || errno == EEXIST;
    _sounds = made ? openat(root, "sounds", O_RDONLY | O_DIRECTORY | O_NOFOLLOW) : -1;
    close(root);
    if (_sounds < 0) return NO;
    struct stat info;
    if (!fstatat(_sounds, "performance", &info, AT_SYMLINK_NOFOLLOW) || errno != ENOENT) {
        _failure = @"An existing timer recording folder was preserved. Move it manually before downloading a replacement.";
        return NO;
    }
    NSString *name = [@".performance-download-" stringByAppendingString:NSUUID.UUID.UUIDString];
    if (mkdirat(_sounds, name.fileSystemRepresentation, 0700)) return NO;
    _stageName = name;
    _stage = openat(_sounds, _stageName.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
    return _stage >= 0;
}
- (void)downloadRecordings {
    dispatch_async(_work, ^{
        if (self.downloading) return;
        if (installedAtURL(self->_support)) {
            @synchronized(self) { self->_installed = YES; }
            [self status:@"Timer recordings are installed."]; return;
        }
        @synchronized(self) { self->_downloading = YES; self->_installed = NO; }
        self->_failure = nil; self->_index = 0;
        if (![self prepareStage]) {
            [self finish:self->_failure ?: @"The recording download folder could not be created. Existing files were preserved."]; return;
        }
        NSOperationQueue *delegates = [[NSOperationQueue alloc] init];
        delegates.maxConcurrentOperationCount = 1;
        self->_session = [NSURLSession sessionWithConfiguration:self->_configuration delegate:self delegateQueue:delegates];
        [self status:@"Checking the timer recording pack…"];
        [self fetch:[NSURL URLWithString:manifestURL]];
    });
}
- (void)cancelDownloads {
    dispatch_async(_work, ^{ if (self.downloading) [self finish:@"Recording download cancelled. Existing files were preserved."]; });
}
- (void)fetch:(NSURL *)url {
    _failure = nil; _accepted = NO; _bytes = [NSMutableData data];
    if (!allowedURL(url)) { [self finish:@"The recording URL is not an approved HTTPS source."]; return; }
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:30];
    [request setValue:@"identity" forHTTPHeaderField:@"Accept-Encoding"];
    _task = [_session dataTaskWithRequest:request];
    [_task resume];
}
- (BOOL)writeStageData:(NSData *)bytes name:(NSString *)name {
    int file = openat(_stage, name.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0644);
    if (file < 0) return NO;
    NSUInteger offset = 0;
    while (offset < bytes.length) {
        ssize_t count = write(file, (const char *)bytes.bytes + offset, bytes.length - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        offset += (NSUInteger)count;
    }
    BOOL saved = offset == bytes.length && !fsync(file);
    if (close(file)) saved = NO;
    return saved;
}
- (void)nextRecording {
    if (_index < HaloTimerAudioCues().count) {
        NSString *cue = HaloTimerAudioCues()[_index];
        [self status:[NSString stringWithFormat:@"Downloading timer recordings — %lu of %lu…", (unsigned long)_index + 1, (unsigned long)HaloTimerAudioCues().count]];
        [self fetch:[NSURL URLWithString:[@"https://dl.oghalo.com/" stringByAppendingString:_entries[cue][@"object_key"]]]];
        return;
    }
    if (![self writeStageData:_manifest name:@"download-manifest.json"]) {
        [self finish:@"The complete recording pack could not be saved. Existing files were preserved."]; return;
    }
    /* Both directories are on the same filesystem. RENAME_EXCL activates all
       clips together and never replaces a user folder created during HTTP. */
    if (fsync(_stage) || renameatx_np(_sounds, _stageName.fileSystemRepresentation, _sounds, "performance", RENAME_EXCL)) {
        [self finish:@"The complete recording pack could not be activated. Existing files were preserved."]; return;
    }
    close(_stage); _stage = -1; _stageName = nil;
    (void)fsync(_sounds);
    [self finish:@"Timer recordings are installed. Restart Halo to enable Timer Audio."];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completion {
    (void)session; (void)response; (void)request;
    dispatch_async(_work, ^{ if (self->_task == task) self->_failure = @"Recording downloads do not follow redirects."; });
    completion(nil);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveResponse:(NSURLResponse *)response
 completionHandler:(void (^)(NSURLSessionResponseDisposition))completion {
    (void)session;
    dispatch_async(_work, ^{
        if (self->_task != task) { completion(NSURLSessionResponseCancel); return; }
        NSUInteger limit = self->_entries ? [self->_entries[HaloTimerAudioCues()[self->_index]][@"file_bytes"] unsignedIntegerValue] : maximumManifestBytes;
        NSHTTPURLResponse *http = [response isKindOfClass:NSHTTPURLResponse.class] ? (NSHTTPURLResponse *)response : nil;
        NSString *encoding = [http valueForHTTPHeaderField:@"Content-Encoding"];
        self->_accepted = http.statusCode == 200 && allowedURL(response.URL) && [response.URL isEqual:task.originalRequest.URL] &&
            (!encoding.length || [encoding.lowercaseString isEqual:@"identity"]) &&
            (response.expectedContentLength < 0 || (unsigned long long)response.expectedContentLength <= limit) &&
            (!self->_entries || response.expectedContentLength < 0 || (unsigned long long)response.expectedContentLength == limit) && !self->_failure;
        if (!self->_accepted && !self->_failure) self->_failure = @"The recording server returned an unexpected response, encoding or file size.";
        completion(self->_accepted ? NSURLSessionResponseAllow : NSURLSessionResponseCancel);
    });
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    dispatch_async(_work, ^{
        if (self->_task != task || !self->_accepted || self->_failure) return;
        NSUInteger limit = self->_entries ? [self->_entries[HaloTimerAudioCues()[self->_index]][@"file_bytes"] unsignedIntegerValue] : maximumManifestBytes;
        if (data.length > limit - self->_bytes.length) {
            self->_failure = @"The recording server sent more bytes than the approved size."; [task cancel]; return;
        }
        [self->_bytes appendData:data];
    });
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    (void)session;
    dispatch_async(_work, ^{
        if (self->_task != task) return;
        self->_task = nil;
        if (self->_failure || error || !self->_accepted) {
            [self finish:self->_failure ?: @"Timer recordings could not be downloaded. Check your connection and retry."]; return;
        }
        if (!self->_entries) {
            self->_entries = HaloValidateTimerAudioManifest(self->_bytes);
            if (!self->_entries) { [self finish:@"The server did not provide a complete, supported timer recording manifest."]; return; }
            self->_manifest = [self->_bytes copy];
        } else {
            NSString *cue = HaloTimerAudioCues()[self->_index];
            NSDictionary *entry = self->_entries[cue];
            if (self->_bytes.length != [entry[@"file_bytes"] unsignedIntegerValue] ||
                ![sha256(self->_bytes) isEqual:entry[@"sha256"]] || !HaloTimerAudioWAVIsValid(self->_bytes)) {
                [self finish:@"A timer recording failed its size, SHA-256 or PCM audio check. Existing files were preserved."]; return;
            }
            if (![self writeStageData:self->_bytes name:[cue stringByAppendingPathExtension:@"wav"]]) {
                [self finish:@"A timer recording could not be saved. Check free space and retry."]; return;
            }
            self->_index++;
        }
        [self nextRecording];
    });
}
@end
