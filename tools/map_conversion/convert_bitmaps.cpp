// SPDX-License-Identifier: GPL-3.0-only
// Offline BC7 compatibility overlay. No resizing, mip generation or stock art.
// Links the reviewed Invader decoder/encoder; writes only copied overlay tags.
#include <invader/tag/parser/parser.hpp>
#include <invader/bitmap/bitmap_encode.hpp>
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

static std::string image_metadata(const Parser::Bitmap &tag, const std::vector<Image> &images) {
    std::ostringstream out;
    out << '[';
    bool separator = false;
    for(const auto &image : images) {
        const auto &b = tag.bitmap_data[image.index];
        if(b.format != HEK::BITMAP_DATA_FORMAT_BC7) continue;
        if(separator) out << ',';
        separator = true;
        out << "{\"index\":" << image.index << ",\"width\":" << b.width << ",\"height\":" << b.height
            << ",\"depth\":" << b.depth << ",\"type\":" << quoted(type_name(b.type))
            << ",\"faces\":" << image.faces << ",\"mips\":" << b.mipmap_count + 1
            << ",\"pixel_bytes\":" << image.bytes << ",\"pixel_offset\":" << b.pixel_data_offset << '}';
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
            auto path = checked_file(root, name);
            auto bytes = read_file(path);
            auto tag = Parser::Bitmap::parse_hek_tag_file(bytes.data(), bytes.size());
            formats = source_formats(tag);
            auto images = inspect(tag);
            if(std::none_of(tag.bitmap_data.begin(), tag.bitmap_data.end(), [](const auto &b) { return b.format == HEK::BITMAP_DATA_FORMAT_BC7; })) continue;
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"convertible\",\"source_formats\":" << formats
                << ",\"target_format\":\"dxt5\",\"metadata\":{\"tag_bytes\":" << bytes.size()
                << ",\"pixel_bytes\":" << tag.processed_pixel_data.size() << ",\"images\":" << image_metadata(tag, images) << "}}\n";
        }
        catch(const std::exception &error) {
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"unsupported\",\"source_formats\":" << formats
                << ",\"reason\":" << quoted(error.what()) << ",\"metadata\":{}}\n";
        }
    }
}

struct Quality {
    std::uint64_t pixels = 0;
    double rgb_squared_error = 0, alpha_squared_error = 0;
    unsigned rgb_max_error = 0, alpha_max_error = 0;
    void add(const std::vector<std::byte> &before, const std::vector<std::byte> &after) {
        if(before.size() != after.size() || before.size() % 4) throw std::runtime_error("Decoded comparison has inconsistent pixel sizes");
        pixels += before.size() / 4;
        for(std::size_t i = 0; i < before.size(); i++) {
            auto delta = int(std::to_integer<unsigned char>(before[i])) - int(std::to_integer<unsigned char>(after[i]));
            auto magnitude = unsigned(std::abs(delta));
            if(i % 4 == 3) { alpha_squared_error += double(delta) * delta; alpha_max_error = std::max(alpha_max_error, magnitude); }
            else { rgb_squared_error += double(delta) * delta; rgb_max_error = std::max(rgb_max_error, magnitude); }
        }
    }
    std::string json() const {
        std::ostringstream out;
        out << std::setprecision(10) << "{\"comparison\":\"decoded_bc7_vs_decoded_dxt5\",\"pixels\":" << pixels
            << ",\"rgb_rmse\":" << (pixels ? std::sqrt(rgb_squared_error / (pixels * 3.0)) : 0)
            << ",\"alpha_rmse\":" << (pixels ? std::sqrt(alpha_squared_error / pixels) : 0)
            << ",\"rgb_max_error\":" << rgb_max_error << ",\"alpha_max_error\":" << alpha_max_error
            << ",\"visual_validation\":\"pending\"}";
        return out.str();
    }
};

struct Prepared {
    std::string name, record;
    std::vector<std::byte> original, output;
};

