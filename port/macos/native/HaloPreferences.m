#import "HaloPreferences.h"
#include "xiso.h"
#include <string.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <CommonCrypto/CommonDigest.h>
#include "../../linux/include/halo_expanded_cache.h"

static NSError *failure(NSString *message) {
    return [NSError errorWithDomain:@"HaloGameData" code:1
                          userInfo:@{NSLocalizedDescriptionKey: message}];
}

@implementation HaloPreferences {
    NSMutableDictionary *_settings;
}
- (instancetype)initWithSupportDirectory:(NSURL *)directory {
    if ((self = [super init])) {
        _supportDirectory = directory;
        NSData *data = [NSData dataWithContentsOfURL:[directory URLByAppendingPathComponent:@"macos-settings.json"]];
        id decoded = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        _settings = [decoded isKindOfClass:NSDictionary.class] ? [decoded mutableCopy] : [NSMutableDictionary dictionary];
    }
    return self;
}
- (NSString *)dataPath { return [_settings[@"data_path"] isKindOfClass:NSString.class] ? _settings[@"data_path"] : nil; }
- (NSString *)isoPath { return [_settings[@"iso_path"] isKindOfClass:NSString.class] ? _settings[@"iso_path"] : nil; }
- (BOOL)windowed { return [_settings[@"windowed"] isKindOfClass:NSNumber.class] && [_settings[@"windowed"] boolValue]; }
- (BOOL)communityDownloadsEnabled {
    id saved = _settings[@"community_downloads"];
    return !saved || ([saved isKindOfClass:NSNumber.class] && [saved boolValue]);
}
- (BOOL)timerAudioDownloadsEnabled {
    id saved = _settings[@"timer_audio_downloads"];
    return [saved isKindOfClass:NSNumber.class] ? [saved boolValue] : YES;
}
- (BOOL)releaseChecksEnabled {
    id saved = _settings[@"release_checks"];
    return !saved || ([saved isKindOfClass:NSNumber.class] && [saved boolValue]);
}
- (BOOL)save:(NSMutableDictionary *)settings error:(NSError **)error {
    NSData *data = [NSJSONSerialization dataWithJSONObject:settings options:NSJSONWritingPrettyPrinted error:error];
    if (!data || ![NSFileManager.defaultManager createDirectoryAtURL:_supportDirectory
                                       withIntermediateDirectories:YES attributes:nil error:error]) return NO;
    if (![data writeToURL:[_supportDirectory URLByAppendingPathComponent:@"macos-settings.json"]
                 options:NSDataWritingAtomic error:error]) return NO;
    _settings = settings;
    return YES;
}
- (BOOL)selectDataRoot:(NSURL *)root iso:(NSURL *)iso error:(NSError **)error {
    NSURL *validated = HaloValidateGameData(root, error);
    if (!validated) return NO;
    NSMutableDictionary *settings = [_settings mutableCopy];
    settings[@"data_path"] = validated.path;
    if (iso) settings[@"iso_path"] = iso.path;
    else [settings removeObjectForKey:@"iso_path"];
    return [self save:settings error:error];
}
- (BOOL)setWindowed:(BOOL)windowed error:(NSError **)error {
    NSMutableDictionary *settings = [_settings mutableCopy];
    settings[@"windowed"] = @(windowed);
    return [self save:settings error:error];
}
- (BOOL)setCommunityDownloadsEnabled:(BOOL)enabled error:(NSError **)error {
    NSMutableDictionary *settings = [_settings mutableCopy];
    settings[@"community_downloads"] = @(enabled);
    return [self save:settings error:error];
}
- (BOOL)setTimerAudioDownloadsEnabled:(BOOL)enabled error:(NSError **)error {
    NSMutableDictionary *settings = [_settings mutableCopy];
    settings[@"timer_audio_downloads"] = @(enabled);
    return [self save:settings error:error];
}
- (BOOL)setReleaseChecksEnabled:(BOOL)enabled error:(NSError **)error {
    NSMutableDictionary *settings = [_settings mutableCopy];
    settings[@"release_checks"] = @(enabled);
    return [self save:settings error:error];
}
@end

static NSDictionary<NSString *, NSURL *> *entries(NSURL *directory, NSError **error) {
    NSArray<NSURL *> *files = [NSFileManager.defaultManager contentsOfDirectoryAtURL:directory
                          includingPropertiesForKeys:@[NSURLIsRegularFileKey] options:0 error:error];
    if (!files) return nil;
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    for (NSURL *file in files) {
        NSString *name = file.lastPathComponent.lowercaseString;
        if (result[name]) {
            if (error) *error = failure(@"This folder contains duplicate names with different capitalization.");
            return nil;
        }
        result[name] = file;
    }
    return result;
}

