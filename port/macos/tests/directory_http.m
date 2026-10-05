/* Production native directory transport with in-process HTTP responses only. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include "game_directory.h"
#include <assert.h>
#include <string.h>

static NSDictionary *fixture;
static unsigned requests;

@interface DirectoryFixtureHTTP : NSURLProtocol
@end
@implementation DirectoryFixtureHTTP
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { (void)request; return YES; }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    assert([self.request.URL.host isEqual:@"directory.fixture.invalid"]);
    assert([self.request.HTTPMethod isEqual:@"GET"]);
    requests++;
    NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:self.request.URL
        statusCode:[fixture[@"status"] integerValue] HTTPVersion:@"HTTP/1.1" headerFields:fixture[@"headers"]];
    [self.client URLProtocol:self didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
    NSData *data = [fixture[@"body"] dataUsingEncoding:NSUTF8StringEncoding];
    if (data.length) [self.client URLProtocol:self didLoadData:data];
    [self.client URLProtocolDidFinishLoading:self];
}
- (void)stopLoading {}
@end

@interface NSURLSessionConfiguration (DirectoryFixture)
+ (NSURLSessionConfiguration *)directoryFixtureConfiguration;
@end
@implementation NSURLSessionConfiguration (DirectoryFixture)
+ (NSURLSessionConfiguration *)directoryFixtureConfiguration {
    NSURLSessionConfiguration *configuration = [self directoryFixtureConfiguration];
    configuration.protocolClasses = @[DirectoryFixtureHTTP.class];
    return configuration;
}
@end

static int request(NSDictionary *response, int capacity, int *status, int *retry) {
    fixture = response;
    char buffer[64] = {0};
    int result = halo_directory_http("GET", "https://directory.fixture.invalid/v1/games", NULL,
        NULL, buffer, capacity, status, retry);
    if (result >= 0) assert(!strcmp(buffer, [response[@"body"] UTF8String]));
    return result;
}

int main(void) {
    @autoreleasepool {
        Method actual = class_getClassMethod(NSURLSessionConfiguration.class, @selector(ephemeralSessionConfiguration));
        Method authored = class_getClassMethod(NSURLSessionConfiguration.class, @selector(directoryFixtureConfiguration));
        method_exchangeImplementations(actual, authored);
        int status = 99, retry = 99;
        assert(request(@{@"status":@429, @"headers":@{@"retry-after":@" \t30 \t", @"Content-Length":@"2"}, @"body":@"{}"},
            64, &status, &retry) == 2 && status == 429 && retry == 30);
        assert(request(@{@"status":@503, @"headers":@{@"Retry-After":@"999999999999999999999999", @"Content-Length":@"999"}, @"body":@"oversized"},
            8, &status, &retry) == -1 && status == 503 && retry == 300);
        /* Exercise a failure after the production delegate saw headers. */
        id<NSURLSessionDataDelegate> transfer = [NSClassFromString(@"HaloDirectoryTransfer") new];
        [(id)transfer setValue:@64 forKey:@"capacity"];
        [(id)transfer setValue:dispatch_semaphore_create(0) forKey:@"done"];
        NSHTTPURLResponse *observed = [[NSHTTPURLResponse alloc] initWithURL:[NSURL URLWithString:@"https://directory.fixture.invalid"]
            statusCode:429 HTTPVersion:@"HTTP/1.1" headerFields:@{@"Retry-After":@"30"}];
        NSURLSession *unusedSession = [NSURLSession sessionWithConfiguration:NSURLSessionConfiguration.ephemeralSessionConfiguration];
        NSURLSessionDataTask *unusedTask = [unusedSession dataTaskWithURL:observed.URL];
        [transfer URLSession:unusedSession dataTask:unusedTask didReceiveResponse:observed completionHandler:^(NSURLSessionResponseDisposition disposition) {
            assert(disposition == NSURLSessionResponseAllow);
        }];
        [transfer URLSession:unusedSession task:unusedTask didCompleteWithError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorNetworkConnectionLost userInfo:nil]];
        assert([[(id)transfer valueForKey:@"status"] intValue] == 429);
        assert([[(id)transfer valueForKey:@"retryAfterSeconds"] intValue] == 30);
        assert([[(id)transfer valueForKey:@"failed"] boolValue]);
        [unusedSession invalidateAndCancel];
        assert(request(@{@"status":@429, @"headers":@{@"Retry-After":@"30x", @"Content-Length":@"2"}, @"body":@"{}"},
            64, &status, &retry) == 2 && status == 429 && retry == 0);
        assert(request(@{@"status":@200, @"headers":@{@"Content-Length":@"2"}, @"body":@"{}"},
            64, &status, &retry) == 2 && status == 200 && retry == 0);
        assert(request(@{@"status":@429, @"headers":@{@"Retry-After":@"30"}, @"body":@"too large"},
            8, &status, &retry) == -1 && status == 429 && retry == 30);
        unsigned before = requests;
        char buffer[16]; status = 99; retry = 99;
        assert(halo_directory_http("GET", "https://directory.fixture.invalid", NULL, NULL,
            buffer, 1, &status, &retry) == -1 && status == 0 && retry == 0 && requests == before);
        method_exchangeImplementations(actual, authored);
        puts("PASS Mac directory Retry-After, bounded error bodies, transport failures, and output reset");
    }
    return 0;
}
