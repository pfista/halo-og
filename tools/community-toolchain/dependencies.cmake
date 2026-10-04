# SPDX-License-Identifier: GPL-3.0-only
# Halo OG extract/build-only dependency replacement for pinned Invader.
# CMake explicitly selects the private static libraries; no Corrosion, Qt, SDL,
# LibArchive, TIFF or Freetype discovery/network fetch is needed.
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(Threads REQUIRED)
find_package(Git)
set(ZLIB_INCLUDE_DIRS "${HALO_CONTENT_PREFIX}/include")
set(ZLIB_LIBRARIES "${HALO_CONTENT_PREFIX}/lib/libz.a")
add_library(riatc STATIC IMPORTED)
set_target_properties(riatc PROPERTIES IMPORTED_LOCATION "${INVADER_RIATC_STATIC_LIBRARY}")
if(WIN32)
    target_link_libraries(riatc INTERFACE advapi32 userenv ws2_32 bcrypt ntdll synchronization)
elseif(NOT APPLE)
    target_link_libraries(riatc INTERFACE dl m pthread rt util)
endif()
set(DEP_AUDIO_LIBRARIES
    "${HALO_CONTENT_PREFIX}/lib/libFLAC.a"
    "${HALO_CONTENT_PREFIX}/lib/libvorbisenc.a"
    "${HALO_CONTENT_PREFIX}/lib/libvorbisfile.a"
    "${HALO_CONTENT_PREFIX}/lib/libvorbis.a"
    "${HALO_CONTENT_PREFIX}/lib/libogg.a"
    "${HALO_CONTENT_PREFIX}/lib/libsamplerate.a")
set(DEP_SQUISH_LIBRARIES "${HALO_CONTENT_PREFIX}/lib/libsquish.a")
include_directories("${HALO_CONTENT_PREFIX}/include")
# External executable options inspect *_FOUND even when disabled.
set(TIFF_FOUND FALSE)
set(FREETYPE_FOUND FALSE)
set(LibArchive_FOUND FALSE)
