/*
PORT_CONFIG.H

The native ports' settings, read from config.toml (port_config.c): next to
the executable on the desktop, in the data folder (the one holding maps/)
on Android. A missing file is written with the defaults. Each setting can
also be set for one run with its HALO_* environment variable when it has one, which wins
over the file (the tools and the Android app pass settings that way).

Settings are named "section.key", as in the file: "display.vsync".
*/

#ifndef PORT_CONFIG_H
#define PORT_CONFIG_H

#include <stddef.h>

int config_boolean(const char *name);
/* One optional replacement set: HUD, font glyphs and faithful menu titles.
 * Retains the legacy HUD preference so existing choices survive the UI rename.
 * Snapshots the launch choice; saving the option applies on relaunch. */
int asset_quality_upres(void);
long config_integer(const char *name);
double config_real(const char *name);
/* never NULL; "" when unset */
const char *config_string(const char *name);
enum config_update_type
{
    _config_update_number,
    _config_update_string
};
struct config_update
{
    const char *name;
    enum config_update_type type;
    double number;
    const char *string;
};
/* Atomically save a mixed batch of registered numeric/string settings, then
 * apply the cached values only after persistence succeeds. Numeric types follow
 * the registration; strings must be non-NULL and valid TOML string contents.
 * Previously returned string pointers remain valid for this process lifetime. */
int config_write_values(const struct config_update *updates, unsigned count);
/* Refresh one registered, file-only string after another application surface
 * saves it. Does not write defaults or refresh any other cached setting. */
int config_refresh_string(const char *name);
/* saves a boolean token into config.toml, preserving other text, and applies
it to this session only after a successful write; 1 on success */
int config_write_boolean(const char *name, int value);
/* Save registered boolean, integer and real settings as one atomic file update,
then apply all values to this session. Boolean values must be 0 or 1; numeric
values must be finite and integers exact. Returns 0 without applying any value
if validation or persistence fails. Other keys and comments are preserved. */
int config_write_numbers(const char *const *names, const double *values, unsigned count);

/* Shared OpenCE callers use these alongside native batch updates. */
int config_write(const char *name, const char *value);
int config_text(const char *name, char *text, size_t size);
void config_folder(char *path, size_t size);
char *config_file_read(const char *path, size_t *size);
int config_default(const char *name, char *text, size_t size);
unsigned long config_changes(void);

#endif
