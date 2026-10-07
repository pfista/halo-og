// SPDX-License-Identifier: GPL-3.0-only
// Offline native-capacity adaptation using existing authored lower mip bytes.
// No decoding, resampling, recompression, mip generation or stock substitution.
#include <invader/tag/parser/parser.hpp>
#include <invader/bitmap/bitmap_encode.hpp>
#include <invader/file/file.hpp>
#include <invader/tag/hek/header.hpp>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace Invader;
namespace fs = std::filesystem;
static constexpr std::size_t MAX_TAG_BYTES = 128 * 1024 * 1024;

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

static void checked_name(const std::string &name, bool bitmap = true) {
    fs::path relative(name);
    if(name.empty() || relative.is_absolute() || relative.lexically_normal().generic_string() != name
            || name.find(':') != std::string::npos || name.find('\\') != std::string::npos
            || (bitmap && relative.extension() != ".bitmap"))
        throw std::runtime_error("Expected a normalized relative bitmap path");
    for(unsigned char c : name) if(c < 0x20 || c == 0x7F) throw std::runtime_error("Control character in tag path");
    quoted(name);  // Validate UTF-8 before emitting a pathname as JSON.
    for(const auto &part : relative)
        if(part.empty() || part == "." || part == "..") throw std::runtime_error("Path traversal refused");
}

