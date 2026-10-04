#ifndef HALO_COMMUNITY_MAPOG_H
#define HALO_COMMUNITY_MAPOG_H
#include <stddef.h>
/* HOGMAP2: 48-byte header + exactly one zlib stream. The caller supplies a
   fresh output in an owned private directory. Returns 0/-1; never overwrites,
   removes only its own failed output, and verifies bounded size + inner SHA. */
int community_mapog_expand(const char *source, const char *destination, char *error, size_t error_size);
#endif
