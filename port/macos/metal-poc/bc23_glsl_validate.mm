// Independent ANGLE raw BC2/BC3 upload and explicit authored-mip oracle.
// Test executable only; never part of the native renderer translation path.
#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <cstdio>
#include <vector>

static void require(bool value,NSString *message) {
    if(!value){fprintf(stderr,"bc23-angle: %s\n",message.UTF8String);exit(1);}
}
static NSData *read(NSString *path) {
    NSData *data=[NSData dataWithContentsOfFile:path];require(data!=nil,path);return data;
}
static NSString *hash(NSData *data) {
    require(data.length<=UINT32_MAX,@"Oversize fixture");
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH];CC_SHA256(data.bytes,(CC_LONG)data.length,bytes);
    NSMutableString *text=[NSMutableString new];for(auto byte:bytes)[text appendFormat:@"%02x",byte];return text;
}
static GLuint shader(GLenum kind,NSData *source) {
    require(source.length<=INT32_MAX,@"Shader too long");
    const char *text=(const char *)source.bytes;GLint length=(GLint)source.length;
    GLuint value=glCreateShader(kind);glShaderSource(value,1,&text,&length);glCompileShader(value);
    GLint okay=0;glGetShaderiv(value,GL_COMPILE_STATUS,&okay);
    if(!okay){char log[8192];glGetShaderInfoLog(value,sizeof(log),nullptr,log);require(false,@(log));}
    return value;
}
int main(int argc,const char **argv) { @autoreleasepool {
    require(argc==3,@"Usage: bc23_glsl_validate fixture.json new-output-directory");
    NSString *path=[@(argv[1]) stringByStandardizingPath],*base=path.stringByDeletingLastPathComponent;
    NSData *manifestBytes=read(path);
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:manifestBytes options:0 error:nil];
    require([manifest isKindOfClass:NSDictionary.class]&&[manifest[@"kind"] isEqual:@"bc23_transport_component_fixture"],@"Wrong fixture");
    NSMutableDictionary *inputs=[NSMutableDictionary new];
    auto payload=[&](NSDictionary *descriptor) {
        NSString *file=descriptor[@"file"];
        require([file isKindOfClass:NSString.class]&&!file.isAbsolutePath&&![file.pathComponents containsObject:@".."],@"Unsafe fixture path");
        NSData *data=read([base stringByAppendingPathComponent:file]);
        require([hash(data) isEqual:descriptor[@"sha256"]]&&data.length==[descriptor[@"size"] unsignedIntegerValue],@"Stale fixture payload");
        inputs[file]=hash(data);return data;
    };
    auto getDisplay=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    require(getDisplay!=nullptr,@"Missing ANGLE display entry");
    EGLint attributes[]={0x3203,0x3489,EGL_NONE}; // Explicit ANGLE Metal renderer.
    EGLDisplay display=getDisplay(0x3202,nullptr,attributes);
    require(eglInitialize(display,nullptr,nullptr)&&eglBindAPI(EGL_OPENGL_ES_API),@"ANGLE initialization");
    EGLint configuration[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    EGLConfig config;EGLint count=0;require(eglChooseConfig(display,configuration,&config,1,&count)&&count,@"ANGLE config");
    EGLint contextAttributes[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,contextAttributes);
    unsigned width=[manifest[@"target"][@"width"] unsignedIntValue],height=[manifest[@"target"][@"height"] unsignedIntValue];
    require(width==80&&height==32,@"Wrong fixture dimensions");
    EGLint surfaceAttributes[]={EGL_WIDTH,(EGLint)width,EGL_HEIGHT,(EGLint)height,EGL_NONE};
    EGLSurface surface=eglCreatePbufferSurface(display,config,surfaceAttributes);
    require(eglMakeCurrent(display,surface,surface,context),@"ANGLE context");
    GLuint color,fbo;glGenTextures(1,&color);glBindTexture(GL_TEXTURE_2D,color);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,color,0);
    require(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,@"Fixture FBO");
    GLuint program=glCreateProgram();
    glAttachShader(program,shader(GL_VERTEX_SHADER,payload(manifest[@"glsl"][@"vertex"])));
    glAttachShader(program,shader(GL_FRAGMENT_SHADER,payload(manifest[@"glsl"][@"fragment"])));
    glLinkProgram(program);GLint linked=0;glGetProgramiv(program,GL_LINK_STATUS,&linked);require(linked,@"GLSL link");glUseProgram(program);
    for(unsigned slot=0;slot<2;slot++) {
        NSDictionary *texture=manifest[@"textures"][slot];
        require([texture[@"type"] isEqual:@"2d"]&&[texture[@"pixel_format"] isEqual:slot?@"bc3_rgba":@"bc2_rgba"]&&[texture[@"mipmaps"] count]==5,@"Unexpected original compressed format");
        GLuint object;glGenTextures(1,&object);glActiveTexture(GL_TEXTURE0+slot);glBindTexture(GL_TEXTURE_2D,object);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST_MIPMAP_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,4);
        for(NSDictionary *mip in texture[@"mipmaps"]) {
            NSData *data=payload(mip);unsigned size=16u>>[mip[@"level"] unsignedIntValue];
            require(size==[mip[@"width"] unsignedIntValue]&&size==[mip[@"height"] unsignedIntValue]&&data.length==((size+3)/4)*((size+3)/4)*16,@"Invalid compressed mip");
            glCompressedTexImage2D(GL_TEXTURE_2D,[mip[@"level"] intValue],slot?0x83f3:0x83f2,size,size,0,(GLsizei)data.length,data.bytes);
        }
        glUniform1i(glGetUniformLocation(program,slot?"bc3":"bc2"),slot);
    }
    NSData *vertices=payload(manifest[@"vertex_streams"][0]);require(vertices.length==64,@"Wrong fixture vertices");
    GLuint vao,vbo;glGenVertexArrays(1,&vao);glBindVertexArray(vao);glGenBuffers(1,&vbo);glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,vertices.length,vertices.bytes,GL_STATIC_DRAW);glEnableVertexAttribArray(0);
    glVertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,16,nullptr);
    GLuint indices[]={0,1,2,0,2,3},ibo;glGenBuffers(1,&ibo);glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,ibo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,sizeof(indices),indices,GL_STATIC_DRAW);
    glViewport(0,0,width,height);glDisable(GL_BLEND);glDisable(GL_CULL_FACE);glDisable(GL_DEPTH_TEST);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);
    glDrawElements(GL_TRIANGLES,6,GL_UNSIGNED_INT,nullptr);
    std::vector<uint8_t> pixels(width*height*4);glReadPixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
    require(glGetError()==GL_NO_ERROR,@"ANGLE compressed draw/upload/readback error");
    require([hash(read(path)) isEqual:hash(manifestBytes)],@"Fixture manifest changed");
    NSString *output=@(argv[2]);require(![NSFileManager.defaultManager fileExistsAtPath:output],@"Preserve previous ANGLE evidence");
    require([NSFileManager.defaultManager createDirectoryAtPath:output withIntermediateDirectories:YES attributes:nil error:nil],@"Output folder");
    NSData *data=[NSData dataWithBytes:pixels.data() length:pixels.size()];require([data writeToFile:[output stringByAppendingPathComponent:@"color.rgba"] atomically:YES],@"Color write");
    NSDictionary *result=@{@"schema_version":@1,@"kind":@"bc23_angle_component_oracle",@"complete":@YES,@"backend":@"angle_metal",
        @"fixture_sha256":hash(manifestBytes),@"color_sha256":hash(data),@"width":@(width),@"height":@(height),
        @"orientation":@"logical_top_left_from_explicit_vertex_y_flip",@"input_sha256":inputs,
        @"runner_sha256":hash(read(@(argv[0]))),@"gl_version":@((const char *)glGetString(GL_VERSION)),
        @"limits":@[@"Synthetic texture transport component; no physical Xbox decode precision claim.",@"Color interpolation is compared with the pinned working ANGLE GPU, without tolerances."]};
    require([[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil]
        writeToFile:[output stringByAppendingPathComponent:@"result.json"] atomically:YES],@"Result write");return 0;
} }