static fs::path checked_file(const fs::path &root, const std::string &name, bool bitmap = true,
                             std::size_t maximum = 0) {
    checked_name(name, bitmap);
    fs::path relative(name);
    auto at = regular_root(root);
    for(const auto &part : relative) {
        if(part.empty() || part == "." || part == "..") throw std::runtime_error("Path traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing, nonregular or hard-linked input refused");
    if(fs::file_size(at) > (maximum ? maximum : bitmap ? MAX_TAG_BYTES : 1024 * 1024)) throw std::runtime_error("Input exceeds the bounded size limit");
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
    std::size_t index, bytes, faces, removed_mips, removed_bytes;
    std::size_t width, height, depth, limit;
};

static std::set<std::string> read_shader_only(const fs::path &path) {
    auto file = checked_file(path.parent_path().empty() ? fs::path(".") : path.parent_path(), path.filename().string(), false);
    std::ifstream input(file);
    std::set<std::string> names;
    for(std::string name; std::getline(input, name);) {
        fs::path relative(name);
        if(name.empty() || relative.is_absolute() || relative.extension() != ".bitmap"
                || relative.lexically_normal().generic_string() != name || name.find('\\') != std::string::npos
                || name.find(':') != std::string::npos)
            throw std::runtime_error("Shader-only list needs normalized bitmap paths");
        for(unsigned char c : name) if(c < 0x20 || c == 0x7F) throw std::runtime_error("Control character in shader-only path");
        for(const auto &part : relative) if(part.empty() || part == "." || part == "..") throw std::runtime_error("Traversal in shader-only path");
        quoted(name);
        if(!names.insert(name).second) throw std::runtime_error("Duplicate shader-only bitmap path");
    }
    if(!input.eof()) throw std::runtime_error("Cannot read shader-only bitmap list");
    return names;
}

struct Consumer { std::string tag, tag_class, field; };
struct BitmapUsage {
    std::size_t tag_bytes, pixel_bytes;
    std::vector<Consumer> consumers;
};

static std::string normalized(std::string value) {
    std::replace(value.begin(), value.end(), '\\', '/');
    return value;
}

static std::string dependency_name(const Parser::Dependency &dependency) {
    auto extension = HEK::tag_fourcc_to_extension(dependency.tag_fourcc);
    if(!extension) throw std::runtime_error("Required dependency has an unknown tag class");
    std::string name = normalized(dependency.path) + '.' + extension;
    fs::path relative(name);
    if(relative.is_absolute() || relative.lexically_normal().generic_string() != name || name.find(':') != std::string::npos)
        throw std::runtime_error("Required dependency has an unsafe tag path");
    for(const auto &part : relative) if(part.empty() || part == "." || part == "..") throw std::runtime_error("Required dependency has a traversal path");
    for(unsigned char c : name) if(c < 0x20 || c == 0x7F) throw std::runtime_error("Required dependency path has control characters");
    quoted(name);
    return name;
}

static void walk_dependencies(const Parser::ParserStruct &tag, const std::string &owner,
                             const std::string &owner_class, const std::set<std::string> &required,
                             std::map<std::string, BitmapUsage> &bitmaps, const std::string &prefix = "",
                             std::size_t depth = 0) {
    if(depth > 64) throw std::runtime_error("Dependency field nesting exceeds the bounded inventory depth");
    using Value = Parser::ParserStructValue;
    for(const auto &value : tag.get_values()) {
        if(!value.get_member_name()) continue;
        auto field = prefix + value.get_member_name();
        if(value.get_type() == Value::VALUE_TYPE_DEPENDENCY) {
            const auto &dependency = value.get_dependency();
            if(dependency.path.empty()) continue;
            auto name = dependency_name(dependency);
            if(!required.count(name)) throw std::runtime_error("Required dependency is absent from complete usage index: " + name);
            if(dependency.tag_fourcc == HEK::TAG_FOURCC_BITMAP) {
                auto found = bitmaps.find(name);
                if(found == bitmaps.end()) throw std::runtime_error("Required bitmap is absent from parsed usage inventory: " + name);
                found->second.consumers.push_back({owner, owner_class, field});
            }
        }
        else if(value.get_type() == Value::VALUE_TYPE_REFLEXIVE) {
            if(value.get_array_size() > 1024 * 1024) throw std::runtime_error("Dependency field array exceeds bounded inventory capacity");
            for(std::size_t i = 0; i < value.get_array_size(); i++)
                walk_dependencies(value.get_object_in_array(i), owner, owner_class, required, bitmaps,
                                  field + '[' + std::to_string(i) + "].", depth + 1);
        }
    }
}

static void usage(const fs::path &input) {
    const auto index = regular_root(input);
    auto roots_file = checked_file(index, "roots.txt", false);
    auto required_file = checked_file(index, "required-tags.txt", false);
    std::vector<fs::path> roots;
    std::set<fs::path> unique_roots;
    std::ifstream root_lines(roots_file);
    for(std::string name; std::getline(root_lines, name);) {
        if(name.empty() || !fs::path(name).is_absolute()) throw std::runtime_error("Usage roots must be priority-ordered absolute paths");
        for(unsigned char c : name) if(c < 0x20 || c == 0x7F) throw std::runtime_error("Control character in usage root");
        auto root = regular_root(name);
        if(!unique_roots.insert(root).second) throw std::runtime_error("Duplicate usage root");
        roots.push_back(root);
    }
    if(!root_lines.eof() || roots.empty()) throw std::runtime_error("Cannot read a nonempty usage roots list");
    std::set<std::string> required;
    std::ifstream names(required_file);
    for(std::string name; std::getline(names, name);)
    {
        checked_name(name, false);
        if(!required.insert(name).second) throw std::runtime_error("Duplicate required tag");
    }
    if(!names.eof() || required.empty()) throw std::runtime_error("Cannot read a nonempty required tag list");
    std::map<std::string, BitmapUsage> bitmaps;
    std::map<std::string, fs::path> winners;
    std::vector<std::pair<std::string, std::string>> failures;
    // First parse and type-check every required winning input. No proof records
    // are printed until this and the subsequent complete dependency walk pass.
    for(const auto &name : required) {
        try {
            std::optional<fs::path> winner;
            for(const auto &root : roots) {
                auto candidate = root / name;
                if(fs::exists(candidate) || fs::is_symlink(fs::symlink_status(candidate))) {
                    winner = checked_file(root, name, false, MAX_TAG_BYTES);
                    break;
                }
            }
            if(!winner) throw std::runtime_error("Required tag has no winning input in usage roots");
            auto bytes = read_file(*winner);
            auto extension = fs::path(name).extension().string();
            if(extension.empty()) throw std::runtime_error("Required tag lacks a class extension");
            HEK::TagFileHeader::validate_header(reinterpret_cast<const HEK::TagFileHeader *>(bytes.data()), bytes.size(),
                                               HEK::tag_extension_to_fourcc(extension.c_str() + 1));
            auto tag = Parser::ParserStruct::parse_hek_tag_file(bytes.data(), bytes.size());
            winners.emplace(name, *winner);
            if(extension == ".bitmap") {
                auto &bitmap = dynamic_cast<Parser::Bitmap &>(*tag);
                bitmaps.emplace(name, BitmapUsage{bytes.size(), bitmap.processed_pixel_data.size(), {}});
            }
        }
        catch(const std::exception &error) { failures.emplace_back(name, error.what()); }
    }
    if(failures.empty()) for(const auto &name : required) {
        try {
            auto path = winners.at(name);
            auto bytes = read_file(checked_file(path.parent_path(), path.filename().string(), false, MAX_TAG_BYTES));
            auto extension = fs::path(name).extension().string();
            HEK::TagFileHeader::validate_header(reinterpret_cast<const HEK::TagFileHeader *>(bytes.data()), bytes.size(),
                                               HEK::tag_extension_to_fourcc(extension.c_str() + 1));
            auto tag = Parser::ParserStruct::parse_hek_tag_file(bytes.data(), bytes.size());
            if(extension == ".bitmap") {
                auto &bitmap = dynamic_cast<Parser::Bitmap &>(*tag);
                auto &item = bitmaps.at(name);
                if(item.tag_bytes != bytes.size() || item.pixel_bytes != bitmap.processed_pixel_data.size())
                    throw std::runtime_error("Required bitmap changed during usage inventory");
            }
            walk_dependencies(*tag, name, extension.substr(1), required, bitmaps);
        }
        catch(const std::exception &error) { failures.emplace_back(name, error.what()); }
    }
    if(!failures.empty()) {
        for(const auto &[name, reason] : failures)
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"unsupported\",\"shader_only\":false,\"consumers\":[],\"reason\":"
                      << quoted(reason) << ",\"metadata\":{\"consumer_count\":0,\"usage_scope\":\"required_reachable_tags\"}}\n";
        throw std::runtime_error("Required tag usage inventory is incomplete; no shader-only proof was emitted");
    }
    for(const auto &[name, bitmap] : bitmaps) {
        const bool shader_only = !bitmap.consumers.empty() && std::all_of(bitmap.consumers.begin(), bitmap.consumers.end(), [](const auto &consumer) {
            return consumer.tag_class == "shader_model" || consumer.tag_class == "shader_environment";
        });
        std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"classified\",\"shader_only\":" << (shader_only ? "true" : "false")
                  << ",\"consumers\":[";
        bool separator = false;
        for(const auto &consumer : bitmap.consumers) {
            if(separator) std::cout << ',';
            separator = true;
            std::cout << "{\"tag\":" << quoted(consumer.tag) << ",\"class\":" << quoted(consumer.tag_class)
                      << ",\"field\":" << quoted(consumer.field) << '}';
        }
        std::cout << "],\"metadata\":{\"consumer_count\":" << bitmap.consumers.size() << ",\"usage_scope\":\"required_reachable_tags\",\"tag_bytes\":"
                  << bitmap.tag_bytes << ",\"pixel_bytes\":" << bitmap.pixel_bytes << "}}\n";
    }
}

static bool power_of_two(std::size_t value) { return value && !(value & (value - 1)); }

static std::vector<Image> inspect(const Parser::Bitmap &tag, bool shader_only = false) {
    if(tag.bitmap_data.size() > 4096 || tag.processed_pixel_data.size() > MAX_TAG_BYTES)
        throw std::runtime_error("Bitmap image table or pixel data exceeds the bounded size limit");
    std::vector<Image> images;
    std::vector<std::pair<std::size_t, std::size_t>> ranges;
    for(std::size_t i = 0; i < tag.bitmap_data.size(); i++) {
        const auto &b = tag.bitmap_data[i];
        format_name(b.format); type_name(b.type);
        if(!b.width || !b.height || !b.depth) throw std::runtime_error("Bitmap dimensions must be nonzero");
        if(b.flags & HEK::BITMAP_DATA_FLAGS_FLAG_SWIZZLED) throw std::runtime_error("HEK bitmap payload must be unswizzled");
        if((b.type != HEK::BITMAP_DATA_TYPE_3D_TEXTURE && b.depth != 1)
                || (b.type == HEK::BITMAP_DATA_TYPE_CUBE_MAP && b.width != b.height))
            throw std::runtime_error("Bitmap dimensions do not match image type");
        auto largest = std::max({std::size_t(b.width), std::size_t(b.height), std::size_t(b.depth)});
        std::size_t maximum_mips = 0;
        for(; largest > 1; largest /= 2) maximum_mips++;
        if(b.mipmap_count > maximum_mips) throw std::runtime_error("Mip count exceeds authored dimensions");
        const auto bytes = BitmapEncode::bitmap_data_size(b.width, b.height, b.depth, b.mipmap_count, b.format, b.type);
        const auto offset = std::size_t(b.pixel_data_offset);
        if(offset > tag.processed_pixel_data.size() || bytes > tag.processed_pixel_data.size() - offset)
            throw std::runtime_error("Bitmap image range exceeds processed pixel data");
        ranges.emplace_back(offset, offset + bytes);
        const std::size_t limit = b.type == HEK::BITMAP_DATA_TYPE_CUBE_MAP ? 512 :
                                  b.type == HEK::BITMAP_DATA_TYPE_3D_TEXTURE ? 256 : 2048;
        Image image = {i, bytes, b.type == HEK::BITMAP_DATA_TYPE_CUBE_MAP ? 6U : 1U,
                       0, 0, b.width, b.height, b.depth, limit};
        while(image.width > limit || image.height > limit || image.depth > limit) {
            if(image.removed_mips >= b.mipmap_count)
                throw std::runtime_error("Oversized bitmap has insufficient existing authored mips for the native limit");
            image.removed_bytes += BitmapEncode::bitmap_data_size(image.width, image.height, image.depth,
                                                                   0, b.format, b.type);
            image.width = std::max<std::size_t>(1, image.width / 2);
            image.height = std::max<std::size_t>(1, image.height / 2);
            image.depth = std::max<std::size_t>(1, image.depth / 2);
            image.removed_mips++;
        }
        if(image.removed_mips) {
            if(tag.type == HEK::BITMAP_TYPE_INTERFACE_BITMAPS || tag.type == HEK::BITMAP_TYPE_SPRITES
                    || (tag.flags & (HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE | HEK::BITMAP_FLAGS_FLAG_FORCE_HUD_USE_HIGHRES_SCALE))
                    || std::any_of(tag.bitmap_group_sequence.begin(), tag.bitmap_group_sequence.end(),
                                   [](const auto &sequence) { return !sequence.sprites.empty(); }))
                throw std::runtime_error("Interface/HUD/sprite mip selection requires a separate placement review");
            if(!shader_only && (b.registration_point.x != 0 || b.registration_point.y != 0))
                throw std::runtime_error("Nonzero image registration point requires a separate placement/usage review");
            if(!power_of_two(b.width) || !power_of_two(b.height) || !power_of_two(b.depth))
                throw std::runtime_error("Native mip selection does not repair non-power-of-two texture layouts");
            const auto retained = BitmapEncode::bitmap_data_size(image.width, image.height, image.depth,
                                                                 b.mipmap_count - image.removed_mips, b.format, b.type);
            if(image.removed_bytes > image.bytes || retained != image.bytes - image.removed_bytes)
                throw std::runtime_error("Existing mip prefix does not match the remaining authored payload");
        }
        images.push_back(image);
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
        if(!image.removed_mips) continue;
        const auto &b = tag.bitmap_data[image.index];
        if(separator) out << ',';
        separator = true;
        out << "{\"index\":" << image.index << ",\"type\":" << quoted(type_name(b.type))
            << ",\"format\":" << quoted(format_name(b.format)) << ",\"faces\":" << image.faces
            << ",\"native_limit\":{\"width\":" << image.limit << ",\"height\":" << image.limit
            << ",\"depth\":" << (b.type == HEK::BITMAP_DATA_TYPE_3D_TEXTURE ? image.limit : 1)
            << "},\"before\":{\"width\":" << b.width << ",\"height\":" << b.height << ",\"depth\":" << b.depth
            << ",\"mips\":" << b.mipmap_count + 1 << "},\"after\":{\"width\":" << image.width
            << ",\"height\":" << image.height << ",\"depth\":" << image.depth
            << ",\"mips\":" << b.mipmap_count + 1 - image.removed_mips << "},\"mips_removed\":" << image.removed_mips
            << ",\"bytes_removed\":" << image.removed_bytes << ",\"retained_bytes\":" << image.bytes - image.removed_bytes
            << ",\"registration_point\":{\"x\":" << b.registration_point.x << ",\"y\":" << b.registration_point.y
            << "},\"registration_point_preserved\":true}";
    }
    return out.str() + ']';
}

// Include raw metadata before layout inspection, so an unsupported authored
// image still explains which capacity or placement decision blocks conversion.
static std::string raw_metadata(const Parser::Bitmap &tag, std::size_t tag_bytes) {
    std::ostringstream out;
    out << "{\"tag_bytes\":" << tag_bytes << ",\"pixel_bytes\":" << tag.processed_pixel_data.size()
        << ",\"bitmap_type\":" << static_cast<unsigned>(tag.type) << ",\"bitmap_flags\":" << tag.flags
        << ",\"image_count\":" << tag.bitmap_data.size()
        << ",\"metadata_images_truncated\":" << (tag.bitmap_data.size() > 4096 ? "true" : "false") << ",\"images\":[";
    bool separator = false;
    for(std::size_t i = 0; i < std::min<std::size_t>(tag.bitmap_data.size(), 4096); i++) {
        if(separator) out << ',';
        separator = true;
        const auto &b = tag.bitmap_data[i];
        out << "{\"index\":" << i << ",\"type\":" << static_cast<unsigned>(b.type)
            << ",\"format\":" << static_cast<unsigned>(b.format) << ",\"width\":" << b.width
            << ",\"height\":" << b.height << ",\"depth\":" << b.depth << ",\"mips\":" << b.mipmap_count + 1
            << ",\"pixel_offset\":" << b.pixel_data_offset << ",\"pixel_bytes\":" << b.pixel_data_size
            << ",\"registration_point\":{\"x\":" << b.registration_point.x << ",\"y\":" << b.registration_point.y << "}}";
    }
    out << "]}";
    return out.str();
}

static void audit(const fs::path &input, const std::set<std::string> &shader_only) {
    const auto root = regular_root(input);
    std::vector<std::string> names;
    for(const auto &entry : fs::recursive_directory_iterator(root))
        if(entry.path().extension() == ".bitmap") names.push_back(entry.path().lexically_relative(root).generic_string());
    std::sort(names.begin(), names.end());
    for(const auto &name : names) {
        std::string formats = "[]";
        std::string metadata = "{}";
        try {
            auto path = checked_file(root, name);
            auto bytes = read_file(path);
            auto tag = Parser::Bitmap::parse_hek_tag_file(bytes.data(), bytes.size());
            metadata = raw_metadata(tag, bytes.size());
            formats = source_formats(tag);
            auto images = inspect(tag, shader_only.count(name));
            if(std::none_of(images.begin(), images.end(), [](const auto &image) { return image.removed_mips > 0; })) continue;
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"convertible\",\"source_formats\":" << formats
                << ",\"target_format\":\"existing_authored_mips\",\"metadata\":{\"tag_bytes\":" << bytes.size()
                << ",\"pixel_bytes\":" << tag.processed_pixel_data.size() << ",\"images\":" << image_metadata(tag, images)
                << ",\"shader_only_usage_verified\":" << (shader_only.count(name) ? "true" : "false") << "}}\n";
        }
        catch(const std::exception &error) {
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"unsupported\",\"source_formats\":" << formats
                << ",\"reason\":" << quoted(error.what()) << ",\"metadata\":" << metadata << "}\n";
        }
    }
}

struct Prepared {
    std::string name, record;
    std::vector<std::byte> original, output;
};

static Prepared prepare(const fs::path &overlay, const std::string &name, bool shader_only) {
    auto snapshot = checked_file(overlay / "source-snapshots", name);
    auto target = checked_file(overlay / "tags", name);
    if(fs::equivalent(snapshot, target)) throw std::runtime_error("Snapshot and output must be independent copies");
    auto original = read_file(snapshot), current = read_file(target);
    if(original != current) throw std::runtime_error("Source snapshot differs from output input; repeat conversion refused");
    auto source = Parser::Bitmap::parse_hek_tag_file(original.data(), original.size());
    auto images = inspect(source, shader_only);
    auto converted = source;
    std::vector<std::pair<std::size_t, std::size_t>> removed;
    std::size_t selected = 0, removed_bytes = 0;
    for(const auto &image : images) if(image.removed_mips) {
        const auto &b = source.bitmap_data[image.index];
        removed.emplace_back(b.pixel_data_offset, b.pixel_data_offset + image.removed_bytes);
        selected++;
        removed_bytes += image.removed_bytes;
    }
    if(!selected) throw std::runtime_error("Selected tag has no image exceeding native dimension limits");
    std::sort(removed.begin(), removed.end());
    std::vector<std::byte> pixels;
    pixels.reserve(source.processed_pixel_data.size() - removed_bytes);
    std::size_t next = 0;
    for(const auto &[start, end] : removed) {
        pixels.insert(pixels.end(), source.processed_pixel_data.begin() + next, source.processed_pixel_data.begin() + start);
        next = end;
    }
    pixels.insert(pixels.end(), source.processed_pixel_data.begin() + next, source.processed_pixel_data.end());
    auto mapped_offset = [&removed](std::size_t position) {
        std::size_t shift = 0;
        for(const auto &[start, end] : removed) {
            if(position > start && position < end) throw std::runtime_error("Cannot map a removed mip byte");
            if(end <= position) shift += end - start;
        }
        return position - shift;
    };
    for(const auto &image : images) {
        auto &b = converted.bitmap_data[image.index];
        b.pixel_data_offset = mapped_offset(source.bitmap_data[image.index].pixel_data_offset + image.removed_bytes);
        if(image.removed_mips) {
            b.width = image.width; b.height = image.height; b.depth = image.depth;
            b.mipmap_count -= image.removed_mips;
            b.pixel_data_size = image.bytes - image.removed_bytes;
        }
    }
    converted.processed_pixel_data = std::move(pixels);
    auto output = converted.generate_hek_tag_data(HEK::TAG_FOURCC_BITMAP, false);
    auto reparsed = Parser::Bitmap::parse_hek_tag_file(output.data(), output.size());
    if(!converted.compare(&reparsed, false)) throw std::runtime_error("Selected mip bitmap did not reparse identically");
    if(reparsed.processed_pixel_data.size() != source.processed_pixel_data.size() - removed_bytes)
        throw std::runtime_error("Selected mip payload reduction does not match removed byte ranges");
    for(const auto &image : images) {
        const auto &before = source.bitmap_data[image.index];
        const auto &after = reparsed.bitmap_data[image.index];
        auto retained = image.bytes - image.removed_bytes;
        auto offset = std::size_t(after.pixel_data_offset);
        if(offset > reparsed.processed_pixel_data.size() || retained > reparsed.processed_pixel_data.size() - offset
                || !std::equal(source.processed_pixel_data.begin() + before.pixel_data_offset + image.removed_bytes,
                               source.processed_pixel_data.begin() + before.pixel_data_offset + image.bytes,
                               reparsed.processed_pixel_data.begin() + offset))
            throw std::runtime_error("Retained authored mip/image bytes changed");
    }
    // The new payload is exactly the original minus selected leading mips;
    // unallocated gaps and every unselected image were copied unchanged too.
    auto restored = reparsed;
    restored.processed_pixel_data = source.processed_pixel_data;
    for(const auto &image : images) {
        auto &b = restored.bitmap_data[image.index];
        const auto &old = source.bitmap_data[image.index];
        b.pixel_data_offset = old.pixel_data_offset;
        b.pixel_data_size = old.pixel_data_size;
        if(image.removed_mips) {
            b.width = old.width; b.height = old.height; b.depth = old.depth;
            b.mipmap_count = old.mipmap_count;
        }
    }
    if(!source.compare(&restored, false)) throw std::runtime_error("Unreviewed bitmap metadata changed");
    std::ostringstream record;
    record << "{\"tag\":" << quoted(name) << ",\"status\":\"converted\",\"source_formats\":" << source_formats(source)
        << ",\"target_format\":\"existing_authored_mips\",\"images_selected\":" << selected
        << ",\"images\":" << image_metadata(source, images)
        << ",\"sizes\":{\"tag_before\":" << original.size() << ",\"tag_after\":" << output.size()
        << ",\"pixel_before\":" << source.processed_pixel_data.size() << ",\"pixel_after\":" << reparsed.processed_pixel_data.size()
        << "},\"retained_mip_bytes_exact\":true,\"metadata_preserved_except_dimensions\":true"
           ",\"unselected_pixels_preserved\":true,\"authored_mip_generation_setting_preserved\":true"
        << ",\"shader_only_usage_verified\":" << (shader_only ? "true" : "false")
        << ",\"registration_points_preserved\":true,\"visual_validation\":\"pending\"}";
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
    // This list is generated by the orchestrator from the complete --usage
    // inventory. The native helper never treats an authored tag name as proof.
    std::set<std::string> shader_only;
    auto proof = overlay / "shader-only.txt";
    if(fs::exists(proof) || fs::is_symlink(fs::symlink_status(proof))) shader_only = read_shader_only(proof);
    std::vector<Prepared> prepared;
    for(const auto &name : names) prepared.push_back(prepare(overlay, name, shader_only.count(name)));
    for(const auto &item : prepared)
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original
                || read_file(checked_file(overlay / "tags", item.name)) != item.original)
            throw std::runtime_error("Input changed during mip-selection preparation");
    for(const auto &item : prepared) {
        auto target = checked_file(overlay / "tags", item.name);
        if(!File::save_file(target, item.output) || read_file(target) != item.output)
            throw std::runtime_error("Selected mip output write verification failed");
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original)
            throw std::runtime_error("Source snapshot changed during output writing");
        std::cout << item.record << '\n';
    }
}

