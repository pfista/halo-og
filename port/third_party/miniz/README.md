Pinned miniz 3.1.0 (`174573d60290f447c13a2b1b3405de2b96e27d6c`) low-level
tinfl inflater. Upstream file hashes are in source-manifest.json.

Upstream files are unchanged. The local miniz_export.h replaces the upstream
CMake-generated static export header. tinfl_only.c disables archive,
compressor and zlib wrappers and compiles only miniz_tinfl.c. Keep LICENSE
with packaged notices. No external runtime library is required.