NSURL *HaloFindAdjacentDiscImage(NSURL *directory, NSError **error) {
    if (error) *error = nil;
    NSArray<NSURL *> *files = [NSFileManager.defaultManager contentsOfDirectoryAtURL:directory
        includingPropertiesForKeys:@[NSURLIsRegularFileKey, NSURLIsSymbolicLinkKey]
        options:NSDirectoryEnumerationSkipsHiddenFiles error:error];
    if (!files) return nil;
    NSURL *candidate = nil;
    BOOL sawImage = NO;
    for (NSURL *file in files) {
        NSString *extension = file.pathExtension.lowercaseString;
        if (![extension isEqualToString:@"iso"] && ![extension isEqualToString:@"xiso"]) continue;
        NSNumber *regular = nil, *linked = nil;
        if (![file getResourceValue:&regular forKey:NSURLIsRegularFileKey error:nil] || !regular.boolValue ||
            ![file getResourceValue:&linked forKey:NSURLIsSymbolicLinkKey error:nil] || linked.boolValue) continue;
        sawImage = YES;
        char detail[512] = {0};
        if (!xiso_probe_maps(file.fileSystemRepresentation, detail, sizeof(detail))) continue;
        if (candidate) {
            if (error) *error = failure(@"More than one supported Xbox Halo disc image is beside Halo OG. Choose the image you want to use.");
            return nil;
        }
        candidate = file;
    }
    if (!candidate && sawImage && error)
        *error = failure(@"The nearby ISO/XISO is not a supported original Xbox Halo disc image. Choose your original Xbox Halo image or a complete extracted maps folder.");
    return candidate;
}

NSURL *HaloValidateGameData(NSURL *selection, NSError **error) {
    NSURL *root = selection.URLByStandardizingPath.URLByResolvingSymlinksInPath;
    NSURL *maps;
    if ([root.lastPathComponent.lowercaseString isEqualToString:@"maps"]) {
        maps = root;
        root = root.URLByDeletingLastPathComponent;
    } else {
        maps = entries(root, error)[@"maps"];
    }
    if (!maps) {
        if (error) *error = failure(@"Choose an extracted Xbox Halo game folder containing maps, or the maps folder itself.");
        return nil;
    }
    NSDictionary<NSString *, NSURL *> *files = entries(maps, error);
    if (!files) return nil;
    NSString *discBuild = nil;
    BOOL hasUI = NO, hasOpeningLevel = NO;
    for (NSString *name in files) {
        if (![name.pathExtension isEqualToString:@"map"]) continue;
        NSURL *file = files[name];
        NSFileHandle *handle = [NSFileHandle fileHandleForReadingFromURL:file error:error];
        if (!handle) return nil;
        NSData *header = [handle readDataUpToLength:2048 error:error];
        [handle closeFile];
        if (!header) return nil;
        const unsigned char *bytes = header.bytes;
        BOOL valid = header.length == 2048 && !memcmp(bytes, "daeh", 4) && !memcmp(bytes + 2044, "toof", 4);
        uint32_t version = 0, length = 0;
        NSString *cacheName = nil, *build = nil;
        if (valid) {
            memcpy(&version, bytes + 4, 4);
            memcpy(&length, bytes + 8, 4);
            const unsigned char *nameEnd = memchr(bytes + 32, 0, 32), *buildEnd = memchr(bytes + 64, 0, 32);
            if (nameEnd && buildEnd) {
                cacheName = [[NSString alloc] initWithBytes:bytes + 32 length:nameEnd - bytes - 32 encoding:NSASCIIStringEncoding];
                build = [[NSString alloc] initWithBytes:bytes + 64 length:buildEnd - bytes - 64 encoding:NSASCIIStringEncoding];
            }
            valid = version == 5 && length >= 2048 && length <= 0x11600000 &&
                [cacheName.lowercaseString isEqualToString:name.stringByDeletingPathExtension] &&
                ([@"01.01.14.2342" isEqualToString:build] || [@"01.10.12.2276" isEqualToString:build]);
        }
        if (!valid) {
            if (error) *error = failure([NSString stringWithFormat:@"%@ is not a supported original Xbox Halo map. PC, Custom Edition, Anniversary and MCC maps cannot be used.", file.lastPathComponent]);
            return nil;
        }
        if (discBuild && ![discBuild isEqualToString:build]) {
            if (error) *error = failure(@"The maps mix different Xbox releases. Choose one complete set from one disc.");
            return nil;
        }
        discBuild = build;
        hasUI |= [name isEqualToString:@"ui.map"];
        hasOpeningLevel |= [name isEqualToString:@"a10.map"];
    }
    if (!hasUI || !hasOpeningLevel) {
        if (error) *error = failure(@"This folder needs ui.map and a10.map from the same Xbox Halo disc. Use a complete maps folder.");
        return nil;
    }
    return root;
}

NSURL *HaloImportDiscImage(NSURL *image, NSURL *supportDirectory,
                          xiso_progress_proc progress, void *context, NSError **error) {
    /* A new directory for every import. Failed imports never replace working data. */
    NSURL *destination = [[supportDirectory URLByAppendingPathComponent:@"Game Data" isDirectory:YES]
                          URLByAppendingPathComponent:NSUUID.UUID.UUIDString isDirectory:YES];
    if (![NSFileManager.defaultManager createDirectoryAtURL:destination withIntermediateDirectories:YES
                                                attributes:nil error:error]) return nil;
    char detail[512] = {0};
    BOOL extracted = xiso_extract_maps(image.fileSystemRepresentation, destination.fileSystemRepresentation,
                                      progress, context, detail, sizeof(detail));
    NSURL *validated = extracted ? HaloValidateGameData(destination, error) : nil;
    if (!validated) {
        [NSFileManager.defaultManager removeItemAtURL:destination error:nil];
        if (!extracted && error) *error = failure([NSString stringWithUTF8String:detail] ?: @"The disc image could not be read.");
    }
    return validated;
}

static NSString *copyHash(CC_SHA256_CTX *context);

