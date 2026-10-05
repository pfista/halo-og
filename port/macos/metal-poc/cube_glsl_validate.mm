// Independent ANGLE BC1 cube fixture: raw authored blocks, explicit face/LOD.
// This is a test executable, never a runtime shader translation path.
#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <cstdio>
#include <vector>

static void require(bool value, NSString *message) {
    if (!value) { fprintf(stderr, "cube-glsl: %s\n", message.UTF8String); exit(1); }
}
static NSData *read(NSString *path) {
    NSData *data=[NSData dataWithContentsOfFile:path]; require(data!=nil,path); return data;
}
static NSString *hash(NSData *data) {
    require(data.length<=UINT32_MAX,@"Oversize test resource");
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes,(CC_LONG)data.length,bytes);
    NSMutableString *text=[NSMutableString new]; for(auto byte:bytes)[text appendFormat:@"%02x",byte]; return text;
}
static GLuint shader(GLenum kind,const char *source) {
    GLuint result=glCreateShader(kind); glShaderSource(result,1,&source,nullptr); glCompileShader(result);
    GLint okay=0; glGetShaderiv(result,GL_COMPILE_STATUS,&okay);
    if(!okay){char log[8192];glGetShaderInfoLog(result,sizeof(log),nullptr,log);require(false,@(log));} return result;
}
int main(int argc,const char **argv) { @autoreleasepool {
    require(argc==3,@"Usage: cube_glsl_validate replay.json output-directory");
    NSString *path=[@(argv[1]) stringByStandardizingPath],*base=path.stringByDeletingLastPathComponent;
    NSData *manifestBytes=read(path); NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:manifestBytes options:0 error:nil];
    require([manifest isKindOfClass:NSDictionary.class],@"Invalid fixture manifest");
    NSMutableDictionary *inputs=[NSMutableDictionary new];
    auto payload=[&](NSDictionary *descriptor) {
        NSString *file=descriptor[@"file"];
        require([file isKindOfClass:NSString.class]&&!file.isAbsolutePath&&![file.pathComponents containsObject:@".."],@"Invalid fixture resource path");
        NSData *data=read([base stringByAppendingPathComponent:file]);
        require([hash(data) isEqual:descriptor[@"sha256"]]&&data.length==[descriptor[@"size"] unsignedIntegerValue],@"Fixture payload hash/size mismatch");
        inputs[file]=hash(data);return data;
    };
    auto getDisplay=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    require(getDisplay!=nullptr,@"Missing ANGLE display entry");
    EGLint displayAttributes[]={0x3203,0x3489,EGL_NONE}; // ANGLE Metal explicitly.
    EGLDisplay display=getDisplay(0x3202,nullptr,displayAttributes);
    require(eglInitialize(display,nullptr,nullptr)&&eglBindAPI(EGL_OPENGL_ES_API),@"ANGLE initialization");
    EGLint configuration[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    EGLConfig config;EGLint count;require(eglChooseConfig(display,configuration,&config,1,&count)&&count,@"ANGLE config");
    EGLint contextAttributes[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,contextAttributes);
    unsigned width=[manifest[@"target"][@"width"] unsignedIntValue],height=[manifest[@"target"][@"height"] unsignedIntValue];
    require(width==32&&height==24,@"Unexpected cube fixture target");
    EGLint surfaceAttributes[]={EGL_WIDTH,(EGLint)width,EGL_HEIGHT,(EGLint)height,EGL_NONE};
    EGLSurface surface=eglCreatePbufferSurface(display,config,surfaceAttributes);
    require(eglMakeCurrent(display,surface,surface,context),@"ANGLE context");
    GLuint color,fbo;glGenTextures(1,&color);glBindTexture(GL_TEXTURE_2D,color);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,color,0);
    require(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,@"Cube test FBO");
    GLuint vs=shader(GL_VERTEX_SHADER,
        "#version 300 es\nprecision highp float;layout(location=0)in vec4 position;layout(location=4)in vec4 uvFace;"
        "out vec2 uv;flat out float face;void main(){gl_Position=vec4(position.x,-position.y,position.z,position.w);uv=uvFace.xy;face=uvFace.z;}");
    GLuint fs=shader(GL_FRAGMENT_SHADER,
        "#version 300 es\nprecision highp float;precision highp samplerCube;in vec2 uv;flat in float face;out vec4 color;uniform samplerCube original;"
        "void main(){float lod=min(floor(uv.y*5.0),4.0);float s=2.0*uv.x-1.0,t=2.0*fract(uv.y*5.0)-1.0;vec3 d;"
        "switch(int(face)){case 0:d=vec3(1,-t,-s);break;case 1:d=vec3(-1,-t,s);break;case 2:d=vec3(s,1,t);break;"
        "case 3:d=vec3(s,-1,-t);break;case 4:d=vec3(s,-t,1);break;default:d=vec3(-s,-t,-1);break;}color=textureLod(original,d,lod);}");
    GLuint program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glLinkProgram(program);
    GLint linked;glGetProgramiv(program,GL_LINK_STATUS,&linked);require(linked,@"Cube GLSL link");glUseProgram(program);
    NSDictionary *texture=manifest[@"textures"][3];
    require([texture[@"type"] isEqual:@"cube"]&&[texture[@"pixel_format"] isEqual:@"bc1_rgba"]&&[texture[@"mipmaps"] count]==5,@"Unexpected BC1 fixture");
    GLuint cube;glGenTextures(1,&cube);glActiveTexture(GL_TEXTURE3);glBindTexture(GL_TEXTURE_CUBE_MAP,cube);
    glTexParameteri(GL_TEXTURE_CUBE_MAP,GL_TEXTURE_MIN_FILTER,GL_NEAREST_MIPMAP_NEAREST);glTexParameteri(GL_TEXTURE_CUBE_MAP,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    for(GLenum axis:{GL_TEXTURE_WRAP_S,GL_TEXTURE_WRAP_T,GL_TEXTURE_WRAP_R})glTexParameteri(GL_TEXTURE_CUBE_MAP,axis,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP,GL_TEXTURE_MAX_LEVEL,4);
    for(NSDictionary *mip in texture[@"mipmaps"]){
        require([mip[@"faces"] count]==6,@"Missing BC1 cube face");
        for(NSDictionary *image in mip[@"faces"]){NSData *data=payload(image);
            glCompressedTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X+[image[@"face"] unsignedIntValue],[mip[@"level"] intValue],0x83f1,
                [mip[@"width"] intValue],[mip[@"height"] intValue],0,(GLsizei)data.length,data.bytes);}
    }
    glUniform1i(glGetUniformLocation(program,"original"),3);
    NSData *vertices=payload(manifest[@"vertex_streams"][0]);require(vertices.length==24*32,@"Unexpected vertex fixture");
    GLuint vao,vbo;glGenVertexArrays(1,&vao);glBindVertexArray(vao);glGenBuffers(1,&vbo);glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,vertices.length,vertices.bytes,GL_STATIC_DRAW);
    for(unsigned location:{0u,4u}){glEnableVertexAttribArray(location);glVertexAttribPointer(location,4,GL_FLOAT,GL_FALSE,32,(void *)(uintptr_t)(location==0?0:16));}
    std::vector<GLuint> indices;for(unsigned face=0;face<6;face++)for(unsigned index:{0u,1u,2u,0u,2u,3u})indices.push_back(face*4+index);
    GLuint ibo;glGenBuffers(1,&ibo);glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,ibo);glBufferData(GL_ELEMENT_ARRAY_BUFFER,indices.size()*4,indices.data(),GL_STATIC_DRAW);
    glViewport(0,0,width,height);glDisable(GL_BLEND);glDisable(GL_CULL_FACE);glDisable(GL_DEPTH_TEST);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);
    glDrawElements(GL_TRIANGLES,(GLsizei)indices.size(),GL_UNSIGNED_INT,nullptr);
    std::vector<uint8_t> pixels(width*height*4);glReadPixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
    require(glGetError()==GL_NO_ERROR,@"ANGLE BC1 draw/readback error");
    require([hash(read(path)) isEqual:hash(manifestBytes)],@"Fixture manifest changed");
    NSString *output=@(argv[2]);require(![NSFileManager.defaultManager fileExistsAtPath:output],@"Preserve previous cube evidence");
    require([NSFileManager.defaultManager createDirectoryAtPath:output withIntermediateDirectories:YES attributes:nil error:nil],@"Output folder");
    NSData *data=[NSData dataWithBytes:pixels.data() length:pixels.size()];require([data writeToFile:[output stringByAppendingPathComponent:@"color.rgba"] atomically:YES],@"Color write");
    NSDictionary *result=@{@"kind":@"bc1_cube_angle_fixture",@"complete":@YES,@"backend":@"angle_metal",@"manifest_sha256":hash(manifestBytes),
        @"color_sha256":hash(data),@"width":@(width),@"height":@(height),@"orientation":@"top_left_from_explicit_vertex_y_flip",@"input_sha256":inputs,
        @"runner_sha256":hash(read(@(argv[0]))),@"gl_version":@((const char *)glGetString(GL_VERSION)),
        @"limits":@[@"Synthetic isolated cube fixture; no original Xbox decode precision claim.",@"Culling/depth disabled in texture-only ANGLE reference; native raster state verified separately."]};
    [[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil]writeToFile:[output stringByAppendingPathComponent:@"result.json"] atomically:YES];
    return 0;
} }
