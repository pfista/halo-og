// Independent ANGLE execution of the existing generated GLES texture stages.
// Uses a cleared float pbuffer target; no game assets, window or port changes.
#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <cmath>
#include <cstdio>
#include <vector>

static void check(bool value, NSString *reason) {
    if(!value) { fprintf(stderr,"pixel-glsl: %s\n",reason.UTF8String);exit(1); }
}
static NSData *read(NSString *path) {
    NSData *d=[NSData dataWithContentsOfFile:path];check(d!=nil,path);return d;
}
static NSString *hash(NSData *data) {
    check(data.length<=UINT32_MAX,@"Input too large");
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH];CC_SHA256(data.bytes,(CC_LONG)data.length,bytes);
    NSMutableString *s=[NSMutableString new];for(auto b:bytes)[s appendFormat:@"%02x",b];return s;
}
static GLuint shader(GLenum kind, NSString *source) {
    GLuint result=glCreateShader(kind);const char *s=source.UTF8String;
    glShaderSource(result,1,&s,nullptr);glCompileShader(result);
    GLint ok=0;glGetShaderiv(result,GL_COMPILE_STATUS,&ok);
    if(!ok) { char log[16384];glGetShaderInfoLog(result,sizeof(log),nullptr,log);check(false,@(log)); }
    return result;
}
static void uniform(GLuint program, NSString *name, NSArray *values) {
    std::vector<GLfloat> flat;
    for(id v:values) {
        if([v isKindOfClass:NSArray.class])for(NSNumber *n:v)flat.push_back(n.floatValue);
        else flat.push_back([v floatValue]);
    }
    GLint location=glGetUniformLocation(program,name.UTF8String);
    if(flat.size()==1)glUniform1fv(location,1,flat.data());
    else { check(flat.size()%4==0,@"Invalid vector uniform");glUniform4fv(location,(GLsizei)flat.size()/4,flat.data()); }
}
static std::vector<uint8_t> pixels(NSArray *values, size_t size) {
    std::vector<uint8_t> result;
    for(NSNumber *v:values) { check(v.doubleValue==v.unsignedCharValue,@"Invalid texture byte");result.push_back(v.unsignedCharValue); }
    check(result.size()==size,@"Texture byte count");return result;
}
static NSString *vertexSource=@"#version 300 es\nprecision highp float;\n"
    "uniform vec4 d0,d1,b0,b1,t[4];uniform float fog;\n"
    "out vec4 xD0,xD1,xB0,xB1,xT0,xT1,xT2,xT3;out float xFog;\n"
    "void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);"
    "gl_Position=vec4(p*2.0-1.0,0.5,1.0);xD0=d0;xD1=d1;xB0=b0;xB1=b1;"
    "xT0=t[0];xT1=t[1];xT2=t[2];xT3=t[3];xFog=fog;}\n";

