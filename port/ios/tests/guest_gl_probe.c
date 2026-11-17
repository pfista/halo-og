/* Calls the generated iOS GL wrapper through its ordinary lookup interface. */
typedef void (*gl_function)(void);
extern gl_function guest_gl_get_proc_address(const char *name);
extern unsigned guest_test(unsigned value);

unsigned guest_probe(unsigned value) {
    typedef void (*shader_source_fn)(unsigned, int, const char *const *, const int *);
    shader_source_fn shader_source = (shader_source_fn)guest_gl_get_proc_address("glShaderSource");
    char stack_text[] = "stack";
    const char *sources[] = {"constant", stack_text, (const char *)0};
    if (!shader_source) return 106;
    shader_source(value, 3, sources, (const int *)0);
    return guest_test(value);
}
