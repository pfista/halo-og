#ifndef HALO_TIMER_AUDIO_H
#define HALO_TIMER_AUDIO_H
#import <Foundation/Foundation.h>

/* Optional recordings use an explicit download action. Construction only
   checks the local pack and never contacts the server. */
@interface HaloTimerAudio : NSObject <NSURLSessionDataDelegate>
@property(nonatomic, readonly) BOOL downloading;
@property(nonatomic, readonly) BOOL installed;
@property(nonatomic, readonly) NSString *statusText;
@property(nonatomic, copy) void (^statusChanged)(void);
- (instancetype)initWithSupportDirectory:(NSURL *)support
                   sessionConfiguration:(NSURLSessionConfiguration *)configuration;
- (void)downloadRecordings;
- (void)cancelDownloads;
@end

NSArray<NSString *> *HaloTimerAudioCues(void);
NSDictionary<NSString *, NSDictionary *> *HaloValidateTimerAudioManifest(NSData *data);
BOOL HaloTimerAudioWAVIsValid(NSData *data);
#endif
