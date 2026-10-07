// SPDX-License-Identifier: GPL-3.0-only
// Offline exact native pixel packing. No resizing, mip generation or lossy codecs.
// Links the reviewed Invader decoder/encoder; writes only copied overlay tags.
#include <invader/tag/parser/parser.hpp>
#include <invader/bitmap/bitmap_encode.hpp>
#include <invader/tag/hek/class/bitmap.hpp>
#include <invader/file/file.hpp>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace Invader;
namespace fs = std::filesystem;
static constexpr std::size_t MAX_TAG_BYTES = 128 * 1024 * 1024;
static constexpr std::size_t MAX_SURFACE_PIXELS = 16 * 1024 * 1024;

// The pinned dependency prefix has no JSON library. This emitter only writes
// fixed-schema JSON; controls and arbitrary UTF-8 filesystem text are escaped.
static std::string quoted(const std::string &text) {
    std::ostringstream out;
    out << '"';
    for(std::size_t i = 0; i < text.size(); i++) {
        auto c = static_cast<unsigned char>(text[i]);
        if(c == '"' || c == '\\') out << '\\' << static_cast<char>(c);
        else if(c < 0x20 || c == 0x7F) {
            out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c) << std::dec;
        }
        else if(c < 0x80) out << static_cast<char>(c);
        else {
            std::size_t count = c >= 0xC2 && c <= 0xDF ? 2 : c >= 0xE0 && c <= 0xEF ? 3 : c >= 0xF0 && c <= 0xF4 ? 4 : 0;
            if(!count || count > text.size() - i) throw std::runtime_error("Invalid UTF-8 in JSON text");
            std::uint32_t code = c & (count == 2 ? 0x1F : count == 3 ? 0x0F : 0x07);
            for(std::size_t j = 1; j < count; j++) {
                auto next = static_cast<unsigned char>(text[i + j]);
                if((next & 0xC0) != 0x80) throw std::runtime_error("Invalid UTF-8 in JSON text");
                code = (code << 6) | (next & 0x3F);
            }
            if((count == 2 && code < 0x80) || (count == 3 && code < 0x800)
                    || (count == 4 && code < 0x10000) || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF))
                throw std::runtime_error("Invalid UTF-8 in JSON text");
            out << text.substr(i, count);
            i += count - 1;
        }
    }
    out << '"';
    return out.str();
}

static fs::path regular_root(const fs::path &root) {
    auto absolute = fs::absolute(root).lexically_normal();
    fs::path at;
    for(const auto &part : absolute) {
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink directory refused");
    }
    if(!fs::is_directory(absolute)) throw std::runtime_error("Expected a regular directory");
    return absolute;
}

