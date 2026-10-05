#import "HaloReleaseUpdates.h"
#include "release_discovery.h"
#include <string.h>

static NSString *const HaloPublishedReleases = @"https://github.com/pfista/halo-og/releases";

static BOOL validBuildIdentity(NSString *sha, NSString *date) {
    if (![sha isKindOfClass:NSString.class] || ![date isKindOfClass:NSString.class] ||
        sha.length != 40 || date.length != 20) return NO;
    NSCharacterSet *hex = [NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"];
    if ([sha rangeOfCharacterFromSet:hex.invertedSet].location != NSNotFound) return NO;
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.calendar = [[NSCalendar alloc] initWithCalendarIdentifier:NSCalendarIdentifierGregorian];
    formatter.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    formatter.dateFormat = @"yyyy-MM-dd'T'HH:mm:ss'Z'";
    formatter.lenient = NO;
    NSDate *instant = [formatter dateFromString:date];
    return instant && [date compare:@"2000-01-01T00:00:00Z"] != NSOrderedAscending &&
        [[formatter stringFromDate:instant] isEqualToString:date];
}

static BOOL allowedMetadataURL(NSURL *url) {
    return [url.absoluteString isEqualToString:@HALO_RELEASE_DISCOVERY_URL];
}

@interface HaloReleaseUpdates ()
@property(nonatomic, readwrite) BOOL automaticChecksAvailable;
@property(nonatomic, readwrite) BOOL checking;
@property(nonatomic, readwrite) BOOL updateAvailable;
@property(nonatomic, readwrite, copy) NSString *statusText;
@property(nonatomic, readwrite, strong) NSURL *downloadURL;
@property(nonatomic, copy) NSString *sourceSHA;
@property(nonatomic, copy) NSString *sourceDate;
@property(nonatomic, strong) NSURLSessionConfiguration *configuration;
@property(nonatomic, strong) NSOperationQueue *networkQueue;
/* The network queue serializes these request fields and all delegate methods. */
@property(nonatomic, strong) NSURLSession *session;
@property(nonatomic, strong) NSURLSessionDataTask *task;
@property(nonatomic, strong) NSMutableData *responseData;
@property(nonatomic, copy) NSString *responseFailure;
@end

@implementation HaloReleaseUpdates
- (instancetype)initWithSourceSHA:(NSString *)sourceSHA sourceDate:(NSString *)sourceDate {
    return [self initWithSourceSHA:sourceSHA sourceDate:sourceDate sessionConfiguration:nil];
}
- (instancetype)initWithSourceSHA:(NSString *)sourceSHA sourceDate:(NSString *)sourceDate
            sessionConfiguration:(NSURLSessionConfiguration *)sessionConfiguration {
    self = [super init];
    if (!self) return nil;
    _sourceSHA = [sourceSHA copy]; _sourceDate = [sourceDate copy];
    _automaticChecksAvailable = validBuildIdentity(sourceSHA, sourceDate);
    _configuration = [sessionConfiguration ?: NSURLSessionConfiguration.ephemeralSessionConfiguration copy];
    _configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
    _configuration.URLCache = nil;
    _configuration.HTTPCookieStorage = nil;
    _configuration.HTTPShouldSetCookies = NO;
    _configuration.timeoutIntervalForRequest = 20;
    _configuration.timeoutIntervalForResource = 30;
    _networkQueue = [[NSOperationQueue alloc] init];
    _networkQueue.maxConcurrentOperationCount = 1;
    _networkQueue.qualityOfService = NSQualityOfServiceUtility;
    if (_automaticChecksAvailable) _statusText = @"Check for a newer Halo OG build.";
    else {
        _statusText = @"This local build cannot compare releases. View the published builds on GitHub.";
        _downloadURL = [NSURL URLWithString:HaloPublishedReleases];
    }
    return self;
}

- (void)notifyChanged {
    NSAssert(NSThread.isMainThread, @"Release status is published on the main thread");
    if (self.statusChanged) self.statusChanged();
}
- (void)checkForUpdates {
    if (!NSThread.isMainThread) {
        dispatch_async(dispatch_get_main_queue(), ^{ [self checkForUpdates]; });
        return;
    }
    if (self.checking) return;
    if (!self.automaticChecksAvailable) {
        [self notifyChanged];
        return;
    }
    self.checking = YES;
    self.updateAvailable = NO;
    self.downloadURL = nil;
    self.statusText = @"Checking GitHub releases…";
    [self notifyChanged];
    [self.networkQueue addOperationWithBlock:^{
        self.responseData = [NSMutableData data];
        self.responseFailure = nil;
        self.session = [NSURLSession sessionWithConfiguration:self.configuration delegate:self
                                               delegateQueue:self.networkQueue];
        NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:@HALO_RELEASE_DISCOVERY_URL]];
        [request setValue:@"application/vnd.github+json" forHTTPHeaderField:@"Accept"];
        [request setValue:@"Halo-OG-release-check" forHTTPHeaderField:@"User-Agent"];
        self.task = [self.session dataTaskWithRequest:request];
        [self.task resume];
    }];
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
 willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest *))completionHandler {
    (void)session; (void)response;
    if (task != self.task || !allowedMetadataURL(request.URL)) {
        self.responseFailure = @"GitHub returned an unsupported redirect.";
        completionHandler(nil);
        return;
    }
    completionHandler(request);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task
 didReceiveResponse:(NSURLResponse *)response completionHandler:(void (^)(NSURLSessionResponseDisposition))completionHandler {
    (void)session;
    if (task != self.task) { completionHandler(NSURLSessionResponseCancel); return; }
    BOOL valid = [response isKindOfClass:NSHTTPURLResponse.class] &&
        ((NSHTTPURLResponse *)response).statusCode == 200 && allowedMetadataURL(response.URL) &&
        [response.MIMEType isEqualToString:@"application/json"];
    if (!valid) self.responseFailure = @"GitHub returned an unsupported response.";
    else if (response.expectedContentLength > (long long)HALO_RELEASE_DISCOVERY_BYTES)
        self.responseFailure = @"GitHub release metadata exceeded the download limit.";
    completionHandler(self.responseFailure ? NSURLSessionResponseCancel : NSURLSessionResponseAllow);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    (void)session;
    if (task != self.task || self.responseFailure) return;
    if (data.length > HALO_RELEASE_DISCOVERY_BYTES - self.responseData.length) {
        self.responseFailure = @"GitHub release metadata exceeded the download limit.";
        [task cancel];
        return;
    }
    [self.responseData appendData:data];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    if (task != self.task) return;
    NSString *failure = self.responseFailure;
    NSData *metadata = [self.responseData copy];
    self.task = nil; self.responseData = nil; self.responseFailure = nil; self.session = nil;
    [session finishTasksAndInvalidate];
    if (!failure && error) failure = @"Unable to check GitHub releases. Try again later.";
    struct halo_release_notice notice;
    memset(&notice, 0, sizeof(notice));
    int available = 0;
    if (!failure) {
        id json = [NSJSONSerialization JSONObjectWithData:metadata options:0 error:nil];
        if (![json isKindOfClass:NSArray.class]) failure = @"GitHub returned invalid release metadata.";
        else available = halo_release_discovery_parse(metadata.bytes, metadata.length, "Halo-OG-macos-arm64.dmg",
            self.sourceSHA.UTF8String, self.sourceDate.UTF8String, &notice);
    }
    NSString *tag = available ? @(notice.tag) : nil;
    NSURL *download = available ? [NSURL URLWithString:@(notice.download_url)] : nil;
    dispatch_async(dispatch_get_main_queue(), ^{
        self.checking = NO;
        self.updateAvailable = available != 0;
        self.downloadURL = download ?: (failure ? [NSURL URLWithString:HaloPublishedReleases] : nil);
        self.statusText = failure ?: (available ? [NSString stringWithFormat:@"A newer Halo OG build is available (%@).", tag]
                                               : @"No newer complete Mac release was found.");
        [self notifyChanged];
    });
}
@end
