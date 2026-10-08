/* Saved renderer choice is shared with the game's display.renderer setting.
 * Keep each host/guest pair immutable; switch processes before AppKit/SDL.
 */
#include "host_renderer.h"
#include "../../third_party/tomlc17/tomlc17.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define CONFIG_LIMIT (1024u * 1024u)
static char bundle_executable[4096], bundle_resources[4096];

static void explain(char *error, size_t capacity, const char *message) {
    if (error && capacity) snprintf(error, capacity, "%s", message);
}
static int path_join(char *path, size_t capacity, const char *root, const char *leaf) {
    int length = snprintf(path, capacity, "%s/%s", root, leaf);
    return length >= 0 && (size_t)length < capacity;
}
static int sibling(char *path, size_t capacity, const char *name) {
    const char *slash = strrchr(bundle_executable, '/');
    if (!slash) return 0;
    int length = snprintf(path, capacity, "%.*s/%s", (int)(slash-bundle_executable), bundle_executable, name);
    return length >= 0 && (size_t)length < capacity;
}
void host_renderer_set_paths(const char *executable, const char *resources) {
    snprintf(bundle_executable, sizeof(bundle_executable), "%s", executable);
    snprintf(bundle_resources, sizeof(bundle_resources), "%s", resources);
}
int host_renderer_active(void) {
#if defined(HALO_MACOS_NATIVE_METAL)
    return HOST_RENDERER_METAL;
#else
    return HOST_RENDERER_ANGLE;
#endif
}
int host_renderer_can_choose(void) {
    char path[4096];
    return sibling(path, sizeof(path), "halo") && !access(path, X_OK) &&
        sibling(path, sizeof(path), "halo-metal") && !access(path, X_OK) &&
        path_join(path, sizeof(path), bundle_resources, "halo_guest.elf") && !access(path, R_OK) &&
        path_join(path, sizeof(path), bundle_resources, "halo_guest-metal.elf") && !access(path, R_OK);
}
int host_renderer_default_guest(char *path, size_t capacity) {
#if defined(HALO_MACOS_NATIVE_METAL)
    if (path_join(path, capacity, bundle_resources, "halo_guest-metal.elf") && !access(path, R_OK)) return 1;
#endif
    return path_join(path, capacity, bundle_resources, "halo_guest.elf");
}
void host_renderer_dispatch_native(int argc, char **argv, char *note, size_t capacity) {
    char executable[4096], image[4096];
    if (!sibling(executable, sizeof(executable), "halo-metal") || access(executable, X_OK) ||
        !path_join(image, sizeof(image), bundle_resources, "halo_guest-metal.elf") || access(image, R_OK)) {
        explain(note, capacity, "Native Metal is unavailable in this build; using ANGLE. The saved renderer was not changed.");
        return;
    }
    char **arguments = calloc((size_t)argc+1, sizeof(*arguments));
    if (!arguments) {
        explain(note, capacity, "Could not prepare the native renderer launch; using ANGLE.");
        return;
    }
    arguments[0] = executable;
    for (int index = 1; index < argc; index++) arguments[index] = argv[index];
    fprintf(stderr, "Renderer dispatch: Native Metal (%s); restart-based selection\n", executable);
    execv(executable, arguments);
    free(arguments);
    explain(note, capacity, "Could not launch Native Metal; using ANGLE. The saved renderer was not changed.");
}