/* The importer checks the generation contract and immutable cache bytes.
   Gameplay additionally validates the expanded tag catalog before loading. */
static NSString *arsenalFileHash(NSURL *file, unsigned long long minimum, unsigned long long maximum,
                               NSData **header) {
    int descriptor = open(file.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    struct stat before, after;
    BOOL valid = descriptor >= 0 && !fstat(descriptor, &before) && S_ISREG(before.st_mode) &&
        before.st_size >= 0 && (unsigned long long)before.st_size >= minimum && (unsigned long long)before.st_size <= maximum;
    CC_SHA256_CTX hash; CC_SHA256_Init(&hash);
    unsigned char bytes[65536]; ssize_t count = 0;
    unsigned long long total = 0;
    while (valid && (count = read(descriptor, bytes, sizeof(bytes))) > 0) {
        if ((unsigned long long)count > (unsigned long long)before.st_size - total) { valid = NO; break; }
        if (header && !total) *header = [NSData dataWithBytes:bytes length:MIN((size_t)count, (size_t)2048)];
        total += (unsigned long long)count;
        CC_SHA256_Update(&hash, bytes, (CC_LONG)count);
    }
    valid = valid && count == 0 && !fstat(descriptor, &after) && total == (unsigned long long)before.st_size &&
        before.st_size == after.st_size && before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec &&
        before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec;
    if (descriptor >= 0) close(descriptor);
    return valid ? copyHash(&hash) : nil;
}

static void arsenalJSONSpace(const unsigned char **cursor, const unsigned char *end) {
    while (*cursor < end && (**cursor == ' ' || **cursor == '\t' || **cursor == '\r' || **cursor == '\n')) ++*cursor;
}
static BOOL arsenalJSONToken(const unsigned char **cursor, const unsigned char *end, unsigned char token) {
    arsenalJSONSpace(cursor, end);
    if (*cursor == end || **cursor != token) return NO;
    ++*cursor;
    return YES;
}
static NSString *arsenalJSONString(const unsigned char **cursor, const unsigned char *end) {
    if (!arsenalJSONToken(cursor, end, '"')) return nil;
    const unsigned char *start = *cursor;
    while (*cursor < end && **cursor != '"') {
        if (**cursor < 32 || **cursor > 126 || **cursor == '\\') return nil;
        ++*cursor;
    }
    if (*cursor == end) return nil;
    NSString *result = [[NSString alloc] initWithBytes:start length:*cursor - start encoding:NSASCIIStringEncoding];
    ++*cursor;
    return result;
}
static NSDictionary *arsenalManifest(NSURL *file) {
    int descriptor = open(file.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    struct stat info;
    unsigned char bytes[4097]; ssize_t count = 0;
    BOOL valid = descriptor >= 0 && !fstat(descriptor, &info) && S_ISREG(info.st_mode) && info.st_size > 0 && info.st_size <= 4096;
    if (valid) count = read(descriptor, bytes, sizeof(bytes));
    if (descriptor >= 0) close(descriptor);
    if (!valid || count != info.st_size) return nil;
    const unsigned char *cursor = bytes, *end = bytes + count;
    NSMutableDictionary *fields = [NSMutableDictionary dictionary];
    if (!arsenalJSONToken(&cursor, end, '{')) return nil;
    do {
        NSString *key = arsenalJSONString(&cursor, end);
        if (!key || fields[key] || !arsenalJSONToken(&cursor, end, ':')) return nil;
        arsenalJSONSpace(&cursor, end);
        id value;
        if (cursor < end && *cursor == '"') value = arsenalJSONString(&cursor, end);
        else {
            const unsigned char *start = cursor;
            unsigned long long integer = 0;
            while (cursor < end && *cursor >= '0' && *cursor <= '9') {
                unsigned digit = *cursor++ - '0';
                if (integer > (128ULL * 1024 * 1024 - digit) / 10) return nil;
                integer = integer * 10 + digit;
            }
            if (cursor == start || (cursor - start > 1 && *start == '0')) return nil;
            value = @(integer);
        }
        if (!value) return nil;
        fields[key] = value;
        if (fields.count > 9) return nil;
        if (arsenalJSONToken(&cursor, end, '}')) break;
        if (!arsenalJSONToken(&cursor, end, ',')) return nil;
    } while (YES);
    arsenalJSONSpace(&cursor, end);
    NSSet *expected = [NSSet setWithArray:@[@"schema_version", @"generation", @"logical_map", @"physical_map", @"cache_sha256",
        @"base_sha256", @"weapon_list_sha256", @"cache_file_bytes", @"cache_declared_bytes"]];
    return cursor == end && [expected isEqualToSet:[NSSet setWithArray:fields.allKeys]] ? fields : nil;
}
static BOOL arsenalDigest(id value) {
    if (![value isKindOfClass:NSString.class] || [value length] != 64) return NO;
    return [value rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"].invertedSet].location == NSNotFound;
}
static BOOL arsenalMapName(id value) {
    if (![value isKindOfClass:NSString.class] || ![value length] || [value length] >= HALO_EXPANDED_CACHE_NAME_SIZE) return NO;
    return [value rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyz0123456789_- "].invertedSet].location == NSNotFound;
}
static NSString *arsenalPhysicalName(NSString *logical) {
    if (logical.length <= 23) return [@"_fiesta_" stringByAppendingString:logical];
    NSData *bytes = [logical dataUsingEncoding:NSASCIIStringEncoding];
    CC_SHA256_CTX hash; CC_SHA256_Init(&hash); CC_SHA256_Update(&hash, bytes.bytes, (CC_LONG)bytes.length);
    return [@"_fiestah_" stringByAppendingString:[copyHash(&hash) substringToIndex:16]];
}
static uint32_t arsenalU32(const unsigned char *bytes) {
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 | (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}
static BOOL arsenalHeader(NSData *header, NSString *name, unsigned long long declared, BOOL expanded) {
    if (header.length != 2048) return NO;
    const unsigned char *bytes = header.bytes;
    const unsigned char *nameEnd = memchr(bytes + 32, 0, 32), *buildEnd = memchr(bytes + 64, 0, 32);
    if (!nameEnd || !buildEnd) return NO;
    NSString *cacheName = [[NSString alloc] initWithBytes:bytes + 32 length:nameEnd - bytes - 32 encoding:NSASCIIStringEncoding];
    NSString *build = [[NSString alloc] initWithBytes:bytes + 64 length:buildEnd - bytes - 64 encoding:NSASCIIStringEncoding];
    uint32_t length = arsenalU32(bytes + 8), offset = arsenalU32(bytes + 16), size = arsenalU32(bytes + 20);
    BOOL valid = !memcmp(bytes, "daeh", 4) && !memcmp(bytes + 2044, "toof", 4) && arsenalU32(bytes + 4) == 5 &&
        bytes[96] == 1 && bytes[97] == 0 && [cacheName isEqual:name] && length >= 2048 && length <= 128ULL * 1024 * 1024 &&
        ([@"01.01.14.2342" isEqual:build] || [@"01.10.12.2276" isEqual:build]);
    return valid && (!expanded || (length == declared && offset >= 2048 && offset <= length && size >= 40 &&
        size <= 22ULL * 1024 * 1024 && size <= length - offset));
}
static BOOL arsenalInvalid(NSError **error) {
    if (error) *error = failure(@"This folder has incomplete or changed Fiesta arsenal files. Restore the matching map and manifest before managing a copy. Your original files are unchanged.");
    return NO;
}
static BOOL arsenalSources(NSDictionary<NSString *, NSURL *> *maps, NSMutableArray *sources, NSError **error) {
    NSURL *arsenal = maps[@"arsenal"];
    if (!arsenal) return YES;
    struct stat info;
    if (lstat(arsenal.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode)) return arsenalInvalid(error);
    NSDictionary *generations = entries(arsenal, error);
    if (!generations) return NO;
    NSURL *generation = generations[@"v1"];
    if (!generation) return YES;
    if (lstat(generation.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode)) return arsenalInvalid(error);
    NSDictionary *files = entries(generation, error);
    if (!files) return NO;
    for (NSString *name in [[files allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
        if (![name.pathExtension isEqual:@"map"] && ![name.pathExtension isEqual:@"json"]) continue;
        NSString *physical = name.stringByDeletingPathExtension;
        NSURL *cache = files[[physical stringByAppendingPathExtension:@"map"]], *manifestFile = files[[physical stringByAppendingPathExtension:@"json"]];
        if (!cache || !manifestFile || (![physical hasPrefix:@"_fiesta_"] && ![physical hasPrefix:@"_fiestah_"])) return arsenalInvalid(error);
        if (![name.pathExtension isEqual:@"json"]) continue;
        NSDictionary *manifest = arsenalManifest(manifestFile);
        NSString *logical = manifest[@"logical_map"];
        if (!manifest || ![manifest[@"schema_version"] isEqual:@1] || ![manifest[@"generation"] isEqual:@(HALO_EXPANDED_CACHE_GENERATION)] ||
            !arsenalMapName(logical) || ![physical isEqual:arsenalPhysicalName(logical)] ||
            ![manifest[@"physical_map"] isEqual:physical] || !arsenalDigest(manifest[@"base_sha256"]) || !arsenalDigest(manifest[@"cache_sha256"]) ||
            ![manifest[@"weapon_list_sha256"] isEqual:@HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256] ||
            ![manifest[@"cache_file_bytes"] isKindOfClass:NSNumber.class] || ![manifest[@"cache_declared_bytes"] isKindOfClass:NSNumber.class]) return arsenalInvalid(error);
        unsigned long long fileBytes = [manifest[@"cache_file_bytes"] unsignedLongLongValue], declared = [manifest[@"cache_declared_bytes"] unsignedLongLongValue];
        if (fileBytes < 2048 || declared < 2048) return arsenalInvalid(error);
        NSURL *base = maps[[logical stringByAppendingPathExtension:@"map"]];
        NSData *baseHeader = nil, *cacheHeader = nil;
        if (!base || ![arsenalFileHash(base, 2048, 128ULL * 1024 * 1024, &baseHeader) isEqual:manifest[@"base_sha256"]] ||
            !arsenalHeader(baseHeader, logical, 0, NO) ||
            ![arsenalFileHash(cache, fileBytes, fileBytes, &cacheHeader) isEqual:manifest[@"cache_sha256"]] ||
            !arsenalHeader(cacheHeader, physical, declared, YES)) return arsenalInvalid(error);
        [sources addObject:cache];
        [sources addObject:manifestFile];
    }
    return YES;
}

/* Copy regular maps and verified generation-1 arsenal pairs only. External
   folder mode remains available for deliberate symlink-based developer data. */
static NSArray<NSURL *> *copySources(NSURL *selection, NSError **error) {
    NSURL *root = HaloValidateGameData(selection, error);
    if (!root) return nil;
    NSMutableArray *sources = [NSMutableArray array];
    NSDictionary<NSString *, NSURL *> *directories = entries(root, error);
    if (!directories) return nil;
    for (NSString *name in @[@"maps", @"maps_de", @"maps_fr", @"maps_es", @"maps_it"]) {
        NSURL *directory = directories[name];
        if (!directory) continue;
        struct stat info;
        if (lstat(directory.fileSystemRepresentation, &info)) continue;
        if (!S_ISDIR(info.st_mode)) {
            if (error) *error = failure(@"Managed copying needs real maps directories. Use This Folder for linked developer data.");
            return nil;
        }
        NSDictionary *files = entries(directory, error);
        if (!files) return nil;
        for (NSString *fileName in [[files allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
            if (![fileName.pathExtension isEqualToString:@"map"]) continue;
            NSURL *file = files[fileName];
            if (lstat(file.fileSystemRepresentation, &info) || !S_ISREG(info.st_mode)) {
                if (error) *error = failure(@"Managed copying needs regular map files. Use This Folder to keep your linked data in place.");
                return nil;
            }
            [sources addObject:file];
        }
        if (!arsenalSources(files, sources, error)) return nil;
    }
    return sources;
}

static unsigned long long copySourcesSize(NSArray<NSURL *> *sources, NSError **error) {
    unsigned long long size = 0;
    for (NSURL *source in sources) {
        struct stat info;
        if (lstat(source.fileSystemRepresentation, &info) || !S_ISREG(info.st_mode) || info.st_size < 0) {
            if (error) *error = failure(@"A source map changed. Choose the folder again.");
            return 0;
        }
        size += (unsigned long long)info.st_size;
    }
    return size;
}
unsigned long long HaloGameDataCopySize(NSURL *root, NSError **error) {
    return copySourcesSize(copySources(root, error), error);
}

static NSString *copyHash(CC_SHA256_CTX *context) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest, context);
    NSMutableString *result = [NSMutableString string];
    for (unsigned i = 0; i < sizeof(digest); i++) [result appendFormat:@"%02x", digest[i]];
    return result;
}
static NSString *copiedFileHash(NSURL *file) {
    int descriptor = open(file.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    if (descriptor < 0) return nil;
    CC_SHA256_CTX context; CC_SHA256_Init(&context);
    unsigned char bytes[65536]; ssize_t count;
    while ((count = read(descriptor, bytes, sizeof(bytes))) > 0) CC_SHA256_Update(&context, bytes, (CC_LONG)count);
    close(descriptor);
    return count == 0 ? copyHash(&context) : nil;
}

NSURL *HaloCopyGameData(NSURL *selection, NSURL *supportDirectory, xiso_progress_proc progress,
                       void *context, NSError **error) {
    NSURL *root = HaloValidateGameData(selection, error);
    NSArray<NSURL *> *sources = root ? copySources(root, error) : nil;
    if (!sources) return nil;
    unsigned long long total = copySourcesSize(sources, error), done = 0;
    if (!total) return nil;
    NSURL *destination = [[supportDirectory URLByAppendingPathComponent:@"Game Data" isDirectory:YES]
                          URLByAppendingPathComponent:NSUUID.UUID.UUIDString isDirectory:YES];
    BOOL success = [NSFileManager.defaultManager createDirectoryAtURL:destination
        withIntermediateDirectories:YES attributes:nil error:error];
    NSMutableArray *records = [NSMutableArray array];
    for (NSURL *source in sources) {
        if (!success) break;
        NSString *relative = [source.path substringFromIndex:root.path.length + 1];
        NSURL *target = [destination URLByAppendingPathComponent:relative];
        NSURL *folder = target.URLByDeletingLastPathComponent;
        success = [NSFileManager.defaultManager createDirectoryAtURL:folder withIntermediateDirectories:YES attributes:nil error:error];
        int input = success ? open(source.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW) : -1;
        struct stat before, after;
        int output = -1;
        success = input >= 0 && !fstat(input, &before) && S_ISREG(before.st_mode);
        if (success) output = open(target.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
        success = success && output >= 0;
        char bytes[65536];
        ssize_t amount;
        unsigned long long copied = 0;
        CC_SHA256_CTX sourceHash; CC_SHA256_Init(&sourceHash);
        while (success && (amount = read(input, bytes, sizeof(bytes))) > 0) {
            if ((unsigned long long)amount > (unsigned long long)before.st_size - copied) { success = NO; break; }
            CC_SHA256_Update(&sourceHash, bytes, (CC_LONG)amount);
            ssize_t offset = 0;
            while (offset < amount) {
                ssize_t written = write(output, bytes + offset, (size_t)(amount - offset));
                if (written <= 0) { success = NO; break; }
                offset += written;
            }
            copied += (unsigned long long)amount;
            done += (unsigned long long)amount;
            if (progress) progress(context, source.lastPathComponent.UTF8String, MIN(done, total), total);
        }
        if (success) success = amount == 0 && !fstat(input, &after) &&
            before.st_size == after.st_size && before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec &&
            before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec && copied == (unsigned long long)before.st_size && !fsync(output);
        if (input >= 0) close(input);
        if (output >= 0) close(output);
        NSString *sourceDigest = copyHash(&sourceHash);
        if (success) success = [sourceDigest isEqual:copiedFileHash(target)];
        if (success) [records addObject:@{@"path": relative,
                                         @"bytes": @(copied), @"sha256": sourceDigest}];
    }
    NSURL *validated = success ? HaloValidateGameData(destination, error) : nil;
    if (validated && !copySources(validated, error)) validated = nil;
    if (validated) {
        NSDictionary *record = @{@"schema_version": @1, @"source_kind": @"copied-folder", @"source_path": root.path,
                                  @"files": records, @"completed": @YES};
        NSData *data = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingPrettyPrinted error:error];
        if (!data || ![data writeToURL:[destination URLByAppendingPathComponent:@"import.json"] options:NSDataWritingAtomic error:error]) validated = nil;
    }
    if (!validated) {
        [NSFileManager.defaultManager removeItemAtURL:destination error:nil];
        if (error && !*error) *error = failure(@"The maps could not be copied. Your original files and previous selection are unchanged.");
    }
    return validated;
}

BOOL HaloUpdateConfigurationIsValid(NSDictionary *info) {
    NSString *feed = info[@"SUFeedURL"], *publicKey = info[@"SUPublicEDKey"];
    if (![feed isKindOfClass:NSString.class] || ![publicKey isKindOfClass:NSString.class]) return NO;
    NSURL *url = [NSURL URLWithString:feed];
    NSData *key = [[NSData alloc] initWithBase64EncodedString:publicKey options:0];
    return [url.scheme isEqualToString:@"https"] && url.host.length && !url.user && !url.password && key.length == 32;
}

static NSURL *migrationRecordURL(NSURL *directory) {
    return [directory URLByAppendingPathComponent:@"legacy-migration.json"];
}
static BOOL migrationCompleted(NSURL *legacy, NSURL *destination) {
    NSURL *file = migrationRecordURL(destination);
    struct stat info;
    if (lstat(file.fileSystemRepresentation, &info) || !S_ISREG(info.st_mode)) return NO;
    NSData *data = [NSData dataWithContentsOfURL:file];
    id record = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    return [record isKindOfClass:NSDictionary.class] && [record[@"schema_version"] isEqual:@1] &&
        [record[@"completed"] isEqual:@YES] && [record[@"source_path"] isEqual:legacy.path] &&
        [record[@"destination_path"] isEqual:destination.path];
}
BOOL HaloSupportDirectoryNeedsMigration(NSURL *directory) {
    /* Protocol-11 saved weapon IDs overlap OpenCE's canonical sets. Do not
     * silently import either installation's profiles into this separate app. */
    (void)directory;
    return NO;
}
static BOOL migrationConflict(NSString *relative, NSArray<NSString *> *conflicts, BOOL descendants) {
    for (NSString *conflict in conflicts) {
        if ([relative isEqual:conflict] || [relative hasPrefix:[conflict stringByAppendingString:@"/"]] ||
            (descendants && [conflict hasPrefix:[relative stringByAppendingString:@"/"]])) return YES;
    }
    return NO;
}
static BOOL migrationSources(NSURL *directory, NSString *prefix, NSMutableArray *sources,
                             unsigned long long *total, NSError **error) {
    NSArray<NSURL *> *files = [NSFileManager.defaultManager contentsOfDirectoryAtURL:directory
        includingPropertiesForKeys:nil options:0 error:error];
    if (!files) return NO;
    files = [files sortedArrayUsingComparator:^NSComparisonResult(NSURL *a, NSURL *b) { return [a.lastPathComponent compare:b.lastPathComponent]; }];
    for (NSURL *file in files) {
        struct stat info;
        if (lstat(file.fileSystemRepresentation, &info)) {
            if (error) *error = failure(@"A legacy file changed while Halo OG was preparing its copy. Close the older app and retry.");
            return NO;
        }
        NSString *relative = prefix.length ? [prefix stringByAppendingPathComponent:file.lastPathComponent] : file.lastPathComponent;
        if (!S_ISDIR(info.st_mode) && !S_ISREG(info.st_mode) && !S_ISLNK(info.st_mode)) {
            if (error) *error = failure([NSString stringWithFormat:@"The legacy folder contains an unsupported file at %@. Its contents were preserved.", relative]);
            return NO;
        }
        [sources addObject:@{@"source":file, @"relative":relative, @"directory":@(S_ISDIR(info.st_mode)), @"link":@(S_ISLNK(info.st_mode))}];
        if (S_ISREG(info.st_mode)) *total += info.st_size;
        if (S_ISDIR(info.st_mode) && !migrationSources(file, relative, sources, total, error)) return NO;
        /* Do not enumerate through symbolic links into external originals. */
    }
    return YES;
}
static BOOL migrationPublishData(NSData *data, NSURL *target, NSURL *staging, NSError **error) {
    NSURL *partial = [staging URLByAppendingPathComponent:NSUUID.UUID.UUIDString];
    if (![data writeToURL:partial options:NSDataWritingWithoutOverwriting error:error]) return NO;
    int descriptor = open(partial.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    BOOL success = descriptor >= 0 && !fsync(descriptor);
    if (descriptor >= 0) close(descriptor);
    success = success && !link(partial.fileSystemRepresentation, target.fileSystemRepresentation);
    unlink(partial.fileSystemRepresentation);
    if (!success && error) *error = failure(@"Halo OG could not publish a complete migration record or settings file. Existing files were preserved.");
    return success;
}
static NSDictionary *migrationCopyFile(NSURL *source, NSURL *target, NSURL *staging,
    unsigned long long *done, unsigned long long total, xiso_progress_proc progress, void *context, NSError **error) {
    int input = open(source.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    struct stat before, after;
    BOOL success = input >= 0 && !fstat(input, &before) && S_ISREG(before.st_mode) && before.st_size >= 0;
    NSURL *partial = [staging URLByAppendingPathComponent:NSUUID.UUID.UUIDString];
    int output = success ? open(partial.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600) : -1;
    success = success && output >= 0;
    unsigned char bytes[65536]; ssize_t count = 0;
    unsigned long long copied = 0;
    CC_SHA256_CTX hash; CC_SHA256_Init(&hash);
    while (success && (count = read(input, bytes, sizeof(bytes))) > 0) {
        if (copied + (unsigned long long)count > (unsigned long long)before.st_size) { success = NO; break; }
        CC_SHA256_Update(&hash, bytes, (CC_LONG)count);
        ssize_t offset = 0;
        while (offset < count) {
            ssize_t written = write(output, bytes + offset, count - offset);
            if (written <= 0) { success = NO; break; }
            offset += written;
        }
        copied += count; *done += count;
        if (progress) progress(context, source.lastPathComponent.UTF8String, MIN(*done, total), total);
    }
    if (success) success = count == 0 && !fstat(input, &after) && copied == (unsigned long long)before.st_size &&
        before.st_size == after.st_size && before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec &&
        before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec && !fsync(output);
    if (input >= 0) close(input);
    if (output >= 0) close(output);
    NSString *digest = copyHash(&hash);
    if (success) success = [digest isEqual:copiedFileHash(partial)];
    if (success) success = !link(partial.fileSystemRepresentation, target.fileSystemRepresentation);
    unlink(partial.fileSystemRepresentation);
    if (!success) {
        if (error) *error = failure([NSString stringWithFormat:@"Could not copy %@ completely. Close the older app, check free space, and retry. Original and existing files were preserved.", source.lastPathComponent]);
        return nil;
    }
    return @{@"file_bytes":@(copied), @"sha256":digest};
}
static NSString *migrationMappedPath(NSString *path, NSURL *legacy, NSURL *destination, NSArray *conflicts) {
    if (![path isKindOfClass:NSString.class]) return nil;
    NSString *old = [NSURL fileURLWithPath:path].URLByStandardizingPath.path;
    NSString *prefix = [legacy.path stringByAppendingString:@"/"];
    if (![old isEqual:legacy.path] && ![old hasPrefix:prefix]) return nil;
    NSString *relative = [old isEqual:legacy.path] ? @"" : [old substringFromIndex:prefix.length];
    if (!relative.length && conflicts.count) return nil;
    if (migrationConflict(relative, conflicts, YES)) return nil;
    NSURL *target = [destination URLByAppendingPathComponent:relative];
    struct stat info;
    return !lstat(target.fileSystemRepresentation, &info) ? target.path : nil;
}
BOOL HaloMigrateLegacySupportDirectory(NSURL *legacy, NSURL *destination, xiso_progress_proc progress,
                                       void *context, NSError **error) {
    legacy = legacy.URLByStandardizingPath;
    destination = destination.URLByStandardizingPath;
    if (error) *error = nil;
    if (migrationCompleted(legacy, destination)) return YES;
    struct stat info;
    if (lstat(legacy.fileSystemRepresentation, &info) && errno == ENOENT) return YES;
    if (lstat(legacy.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode) ||
        [legacy.path isEqual:destination.path] || [destination.path hasPrefix:[legacy.path stringByAppendingString:@"/"]] ||
        [legacy.path hasPrefix:[destination.path stringByAppendingString:@"/"]]) {
        if (error) *error = failure(@"The legacy Application Support location must be a real folder separate from Halo OG. No original data was changed.");
        return NO;
    }
    if ((!lstat(destination.fileSystemRepresentation, &info) && !S_ISDIR(info.st_mode)) ||
        ![NSFileManager.defaultManager createDirectoryAtURL:destination withIntermediateDirectories:YES attributes:nil error:error]) {
        if (error && !*error) *error = failure(@"The Halo OG data location is not a writable real folder. The legacy files remain available.");
        return NO;
    }
    if (!lstat(migrationRecordURL(destination).fileSystemRepresentation, &info)) {
        if (error) *error = failure(@"An unrecognized migration record already exists in Halo OG. It was preserved; migration cannot safely continue.");
        return NO;
    }
    NSURL *staging = [destination URLByAppendingPathComponent:[@".migration-" stringByAppendingString:NSUUID.UUID.UUIDString] isDirectory:YES];
    if (![NSFileManager.defaultManager createDirectoryAtURL:staging withIntermediateDirectories:NO attributes:nil error:error]) return NO;
    NSMutableArray *sources = [NSMutableArray array], *records = [NSMutableArray array], *conflicts = [NSMutableArray array];
    NSMutableDictionary *rewrites = [NSMutableDictionary dictionary];
    unsigned long long total = 0, done = 0;
    if (progress) progress(context, "Preparing legacy data copy", 0, 0);
    BOOL success = migrationSources(legacy, @"", sources, &total, error);
    NSDictionary *settingsSource = nil;
    for (NSDictionary *item in sources) {
        if (!success) break;
        NSURL *source = item[@"source"];
        NSString *relative = item[@"relative"];
        if ([relative isEqual:@"macos-settings.json"] && ![item[@"directory"] boolValue] && ![item[@"link"] boolValue]) { settingsSource = item; continue; }
        if (migrationConflict(relative, conflicts, NO)) continue;
        NSURL *target = [destination URLByAppendingPathComponent:relative];
        BOOL exists = !lstat(target.fileSystemRepresentation, &info);
        if ([item[@"directory"] boolValue]) {
            if (exists && !S_ISDIR(info.st_mode)) [conflicts addObject:relative];
            else if (!exists) success = [NSFileManager.defaultManager createDirectoryAtURL:target withIntermediateDirectories:NO attributes:nil error:error];
            continue;
        }
        if (exists) {
            BOOL equal = NO;
            if ([item[@"link"] boolValue] && S_ISLNK(info.st_mode))
                equal = [[NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:source.path error:nil]
                    isEqual:[NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:target.path error:nil]];
            else if (![item[@"link"] boolValue] && S_ISREG(info.st_mode))
                equal = [copiedFileHash(source) isEqual:copiedFileHash(target)];
            if (!equal) [conflicts addObject:relative];
            [records addObject:@{@"path":relative, @"action":equal ? @"existing-identical" : @"existing-preserved"}];
            continue;
        }
        if ([item[@"link"] boolValue]) {
            NSString *linkTarget = [NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:source.path error:error];
            /* Relative links keep their relationship inside the copied tree.
               Absolute links keep their original targets, including external
               developer files; external bytes are never traversed/copied. */
            success = linkTarget && !symlink(linkTarget.fileSystemRepresentation, target.fileSystemRepresentation);
            if (!success && error && !*error) *error = failure(@"A legacy link could not be preserved. No linked original files were changed.");
            if (success) [records addObject:@{@"path":relative, @"action":@"link-preserved", @"target":linkTarget}];
        } else {
            NSDictionary *digest = migrationCopyFile(source, target, staging, &done, total, progress, context, error);
            success = digest != nil;
            if (success) [records addObject:@{@"path":relative, @"action":@"copied", @"file_bytes":digest[@"file_bytes"], @"sha256":digest[@"sha256"]}];
        }
    }
    if (success && settingsSource) {
        NSURL *target = [destination URLByAppendingPathComponent:@"macos-settings.json"];
        if (!lstat(target.fileSystemRepresentation, &info)) {
            NSData *bytes = [NSData dataWithContentsOfURL:target options:0 error:error];
            id decoded = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:error] : nil;
            success = [decoded isKindOfClass:NSDictionary.class];
            if (!success && error && !*error) *error = failure(@"Existing Halo OG settings are invalid. They were preserved; the game will not silently start with empty settings.");
            if (success) [records addObject:@{@"path":@"macos-settings.json", @"action":@"existing-settings-preserved"}];
        } else {
            NSData *bytes = [NSData dataWithContentsOfURL:settingsSource[@"source"] options:0 error:error];
            id decoded = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:error] : nil;
            success = [decoded isKindOfClass:NSDictionary.class];
            NSMutableDictionary *settings = success ? [decoded mutableCopy] : nil;
            if (!success && error && !*error) *error = failure(@"The legacy settings file is invalid. It was preserved; Halo OG will not silently start with empty settings.");
            for (NSString *key in @[@"data_path", @"iso_path"]) {
                NSString *mapped = success ? migrationMappedPath(settings[key], legacy, destination, conflicts) : nil;
                if (mapped) { rewrites[key] = @{@"from":settings[key], @"to":mapped}; settings[key] = mapped; }
            }
            NSData *updated = success ? [NSJSONSerialization dataWithJSONObject:settings options:NSJSONWritingPrettyPrinted error:error] : nil;
            success = updated && migrationPublishData(updated, target, staging, error);
            if (success) [records addObject:@{@"path":@"macos-settings.json", @"action":@"copied-settings", @"sha256":copiedFileHash(target) ?: @""}];
        }
    }
    NSMutableDictionary *report = [@{@"schema_version":@1, @"source_path":legacy.path, @"destination_path":destination.path,
        @"completed":@(success), @"completed_at":[NSDate.now description], @"source_bytes":@(total), @"copied_bytes":@(done),
        @"files":records, @"conflicts":conflicts, @"settings_rewrites":rewrites,
        @"link_policy":@"Preserve link targets; never traverse external links", @"legacy_preserved":@YES} mutableCopy];
    if (!success) report[@"error"] = error && *error ? (*error).localizedDescription : @"Legacy copy failed. Original files were preserved.";
    NSData *recordBytes = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    if (success) success = recordBytes && migrationPublishData(recordBytes, migrationRecordURL(destination), staging, error);
    if (!success) {
        report[@"completed"] = @NO;
        report[@"error"] = error && *error ? (*error).localizedDescription : @"Migration could not finish. Retry before launching the game.";
        NSURL *failed = [destination URLByAppendingPathComponent:[NSString stringWithFormat:@"legacy-migration-failed-%@.json", NSUUID.UUID.UUIDString]];
        migrationPublishData([NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil], failed, staging, nil);
    }
    [NSFileManager.defaultManager removeItemAtURL:staging error:nil];
    if (progress && success) progress(context, "Legacy data copied; originals preserved", total, total);
    return success;
}
