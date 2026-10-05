/* Native test library support; production keeps d3d8_gl.c's text allocator. */
#include "xgpu_shader_standalone.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
struct xgpu_capabilities xgpu_capabilities = {0, "300 es"};
void xgpu_text_append(struct xgpu_text *text, const char *format, ...) {
    va_list args, copy;
    va_start(args, format); va_copy(copy, args);
    int count = vsnprintf(NULL, 0, format, copy);
    va_end(copy);
    if (count < 0) abort();
    unsigned long required = text->length + (unsigned long)count + 1;
    if (required > text->capacity) {
        unsigned long capacity = required * 2;
        char *buffer = realloc(text->buffer, capacity);
        if (!buffer) abort();
        text->buffer = buffer; text->capacity = capacity;
    }
    vsnprintf(text->buffer + text->length, (size_t)count + 1, format, args);
    va_end(args); text->length += (unsigned long)count;
}
