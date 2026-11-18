/* The Windows and Linux OpenGL ports read flare queries asynchronously. */
#ifndef HALO_FLARE_VISIBILITY_H
#define HALO_FLARE_VISIBILITY_H

#if defined(HALO_PORT_MAXIMUM_NETWORK_PLAYERS) && (defined(__linux__) || defined(_WIN32)) && \
    !defined(HALO_ANDROID) && !defined(HALO_MACOS) && !defined(HALO_MACOS_NATIVE_METAL)
#define HALO_DESKTOP_GL_FLARE_QUERIES 1
/* Slots above these remain available for the transparent-geometry counter. */
enum { LENS_FLARE_OCCLUSION_SLOT_COUNT = 2048 };
unsigned long long xgpu_visibility_tests_ended(unsigned long index);
unsigned long long xgpu_visibility_test_counted(unsigned long index);
#endif
#endif