int main(int argc,const char **argv) { @autoreleasepool {
    check(argc==2,@"Usage: pixel_glsl_validate manifest.json");
    NSString *path=@(argv[1]),*root=path.stringByDeletingLastPathComponent;
    NSData *manifestData=read(path);NSDictionary *m=[NSJSONSerialization JSONObjectWithData:manifestData options:0 error:nil];
    check([m isKindOfClass:NSDictionary.class],@"Invalid manifest");
    NSString *runnerHash=hash(read(@(argv[0])));check([runnerHash isEqual:m[@"runner_sha256"]],@"Runner SHA mismatch");
    PFNEGLGETPLATFORMDISPLAYEXTPROC getDisplay=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    check(getDisplay!=nullptr,@"Missing ANGLE display API");
    EGLint displayAttributes[]={0x3203,0x3489,EGL_NONE}; // Explicit ANGLE Metal backend.
    EGLDisplay display=getDisplay(0x3202,nullptr,displayAttributes);
    check(eglInitialize(display,nullptr,nullptr)&&eglBindAPI(EGL_OPENGL_ES_API),@"ANGLE initialization");
    EGLint configAttributes[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    EGLConfig config;EGLint count;check(eglChooseConfig(display,configAttributes,&config,1,&count)&&count,@"ANGLE config");
    EGLint contextAttributes[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,contextAttributes);
    EGLint surfaceAttributes[]={EGL_WIDTH,4,EGL_HEIGHT,4,EGL_NONE};
    EGLSurface surface=eglCreatePbufferSurface(display,config,surfaceAttributes);
    check(eglMakeCurrent(display,surface,surface,context),@"ANGLE context");glViewport(0,0,4,4);
    GLuint color,fbo;glGenTextures(1,&color);glBindTexture(GL_TEXTURE_2D,color);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA32F,4,4,0,GL_RGBA,GL_FLOAT,nullptr);
    glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,color,0);
    check(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,@"RGBA32F target unsupported");
    NSMutableDictionary *programs=[NSMutableDictionary new];GLuint vs=shader(GL_VERTEX_SHADER,vertexSource);
    unsigned passed=0;float maxError=0;
    for(NSDictionary *f in m[@"tests"]) {
        NSString *name=f[@"shader"];NSNumber *cached=programs[name];GLuint p=cached.unsignedIntValue;
        if(!cached) {
            NSData *data=read([root stringByAppendingPathComponent:name]);check([hash(data) isEqual:m[@"shader_sha256"][name]],@"Shader SHA mismatch");
            GLuint fs=shader(GL_FRAGMENT_SHADER,[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]);
            p=glCreateProgram();glAttachShader(p,vs);glAttachShader(p,fs);glLinkProgram(p);GLint ok=0;
            glGetProgramiv(p,GL_LINK_STATUS,&ok);check(ok,@"GLSL link failure");glDeleteShader(fs);programs[name]=@(p);
        }
        glUseProgram(p);NSDictionary *in=f[@"inputs"],*u=f[@"uniforms"];
        for(NSString *n in @[@"d0",@"d1",@"b0",@"b1",@"t"])uniform(p,n,in[n]);
        uniform(p,@"fog",@[in[@"fog"]]);
        NSDictionary *names=@{@"c0":@"ps_c0",@"c1":@"ps_c1",@"final_c0":@"ps_final_c0",@"final_c1":@"ps_final_c1"};
        for(NSString *n in u)uniform(p,names[n]?:n,[u[n] isKindOfClass:NSArray.class]?u[n]:@[u[n]]);
        std::vector<GLuint> resources;
        for(int slot=0;slot<4;slot++) {
            NSDictionary *t=f[@"textures"][slot];int kind=[t[@"kind"] intValue];if(!kind)continue;
            GLenum target=kind==3?GL_TEXTURE_CUBE_MAP:kind==2?GL_TEXTURE_3D:GL_TEXTURE_2D;
            GLsizei width=[t[@"width"] intValue],height=[t[@"height"] intValue],depth=kind==2?[t[@"depth"] intValue]:1;
            GLuint texture;glGenTextures(1,&texture);resources.push_back(texture);
            glActiveTexture(GL_TEXTURE0+slot);glBindTexture(target,texture);
            check(width>0&&height>0&&depth>0,@"Texture dimensions");
            if(kind==3) {
                check([t[@"faces"] count]==6,@"Cube face count");
                for(int face=0;face<6;face++) { auto bytes=pixels(t[@"faces"][face],(size_t)width*height*4);
                    glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X+face,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,bytes.data()); }
            } else {
                auto bytes=pixels(t[@"rgba"],(size_t)width*height*depth*4);
                if(kind==2)glTexImage3D(target,0,GL_RGBA8,width,height,depth,0,GL_RGBA,GL_UNSIGNED_BYTE,bytes.data());
                else glTexImage2D(target,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,bytes.data());
            }
            glTexParameteri(target,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(target,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            unsigned axes=[t[@"clamp_axes"] unsignedIntValue];
            glTexParameteri(target,GL_TEXTURE_WRAP_S,axes&1?GL_CLAMP_TO_EDGE:GL_REPEAT);
            glTexParameteri(target,GL_TEXTURE_WRAP_T,axes&2?GL_CLAMP_TO_EDGE:GL_REPEAT);
            glTexParameteri(target,GL_TEXTURE_WRAP_R,axes&4?GL_CLAMP_TO_EDGE:GL_REPEAT);
            glUniform1i(glGetUniformLocation(p,[[NSString stringWithFormat:@"tex%d",slot] UTF8String]),slot);
        }
        glClearColor(-1,-1,-1,-1);glClear(GL_COLOR_BUFFER_BIT);glDrawArrays(GL_TRIANGLES,0,3);
        float actual[4];glReadPixels(2,2,1,1,GL_RGBA,GL_FLOAT,actual);
        check(glGetError()==GL_NO_ERROR,@"ANGLE GL error");
        for(int c=0;c<4;c++) { float expected=[f[@"expected"][c] floatValue],error=fabsf(actual[c]-expected);
            maxError=fmaxf(maxError,error);check(std::isfinite(actual[c])&&error<.00002f,
                [NSString stringWithFormat:@"%@: channel%d actual%.9g expected%.9g",f[@"name"],c,actual[c],expected]); }
        glDeleteTextures((GLsizei)resources.size(),resources.data());passed++;
    }
    NSDictionary *result=@{@"backend":@"ANGLE-GLES-Metal",@"renderer":@((const char *)glGetString(GL_RENDERER)),
        @"pixel_cases":@(passed),@"max_float_error":@(maxError),@"runner_sha256":runnerHash,@"manifest_sha256":hash(manifestData)};
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(data.bytes,1,data.length,stdout);puts("");return 0;
} }
