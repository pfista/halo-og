/* A query buffer can contain the new pixels before its fence is signaled.
   The CPU must publish only completed counts and their matching generations. */
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef unsigned GLuint, GLenum, DWORD, UINT;
typedef uint64_t ULONGLONG;
typedef int HRESULT;
typedef unsigned *GLsync;
#define WINAPI
enum { FALSE, TRUE, S_OK=0, D3DERR_TESTINCOMPLETE=1 };
enum { VISIBILITY_QUERY, GL_QUERY_BUFFER, GL_QUERY_RESULT, GL_QUERY_RESULT_AVAILABLE,
    GL_SYNC_GPU_COMMANDS_COMPLETE, GL_TIMEOUT_EXPIRED, GL_WAIT_FAILED, GL_CONDITION_SATISFIED };
enum { VISIBILITY_TEST_SLOTS=4096 };
#include "config.inc"

static struct {
    GLuint queries[VISIBILITY_TEST_SLOTS+1], visibility_results_buffer;
    int query_pending[VISIBILITY_TEST_SLOTS], gl_ready, visibility_test_active;
    float query_area[VISIBILITY_TEST_SLOTS];
    volatile GLuint *visibility_results;
    struct flare_query_batch flare_batches[FLARE_BATCH_COUNT];
    unsigned flare_read_bank, flare_write_bank, flare_sealed_banks;
    unsigned long long flare_tests_ended[LENS_FLARE_OCCLUSION_SLOT_COUNT];
    unsigned long long flare_tests_counted[LENS_FLARE_OCCLUSION_SLOT_COUNT];
    GLuint flare_pixels[LENS_FLARE_OCCLUSION_SLOT_COUNT];
} device;
static float target_scale[2]={1,1};
static GLuint words[VISIBILITY_TEST_SLOTS+FLARE_BATCH_COUNT*FLARE_BATCH_CAPACITY];
static GLuint active, samples[VISIBILITY_TEST_SLOTS+2], next_samples, bound_buffer, ready;
static unsigned fences[16], fences_used;
static void glBeginQuery(GLenum type,GLuint query) {
    assert(type==VISIBILITY_QUERY && query && !active);
    active=query;
}
static void glEndQuery(GLenum type) {
    assert(type==VISIBILITY_QUERY && active);
    samples[active]=next_samples;
    active=0;
}
static void glBindBuffer(GLenum type,GLuint buffer) {
    assert(type==GL_QUERY_BUFFER); bound_buffer=buffer;
}
static void glGetQueryObjectuiv(GLuint query,GLenum type,GLuint *result) {
    if (bound_buffer) {
        size_t word=(size_t)result/sizeof(GLuint);
        assert(type==GL_QUERY_RESULT && word<sizeof(words)/sizeof(*words));
        words[word]=samples[query];
    } else if (type==GL_QUERY_RESULT_AVAILABLE) {
        *result=ready;
    } else {
        assert(type==GL_QUERY_RESULT && ready);
        *result=samples[query];
    }
}
static GLsync glFenceSync(GLenum condition,unsigned flags) {
    assert(condition==GL_SYNC_GPU_COMMANDS_COMPLETE && !flags && fences_used<16);
    return &fences[fences_used++];
}
static GLenum glClientWaitSync(GLsync fence,unsigned flags,uint64_t timeout) {
    assert(!flags && !timeout);
    return *fence ? GL_CONDITION_SATISFIED : GL_TIMEOUT_EXPIRED;
}
static void glDeleteSync(GLsync fence) { assert(*fence); }
static void glFinish(void) { assert(0 && "the normal readback path must not stall"); }
#include "under_test.inc"

static void submit(unsigned samples_to_draw) {
    next_samples=samples_to_draw;
    D3DDevice_BeginVisibilityTest();
    assert(D3DDevice_EndVisibilityTest(0)==S_OK);
}
static void check(unsigned count,unsigned generation) {
    UINT value=1234;
    assert(D3DDevice_GetVisibilityTestResult(0,&value,NULL)==S_OK && value==count);
    assert(xgpu_visibility_test_counted(0)==generation);
}
int main(int argc,char **argv) {
    assert(argc==2); device.gl_ready=1; device.visibility_results_buffer=1;
    for(unsigned i=0;i<=VISIBILITY_TEST_SLOTS;i++) device.queries[i]=i+1;
    if (!strcmp(argv[1],"direct")) {
        UINT value;
        target_scale[0]=2; submit(20);
        assert(D3DDevice_GetVisibilityTestResult(0,&value,NULL)==D3DERR_TESTINCOMPLETE);
        assert(xgpu_visibility_test_counted(0)==0);
        ready=1; check(10,1); submit(0); check(0,2);
        return 0;
    }
    assert(!strcmp(argv[1],"buffer"));
    device.visibility_results=words;
    target_scale[0]=2; target_scale[1]=3;
    submit(120); flare_query_buffer_seal();
    target_scale[0]=1; target_scale[1]=1;
    submit(33); flare_query_buffer_seal();
    submit(0); flare_query_buffer_seal();
    /* Dependent submissions while the ring is full still advance ownership. */
    for(unsigned i=0;i<20;i++) { submit(99); flare_query_buffer_seal(); }
    assert(xgpu_visibility_tests_ended(0)==23 && fences_used==3);
    fences[1]=1; flare_query_buffer_collect(); check(0,0);
    fences[0]=1; flare_query_buffer_collect(); check(33,2);
    fences[2]=1; flare_query_buffer_collect(); check(0,3);
    target_scale[0]=3; target_scale[1]=4; submit(240); flare_query_buffer_seal();
    target_scale[0]=target_scale[1]=1; check(0,3);
    fences[3]=1; flare_query_buffer_collect(); check(20,24);
    return 0;
}
