#ifndef HALO_DIRECTORY_RETRY_AFTER_H
#define HALO_DIRECTORY_RETRY_AFTER_H

/* The directory emits delta-seconds. Reject ambiguous/malformed values and
   cap server-directed waits to five minutes without overflowing integers. */
#define HALO_DIRECTORY_RETRY_AFTER_MAX_SECONDS 300
static inline int halo_directory_retry_after_seconds(const char *value)
{
    int seconds = 0;
    if (!value) return 0;
    while (*value == ' ' || *value == '\t') value++;
    if (*value < '0' || *value > '9') return 0;
    do {
        int digit = *value++ - '0';
        if (seconds > (HALO_DIRECTORY_RETRY_AFTER_MAX_SECONDS - digit) / 10)
            seconds = HALO_DIRECTORY_RETRY_AFTER_MAX_SECONDS;
        else seconds = seconds * 10 + digit;
    } while (*value >= '0' && *value <= '9');
    while (*value == ' ' || *value == '\t') value++;
    return *value ? 0 : seconds;
}

#endif
