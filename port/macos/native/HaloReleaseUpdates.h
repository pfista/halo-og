#ifndef HALO_RELEASE_UPDATES_H
#define HALO_RELEASE_UPDATES_H

#import <Foundation/Foundation.h>

/* Read-only release discovery. The host decides when to show a notice or open
   downloadURL in the browser; this class never downloads or installs a build. */
@interface HaloReleaseUpdates : NSObject <NSURLSessionDataDelegate>
@property(nonatomic, readonly) BOOL automaticChecksAvailable;
@property(nonatomic, readonly) BOOL checking;
@property(nonatomic, readonly) BOOL updateAvailable;
@property(nonatomic, readonly) NSString *statusText;
@property(nonatomic, readonly) NSURL *downloadURL;
@property(nonatomic, copy) void (^statusChanged)(void);
- (instancetype)initWithSourceSHA:(NSString *)sourceSHA sourceDate:(NSString *)sourceDate;
- (instancetype)initWithSourceSHA:(NSString *)sourceSHA sourceDate:(NSString *)sourceDate
            sessionConfiguration:(NSURLSessionConfiguration *)sessionConfiguration;
- (void)checkForUpdates;
@end

#endif
