#ifndef HALO_MAP_PACKAGES_H
#define HALO_MAP_PACKAGES_H
#import <Foundation/Foundation.h>
/* Bounded JSON must also reject duplicate or escaped-alias keys. */
id HaloParseStrictContentJSON(NSData *data, NSError **error);

/* Inspection authenticates all whole literal assets. Compressed .mapog files
   expand only into owned temporary storage, which is removed before return.
   Plain HOGPKG1 .hogpkg files remain supported for local imports. */
NSDictionary *HaloInspectCommunityPackage(NSURL *file, NSError **error);

/* Call on a worker queue. Only private work files and a verified, new map are
   written; original caches and existing installed maps are never replaced. */
NSURL *HaloAssembleCommunityPackage(NSURL *package, NSURL *gameDataRoot,
    NSURL *supportDirectory, NSURL *toolsDirectory, NSDictionary *toolsRecord,
    void (^progress)(NSString *), NSError **error);
#endif
