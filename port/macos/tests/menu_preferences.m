#import <Foundation/Foundation.h>
#import "HaloPreferences.h"
#include <assert.h>
#include <sys/stat.h>
#include <CommonCrypto/CommonDigest.h>
#include "../../linux/include/halo_expanded_cache.h"

static unsigned progressCalls;
static void progress(void *context, const char *name, unsigned long long done, unsigned long long total) {
    (void)context;
    assert(name && done <= total);
    progressCalls++;
}

static void writeFixture(NSData *bytes, NSURL *file) {
    assert([NSFileManager.defaultManager createDirectoryAtURL:file.URLByDeletingLastPathComponent
        withIntermediateDirectories:YES attributes:nil error:nil]);
    assert([bytes writeToURL:file atomically:YES]);
}
static NSDictionary *snapshot(NSURL *root) {
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    NSDirectoryEnumerator<NSURL *> *walk = [NSFileManager.defaultManager enumeratorAtURL:root
        includingPropertiesForKeys:nil options:0 errorHandler:nil];
    for (NSURL *file in walk) {
        struct stat info;
        assert(!lstat(file.fileSystemRepresentation, &info));
        NSString *relative = [file.path substringFromIndex:root.path.length + 1];
        if (S_ISREG(info.st_mode)) result[relative] = [NSData dataWithContentsOfURL:file];
        else if (S_ISLNK(info.st_mode)) {
            result[relative] = [@"link:" stringByAppendingString:[NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:file.path error:nil]];
            [walk skipDescendants];
        }
    }
    return result;
}
static NSString *fixtureSHA(NSData *data) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *result = [NSMutableString string];
    for (unsigned i = 0; i < sizeof(digest); i++) [result appendFormat:@"%02x", digest[i]];
    return result;
}
static NSData *arsenalMapFixture(NSData *template, NSString *name, BOOL expanded) {
    NSMutableData *result = [template mutableCopy];
    if (expanded || result.length < 2112) result.length = 2112;
    unsigned char *bytes = result.mutableBytes;
    memset(bytes + 32, 0, 32);
    memcpy(bytes + 32, name.UTF8String, name.length);
    bytes[96] = 1;
    uint32_t length = (uint32_t)result.length, offset = 2048, tagSize = 64;
    memcpy(bytes + 8, &length, 4);
    memcpy(bytes + 16, &offset, 4); memcpy(bytes + 20, &tagSize, 4);
    return result;
}
static NSDictionary *writeArsenalFixture(NSURL *maps, NSData *template, NSString *logical) {
    NSString *physical = logical.length <= 23 ? [@"_fiesta_" stringByAppendingString:logical] :
        [@"_fiestah_" stringByAppendingString:[fixtureSHA([logical dataUsingEncoding:NSASCIIStringEncoding]) substringToIndex:16]];
    NSData *base = arsenalMapFixture(template, logical, NO), *cache = arsenalMapFixture(template, physical, YES);
    NSDictionary *manifest = @{@"schema_version":@1, @"generation":@(HALO_EXPANDED_CACHE_GENERATION), @"logical_map":logical,
        @"physical_map":physical, @"base_sha256":fixtureSHA(base), @"cache_sha256":fixtureSHA(cache),
        @"weapon_list_sha256":@HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256, @"cache_file_bytes":@(cache.length), @"cache_declared_bytes":@(cache.length)};
    writeFixture(base, [maps URLByAppendingPathComponent:[logical stringByAppendingPathExtension:@"map"]]);
    NSURL *hidden = [maps URLByAppendingPathComponent:@"arsenal/v1"];
    writeFixture(cache, [hidden URLByAppendingPathComponent:[physical stringByAppendingPathExtension:@"map"]]);
    writeFixture([NSJSONSerialization dataWithJSONObject:manifest options:0 error:nil],
        [hidden URLByAppendingPathComponent:[physical stringByAppendingPathExtension:@"json"]]);
    return manifest;
}
static void changeArsenalDuringCopy(void *context, const char *name, unsigned long long done, unsigned long long total) {
    (void)name; (void)done; (void)total;
    NSURL *file = (__bridge NSURL *)context;
    NSMutableDictionary *manifest = [[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfURL:file] options:0 error:nil] mutableCopy];
    manifest[@"cache_sha256"] = [@"0" stringByPaddingToLength:64 withString:@"0" startingAtIndex:0];
    writeFixture([NSJSONSerialization dataWithJSONObject:manifest options:0 error:nil], file);
}
static void arsenalCopyFixtures(NSURL *test, NSURL *valid) {
    NSURL *root = [test URLByAppendingPathComponent:@"arsenal-copy-source"], *support = [test URLByAppendingPathComponent:@"arsenal-copy-support"];
    assert([NSFileManager.defaultManager copyItemAtURL:valid toURL:root error:nil]);
    NSData *template = [NSData dataWithContentsOfURL:[valid URLByAppendingPathComponent:@"maps/ui.map"]];
    NSDictionary *manifest = writeArsenalFixture([root URLByAppendingPathComponent:@"maps"], template, @"prisoner");
    writeArsenalFixture([root URLByAppendingPathComponent:@"maps"], template, @"long_community_map_identity");
    writeArsenalFixture([root URLByAppendingPathComponent:@"maps_de"], template, @"prisoner");
    NSURL *hidden = [root URLByAppendingPathComponent:@"maps/arsenal/v1"], *manifestFile = [hidden URLByAppendingPathComponent:@"_fiesta_prisoner.json"];
    writeFixture([@"original unrelated file" dataUsingEncoding:NSUTF8StringEncoding], [hidden URLByAppendingPathComponent:@"notes.txt"]);
    writeFixture([@"existing managed file" dataUsingEncoding:NSUTF8StringEncoding], [support URLByAppendingPathComponent:@"Game Data/existing/keep.txt"]);
    NSDictionary *original = snapshot(root), *existing = snapshot(support);
    NSError *error = nil;
    unsigned long long expectedSize = 0;
    for (NSString *name in original) if (![name hasSuffix:@"notes.txt"]) expectedSize += [original[name] length];
    assert(HaloGameDataCopySize(root, &error) == expectedSize);
    NSURL *copied = HaloCopyGameData(root, support, NULL, NULL, &error);
    assert(copied && [snapshot(root) isEqual:original]);
    NSDictionary *copiedFiles = snapshot(copied);
    for (NSString *name in original) if (![name hasSuffix:@"notes.txt"]) assert([original[name] isEqual:copiedFiles[name]]);
    assert(!copiedFiles[@"maps/arsenal/v1/notes.txt"] && !copiedFiles[@"v1/_fiesta_prisoner.map"]);
    NSDictionary *record = [NSJSONSerialization JSONObjectWithData:copiedFiles[@"import.json"] options:0 error:nil];
    BOOL recorded = NO;
    for (NSDictionary *file in record[@"files"]) if ([file[@"path"] isEqual:@"maps/arsenal/v1/_fiesta_prisoner.json"]) recorded = YES;
    assert(recorded && [record[@"completed"] boolValue]);
    for (NSString *name in existing) assert([existing[name] isEqual:snapshot(support)[name]]);
    NSDictionary *preserved = snapshot(support);
    NSString *zeros = [@"0" stringByPaddingToLength:64 withString:@"0" startingAtIndex:0];
    NSArray *changes = @[@{@"schema_version":@2}, @{@"schema_version":@YES}, @{@"generation":@2}, @{@"logical_map":@"../prisoner"},
        @{@"physical_map":@"_fiesta_other"}, @{@"base_sha256":zeros}, @{@"cache_sha256":zeros}, @{@"weapon_list_sha256":zeros},
        @{@"cache_file_bytes":@2049}, @{@"cache_declared_bytes":@2113}, @{@"cache_file_bytes":@(128ULL * 1024 * 1024 + 1)}, @{@"extra":@1}];
    NSMutableArray *badManifests = [NSMutableArray array];
    for (NSDictionary *change in changes) {
        NSMutableDictionary *bad = [manifest mutableCopy]; [bad addEntriesFromDictionary:change];
        [badManifests addObject:[NSJSONSerialization dataWithJSONObject:bad options:0 error:nil]];
    }
    NSString *json = [[NSString alloc] initWithData:original[@"maps/arsenal/v1/_fiesta_prisoner.json"] encoding:NSUTF8StringEncoding];
    [badManifests addObject:[[[json substringToIndex:1] stringByAppendingFormat:@"\"schema_version\":1,%@", [json substringFromIndex:1]] dataUsingEncoding:NSUTF8StringEncoding]];
    [badManifests addObject:[[json stringByReplacingOccurrencesOfString:@"\"logical_map\"" withString:@"\"logical\\u005fmap\""] dataUsingEncoding:NSUTF8StringEncoding]];
    [badManifests addObject:[NSMutableData dataWithLength:4097]];
    for (NSData *bad in badManifests) {
        writeFixture(bad, manifestFile); NSDictionary *before = snapshot(root); error = nil;
        assert(!HaloCopyGameData(root, support, NULL, NULL, &error) && error);
        assert([snapshot(root) isEqual:before] && [snapshot(support) isEqual:preserved]);
    }
    writeFixture(original[@"maps/arsenal/v1/_fiesta_prisoner.json"], manifestFile);
    NSURL *cacheFile = [hidden URLByAppendingPathComponent:@"_fiesta_prisoner.map"];
    for (unsigned field = 0; field < 4; field++) {
        NSMutableData *badCache = [original[@"maps/arsenal/v1/_fiesta_prisoner.map"] mutableCopy];
        unsigned char *bytes = badCache.mutableBytes;
        if (field == 0) bytes[4] = 7;
        if (field == 1) bytes[96] = 0;
        if (field == 2) bytes[32] = 'x';
        if (field == 3) { uint32_t tagSize = 22U * 1024 * 1024 + 1; memcpy(bytes + 20, &tagSize, 4); }
        NSMutableDictionary *bad = [manifest mutableCopy]; bad[@"cache_sha256"] = fixtureSHA(badCache);
        writeFixture(badCache, cacheFile); writeFixture([NSJSONSerialization dataWithJSONObject:bad options:0 error:nil], manifestFile);
        error = nil; assert(!HaloCopyGameData(root, support, NULL, NULL, &error) && error);
        assert([snapshot(support) isEqual:preserved]);
    }
    writeFixture(original[@"maps/arsenal/v1/_fiesta_prisoner.map"], cacheFile);
    writeFixture(original[@"maps/arsenal/v1/_fiesta_prisoner.json"], manifestFile);
    for (NSString *name in @[@"_fiesta_prisoner.map", @"_fiesta_prisoner.json"]) {
        NSURL *file = [hidden URLByAppendingPathComponent:name]; NSData *bytes = [NSData dataWithContentsOfURL:file];
        assert([NSFileManager.defaultManager removeItemAtURL:file error:nil]); error = nil;
        assert(!HaloCopyGameData(root, support, NULL, NULL, &error) && error);
        assert([NSFileManager.defaultManager createSymbolicLinkAtURL:file withDestinationURL:[copied URLByAppendingPathComponent:[@"maps/arsenal/v1" stringByAppendingPathComponent:name]] error:nil]); error = nil;
        assert(!HaloCopyGameData(root, support, NULL, NULL, &error) && error);
        assert([NSFileManager.defaultManager removeItemAtURL:file error:nil]); writeFixture(bytes, file);
        assert([snapshot(support) isEqual:preserved]);
    }
    NSURL *generation = [root URLByAppendingPathComponent:@"maps/arsenal/v1"], *parked = [root URLByAppendingPathComponent:@"parked-generation"];
    assert([NSFileManager.defaultManager moveItemAtURL:generation toURL:parked error:nil]);
    assert([NSFileManager.defaultManager createSymbolicLinkAtURL:generation withDestinationURL:parked error:nil]); error = nil;
    assert(!HaloCopyGameData(root, support, NULL, NULL, &error) && error);
    assert([NSFileManager.defaultManager removeItemAtURL:generation error:nil]);
    assert([NSFileManager.defaultManager moveItemAtURL:parked toURL:generation error:nil]);
    assert([snapshot(support) isEqual:preserved]);
    error = nil;
    assert(!HaloCopyGameData(root, support, changeArsenalDuringCopy, (__bridge void *)manifestFile, &error) && error);
    assert([snapshot(support) isEqual:preserved]); // A changed manifest cannot publish a partial managed import.
    writeFixture(original[@"maps/arsenal/v1/_fiesta_prisoner.json"], manifestFile);
    assert([snapshot(root) isEqual:original]);
    puts("Managed arsenal copying: exact hierarchy/bytes/records, community and long names, language maps, strict manifests, changed-source rollback and originals/existing destination preservation passed");
}
static void timerDownloadPreferenceFixtures(NSURL *test, NSURL *valid) {
    NSURL *support = [test URLByAppendingPathComponent:@"timer-download-preferences"];
    NSURL *file = [support URLByAppendingPathComponent:@"macos-settings.json"];
    HaloPreferences *preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
    assert(preferences.timerAudioDownloadsEnabled);
    assert(![NSFileManager.defaultManager fileExistsAtPath:file.path]);
    NSMutableDictionary *settings = [@{@"data_path":valid.path, @"windowed":@YES,
        @"community_downloads":@NO, @"release_checks":@NO, @"future_setting":@"preserve me"} mutableCopy];
    writeFixture([NSJSONSerialization dataWithJSONObject:settings options:0 error:nil], file);
    preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
    assert(preferences.timerAudioDownloadsEnabled); // Older settings inherit the default.
    NSError *error = nil;
    assert([preferences setTimerAudioDownloadsEnabled:NO error:&error]);
    preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
    assert(!preferences.timerAudioDownloadsEnabled);
    assert([preferences setWindowed:NO error:&error]);
    preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
    assert(!preferences.timerAudioDownloadsEnabled); // Other settings preserve the opt-out.
    assert([preferences setTimerAudioDownloadsEnabled:YES error:&error]);
    preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
    assert(preferences.timerAudioDownloadsEnabled);
    assert([preferences.dataPath isEqual:valid.path] && !preferences.windowed &&
        !preferences.communityDownloadsEnabled && !preferences.releaseChecksEnabled);
    settings = [[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfURL:file] options:0 error:nil] mutableCopy];
    assert([settings[@"future_setting"] isEqual:@"preserve me"]);
    for (id invalid in @[@"off", NSNull.null, @[], @{}]) {
        settings[@"timer_audio_downloads"] = invalid;
        writeFixture([NSJSONSerialization dataWithJSONObject:settings options:0 error:nil], file);
        preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert(preferences.timerAudioDownloadsEnabled);
        assert([preferences setTimerAudioDownloadsEnabled:NO error:&error]);
        assert(![[HaloPreferences alloc] initWithSupportDirectory:support].timerAudioDownloadsEnabled);
    }
    NSURL *blocked = [test URLByAppendingPathComponent:@"timer-preferences-blocked"];
    writeFixture([@"existing file" dataUsingEncoding:NSUTF8StringEncoding], blocked);
    preferences = [[HaloPreferences alloc] initWithSupportDirectory:blocked];
    error = nil;
    assert(![preferences setTimerAudioDownloadsEnabled:NO error:&error] && error);
    assert(preferences.timerAudioDownloadsEnabled); // Failed saves do not change memory.
    assert([[NSString stringWithContentsOfURL:blocked encoding:NSUTF8StringEncoding error:nil] isEqual:@"existing file"]);
    puts("Timer recording download preferences: defaults, opt-out/reload, invalid values and atomic failure preservation passed");
}
static void migrationFixtures(NSURL *test, NSURL *valid, NSURL *image) {
    NSURL *legacy = [test URLByAppendingPathComponent:@"migration/legacy"], *destination = [test URLByAppendingPathComponent:@"migration/Halo OG"];
    NSURL *oldImport = [legacy URLByAppendingPathComponent:@"Game Data/import-a"];
    assert([NSFileManager.defaultManager createDirectoryAtURL:oldImport.URLByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:nil]);
    assert([NSFileManager.defaultManager copyItemAtURL:valid toURL:oldImport error:nil]);
    NSURL *oldImage = [legacy URLByAppendingPathComponent:@"Images/local.iso"];
    writeFixture([NSData dataWithContentsOfURL:image], oldImage);
    NSData *controls = [@"legacy controls" dataUsingEncoding:NSUTF8StringEncoding];
    writeFixture(controls, [legacy URLByAppendingPathComponent:@"config.toml"]);
    writeFixture([@"save bytes" dataUsingEncoding:NSUTF8StringEncoding], [legacy URLByAppendingPathComponent:@"profiles/player/save.bin"]);
    writeFixture([NSData dataWithContentsOfURL:[valid URLByAppendingPathComponent:@"maps/ui.map"]], [legacy URLByAppendingPathComponent:@"Community Maps/maps/fixture.map"]);
    NSURL *externalLink = [legacy URLByAppendingPathComponent:@"external-maps"];
    assert([NSFileManager.defaultManager createSymbolicLinkAtURL:externalLink withDestinationURL:valid error:nil]);
    NSURL *relativeLink = [legacy URLByAppendingPathComponent:@"relative-import"];
    assert([NSFileManager.defaultManager createSymbolicLinkAtPath:relativeLink.path withDestinationPath:@"Game Data/import-a" error:nil]);
    NSDictionary *oldSettings = @{@"data_path":oldImport.path, @"iso_path":oldImage.path, @"windowed":@YES, @"community_downloads":@YES, @"future_key":@"kept"};
    writeFixture([NSJSONSerialization dataWithJSONObject:oldSettings options:0 error:nil], [legacy URLByAppendingPathComponent:@"macos-settings.json"]);
    NSDictionary *original = snapshot(legacy);
    NSError *error = nil;
    unsigned beforeProgress = progressCalls;
    assert(HaloMigrateLegacySupportDirectory(legacy, destination, progress, NULL, &error));
    assert(!error && progressCalls > beforeProgress);
    assert([snapshot(legacy) isEqual:original]);
    HaloPreferences *migrated = [[HaloPreferences alloc] initWithSupportDirectory:destination];
    assert([migrated.dataPath isEqual:[destination URLByAppendingPathComponent:@"Game Data/import-a"].path]);
    assert([migrated.isoPath isEqual:[destination URLByAppendingPathComponent:@"Images/local.iso"].path]);
    assert(migrated.windowed && migrated.communityDownloadsEnabled);
    assert([[NSData dataWithContentsOfURL:[destination URLByAppendingPathComponent:@"config.toml"]] isEqual:controls]);
    assert([[NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:[destination URLByAppendingPathComponent:@"external-maps"].path error:nil] isEqual:valid.path]);
    assert([[NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:[destination URLByAppendingPathComponent:@"relative-import"].path error:nil] isEqual:@"Game Data/import-a"]);
    NSDictionary *record = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfURL:[destination URLByAppendingPathComponent:@"legacy-migration.json"]] options:0 error:nil];
    assert([record[@"completed"] boolValue] && [record[@"legacy_preserved"] boolValue]);
    assert([record[@"settings_rewrites"] count] == 2);
    NSDictionary *newSnapshot = snapshot(destination);
    assert(HaloMigrateLegacySupportDirectory(legacy, destination, NULL, NULL, &error));
    assert([snapshot(destination) isEqual:newSnapshot] && [snapshot(legacy) isEqual:original]);

    /* A conflicting map cannot redirect the copied selection to mixed bytes. */
    NSURL *conflicting = [test URLByAppendingPathComponent:@"migration/conflicts"];
    NSData *newMap = [@"existing user map" dataUsingEncoding:NSUTF8StringEncoding];
    NSURL *collision = [conflicting URLByAppendingPathComponent:@"Game Data/import-a/maps/ui.map"];
    writeFixture(newMap, collision);
    assert(HaloMigrateLegacySupportDirectory(legacy, conflicting, NULL, NULL, &error));
    assert([[NSData dataWithContentsOfURL:collision] isEqual:newMap]);
    assert([[[HaloPreferences alloc] initWithSupportDirectory:conflicting].dataPath isEqual:oldImport.path]);
    assert([snapshot(legacy) isEqual:original]);

    /* Newer destination preferences/controls win; external selections remain. */
    NSURL *existing = [test URLByAppendingPathComponent:@"migration/existing"];
    NSData *newSettings = [NSJSONSerialization dataWithJSONObject:@{@"data_path":valid.path, @"windowed":@NO} options:0 error:nil];
    writeFixture(newSettings, [existing URLByAppendingPathComponent:@"macos-settings.json"]);
    NSData *newControls = [@"new controls" dataUsingEncoding:NSUTF8StringEncoding];
    writeFixture(newControls, [existing URLByAppendingPathComponent:@"config.toml"]);
    assert(HaloMigrateLegacySupportDirectory(legacy, existing, NULL, NULL, &error));
    assert([[NSData dataWithContentsOfURL:[existing URLByAppendingPathComponent:@"macos-settings.json"]] isEqual:newSettings]);
    assert([[NSData dataWithContentsOfURL:[existing URLByAppendingPathComponent:@"config.toml"]] isEqual:newControls]);
    assert([[[HaloPreferences alloc] initWithSupportDirectory:existing].dataPath isEqual:valid.path]);

    NSURL *externalLegacy = [test URLByAppendingPathComponent:@"migration/external-legacy"];
    NSData *externalSettings = [NSJSONSerialization dataWithJSONObject:@{@"data_path":valid.path, @"iso_path":image.path} options:0 error:nil];
    writeFixture(externalSettings, [externalLegacy URLByAppendingPathComponent:@"macos-settings.json"]);
    NSURL *externalDestination = [test URLByAppendingPathComponent:@"migration/external-new"];
    assert(HaloMigrateLegacySupportDirectory(externalLegacy, externalDestination, NULL, NULL, &error));
    HaloPreferences *externalPreferences = [[HaloPreferences alloc] initWithSupportDirectory:externalDestination];
    assert([externalPreferences.dataPath isEqual:valid.path] && [externalPreferences.isoPath isEqual:image.path]);

    /* Never traverse a destination link to overwrite external files. */
    NSURL *linkedDestination = [test URLByAppendingPathComponent:@"migration/linked-new"];
    assert([NSFileManager.defaultManager createDirectoryAtURL:linkedDestination withIntermediateDirectories:YES attributes:nil error:nil]);
    assert([NSFileManager.defaultManager createSymbolicLinkAtURL:[linkedDestination URLByAppendingPathComponent:@"Game Data"] withDestinationURL:valid error:nil]);
    NSDictionary *externalBefore = snapshot(valid);
    assert(HaloMigrateLegacySupportDirectory(legacy, linkedDestination, NULL, NULL, &error));
    assert([snapshot(valid) isEqual:externalBefore]);
    assert([[[HaloPreferences alloc] initWithSupportDirectory:linkedDestination].dataPath isEqual:oldImport.path]);

    /* Failure leaves settings unpublished; a corrected source retries safely. */
    NSURL *brokenLegacy = [test URLByAppendingPathComponent:@"migration/invalid-legacy"], *retry = [test URLByAppendingPathComponent:@"migration/retry"];
    writeFixture([@"{broken json" dataUsingEncoding:NSUTF8StringEncoding], [brokenLegacy URLByAppendingPathComponent:@"macos-settings.json"]);
    writeFixture(controls, [brokenLegacy URLByAppendingPathComponent:@"config.toml"]);
    assert(!HaloMigrateLegacySupportDirectory(brokenLegacy, retry, NULL, NULL, &error));
    assert(error.localizedDescription.length);
    assert(![NSFileManager.defaultManager fileExistsAtPath:[retry URLByAppendingPathComponent:@"macos-settings.json"].path]);
    assert(![NSFileManager.defaultManager fileExistsAtPath:[retry URLByAppendingPathComponent:@"legacy-migration.json"].path]);
    assert([[NSData dataWithContentsOfURL:[retry URLByAppendingPathComponent:@"config.toml"]] isEqual:controls]);
    writeFixture(externalSettings, [brokenLegacy URLByAppendingPathComponent:@"macos-settings.json"]);
    assert(HaloMigrateLegacySupportDirectory(brokenLegacy, retry, NULL, NULL, &error));
    for (NSURL *file in [NSFileManager.defaultManager contentsOfDirectoryAtURL:retry includingPropertiesForKeys:nil options:0 error:nil])
        assert(![file.lastPathComponent hasPrefix:@".migration-"]);
    NSURL *invalidExisting = [test URLByAppendingPathComponent:@"migration/invalid-existing"];
    NSData *invalidSettings = [@"{invalid existing" dataUsingEncoding:NSUTF8StringEncoding];
    writeFixture(invalidSettings, [invalidExisting URLByAppendingPathComponent:@"macos-settings.json"]);
    assert(!HaloMigrateLegacySupportDirectory(legacy, invalidExisting, NULL, NULL, &error));
    assert([[NSData dataWithContentsOfURL:[invalidExisting URLByAppendingPathComponent:@"macos-settings.json"]] isEqual:invalidSettings]);
    assert(![NSFileManager.defaultManager fileExistsAtPath:[invalidExisting URLByAppendingPathComponent:@"legacy-migration.json"].path]);
    assert(!HaloSupportDirectoryNeedsMigration(test));
    const char *previousOverride = getenv("HALO_SAVE_ROOT");
    NSString *savedOverride = previousOverride ? @(previousOverride) : nil;
    setenv("HALO_SAVE_ROOT", test.fileSystemRepresentation, 1);
    NSURL *canonical = [NSURL fileURLWithPath:[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/Halo OG"] isDirectory:YES];
    assert(!HaloSupportDirectoryNeedsMigration(canonical));
    if (savedOverride) setenv("HALO_SAVE_ROOT", savedOverride.UTF8String, 1);
    else unsetenv("HALO_SAVE_ROOT");
    puts("Legacy support migration: hashes/bytes, managed path rewrites, links, conflicts, external selections, existing settings, failure/retry and original preservation passed");
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        assert(argc >= 2);
        NSURL *test = [NSURL fileURLWithPath:@(argv[1]) isDirectory:YES];
        NSURL *valid = [test URLByAppendingPathComponent:@"valid"];
        NSURL *support = [test URLByAppendingPathComponent:@"support"];
        NSError *error = nil;
        assert([HaloValidateGameData(valid, &error).path isEqualToString:valid.path]);
        assert([HaloValidateGameData([valid URLByAppendingPathComponent:@"maps"], &error).path isEqualToString:valid.path]);
        for (NSString *name in @[@"pc", @"mixed", @"missing", @"truncated"]) {
            error = nil;
            assert(!HaloValidateGameData([test URLByAppendingPathComponent:name], &error));
            assert(error.localizedDescription.length);
        }
        timerDownloadPreferenceFixtures(test, valid);
        arsenalCopyFixtures(test, valid);
        if (argc == 3) assert(HaloValidateGameData([NSURL fileURLWithPath:@(argv[2])], &error));
        HaloPreferences *preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert(preferences.communityDownloadsEnabled);
        assert(preferences.releaseChecksEnabled);
        assert(![NSFileManager.defaultManager fileExistsAtPath:[support URLByAppendingPathComponent:@"macos-settings.json"].path]);
        assert([preferences selectDataRoot:valid iso:nil error:&error]);
        NSURL *settings = [support URLByAppendingPathComponent:@"macos-settings.json"];
        NSMutableDictionary *saved = [[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfURL:settings]
            options:0 error:nil] mutableCopy];
        saved[@"future_setting"] = @"preserve me";
        assert([[NSJSONSerialization dataWithJSONObject:saved options:0 error:nil] writeToURL:settings atomically:YES]);
        NSURL *controls = [support URLByAppendingPathComponent:@"config.toml"];
        assert([@"[bindings]\nx = \"E\"\n" writeToURL:controls atomically:YES encoding:NSUTF8StringEncoding error:&error]);
        preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert([preferences setWindowed:YES error:&error]);
        // Older settings with no saved choice inherit the enabled default.
        assert(preferences.communityDownloadsEnabled);
        assert(preferences.releaseChecksEnabled);
        assert([preferences setReleaseChecksEnabled:NO error:&error]);
        assert(![[HaloPreferences alloc] initWithSupportDirectory:support].releaseChecksEnabled);
        assert([preferences setCommunityDownloadsEnabled:YES error:&error]);
        assert([[HaloPreferences alloc] initWithSupportDirectory:support].communityDownloadsEnabled);
        assert([preferences setCommunityDownloadsEnabled:NO error:&error]);
        assert(![[HaloPreferences alloc] initWithSupportDirectory:support].communityDownloadsEnabled);
        assert([preferences setWindowed:NO error:&error]);
        assert(![[HaloPreferences alloc] initWithSupportDirectory:support].communityDownloadsEnabled);
        assert([preferences setWindowed:YES error:&error]);
        assert(![[HaloPreferences alloc] initWithSupportDirectory:support].releaseChecksEnabled);
        assert([preferences setReleaseChecksEnabled:YES error:&error]);
        assert([[HaloPreferences alloc] initWithSupportDirectory:support].releaseChecksEnabled);
        NSData *before = [NSData dataWithContentsOfURL:settings];
        assert(![preferences selectDataRoot:[test URLByAppendingPathComponent:@"pc"] iso:nil error:&error]);
        assert([[NSData dataWithContentsOfURL:settings] isEqualToData:before]);
        assert([preferences.dataPath isEqualToString:valid.path]);
        assert(HaloGameDataCopySize(valid, &error) == 4096);
        NSURL *copied = HaloCopyGameData(valid, support, NULL, NULL, &error);
        assert(copied && ![copied.path isEqual:valid.path]);
        assert([[NSData dataWithContentsOfURL:[copied URLByAppendingPathComponent:@"maps/ui.map"]]
            isEqual:[NSData dataWithContentsOfURL:[valid URLByAppendingPathComponent:@"maps/ui.map"]]]);
        assert([preferences.dataPath isEqual:valid.path]);
        assert([NSFileManager.defaultManager fileExistsAtPath:[valid URLByAppendingPathComponent:@"maps/a10.map"].path]);
        NSData *unchanged = [NSData dataWithContentsOfURL:settings];
        assert(!HaloCopyGameData([test URLByAppendingPathComponent:@"pc"], support, NULL, NULL, &error));
        assert([[NSData dataWithContentsOfURL:settings] isEqual:unchanged]);
        NSURL *uppercase = [test URLByAppendingPathComponent:@"upper/MAPS"];
        assert([NSFileManager.defaultManager createDirectoryAtURL:uppercase withIntermediateDirectories:YES attributes:nil error:nil]);
        for (NSString *name in @[@"ui", @"a10"]) {
            NSData *bytes = [NSData dataWithContentsOfURL:[valid URLByAppendingPathComponent:[NSString stringWithFormat:@"maps/%@.map", name]]];
            assert([bytes writeToURL:[uppercase URLByAppendingPathComponent:[name.uppercaseString stringByAppendingString:@".MAP"]] atomically:YES]);
        }
        assert(HaloGameDataCopySize(uppercase, &error) == 4096);
        assert(HaloCopyGameData(uppercase, support, NULL, NULL, &error));
        NSURL *linkedRoot = [test URLByAppendingPathComponent:@"linked/maps"];
        assert([NSFileManager.defaultManager createDirectoryAtURL:linkedRoot withIntermediateDirectories:YES attributes:nil error:nil]);
        for (NSString *name in @[@"ui", @"a10"]) {
            assert(([NSFileManager.defaultManager createSymbolicLinkAtURL:[linkedRoot URLByAppendingPathComponent:[name stringByAppendingPathExtension:@"map"]]
                withDestinationURL:[valid URLByAppendingPathComponent:[NSString stringWithFormat:@"maps/%@.map", name]] error:nil]));
        }
        assert(HaloValidateGameData(linkedRoot, &error));
        assert(!HaloCopyGameData(linkedRoot, support, NULL, NULL, &error));
        assert([[NSData dataWithContentsOfURL:settings] isEqual:unchanged]);
        NSURL *image = [test URLByAppendingPathComponent:@"disc.iso"];
        NSURL *nearby = [test URLByAppendingPathComponent:@"adjacent" isDirectory:YES];
        assert([NSFileManager.defaultManager createDirectoryAtURL:nearby withIntermediateDirectories:YES attributes:nil error:&error]);
        assert(!HaloFindAdjacentDiscImage(nearby, &error) && !error);
        NSURL *unrelated = [nearby URLByAppendingPathComponent:@"other.iso"];
        assert([@"not an Xbox disc" writeToURL:unrelated atomically:YES encoding:NSUTF8StringEncoding error:&error]);
        assert(!HaloFindAdjacentDiscImage(nearby, &error) && error);
        NSURL *autoImage = [nearby URLByAppendingPathComponent:@"Halo.XISO"];
        assert([NSFileManager.defaultManager copyItemAtURL:image toURL:autoImage error:&error]);
        assert([HaloFindAdjacentDiscImage(nearby, &error) isEqual:autoImage] && !error);
        NSURL *duplicate = [nearby URLByAppendingPathComponent:@"second.iso"];
        assert([NSFileManager.defaultManager copyItemAtURL:image toURL:duplicate error:&error]);
        assert(!HaloFindAdjacentDiscImage(nearby, &error) && error);
        assert([NSFileManager.defaultManager removeItemAtURL:duplicate error:&error]);
        NSURL *link = [nearby URLByAppendingPathComponent:@"linked.iso"];
        assert([NSFileManager.defaultManager createSymbolicLinkAtURL:link withDestinationURL:image error:&error]);
        assert([HaloFindAdjacentDiscImage(nearby, &error) isEqual:autoImage] && !error);
        assert([[NSData dataWithContentsOfURL:autoImage] isEqualToData:[NSData dataWithContentsOfURL:image]]);
        assert([[NSString stringWithContentsOfURL:unrelated encoding:NSUTF8StringEncoding error:&error] isEqual:@"not an Xbox disc"]);
        NSURL *imported = HaloImportDiscImage(image, support, progress, NULL, &error);
        assert(imported && progressCalls == 2);
        assert([preferences.dataPath isEqualToString:valid.path]);
        assert([[NSData dataWithContentsOfURL:[imported URLByAppendingPathComponent:@"maps/ui.map"]]
            isEqualToData:[NSData dataWithContentsOfURL:[valid URLByAppendingPathComponent:@"maps/ui.map"]]]);
        assert([preferences selectDataRoot:imported iso:image error:&error]);
        before = [NSData dataWithContentsOfURL:settings];
        NSURL *imports = [support URLByAppendingPathComponent:@"Game Data"];
        NSUInteger count = [NSFileManager.defaultManager contentsOfDirectoryAtURL:imports
            includingPropertiesForKeys:nil options:0 error:nil].count;
        for (NSString *name in @[@"broken.iso", @"pc.iso"]) {
            assert(!HaloImportDiscImage([test URLByAppendingPathComponent:name], support, NULL, NULL, &error));
            assert([NSFileManager.defaultManager contentsOfDirectoryAtURL:imports
                includingPropertiesForKeys:nil options:0 error:nil].count == count);
            assert([[NSData dataWithContentsOfURL:settings] isEqualToData:before]);
        }
        preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert(preferences.windowed && [preferences.isoPath isEqualToString:image.path]);
        assert([preferences.dataPath isEqualToString:imported.path]);
        saved = [NSJSONSerialization JSONObjectWithData:before options:0 error:nil];
        assert([saved[@"future_setting"] isEqualToString:@"preserve me"]);
        assert([[NSString stringWithContentsOfURL:controls encoding:NSUTF8StringEncoding error:nil]
            isEqualToString:@"[bindings]\nx = \"E\"\n"]);
        NSURL *blocked = [test URLByAppendingPathComponent:@"not-a-directory"];
        assert([@"file" writeToURL:blocked atomically:YES encoding:NSUTF8StringEncoding error:&error]);
        HaloPreferences *unwritable = [[HaloPreferences alloc] initWithSupportDirectory:blocked];
        assert(![unwritable selectDataRoot:valid iso:nil error:&error]);
        assert(!unwritable.dataPath);
        NSString *key = [[NSMutableData dataWithLength:32] base64EncodedStringWithOptions:0];
        assert(HaloUpdateConfigurationIsValid(@{@"SUFeedURL":@"https://example.com/appcast.xml", @"SUPublicEDKey":key}));
        for (NSString *url in @[@"http://example.com/feed.xml", @"https://user:pass@example.com/feed.xml", @"file:///feed.xml"])
            assert(!HaloUpdateConfigurationIsValid(@{@"SUFeedURL":url, @"SUPublicEDKey":key}));
        assert(!HaloUpdateConfigurationIsValid(@{}));
        assert(!HaloUpdateConfigurationIsValid(@{@"SUFeedURL":@"https://example.com/feed.xml", @"SUPublicEDKey":@"invalid"}));
        migrationFixtures(test, valid, image);
        puts("Map validation, XISO import, failed-import rollback, persistent preferences and update configuration passed");
    }
    return 0;
}