static char *read_text(const char *path, size_t *size, int *missing) {
    struct stat attributes;
    *size = 0; *missing = 0;
    if (lstat(path, &attributes)) { *missing = errno == ENOENT; return NULL; }
    if (!S_ISREG(attributes.st_mode) || attributes.st_size < 0 || attributes.st_size > CONFIG_LIMIT) return NULL;
    FILE *file = fopen(path, "rb");
    if (!file) return NULL;
    size_t length = (size_t)attributes.st_size;
    char *text = malloc(length+1);
    int okay = text && fread(text, 1, length, file) == length && fgetc(file) == EOF && !ferror(file);
    if (fclose(file)) okay = 0;
    if (!okay || memchr(text, 0, length)) { free(text); return NULL; }
    text[length] = 0; *size = length; return text;
}
int host_renderer_read(const char *support, char *error, size_t capacity) {
    char path[4096]; size_t size; int missing;
    explain(error, capacity, "");
    if (!path_join(path, sizeof(path), support, "config.toml")) {
        explain(error, capacity, "The settings path is too long; using ANGLE."); return HOST_RENDERER_ANGLE;
    }
    char *text = read_text(path, &size, &missing);
    if (!text) {
        if (!missing) explain(error, capacity, "Could not read config.toml; using ANGLE.");
        return missing ? HOST_RENDERER_METAL : HOST_RENDERER_ANGLE;
    }
    toml_result_t parsed = toml_parse(text, (int)size);
    int renderer = HOST_RENDERER_ANGLE;
    if (!parsed.ok) explain(error, capacity, "config.toml is not valid TOML; using ANGLE.");
    else {
        toml_datum_t table = toml_get(parsed.toptab, "display");
        toml_datum_t value = toml_seek(parsed.toptab, "display.renderer");
        if (table.type != TOML_UNKNOWN && table.type != TOML_TABLE)
            explain(error, capacity, "display must be a TOML table; using ANGLE.");
        else if (value.type == TOML_UNKNOWN ||
                 (value.type == TOML_STRING && !strcmp(value.u.s, "metal"))) renderer = HOST_RENDERER_METAL;
        else if (value.type != TOML_UNKNOWN && !(value.type == TOML_STRING && !strcmp(value.u.s, "angle")))
            explain(error, capacity, "display.renderer must be \"angle\" or \"metal\"; using ANGLE.");
    }
    toml_free(parsed); free(text); return renderer;
}
static const char *source_line(const char *text, int number) {
    if (number < 1) return NULL;
    const char *line = text;
    for (int current = 1; current < number; current++) {
        line = strchr(line, '\n'); if (!line) return NULL; line++;
    }
    return line;
}
static const char *source_token(const char *text, toml_datum_t value) {
    const char *line = source_line(text, value.lineno);
    if (!line || value.colno < 1 || (size_t)(value.colno-1) > strcspn(line, "\r\n")) return NULL;
    const char *token = line+value.colno-1;
    if (value.type == TOML_STRING) {
        /* tomlc17 coordinates point at string content, after its delimiter
         * and the optional trimmed opening newline for multiline strings. */
        const char *opening = token;
        if (opening > text && opening[-1] == '\n') {
            opening--;
            if (opening > text && opening[-1] == '\r') opening--;
        }
        if (opening-text >= 3 && (opening[-1] == '\'' || opening[-1] == '"') &&
            opening[-1] == opening[-2] && opening[-1] == opening[-3]) return opening-3;
        if (token > text && (token[-1] == '\'' || token[-1] == '"')) return token-1;
        return NULL;
    }
    return token;
}
/* Parsed source coordinates locate the value. Scan only its quoted token,
 * respecting escaped quotes and all TOML basic/literal/multiline strings. */