static Prepared prepare(const fs::path &overlay, const std::string &name) {
    auto snapshot = checked_file(overlay / "source-snapshots", name);
    auto target = checked_file(overlay / "tags", name);
    if(fs::equivalent(snapshot, target)) throw std::runtime_error("Snapshot and output must be independent copies");
    auto original = read_file(snapshot), current = read_file(target);
    if(original != current) throw std::runtime_error("Source snapshot differs from output input; repeat conversion refused");
    auto source = Parser::Bitmap::parse_hek_tag_file(original.data(), original.size());
    auto images = inspect(source);
    auto converted = source;
    Quality quality;
    std::size_t changed = 0;
    for(const auto &image : images) {
        auto &b = converted.bitmap_data[image.index];
        if(b.format != HEK::BITMAP_DATA_FORMAT_BC7) continue;
        std::size_t width = b.width, height = b.height, depth = b.depth, offset = b.pixel_data_offset;
        std::vector<std::byte> encoded_image;
        encoded_image.reserve(image.bytes);
        for(std::size_t mip = 0; mip <= b.mipmap_count; mip++) {
            for(std::size_t face = 0; face < image.faces; face++) for(std::size_t z = 0; z < depth; z++) {
                auto surface_bytes = BitmapEncode::bitmap_data_size(width, height, 1, 0, HEK::BITMAP_DATA_FORMAT_BC7, HEK::BITMAP_DATA_TYPE_2D_TEXTURE);
                if(offset > source.processed_pixel_data.size() || surface_bytes > source.processed_pixel_data.size() - offset)
                    throw std::runtime_error("BC7 surface exceeds its source payload");
                const auto *pixels = source.processed_pixel_data.data() + offset;
                // The pinned multi-face API assumes ARGB32 strides. Deliberate
                // per-face/mip/slice calls preserve compressed canonical order.
                auto encoded = BitmapEncode::encode_bitmap(pixels, HEK::BITMAP_DATA_FORMAT_BC7, HEK::BITMAP_DATA_FORMAT_DXT5, width, height, false);
                if(encoded.size() != surface_bytes) throw std::runtime_error("DXT5 surface size differs from BC7 layout");
                auto decoded_before = BitmapEncode::encode_bitmap(pixels, HEK::BITMAP_DATA_FORMAT_BC7, HEK::BITMAP_DATA_FORMAT_A8R8G8B8, width, height, false);
                auto decoded_after = BitmapEncode::encode_bitmap(encoded.data(), HEK::BITMAP_DATA_FORMAT_DXT5, HEK::BITMAP_DATA_FORMAT_A8R8G8B8, width, height, false);
                quality.add(decoded_before, decoded_after);
                encoded_image.insert(encoded_image.end(), encoded.begin(), encoded.end());
                offset += surface_bytes;
            }
            width = std::max<std::size_t>(1, width / 2);
            height = std::max<std::size_t>(1, height / 2);
            depth = std::max<std::size_t>(1, depth / 2);
        }
        if(encoded_image.size() != image.bytes || offset - b.pixel_data_offset != image.bytes)
            throw std::runtime_error("Converted face/mip stride differs from source layout");
        std::copy(encoded_image.begin(), encoded_image.end(), converted.processed_pixel_data.begin() + b.pixel_data_offset);
        b.format = HEK::BITMAP_DATA_FORMAT_DXT5;
        b.flags |= HEK::BITMAP_DATA_FLAGS_FLAG_COMPRESSED;
        b.pixel_data_size = image.bytes;
        changed++;
    }
    if(!changed) throw std::runtime_error("Selected tag has no BC7 images");
    converted.encoding_format = HEK::BITMAP_FORMAT_DXT5;
    auto output = converted.generate_hek_tag_data(HEK::TAG_FOURCC_BITMAP, false);
    auto reparsed = Parser::Bitmap::parse_hek_tag_file(output.data(), output.size());
    if(!converted.compare(&reparsed, false)) throw std::runtime_error("Converted bitmap did not reparse identically");
    if(reparsed.processed_pixel_data.size() != source.processed_pixel_data.size()) throw std::runtime_error("Pixel data grew during conversion");
    // Verify every unconverted image and all unallocated pixel bytes directly.
    std::vector<std::pair<std::size_t, std::size_t>> changed_ranges;
    for(const auto &image : images) if(source.bitmap_data[image.index].format == HEK::BITMAP_DATA_FORMAT_BC7) {
        const auto &b = source.bitmap_data[image.index];
        changed_ranges.emplace_back(b.pixel_data_offset, b.pixel_data_offset + image.bytes);
    }
    std::sort(changed_ranges.begin(), changed_ranges.end());
    std::size_t next = 0;
    for(const auto &[start, end] : changed_ranges) {
        if(!std::equal(source.processed_pixel_data.begin() + next, source.processed_pixel_data.begin() + start,
                       reparsed.processed_pixel_data.begin() + next)) throw std::runtime_error("Unselected pixel bytes changed");
        next = end;
    }
    if(!std::equal(source.processed_pixel_data.begin() + next, source.processed_pixel_data.end(),
                   reparsed.processed_pixel_data.begin() + next)) throw std::runtime_error("Unselected trailing pixel bytes changed");
    // Restore only the permitted codec/payload fields, then compare all authored
    // metadata, including dimensions, flags, sequences and registration points.
    auto restored = reparsed;
    restored.encoding_format = source.encoding_format;
    restored.processed_pixel_data = source.processed_pixel_data;
    for(std::size_t i = 0; i < restored.bitmap_data.size(); i++) {
        if(source.bitmap_data[i].format != HEK::BITMAP_DATA_FORMAT_BC7) continue;
        restored.bitmap_data[i].format = source.bitmap_data[i].format;
        restored.bitmap_data[i].flags = source.bitmap_data[i].flags;
        restored.bitmap_data[i].pixel_data_offset = source.bitmap_data[i].pixel_data_offset;
        restored.bitmap_data[i].pixel_data_size = source.bitmap_data[i].pixel_data_size;
    }
    if(!source.compare(&restored, false)) throw std::runtime_error("Unreviewed bitmap metadata changed");
    std::ostringstream record;
    record << "{\"tag\":" << quoted(name) << ",\"status\":\"converted\",\"source_formats\":" << source_formats(source)
        << ",\"target_format\":\"dxt5\",\"images_converted\":" << changed << ",\"images\":" << image_metadata(source, images)
        << ",\"sizes\":{\"tag_before\":" << original.size() << ",\"tag_after\":" << output.size()
        << ",\"pixel_before\":" << source.processed_pixel_data.size() << ",\"pixel_after\":" << reparsed.processed_pixel_data.size()
        << "},\"pixel_quality\":" << quality.json() << ",\"metadata_preserved\":true,\"unselected_pixels_preserved\":true}";
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
    // Reject all changed inputs before the first write. Source snapshots are
    // never opened for writing; failures stay isolated in the fresh overlay.
    for(const auto &item : prepared)
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original
                || read_file(checked_file(overlay / "tags", item.name)) != item.original)
            throw std::runtime_error("Input changed during conversion preparation");
    for(const auto &item : prepared) {
        auto target = checked_file(overlay / "tags", item.name);
        if(!File::save_file(target, item.output) || read_file(target) != item.output)
            throw std::runtime_error("Converted output write verification failed");
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original)
            throw std::runtime_error("Source snapshot changed during output writing");
        std::cout << item.record << '\n';
    }
}

int main(int argc, char **argv) {
    if(argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "Usage: convert-bitmaps --audit TAG_ROOT | --convert FRESH_OVERLAY\n"
                     "Conversion requires asset-paths.txt and independent identical source-snapshots/ and tags/.\n";
        return 0;
    }
    if(argc != 3) { std::cerr << "Expected --audit TAG_ROOT or --convert FRESH_OVERLAY\n"; return 2; }
    try {
        const std::string mode = argv[1];
        if(mode == "--audit") audit(argv[2]);
        else if(mode == "--convert") convert(argv[2]);
        else throw std::runtime_error("Unknown bitmap helper operation");
        return 0;
    }
    catch(const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