int main(int argc, char **argv) {
    if(argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "Usage: select-native-mips --usage INDEX | --audit TAG_ROOT [--shader-only LIST] | --convert FRESH_OVERLAY\n"
                     "Usage requires roots.txt and the complete required-tags.txt dependency list.\n"
                     "Conversion requires asset-paths.txt and independent identical source-snapshots/ and tags/.\n"
                     "Optional shader-only.txt must come from the complete usage inventory.\n";
        return 0;
    }
    if(argc != 3 && argc != 5) { std::cerr << "Expected --usage INDEX, --audit TAG_ROOT [--shader-only LIST], or --convert FRESH_OVERLAY\n"; return 2; }
    try {
        const std::string mode = argv[1];
        if(mode == "--audit") {
            std::set<std::string> shader_only;
            if(argc == 5) {
                if(std::string(argv[3]) != "--shader-only") throw std::runtime_error("Expected --shader-only LIST");
                shader_only = read_shader_only(argv[4]);
            }
            audit(argv[2], shader_only);
        }
        else if(mode == "--convert" && argc == 3) convert(argv[2]);
        else if(mode == "--usage" && argc == 3) usage(argv[2]);
        else throw std::runtime_error("Unknown native-mip helper operation");
        return 0;
    }
    catch(const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