static fs::path checked_file(const fs::path &root, const std::string &name, bool bitmap = true) {
    fs::path relative(name);
    if(name.empty() || relative.is_absolute() || relative.lexically_normal().generic_string() != name
            || name.find(':') != std::string::npos || name.find('\\') != std::string::npos
            || (bitmap && relative.extension() != ".bitmap"))
        throw std::runtime_error("Expected a normalized relative bitmap path");
    for(unsigned char c : name) if(c < 0x20 || c == 0x7F) throw std::runtime_error("Control character in tag path");
    quoted(name);  // Validate UTF-8 before emitting a pathname as JSON.
    auto at = regular_root(root);
    for(const auto &part : relative) {
        if(part.empty() || part == "." || part == "..") throw std::runtime_error("Path traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing, nonregular or hard-linked input refused");
    if(fs::file_size(at) > (bitmap ? MAX_TAG_BYTES : 1024 * 1024)) throw std::runtime_error("Input exceeds the bounded size limit");
    return at;
}

static std::vector<std::byte> read_file(const fs::path &path) {
    auto bytes = File::open_file(path);
    if(!bytes || bytes->size() > MAX_TAG_BYTES) throw std::runtime_error("Cannot read bounded input file");
    return std::move(*bytes);
}

static const char *format_name(HEK::BitmapDataFormat format) {
    switch(format) {
        case HEK::BITMAP_DATA_FORMAT_A8: return "a8";
        case HEK::BITMAP_DATA_FORMAT_Y8: return "y8";
        case HEK::BITMAP_DATA_FORMAT_AY8: return "ay8";
        case HEK::BITMAP_DATA_FORMAT_A8Y8: return "a8y8";
        case HEK::BITMAP_DATA_FORMAT_R5G6B5: return "r5g6b5";
        case HEK::BITMAP_DATA_FORMAT_A1R5G5B5: return "a1r5g5b5";
        case HEK::BITMAP_DATA_FORMAT_A4R4G4B4: return "a4r4g4b4";
        case HEK::BITMAP_DATA_FORMAT_X8R8G8B8: return "x8r8g8b8";
        case HEK::BITMAP_DATA_FORMAT_A8R8G8B8: return "a8r8g8b8";
        case HEK::BITMAP_DATA_FORMAT_DXT1: return "dxt1";
        case HEK::BITMAP_DATA_FORMAT_DXT3: return "dxt3";
        case HEK::BITMAP_DATA_FORMAT_DXT5: return "dxt5";
        case HEK::BITMAP_DATA_FORMAT_P8_BUMP: return "p8 bump";
        case HEK::BITMAP_DATA_FORMAT_BC7: return "bc7";
        default: throw std::runtime_error("Unsupported bitmap pixel format");
    }
}

static const char *type_name(HEK::BitmapDataType type) {
    switch(type) {
        case HEK::BITMAP_DATA_TYPE_2D_TEXTURE: return "2d";
        case HEK::BITMAP_DATA_TYPE_3D_TEXTURE: return "3d";
        case HEK::BITMAP_DATA_TYPE_CUBE_MAP: return "cubemap";
        case HEK::BITMAP_DATA_TYPE_WHITE: return "white";
        default: throw std::runtime_error("Unsupported bitmap image type");
    }
}

struct Image {
    std::size_t index, bytes, faces;
};

static std::vector<Image> inspect(const Parser::Bitmap &tag) {
    if(tag.bitmap_data.size() > 4096 || tag.processed_pixel_data.size() > MAX_TAG_BYTES)
        throw std::runtime_error("Bitmap image table or pixel data exceeds the bounded size limit");
    std::vector<Image> images;
    std::vector<std::pair<std::size_t, std::size_t>> ranges;
    for(std::size_t i = 0; i < tag.bitmap_data.size(); i++) {
        const auto &b = tag.bitmap_data[i];
        format_name(b.format); type_name(b.type);
        if(!b.width || !b.height || !b.depth || b.width > 16384 || b.height > 16384
                || b.depth > 16384 || std::size_t(b.width) > MAX_SURFACE_PIXELS / b.height)
            throw std::runtime_error("Bitmap dimensions exceed bounded decoder capacity");
        if(b.flags & HEK::BITMAP_DATA_FLAGS_FLAG_SWIZZLED) throw std::runtime_error("HEK bitmap payload must be unswizzled");
        if((b.type != HEK::BITMAP_DATA_TYPE_3D_TEXTURE && b.depth != 1)
                || (b.type == HEK::BITMAP_DATA_TYPE_CUBE_MAP && b.width != b.height))
            throw std::runtime_error("Bitmap dimensions do not match image type");
        if(b.type == HEK::BITMAP_DATA_TYPE_WHITE && b.format == HEK::BITMAP_DATA_FORMAT_BC7)
            throw std::runtime_error("BC7 white-image layout is not supported");
        auto largest = std::max({std::size_t(b.width), std::size_t(b.height), std::size_t(b.depth)});
        std::size_t maximum_mips = 0;
        for(; largest > 1; largest /= 2) maximum_mips++;
        if(b.mipmap_count > maximum_mips) throw std::runtime_error("Mip count exceeds the authored image dimensions");
        auto bytes = BitmapEncode::bitmap_data_size(b.width, b.height, b.depth, b.mipmap_count, b.format, b.type);
        auto offset = std::size_t(b.pixel_data_offset);
        if(offset > tag.processed_pixel_data.size() || bytes > tag.processed_pixel_data.size() - offset)
            throw std::runtime_error("Bitmap image range exceeds processed pixel data");
        ranges.emplace_back(offset, offset + bytes);
        images.push_back({i, bytes, b.type == HEK::BITMAP_DATA_TYPE_CUBE_MAP ? 6U : 1U});
    }
    std::sort(ranges.begin(), ranges.end());
    for(std::size_t i = 1; i < ranges.size(); i++)
        if(ranges[i].first < ranges[i - 1].second) throw std::runtime_error("Overlapping bitmap image payloads are unsupported");
    return images;
}

static std::string source_formats(const Parser::Bitmap &tag) {
    std::set<std::string> names;
    for(const auto &image : tag.bitmap_data) names.insert(format_name(image.format));
    std::string result = "[";
    for(const auto &name : names) { if(result.size() > 1) result += ','; result += quoted(name); }
    return result + ']';
}

static const HEK::BitmapDataFormat native_formats[] = {
    HEK::BITMAP_DATA_FORMAT_A8, HEK::BITMAP_DATA_FORMAT_Y8,
    HEK::BITMAP_DATA_FORMAT_AY8, HEK::BITMAP_DATA_FORMAT_A8Y8,
    HEK::BITMAP_DATA_FORMAT_R5G6B5, HEK::BITMAP_DATA_FORMAT_A1R5G5B5,
    HEK::BITMAP_DATA_FORMAT_A4R4G4B4, HEK::BITMAP_DATA_FORMAT_X8R8G8B8,
    HEK::BITMAP_DATA_FORMAT_A8R8G8B8
};

static bool native_uncompressed(HEK::BitmapDataFormat format) {
    return std::find(std::begin(native_formats), std::end(native_formats), format) != std::end(native_formats);
}

// Mirror the sampled channels in source/bitmaps/bitmaps.c:787 and
// port/linux/src/xbox_textures.c:318. These differ from Invader for A8,
// stored X8 alpha and some 16-bit expansion values. Preserve BOTH consumers;
// an Invader-only roundtrip is insufficient for packed HUD channels.
static std::vector<std::byte> consumer_pixels(const std::byte *input, HEK::BitmapDataFormat format,
                                             std::size_t pixels, bool software) {
    std::vector<std::byte> output(pixels * 4);
    const auto stride = HEK::calculate_bits_per_pixel(format) / 8;
    auto expand5 = [](unsigned v) { return (v << 3) | (v >> 2); };
    auto expand6 = [](unsigned v) { return (v << 2) | (v >> 4); };
    auto expand4 = [](unsigned v) { return (v << 4) | v; };
    for(std::size_t i = 0; i < pixels; i++) {
        auto at = input + i * stride;
        auto value = [&](std::size_t n) { return std::to_integer<unsigned>(at[n]); };
        unsigned a = 255, r = 0, g = 0, b = 0;
        unsigned v = stride >= 2 ? value(0) | value(1) << 8 : value(0);
        switch(format) {
            case HEK::BITMAP_DATA_FORMAT_A8: a = value(0); r = g = b = software ? 0 : 255; break;
            case HEK::BITMAP_DATA_FORMAT_Y8: r = g = b = value(0); break;
            case HEK::BITMAP_DATA_FORMAT_AY8: a = r = g = b = value(0); break;
            case HEK::BITMAP_DATA_FORMAT_A8Y8: a = value(1); r = g = b = value(0); break;
            case HEK::BITMAP_DATA_FORMAT_R5G6B5: r = expand5(v >> 11); g = expand6((v >> 5) & 63); b = expand5(v & 31); break;
            case HEK::BITMAP_DATA_FORMAT_A1R5G5B5: a = v & 0x8000 ? 255 : 0; r = expand5((v >> 10) & 31); g = expand5((v >> 5) & 31); b = expand5(v & 31); break;
            case HEK::BITMAP_DATA_FORMAT_A4R4G4B4: a = expand4(v >> 12); r = expand4((v >> 8) & 15); g = expand4((v >> 4) & 15); b = expand4(v & 15); break;
            case HEK::BITMAP_DATA_FORMAT_X8R8G8B8: a = software ? value(3) : 255; b = value(0); g = value(1); r = value(2); break;
            case HEK::BITMAP_DATA_FORMAT_A8R8G8B8: a = value(3); b = value(0); g = value(1); r = value(2); break;
            default: throw std::runtime_error("Unreviewed native pixel consumer format");
        }
        output[i * 4] = std::byte(b); output[i * 4 + 1] = std::byte(g);
        output[i * 4 + 2] = std::byte(r); output[i * 4 + 3] = std::byte(a);
    }
    return output;
}

struct Packing {
    std::size_t index, before_bytes, after_bytes;
    HEK::BitmapDataFormat before, after;
    std::vector<std::byte> pixels;
    std::vector<std::string> rejected;
};

static std::vector<std::byte> encode_exact(const Parser::BitmapData &b,
        const std::vector<std::byte> &pixels, const Image &image, HEK::BitmapDataFormat target,
        std::string &rejection) {
    std::vector<std::byte> output;
    const auto expected = BitmapEncode::bitmap_data_size(b.width, b.height, b.depth, b.mipmap_count, target, b.type);
    output.reserve(expected);
    std::size_t width = b.width, height = b.height, depth = b.depth, offset = b.pixel_data_offset;
    for(std::size_t mip = 0; mip <= b.mipmap_count; mip++) {
        for(std::size_t face = 0; face < image.faces; face++) for(std::size_t z = 0; z < depth; z++) {
            auto bytes = BitmapEncode::bitmap_data_size(width, height, 1, 0, b.format, HEK::BITMAP_DATA_TYPE_2D_TEXTURE);
            if(offset > pixels.size() || bytes > pixels.size() - offset) throw std::runtime_error("Source surface exceeds bitmap payload");
            const auto *source = pixels.data() + offset;
            // Never use the pinned multi-face encoder's ARGB-specific strides.
            auto encoded = BitmapEncode::encode_bitmap(source, b.format, target, width, height, false);
            if(encoded.size() != BitmapEncode::bitmap_data_size(width, height, 1, 0, target, HEK::BITMAP_DATA_TYPE_2D_TEXTURE))
                throw std::runtime_error("Candidate surface size differs from native format layout");
            auto before = BitmapEncode::encode_bitmap(source, b.format, HEK::BITMAP_DATA_FORMAT_A8R8G8B8, width, height, false);
            auto after = BitmapEncode::encode_bitmap(encoded.data(), target, HEK::BITMAP_DATA_FORMAT_A8R8G8B8, width, height, false);
            if(before != after) { rejection = "Invader decoded ARGB pixel values differ"; return {}; }
            if(consumer_pixels(source, b.format, width * height, false) != consumer_pixels(encoded.data(), target, width * height, false)) {
                rejection = "Native GPU sampled channel values differ"; return {};
            }
            if(consumer_pixels(source, b.format, width * height, true) != consumer_pixels(encoded.data(), target, width * height, true)) {
                rejection = "Native software bitmap sampled channel values differ"; return {};
            }
            output.insert(output.end(), encoded.begin(), encoded.end());
            offset += bytes;
        }
        width = std::max<std::size_t>(1, width / 2);
        height = std::max<std::size_t>(1, height / 2);
        depth = std::max<std::size_t>(1, depth / 2);
    }
    if(output.size() != expected || offset - b.pixel_data_offset != image.bytes)
        throw std::runtime_error("Candidate image stride differs from authored mip/face/depth layout");
    return output;
}

static std::vector<Packing> plan(const Parser::Bitmap &tag, const std::vector<Image> &images) {
    std::vector<Packing> packed;
    for(const auto &image : images) {
        const auto &b = tag.bitmap_data[image.index];
        if(!native_uncompressed(b.format)) continue; // Native compression/bump data stays exact.
        if(b.flags & (HEK::BITMAP_DATA_FLAGS_FLAG_COMPRESSED | HEK::BITMAP_DATA_FLAGS_FLAG_PALETTIZED))
            throw std::runtime_error("Uncompressed pixel format has compressed/palettized flags");
        std::vector<HEK::BitmapDataFormat> candidates;
        for(auto format : native_formats)
            if(BitmapEncode::bitmap_data_size(b.width, b.height, b.depth, b.mipmap_count, format, b.type) < image.bytes)
                candidates.push_back(format);
        std::stable_sort(candidates.begin(), candidates.end(), [&](auto a, auto c) {
            return BitmapEncode::bitmap_data_size(b.width, b.height, b.depth, b.mipmap_count, a, b.type) <
                   BitmapEncode::bitmap_data_size(b.width, b.height, b.depth, b.mipmap_count, c, b.type);
        });
        Packing choice{image.index, image.bytes, image.bytes, b.format, b.format, {}, {}};
        for(auto candidate : candidates) {
            std::string reason;
            auto encoded = encode_exact(b, tag.processed_pixel_data, image, candidate, reason);
            if(!reason.empty()) { choice.rejected.push_back(std::string(format_name(candidate)) + ": " + reason); continue; }
            choice.after = candidate; choice.after_bytes = encoded.size(); choice.pixels = std::move(encoded);
            break; // Sorted smallest size, then stable native-format order.
        }
        if(choice.after != choice.before) packed.push_back(std::move(choice));
    }
    return packed;
}

static std::string packing_json(const Parser::Bitmap &tag, const std::vector<Packing> &packed) {
    std::ostringstream out;
    out << '[';
    bool separator = false;
    for(const auto &p : packed) {
        const auto &b = tag.bitmap_data[p.index];
        if(separator) out << ','; separator = true;
        out << "{\"index\":" << p.index << ",\"source_format\":" << quoted(format_name(p.before))
            << ",\"target_format\":" << quoted(format_name(p.after)) << ",\"width\":" << b.width << ",\"height\":" << b.height
            << ",\"depth\":" << b.depth << ",\"type\":" << quoted(type_name(b.type))
            << ",\"faces\":" << (b.type == HEK::BITMAP_DATA_TYPE_CUBE_MAP ? 6 : 1) << ",\"mips\":" << b.mipmap_count + 1
            << ",\"bytes_before\":" << p.before_bytes << ",\"bytes_after\":" << p.after_bytes
            << ",\"decoded_pixels_exact\":true,\"native_gpu_pixels_exact\":true,\"software_pixels_exact\":true"
            << ",\"rejected_candidates\":[";
        for(std::size_t i = 0; i < p.rejected.size(); i++) { if(i) out << ','; out << quoted(p.rejected[i]); }
        out << "]}";
    }
    return out.str() + ']';
}

static void audit(const fs::path &input) {
    const auto root = regular_root(input);
    std::vector<std::string> names;
    for(const auto &entry : fs::recursive_directory_iterator(root))
        if(entry.path().extension() == ".bitmap") names.push_back(entry.path().lexically_relative(root).generic_string());
    std::sort(names.begin(), names.end());
    for(const auto &name : names) {
        std::string formats = "[]";
        try {
            auto bytes = read_file(checked_file(root, name));
            auto tag = Parser::Bitmap::parse_hek_tag_file(bytes.data(), bytes.size());
            formats = source_formats(tag);
            auto images = inspect(tag);
            auto packed = plan(tag, images);
            if(packed.empty()) continue;
            std::size_t saved = 0; for(const auto &p : packed) saved += p.before_bytes - p.after_bytes;
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"convertible\",\"source_formats\":" << formats
                << ",\"target_format\":\"lossless_native_pixels\",\"images_packed\":" << packed.size()
                << ",\"metadata\":{\"tag_bytes\":" << bytes.size() << ",\"pixel_bytes\":" << tag.processed_pixel_data.size()
                << ",\"pixel_bytes_saved\":" << saved << ",\"images\":" << packing_json(tag, packed)
                << "},\"decoded_pixels_exact\":true,\"native_gpu_pixels_exact\":true,\"software_pixels_exact\":true,\"visual_validation\":\"pending\"}\n";
        }
        catch(const std::exception &error) {
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"unsupported\",\"source_formats\":" << formats
                << ",\"target_format\":\"lossless_native_pixels\",\"reason\":" << quoted(error.what()) << ",\"metadata\":{}}\n";
        }
    }
}

struct Prepared {
    std::string name, record;
    std::vector<std::byte> original, output;
};

struct PreservedSpan { std::size_t before, after, bytes; };

static Prepared prepare(const fs::path &overlay, const std::string &name) {
    auto snapshot = checked_file(overlay / "source-snapshots", name);
    auto target = checked_file(overlay / "tags", name);
    if(fs::equivalent(snapshot, target)) throw std::runtime_error("Snapshot and output must be independent copies");
    auto original = read_file(snapshot), current = read_file(target);
    if(original != current) throw std::runtime_error("Source snapshot differs from output input; repeat conversion refused");
    auto source = Parser::Bitmap::parse_hek_tag_file(original.data(), original.size());
    auto images = inspect(source);
    auto packed = plan(source, images);
    if(packed.empty()) throw std::runtime_error("Selected tag has no exact smaller native pixel format");
    auto converted = source;
    std::vector<std::byte> pixels;
    std::vector<PreservedSpan> preserved;
    auto ordered = images;
    std::sort(ordered.begin(), ordered.end(), [&](const auto &a, const auto &b) {
        return source.bitmap_data[a.index].pixel_data_offset < source.bitmap_data[b.index].pixel_data_offset;
    });
    auto preserve = [&](std::size_t first, std::size_t count) {
        preserved.push_back({first, pixels.size(), count});
        pixels.insert(pixels.end(), source.processed_pixel_data.begin() + first, source.processed_pixel_data.begin() + first + count);
    };
    std::size_t at = 0;
    for(const auto &image : ordered) {
        const auto &old = source.bitmap_data[image.index];
        preserve(at, old.pixel_data_offset - at); // Keep unused gaps and padding exact.
        auto &b = converted.bitmap_data[image.index];
        b.pixel_data_offset = pixels.size();
        auto choice = std::find_if(packed.begin(), packed.end(), [&](const auto &p) { return p.index == image.index; });
        if(choice == packed.end()) preserve(old.pixel_data_offset, image.bytes);
        else {
            pixels.insert(pixels.end(), choice->pixels.begin(), choice->pixels.end());
            b.format = choice->after;
            b.pixel_data_size = choice->after_bytes;
        }
        at = old.pixel_data_offset + image.bytes;
    }
    preserve(at, source.processed_pixel_data.size() - at);
    converted.processed_pixel_data = std::move(pixels);
    auto output = converted.generate_hek_tag_data(HEK::TAG_FOURCC_BITMAP, false);
    auto reparsed = Parser::Bitmap::parse_hek_tag_file(output.data(), output.size());
    if(!converted.compare(&reparsed, false)) throw std::runtime_error("Packed bitmap did not reparse identically");
    auto output_images = inspect(reparsed);
    for(const auto &span : preserved) {
        if(span.after > reparsed.processed_pixel_data.size() || span.bytes > reparsed.processed_pixel_data.size() - span.after ||
           !std::equal(source.processed_pixel_data.begin() + span.before, source.processed_pixel_data.begin() + span.before + span.bytes,
                       reparsed.processed_pixel_data.begin() + span.after))
            throw std::runtime_error("Unselected image or unallocated pixel bytes changed");
    }
    for(const auto &p : packed) {
        const auto &b = reparsed.bitmap_data[p.index];
        if(b.format != p.after || output_images[p.index].bytes != p.after_bytes ||
           !std::equal(p.pixels.begin(), p.pixels.end(), reparsed.processed_pixel_data.begin() + b.pixel_data_offset))
            throw std::runtime_error("Reparsed packed pixel payload differs from the exact candidate");
    }
    // Restore ONLY per-image format/offset/size and raw pixel payload. All
    // flags, top-level encoding hints, dimensions, mips, sequences, channel
    // values, sprite coordinates and registration points remain authored.
    auto restored = reparsed;
    restored.processed_pixel_data = source.processed_pixel_data;
    for(std::size_t i = 0; i < restored.bitmap_data.size(); i++) {
        restored.bitmap_data[i].format = source.bitmap_data[i].format;
        restored.bitmap_data[i].pixel_data_offset = source.bitmap_data[i].pixel_data_offset;
        restored.bitmap_data[i].pixel_data_size = source.bitmap_data[i].pixel_data_size;
    }
    if(!source.compare(&restored, false)) throw std::runtime_error("Authored bitmap metadata changed");
    std::ostringstream record;
    record << "{\"tag\":" << quoted(name) << ",\"status\":\"converted\",\"source_formats\":" << source_formats(source)
        << ",\"target_format\":\"lossless_native_pixels\",\"images_packed\":" << packed.size()
        << ",\"images\":" << packing_json(source, packed) << ",\"sizes\":{\"tag_before\":" << original.size()
        << ",\"tag_after\":" << output.size() << ",\"pixel_before\":" << source.processed_pixel_data.size()
        << ",\"pixel_after\":" << reparsed.processed_pixel_data.size()
        << "},\"decoded_pixels_exact\":true,\"native_gpu_pixels_exact\":true,\"software_pixels_exact\":true"
           ",\"metadata_preserved\":true,\"unselected_pixels_preserved\":true,\"visual_validation\":\"pending\"}";
    return {name, record.str(), std::move(original), std::move(output)};
}

static void convert(const fs::path &input) {
    const auto overlay = regular_root(input);
    if(fs::exists(overlay / "conversion.completed") || fs::is_symlink(fs::symlink_status(overlay / "conversion.completed")))
        throw std::runtime_error("Overlay was already converted; use a fresh overlay");
    auto list = checked_file(overlay, "asset-paths.txt", false);
    std::ifstream paths(list);
    if(!paths) throw std::runtime_error("Missing asset-paths.txt");
    std::set<std::string> names;
    for(std::string name; std::getline(paths, name);)
        if(name.empty() || !names.insert(name).second) throw std::runtime_error("Empty or duplicate asset path");
    if(!paths.eof() || names.empty()) throw std::runtime_error("Cannot read a nonempty asset-paths.txt");
    std::vector<Prepared> prepared;
    for(const auto &name : names) prepared.push_back(prepare(overlay, name));
    for(const auto &item : prepared)
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original ||
           read_file(checked_file(overlay / "tags", item.name)) != item.original)
            throw std::runtime_error("Input changed during conversion preparation");
    for(const auto &item : prepared) {
        auto target = checked_file(overlay / "tags", item.name);
        if(!File::save_file(target, item.output) || read_file(target) != item.output)
            throw std::runtime_error("Packed output write verification failed");
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original)
            throw std::runtime_error("Source snapshot changed during output writing");
        std::cout << item.record << '\n';
    }
}

int main(int argc, char **argv) {
    if(argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "Usage: pack-lossless-bitmaps --audit TAG_ROOT | --convert FRESH_OVERLAY\n"
                     "Requires asset-paths.txt and independent identical source-snapshots/ and tags/.\n"
                     "Exact Invader, native GPU and software channel values; no resizing or lossy encoding.\n";
        return 0;
    }
    if(argc != 3) { std::cerr << "Expected --audit TAG_ROOT or --convert FRESH_OVERLAY\n"; return 2; }
    try {
        const std::string mode = argv[1];
        if(mode == "--audit") audit(argv[2]);
        else if(mode == "--convert") convert(argv[2]);
        else throw std::runtime_error("Unknown lossless bitmap helper operation");
        return 0;
    }
    catch(const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