static size_t string_extent(const char *token) {
    char quote = *token;
    if (quote != '\'' && quote != '"') return 0;
    int triple = token[1] == quote && token[2] == quote;
    const char *cursor = token+(triple ? 3 : 1);
    while (*cursor) {
        if (quote == '"' && *cursor == '\\') { if (!cursor[1]) return 0; cursor += 2; continue; }
        if (*cursor == quote) {
            if (!triple) return (size_t)(cursor+1-token);
            if (cursor[1] == quote && cursor[2] == quote) {
                cursor += 3;
                /* Four/five closing quotes include one/two literal quotes. */
                for (int extra = 0; extra < 2 && *cursor == quote; extra++) cursor++;
                return (size_t)(cursor-token);
            }
        }
        cursor++;
    }
    return 0;
}
static char *replace(const char *text, size_t size, size_t offset, size_t length, const char *value) {
    size_t added = strlen(value);
    if (offset > size || length > size-offset || added > CONFIG_LIMIT || size-length > CONFIG_LIMIT-added) return NULL;
    char *updated = malloc(size-length+added+1);
    if (!updated) return NULL;
    memcpy(updated, text, offset); memcpy(updated+offset, value, added);
    memcpy(updated+offset+added, text+offset+length, size-offset-length);
    updated[size-length+added] = 0; return updated;
}
static char *edit_renderer(const char *text, size_t size, int renderer) {
    const char *word = renderer == HOST_RENDERER_METAL ? "\"metal\"" : "\"angle\"";
    toml_result_t parsed = toml_parse(text, (int)size);
    char *updated = NULL;
    if (parsed.ok) {
        toml_datum_t value = toml_seek(parsed.toptab, "display.renderer");
        if (value.type == TOML_STRING) {
            const char *token = source_token(text, value);
            size_t length = token ? string_extent(token) : 0;
            if (length) updated = replace(text, size, (size_t)(token-text), length, word);
        } else if (value.type == TOML_UNKNOWN) {
            toml_datum_t table = toml_get(parsed.toptab, "display");
            const char *token = source_token(text, table);
            char addition[96];
            if (table.type == TOML_UNKNOWN) {
                snprintf(addition, sizeof(addition), "%s[display]\nrenderer = %s\n", size && text[size-1] != '\n' ? "\n" : "", word);
                updated = replace(text, size, size, 0, addition);
            } else if (table.type == TOML_TABLE && token && *token == '{') {
                snprintf(addition, sizeof(addition), " renderer = %s%s", word, table.u.tab.size ? "," : " ");
                updated = replace(text, size, (size_t)(token+1-text), 0, addition);
            } else if (table.type == TOML_TABLE && (table.flag & TOML_FLAG_STDEXPR) &&
                (table.flag & TOML_FLAG_EXPLICIT)) {
                const char *line = source_line(text, table.lineno);
                const char *end = line ? strchr(line, '\n') : NULL;
                snprintf(addition, sizeof(addition), "%srenderer = %s\n", end ? "" : "\n", word);
                if (line) updated = replace(text, size, end ? (size_t)(end+1-text) : size, 0, addition);
            } else if (table.type == TOML_TABLE) {
                snprintf(addition, sizeof(addition), "display.renderer = %s\n", word);
                updated = replace(text, size, 0, 0, addition);
            }
        }
    }
    toml_free(parsed);
    if (updated) {
        toml_result_t check = toml_parse(updated, (int)strlen(updated));
        toml_datum_t value = check.ok ? toml_seek(check.toptab, "display.renderer") : (toml_datum_t){0};
        int okay = value.type == TOML_STRING && !strcmp(value.u.s, renderer == HOST_RENDERER_METAL ? "metal" : "angle");
        toml_free(check);
        if (!okay) { free(updated); updated = NULL; }
    }
    return updated;
}
static int atomic_write(const char *path, const char *before, size_t size, int missing, const char *updated) {
    struct stat attributes;
    if (!missing && (lstat(path, &attributes) || !S_ISREG(attributes.st_mode) ||
        !(attributes.st_mode & 0222) || access(path, W_OK))) return 0;
    char temporary[4112];
    int length = snprintf(temporary, sizeof(temporary), "%s.XXXXXX", path);
    if (length < 0 || (size_t)length >= sizeof(temporary)) return 0;
    int descriptor = mkstemp(temporary);
    if (descriptor < 0) return 0;
    FILE *file = fdopen(descriptor, "wb"); int okay = file != NULL;
    if (file) {
        size_t length = strlen(updated);
        okay = (missing || !fchmod(descriptor, attributes.st_mode & 0777)) &&
            fwrite(updated, 1, length, file) == length && !fflush(file) && !fsync(descriptor);
        if (fclose(file)) okay = 0;
    } else close(descriptor);
    if (okay) {
        /* Preserve a concurrent external edit rather than silently overwriting
         * it. Settings can be retried after refreshing the latest file. */
        size_t current_size; int current_missing;
        char *current = read_text(path, &current_size, &current_missing);
        okay = missing ? current_missing : current && current_size == size && !memcmp(current, before, size);
        free(current);
    }
    if (okay) okay = !rename(temporary, path);
    if (!okay) unlink(temporary);
    return okay;
}
int host_renderer_write(const char *support, int renderer, char *error, size_t capacity) {
    char path[4096]; size_t size; int missing;
    explain(error, capacity, "");
    if ((renderer != HOST_RENDERER_ANGLE && renderer != HOST_RENDERER_METAL) ||
        !path_join(path, sizeof(path), support, "config.toml")) {
        explain(error, capacity, "The renderer choice or settings path is invalid."); return 0;
    }
    char *text = read_text(path, &size, &missing);
    if (!text && missing) text = calloc(1, 1);
    if (!text) { explain(error, capacity, "Could not read config.toml. Your settings were not changed."); return 0; }
    char *updated = edit_renderer(text, size, renderer);
    int okay = updated && atomic_write(path, text, size, missing, updated);
    free(updated); free(text);
    if (!okay) explain(error, capacity, "Could not save the renderer to config.toml. Check Advanced Settings and file permissions; your settings were not changed.");
    return okay;
}
