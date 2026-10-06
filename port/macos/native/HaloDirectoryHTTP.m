#import <Foundation/Foundation.h>
#include "game_directory.h"
#include "directory_retry_after.h"
#include <string.h>

@interface HaloDirectoryTransfer : NSObject <NSURLSessionDataDelegate>
@property(nonatomic, strong) NSMutableData *data;
@property(nonatomic, strong) dispatch_semaphore_t done;
@property(nonatomic) NSInteger capacity;
@property(nonatomic) NSInteger status;
@property(nonatomic) int retryAfterSeconds;
@property(nonatomic) BOOL failed;
@end
@implementation HaloDirectoryTransfer
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
    willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request
    completionHandler:(void (^)(NSURLRequest *))completionHandler {
    completionHandler(nil);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task
    didReceiveResponse:(NSURLResponse *)response completionHandler:(void (^)(NSURLSessionResponseDisposition))handler {
    self.status = [response isKindOfClass:NSHTTPURLResponse.class] ? ((NSHTTPURLResponse *)response).statusCode : 0;
    NSString *retryAfter = self.status ? [(NSHTTPURLResponse *)response valueForHTTPHeaderField:@"Retry-After"] : nil;
    self.retryAfterSeconds = halo_directory_retry_after_seconds(retryAfter.UTF8String);
    self.failed = !self.status || response.expectedContentLength >= self.capacity;
    handler(self.failed ? NSURLSessionResponseCancel : NSURLSessionResponseAllow);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    if (self.data.length + data.length >= (NSUInteger)self.capacity) { self.failed = YES; [task cancel]; }
    else [self.data appendData:data];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError *)error {
    self.failed = self.failed || error != nil;
    dispatch_semaphore_signal(self.done);
}
@end

int halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status, int *retry_after_seconds) {
    @autoreleasepool {
        if (status) *status = 0;
        if (retry_after_seconds) *retry_after_seconds = 0;
        if (!status || !method || !url || !response || capacity < 2 || capacity > HALO_DIRECTORY_BODY_LIMIT || (body && strlen(body) > 4096) ||
            (lease && *lease && (strlen(lease) != 64 || strspn(lease, "0123456789abcdef") != 64))) return -1;
        NSURL *endpoint = [NSURL URLWithString:@(url)];
        if (![endpoint.scheme isEqualToString:@"https"] || !endpoint.host.length || endpoint.user || endpoint.password) return -1;
        NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
        configuration.timeoutIntervalForRequest = 5; configuration.timeoutIntervalForResource = 8;
        HaloDirectoryTransfer *transfer = [HaloDirectoryTransfer new];
        transfer.capacity = capacity; transfer.data = [NSMutableData data]; transfer.done = dispatch_semaphore_create(0);
        NSOperationQueue *queue = [NSOperationQueue new]; queue.maxConcurrentOperationCount = 1;
        NSURLSession *session = [NSURLSession sessionWithConfiguration:configuration delegate:transfer delegateQueue:queue];
        NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:endpoint];
        request.HTTPMethod = @(method);
        [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
        [request setValue:@"application/json" forHTTPHeaderField:@"Accept"];
        [request setValue:@"Halo-OG-game-directory" forHTTPHeaderField:@"User-Agent"];
        if (body) request.HTTPBody = [NSData dataWithBytes:body length:strlen(body)];
        if (lease && *lease) [request setValue:[@"Bearer " stringByAppendingString:@(lease)] forHTTPHeaderField:@"Authorization"];
        [[session dataTaskWithRequest:request] resume];
        int result = -1;
        if (!dispatch_semaphore_wait(transfer.done, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC))) {
            *status = (int)transfer.status;
            if (retry_after_seconds) *retry_after_seconds = transfer.retryAfterSeconds;
            if (!transfer.failed) {
                result = (int)transfer.data.length; memcpy(response, transfer.data.bytes, (unsigned)result);
                response[result] = 0;
            }
        }
        [session invalidateAndCancel];
        return result;
    }
}
