// SPDX-License-Identifier: GPL-3.0-only
// Offline MCC HUD normalization against canonical native Xbox sequence geometry.
// Links the reviewed Invader decoder/encoder; writes only copied overlay tags.
#include <invader/tag/parser/parser.hpp>
#include <invader/file/file.hpp>
#include <invader/bitmap/bitmap_encode.hpp>
#include <map>
#include <memory>
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

static fs::path checked_file(const fs::path &root, const std::string &name, bool tag = true) {
    fs::path relative(name);
    if(name.empty() || relative.is_absolute() || relative.lexically_normal().generic_string() != name
            || name.find(':') != std::string::npos || name.find('\\') != std::string::npos
            || (tag && relative.extension().empty()))
        throw std::runtime_error("Expected a normalized relative tag path");
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
    if(fs::file_size(at) > (tag ? MAX_TAG_BYTES : 1024 * 1024)) throw std::runtime_error("Input exceeds the bounded size limit");
    return at;
}

static std::vector<std::byte> read_file(const fs::path &path) {
    auto bytes = File::open_file(path);
    if(!bytes || bytes->size() > MAX_TAG_BYTES) throw std::runtime_error("Cannot read bounded input file");
    return std::move(*bytes);
}

using Value = Parser::ParserStructValue;
using Numbers = std::vector<Value::Number>;
static std::vector<std::string> split(const std::string &text, char delimiter) {
    std::vector<std::string> result; std::stringstream stream(text); std::string part;
    while(std::getline(stream, part, delimiter)) result.push_back(part);
    return result;
}
static std::vector<std::string> lines(const fs::path &root, const std::string &name) {
    std::ifstream input(checked_file(root, name, false)); std::vector<std::string> result; std::string line;
    while(std::getline(input, line)) {
        if(!line.empty() && line.back() == '\r') line.pop_back();
        if(!line.empty()) result.push_back(line);
    }
    if(!input.eof()) throw std::runtime_error("Failed reading index or rules");
    return result;
}
static Value *member(Parser::ParserStruct &object, const std::string &name) {
    auto &values = object.get_values();
    auto it = std::find_if(values.begin(), values.end(), [&](auto &v) {
        return v.get_member_name() && name == v.get_member_name();
    });
    return it == values.end() ? nullptr : &*it;
}
static Value &field_at(Parser::ParserStruct &root, const std::string &path) {
    auto parts = split(path, '.'); auto *object = &root;
    for(std::size_t i = 0; i < parts.size(); i++) {
        auto opening = parts[i].find('['); auto name = parts[i].substr(0, opening);
        auto *value = member(*object, name);
        if(!value) throw std::runtime_error("Missing field: " + path);
        if(opening != std::string::npos) {
            auto closing = parts[i].find(']', opening);
            if(closing != parts[i].size() - 1) throw std::runtime_error("Malformed array field: " + path);
            auto index_text = parts[i].substr(opening + 1, closing - opening - 1);
            if(index_text.empty() || index_text.find_first_not_of("0123456789") != std::string::npos)
                throw std::runtime_error("Malformed array index");
            auto index = std::stoull(index_text);
            if(value->get_type() != Value::VALUE_TYPE_REFLEXIVE || index >= value->get_array_size())
                throw std::runtime_error("Invalid array field: " + path);
            object = &value->get_object_in_array(index);
        }
        else if(i + 1 == parts.size()) return *value;
        else throw std::runtime_error("Non-array intermediate field: " + path);
    }
    throw std::runtime_error("Missing final field: " + path);
}
static double numeric(const Value::Number &number) {
    auto result = std::visit([](auto n) { return static_cast<double>(n); }, number);
    if(!std::isfinite(result)) throw std::runtime_error("Nonfinite numeric field");
    return result;
}
static std::string numbers_json(const Numbers &values) {
    std::ostringstream out; out << '[' << std::setprecision(17);
    for(std::size_t i = 0; i < values.size(); i++) { if(i) out << ','; out << numeric(values[i]); }
    out << ']'; return out.str();
}
static Value::Number checked_target(const Value &field, double target) {
    if(!std::isfinite(target)) throw std::runtime_error("Nonfinite numeric target");
    auto type = field.get_type();
    if(field.get_number_format() == Value::NUMBER_FORMAT_INT
            || type == Value::VALUE_TYPE_ENUM || type == Value::VALUE_TYPE_BITMASK) {
        if(target != std::round(target)) throw std::runtime_error("Nonintegral integer target");
        double minimum, maximum;
        switch(type) {
            case Value::VALUE_TYPE_INT8: minimum = -128; maximum = 127; break;
            case Value::VALUE_TYPE_UINT8:
            case Value::VALUE_TYPE_COLORARGBINT: minimum = 0; maximum = 255; break;
            case Value::VALUE_TYPE_INT16:
            case Value::VALUE_TYPE_POINT2DINT:
            case Value::VALUE_TYPE_RECTANGLE2D: minimum = -32768; maximum = 32767; break;
            case Value::VALUE_TYPE_ENUM:
            case Value::VALUE_TYPE_BITMASK:
            case Value::VALUE_TYPE_INDEX:
            case Value::VALUE_TYPE_UINT16: minimum = 0; maximum = 65535; break;
            case Value::VALUE_TYPE_INT32: minimum = -2147483648.0; maximum = 2147483647.0; break;
            case Value::VALUE_TYPE_UINT32: minimum = 0; maximum = 4294967295.0; break;
            default: throw std::runtime_error("Unsupported integer field");
        }
        if(target < minimum || target > maximum) throw std::runtime_error("Target exceeds numeric storage");
        return static_cast<std::int64_t>(target);
    }
    if(field.get_number_format() != Value::NUMBER_FORMAT_FLOAT) throw std::runtime_error("Unsupported numeric field");
    float stored = static_cast<float>(target);
    if(!std::isfinite(stored) || (target && !stored)) throw std::runtime_error("Target exceeds float storage");
    return static_cast<double>(stored);
}
static std::string join_field(const std::string &base, const std::string &name) {
    return base.empty() ? name : base + "." + name;
}
static bool ends_with(const std::string &text, const std::string &suffix) {
    return text.size() >= suffix.size() && text.compare(text.size() - suffix.size(), suffix.size(), suffix) == 0;
}
static std::string dependency_name(const Value &value) {
    if(value.get_type() != Value::VALUE_TYPE_DEPENDENCY) return {};
    const auto &dependency = value.get_dependency();
    if(dependency.path.empty() || dependency.tag_fourcc != HEK::TAG_FOURCC_BITMAP) return {};
    auto path = dependency.path; std::replace(path.begin(), path.end(), '\\', '/');
    return path + ".bitmap";
}
struct Index {
    std::vector<fs::path> roots;
    fs::path stock;
    std::set<std::string> required;
    std::map<std::string, std::shared_ptr<Parser::ParserStruct>> source_tags, stock_tags;
    bool native_fallback(const std::string &name) const {
        for(const auto &root : roots) if(fs::exists(root / name)) return fs::equivalent(root, stock);
        throw std::runtime_error("Cannot resolve tag provenance: " + name);
    }
    std::shared_ptr<Parser::ParserStruct> load(const std::string &name, bool canonical = false) {
        auto &cache = canonical ? stock_tags : source_tags;
        if(auto found = cache.find(name); found != cache.end()) return found->second;
        std::vector<fs::path> candidates = canonical ? std::vector<fs::path>{stock} : roots;
        for(const auto &root : candidates) {
            if(!fs::exists(root / name)) continue;
            auto bytes = read_file(checked_file(root, name));
            auto parsed = Parser::ParserStruct::parse_hek_tag_file(bytes.data(), bytes.size());
            return cache[name] = std::shared_ptr<Parser::ParserStruct>(std::move(parsed));
        }
        if(canonical) return {};
        throw std::runtime_error("Required source tag is missing: " + name);
    }
};
struct Rule { std::string field, reason; Numbers before, after; };
struct Decision {
    std::string tag;
    std::map<std::string, Rule> rules;
    std::vector<std::string> evidence, warnings, failures;
    unsigned bitmap_divisor = 0;
};
static void add_rule(Decision &decision, Parser::ParserStruct &tag, const std::string &field,
        const std::vector<double> &targets, const std::string &reason) {
    auto &value = field_at(tag, field); auto before = value.get_values(); Numbers after;
    if(before.size() != targets.size()) throw std::runtime_error("Target cardinality mismatch");
    for(auto target : targets) after.push_back(checked_target(value, target));
    if(before == after) return;
    if(auto found = decision.rules.find(field); found != decision.rules.end() && found->second.after != after)
        throw std::runtime_error("Conflicting normalization rules: " + field);
    decision.rules[field] = {field, reason, before, after};
}
struct Frame { double width, height; unsigned image; };
static std::vector<Frame> frames(const Parser::Bitmap &tag, std::size_t sequence) {
    if(sequence >= tag.bitmap_group_sequence.size()) throw std::runtime_error("HUD sequence index exceeds bitmap");
    const auto &s = tag.bitmap_group_sequence[sequence]; std::vector<Frame> out;
    if(!s.sprites.empty()) {
        for(const auto &sprite : s.sprites) {
            auto index = sprite.bitmap_index;
            if(index >= tag.bitmap_data.size()) throw std::runtime_error("HUD sprite image index exceeds bitmap");
            const auto &image = tag.bitmap_data[index];
            double width = sprite.right - sprite.left, height = sprite.bottom - sprite.top;
            if(tag.type != HEK::BITMAP_TYPE_INTERFACE_BITMAPS) { width *= image.width; height *= image.height; }
            if(!(width > 0) || !(height > 0) || !std::isfinite(width) || !std::isfinite(height))
                throw std::runtime_error("HUD sprite has invalid footprint");
            out.push_back({width, height, static_cast<unsigned>(index)});
        }
    }
    else {
        for(std::size_t i = 0; i < s.bitmap_count; i++) {
            auto index = s.first_bitmap_index + i;
            if(index >= tag.bitmap_data.size()) throw std::runtime_error("HUD sequence image range exceeds bitmap");
            const auto &image = tag.bitmap_data[index]; out.push_back({double(image.width), double(image.height), unsigned(index)});
        }
    }
    if(out.empty()) throw std::runtime_error("HUD sequence has no frames");
    return out;
}
static std::size_t stock_sequence(const Parser::Bitmap &source, const Parser::Bitmap &stock, std::size_t sequence) {
    if(sequence >= source.bitmap_group_sequence.size()) throw std::runtime_error("Missing source sequence");
    const std::string name = source.bitmap_group_sequence[sequence].name.string;
    if(sequence < stock.bitmap_group_sequence.size() && name == stock.bitmap_group_sequence[sequence].name.string)
        return sequence;
    if(name.empty()) throw std::runtime_error("Unmatched unnamed HUD sequence");
    std::size_t match = stock.bitmap_group_sequence.size(), count = 0;
    for(std::size_t i = 0; i < stock.bitmap_group_sequence.size(); i++) if(name == stock.bitmap_group_sequence[i].name.string) {
        match = i; count++;
    }
    if(count != 1) throw std::runtime_error("HUD sequence lacks unique canonical match");
    return match;
}
struct Density { unsigned divisor; std::string evidence; };
static Density density(const Parser::Bitmap &source, const Parser::Bitmap &stock,
        const std::string &source_name, const std::string &stock_name, std::size_t sequence) {
    auto matched = stock_sequence(source, stock, sequence);
    auto a = frames(source, sequence), b = frames(stock, matched);
    if(a.size() != b.size()) throw std::runtime_error("HUD frame count differs from canonical sequence");
    unsigned factor = 0; std::ostringstream proof;
    proof << "{\"source_bitmap\":" << quoted(source_name) << ",\"stock_bitmap\":" << quoted(stock_name)
          << ",\"source_sequence\":" << sequence << ",\"stock_sequence\":" << matched
          << ",\"method\":\"matched_sequence_frame_footprints\",\"frames\":[" << std::setprecision(17);
    for(std::size_t i = 0; i < a.size(); i++) {
        double rx = a[i].width / b[i].width, ry = a[i].height / b[i].height;
        unsigned next = 0;
        for(unsigned candidate : {1U, 2U, 4U}) if(std::abs(rx - candidate) <= 0.0001 && std::abs(ry - candidate) <= 0.0001) next = candidate;
        if(!next || (factor && factor != next)) throw std::runtime_error("HUD footprint ratios are altered or nonuniform; cannot infer native density");
        factor = next;
        if(i) proof << ',';
        proof << "{\"source_image\":" << a[i].image << ",\"stock_image\":" << b[i].image
              << ",\"source\":[" << a[i].width << ',' << a[i].height << "],\"stock\":[" << b[i].width << ','
              << b[i].height << "],\"ratio\":[" << rx << ',' << ry << "]}";
    }
    proof << "],\"divisor\":" << factor << '}'; return {factor, proof.str()};
}
struct Use {
    std::string hud, bitmap, stock_bitmap, width, height, flags, anchor;
    std::size_t sequence = 0;
    bool physical = false, all_sequences = false;
};
static std::string canonical_dependency(Parser::ParserStruct *canonical, const std::string &field) {
    if(!canonical) return {};
    try { return dependency_name(field_at(*canonical, field)); } catch(const std::exception &) { return {}; }
}
static void collect_uses(Parser::ParserStruct &object, Parser::ParserStruct *canonical,
        const std::string &hud, const std::string &path, std::vector<Use> &uses,
        std::string inherited_bitmap = {}, std::string inherited_stock = {}) {
    std::vector<std::pair<std::string, std::string>> candidates;
    for(auto &value : object.get_values()) {
        if(!value.get_member_name()) continue;
        std::string name = value.get_member_name(); auto bitmap = dependency_name(value);
        if(bitmap.empty()) continue;
        auto full = join_field(path, name), stock = canonical_dependency(canonical, full);
        bool fixed = (ends_with(hud, ".hud_number") && name == "digits_bitmap")
                || (ends_with(hud, ".hud_globals") && (name == "icon_bitmap" || name == "arrow_bitmap" || name == "hud_damage_indicator_bitmap"));
        if(fixed) { uses.push_back({hud, bitmap, stock, {}, {}, {}, {}, 0, true, true}); continue; }
        for(const std::string suffix : {"interface_bitmap", "meter_bitmap"}) if(ends_with(name, suffix)) {
            auto prefix = name.substr(0, name.size() - suffix.size());
            auto *width = member(object, prefix + "width_scale"), *height = member(object, prefix + "height_scale");
            if(!width || !height) continue;
            auto *seq = member(object, prefix + "sequence_index");
            std::size_t sequence = seq && seq->get_values().size() == 1 ? numeric(seq->get_values()[0]) : 0;
            if(sequence == 65535) continue; // NONE: this placement does not draw a bitmap.
            uses.push_back({hud, bitmap, stock, join_field(path, prefix + "width_scale"), join_field(path, prefix + "height_scale"),
                member(object, prefix + "scaling_flags") ? join_field(path, prefix + "scaling_flags") : "",
                member(object, prefix + "anchor_offset") ? join_field(path, prefix + "anchor_offset") : "", sequence});
        }
        // Child overlay/crosshair placement blocks inherit their parent's bitmap.
        if(name == "crosshair_bitmap" || name == "overlay_bitmap" || name == "total_grenades_overlay_bitmap")
            candidates.push_back({bitmap, stock});
    }
    if(candidates.size() > 1) throw std::runtime_error("Ambiguous parent HUD bitmap references");
    if(!candidates.empty()) { inherited_bitmap = candidates[0].first; inherited_stock = candidates[0].second; }
    if(!inherited_bitmap.empty() && member(object, "width_scale") && member(object, "height_scale")) {
        auto *seq = member(object, "sequence_index");
        std::size_t sequence = seq && seq->get_values().size() == 1 ? numeric(seq->get_values()[0]) : 0;
        if(sequence != 65535) uses.push_back({hud, inherited_bitmap, inherited_stock,
            join_field(path, "width_scale"), join_field(path, "height_scale"),
            member(object, "scaling_flags") ? join_field(path, "scaling_flags") : "",
            member(object, "anchor_offset") ? join_field(path, "anchor_offset") : "", sequence});
    }
    for(auto &value : object.get_values()) {
        if(value.get_type() != Value::VALUE_TYPE_REFLEXIVE || !value.get_member_name()) continue;
        std::string name = value.get_member_name();
        for(std::size_t i = 0; i < value.get_array_size(); i++)
            collect_uses(value.get_object_in_array(i), canonical, hud,
                join_field(path, name) + "[" + std::to_string(i) + "]", uses, inherited_bitmap, inherited_stock);
    }
}
static bool hud_tag(const std::string &name) {
    auto extension = fs::path(name).extension().string();
    return extension == ".weapon_hud_interface" || extension == ".unit_hud_interface"
        || extension == ".grenade_hud_interface" || extension == ".hud_globals" || extension == ".hud_number";
}
static void check_anchor_capabilities(Parser::ParserStruct &object, bool weapon_hud,
        const std::string &tag, const std::string &path = {}) {
    for(auto &value : object.get_values()) {
        if(!value.get_member_name()) continue;
        std::string name = value.get_member_name(), full = join_field(path, name);
        if(value.get_type() == Value::VALUE_TYPE_ENUM && (name == "anchor" || name == "auxiliary_overlay_anchor")) {
            auto values = value.get_values();
            if(values.size() != 1) throw std::runtime_error("Anchor enum cardinality mismatch: " + tag + " " + full);
            auto anchor = numeric(values[0]);
            bool child = weapon_hud && !path.empty() && name == "anchor";
            if(child && anchor != 0)
                throw std::runtime_error("MCC child anchor is unsupported by native Xbox HUD: " + tag + " " + full
                    + " = " + value.read_enum() + " (" + std::to_string(static_cast<int>(anchor))
                    + "); native child elements inherit the parent anchor, so only from_parent (0) is convertible without a reviewed translation");
            if(!child && (anchor < 0 || anchor > 4))
                throw std::runtime_error("HUD anchor is unsupported by native Xbox HUD: " + tag + " " + full
                    + " = " + value.read_enum() + " (" + std::to_string(static_cast<int>(anchor))
                    + "); native anchors are top_left, top_right, bottom_left, bottom_right and center (0..4)");
        }
        if(value.get_type() == Value::VALUE_TYPE_REFLEXIVE)
            for(std::size_t i = 0; i < value.get_array_size(); i++)
                check_anchor_capabilities(value.get_object_in_array(i), weapon_hud, tag,
                    full + "[" + std::to_string(i) + "]");
    }
}
static unsigned bitmap_density_flags(const Parser::Bitmap &bitmap) {
    return bitmap.flags & (HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE | HEK::BITMAP_FLAGS_FLAG_FORCE_HUD_USE_HIGHRES_SCALE);
}
static void canonical_offset(Decision &decision, Parser::ParserStruct &tag, Parser::ParserStruct *stock,
        const std::string &field, const std::string &reason = {}) {
    if(field.empty()) return;
    auto &value = field_at(tag, field); auto source = value.get_values(); Numbers reference;
    if(stock) try { reference = field_at(*stock, field).get_values(); } catch(const std::exception &) {}
    // MCC's HUD canvas is 960p versus native 480p. The placement highres
    // flag independently doubles the MCC offset (it does not halve artwork).
    auto separator = field.rfind('.'); auto base = separator == std::string::npos ? std::string() : field.substr(0, separator);
    auto leaf = separator == std::string::npos ? field : field.substr(separator + 1);
    std::string flags;
    if(leaf == "anchor_offset") flags = "scaling_flags";
    else if(ends_with(leaf, "_anchor_offset")) flags = leaf.substr(0, leaf.size() - std::string("anchor_offset").size()) + "scaling_flags";
    bool highres = false;
    if(!flags.empty()) try {
        auto values = field_at(tag, join_field(base, flags)).get_values();
        highres = !values.empty() && (static_cast<unsigned>(numeric(values[0])) & 4U);
    } catch(const std::exception &) {}
    std::vector<double> targets;
    bool quantized = false, canonical_quantization = false;
    for(std::size_t i = 0; i < source.size(); i++) {
        auto target = numeric(source[i]) * (highres ? 1.0 : 0.5);
        if(value.get_number_format() == Value::NUMBER_FORMAT_INT) {
            auto rounded = std::round(target);
            if(reference.size() == source.size()) {
                auto canonical = numeric(reference[i]);
                if(canonical == std::floor(target) || canonical == std::ceil(target)) {
                    rounded = canonical; canonical_quantization = target != canonical;
                }
            }
            quantized = quantized || target != rounded; target = rounded;
        }
        targets.push_back(target);
    }
    add_rule(decision, tag, field, targets, reason.empty()
        ? "MCC 960p to native 480p canvas; MCC highres flag doubles anchor before canvas normalization; integer coordinates use canonical floor/ceil where proven, otherwise nearest integer half away from zero"
        : reason + "; integer coordinates use canonical floor/ceil where proven, otherwise nearest integer half away from zero");
    if(quantized) decision.warnings.push_back("Quantized " + field + " by at most 0.5 native pixel"
        + (canonical_quantization ? " using canonical Xbox coordinate" : " using nearest integer half away from zero"));
}
static void canonical_offsets(Decision &decision, Parser::ParserStruct &object, Parser::ParserStruct &tag,
        Parser::ParserStruct *stock, const std::string &path = {}) {
    for(auto &value : object.get_values()) {
        if(!value.get_member_name()) continue;
        std::string name = value.get_member_name(), full = join_field(path, name);
        if(name == "anchor_offset" || ends_with(name, "_anchor_offset") || name == "offset_from_reference_corner")
            canonical_offset(decision, tag, stock, full);
        if(value.get_type() == Value::VALUE_TYPE_REFLEXIVE)
            for(std::size_t i = 0; i < value.get_array_size(); i++)
                canonical_offsets(decision, value.get_object_in_array(i), tag, stock, full + "[" + std::to_string(i) + "]");
        if(name == "scaling_flags" || ends_with(name, "_scaling_flags")) {
            auto flags = value.get_values();
            if(flags.size() != 1) throw std::runtime_error("HUD scaling flags cardinality mismatch");
            auto before = static_cast<unsigned>(numeric(flags[0]));
            if(before & 4U) add_rule(decision, tag, full, {double(before & ~4U)},
                "Xbox HUD lacks use_high_res_scale; MCC offset doubling accounted independently before clearing the flag");
        }
    }
}
static void hud_globals_pixel_metrics(Decision &decision, Parser::ParserStruct &tag, Parser::ParserStruct *stock) {
    // Enumerate native display-pixel consumers. Do not infer units from a field
    // being called "scale", "spacing", or "offset": text_spacing is a ratio of
    // font line height, while range/velocity/timing/color remain authored.
    for(const std::string field : {"hud_damage_top_offset", "hud_damage_bottom_offset", "hud_damage_left_offset", "hud_damage_right_offset"})
        canonical_offset(decision, tag, stock, field,
            "MCC 960p to native 480p damage-indicator screen-edge pixel inset; native hud_unit.c adds/subtracts this value directly from window bounds");
    for(const std::string field : {"top_offset", "bottom_offset", "left_offset", "right_offset"})
        canonical_offset(decision, tag, stock, field,
            "MCC 960p to native 480p waypoint screen-edge pixel margin; native hud_nav_points.c subtracts these margins from the screen window dimensions");
    canonical_offset(decision, tag, stock, "motion_sensor_scale",
        "MCC 960p to native 480p radar display-pixel radius; native motion_sensor.c divides this visual scale by world detection range, which remains unchanged");
    canonical_offset(decision, tag, stock, "default_chapter_title_bounds",
        "MCC 960p to native 480p default title text pixel rectangle; native cinematics.c uses these bounds for screen text placement");
    auto *icons = member(tag, "button_icons");
    if(icons && icons->get_type() == Value::VALUE_TYPE_REFLEXIVE)
        for(std::size_t i = 0; i < icons->get_array_size(); i++)
            canonical_offset(decision, tag, stock, "button_icons[" + std::to_string(i) + "].width_offset",
                "MCC 960p to native 480p HUD icon text-cursor pixel advance; native hud_messaging.c adds this to the rendered icon width or uses it as absolute cursor advance");
}
static void hud_number_pixel_metrics(Decision &decision, Parser::ParserStruct &tag, Parser::ParserStruct *stock) {
    // Numeric metrics belong to the authored HUDNumber, independently of
    // whether its glyph bitmap was authored MCC art or native stock fallback.
    for(const std::string field : {"bitmap_digit_width", "screen_digit_width", "x_offset", "y_offset", "decimal_point_width", "colon_width"})
        canonical_offset(decision, tag, stock, field,
            "MCC 960p numeric pixel spacing to native 480p is 2x independently of glyph bitmap half-scale density and glyph bitmap provenance");
}
static std::string string_array(const std::vector<std::string> &values) {
    std::ostringstream out; out << '[';
    for(std::size_t i = 0; i < values.size(); i++) { if(i) out << ','; out << quoted(values[i]); }
    out << ']'; return out.str();
}
static void emit_decision(const Decision &decision) {
    if(decision.rules.empty() && !decision.bitmap_divisor && decision.failures.empty() && decision.warnings.empty()) return;
    std::cout << "{\"tag\":" << quoted(decision.tag) << ",\"status\":"
              << quoted(!decision.failures.empty() ? "needs_profile"
                  : decision.rules.empty() && !decision.bitmap_divisor ? "unchanged" : "requires_conversion")
              << ",\"source_formats\":[\"mcc_hud_density\"],\"target_format\":\"native_xbox_hud\",\"field_rules\":[";
    std::size_t n = 0;
    for(const auto &[field, rule] : decision.rules) {
        if(n++) std::cout << ',';
        std::cout << "{\"field\":" << quoted(field) << ",\"before\":" << numbers_json(rule.before)
                  << ",\"after\":" << numbers_json(rule.after) << ",\"reason\":" << quoted(rule.reason) << '}';
    }
    std::cout << ']';
    if(decision.bitmap_divisor) std::cout << ",\"bitmap_divisor\":" << decision.bitmap_divisor;
    std::cout << ",\"reason\":" << quoted(decision.failures.empty() ? "Canonical Xbox HUD geometry proves the listed field or atlas normalization" : decision.failures.front())
              << ",\"warnings\":" << string_array(decision.warnings) << ",\"blockers\":" << string_array(decision.failures)
              << ",\"evidence\":{\"invader_source_commit\":\"7d25a855f5ef9e4ab8407abf490b21f8780abf27\","
                 "\"mcc_density_reference\":\"https://github.com/Aerocatia/halopc-restored/blob/2ed57083cdab6d625789c551faf218a9ef50e9c8/README.md#L38-L41\","
                 "\"source_canvas_pixels\":960,\"native_canvas_pixels\":480,\"source_format_gate\":\"MCC_v13_only\","
                 "\"native_consumer\":\"source/interface/hud_draw.c\",\"density_proofs\":[";
    for(std::size_t i = 0; i < decision.evidence.size(); i++) { if(i) std::cout << ','; std::cout << decision.evidence[i]; }
    std::cout << "],\"placement_scales_preserve_authored_relative_values\":true,\"anchor_policy\":\"MCC_canvas_with_highres_offset_semantics_and_explicit_integer_quantization\","
                 "\"visual_validation\":\"pending\"}}\n";
}
static void audit(const fs::path &input) {
    auto root = regular_root(input); Index index;
    for(const auto &path : lines(root, "roots.txt")) index.roots.push_back(regular_root(path));
    auto stock = lines(root, "stock-root.txt");
    if(index.roots.empty() || stock.size() != 1) throw std::runtime_error("Index requires winning roots and exactly one canonical stock root");
    index.stock = regular_root(stock[0]);
    for(const auto &name : lines(root, "required-tags.txt")) {
        // Validate required names even if their tag classes are outside the HUD stage.
        fs::path relative(name);
        if(relative.is_absolute() || relative.lexically_normal().generic_string() != name || name.find('\\') != std::string::npos)
            throw std::runtime_error("Required tag name must be normalized");
        for(const auto &part : relative) if(part == ".." || part == ".") throw std::runtime_error("Required tag traversal refused");
        index.required.insert(name);
    }
    // The Python reuse stage produces this bounded, protected index only from
    // canonical stock HUD copies whose reference aliases were checked. Their
    // pixels and coordinates already use the native canvas.
    std::set<std::string> native_reused;
    if(fs::exists(root / "native-hud-tags.txt")) {
        for(const auto &name : lines(root, "native-hud-tags.txt")) {
            if(!index.required.count(name) || !hud_tag(name))
                throw std::runtime_error("Native reuse marker must identify a reachable HUD tag");
            index.load(name);
            native_reused.insert(name);
        }
    }
    std::map<std::string, Decision> decisions; std::vector<Use> uses;
    for(const auto &name : index.required) if(hud_tag(name)) {
        auto &decision = decisions[name]; decision.tag = name;
        try {
            if(native_reused.count(name) || index.native_fallback(name)) {
                decision.warnings.push_back("Winning HUD tag is already verified native stock presentation; no MCC normalization applied");
                continue;
            }
            auto tag = index.load(name), canonical = index.load(name, true);
            check_anchor_capabilities(*tag, fs::path(name).extension() == ".weapon_hud_interface", name);
            collect_uses(*tag, canonical.get(), name, {}, uses);
            canonical_offsets(decision, *tag, *tag, canonical.get());
            if(fs::path(name).extension() == ".hud_globals") hud_globals_pixel_metrics(decision, *tag, canonical.get());
            if(fs::path(name).extension() == ".hud_number") hud_number_pixel_metrics(decision, *tag, canonical.get());
        }
        catch(const std::exception &error) { decision.failures.push_back(error.what()); }
    }
    // Fixed native geometry consumers must change their atlas, not element scale.
    // MCC format semantics select density. Stock frame footprints crosscheck
    // rather than overwrite authored UV shapes or require retail artwork.
    std::map<std::string, unsigned> physical;
    for(const auto &use : uses) if(use.physical) {
        auto &decision = decisions[use.bitmap]; decision.tag = use.bitmap;
        try {
            if(index.native_fallback(use.bitmap)) {
                decision.warnings.push_back("Fixed atlas is already native canonical stock fallback; preserve its native pixels");
                continue;
            }
            auto source = index.load(use.bitmap);
            auto *bitmap = dynamic_cast<Parser::Bitmap *>(source.get());
            if(!bitmap) throw std::runtime_error("HUD bitmap dependency has wrong tag class");
            auto canonical = use.stock_bitmap.empty() ? index.load(use.bitmap, true) : index.load(use.stock_bitmap, true);
            auto *stock_bitmap = canonical ? dynamic_cast<Parser::Bitmap *>(canonical.get()) : nullptr;
            if(bitmap->flags & HEK::BITMAP_FLAGS_FLAG_FORCE_HUD_USE_HIGHRES_SCALE)
                throw std::runtime_error("Custom CE force_hud_use_highres_scale has no proven MCC v13 interpretation");
            unsigned factor = (bitmap->flags & HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE) ? 4 : 2;
            std::set<unsigned> covered;
            for(std::size_t sequence = 0; sequence < bitmap->bitmap_group_sequence.size(); sequence++) {
                if(stock_bitmap) try {
                    auto proof = density(*bitmap, *stock_bitmap, use.bitmap, use.stock_bitmap.empty() ? use.bitmap : use.stock_bitmap, sequence);
                    decision.evidence.push_back(proof.evidence);
                    if(proof.divisor != factor) decision.warnings.push_back("Canonical sequence footprint differs from MCC display density for sequence "
                        + std::to_string(sequence) + "; retain authored shape and apply source-format canvas semantics");
                } catch(const std::exception &error) {
                    decision.warnings.push_back("Canonical footprint crosscheck unavailable for sequence " + std::to_string(sequence) + ": " + error.what()
                        + "; source-format canvas semantics preserve authored shape");
                }
                for(const auto &frame : frames(*bitmap, sequence)) covered.insert(frame.image);
            }
            if(covered.size() != bitmap->bitmap_data.size()) throw std::runtime_error("Fixed HUD atlas contains images without HUD sequence consumers");
            if(bitmap->type == HEK::BITMAP_TYPE_INTERFACE_BITMAPS)
                for(const auto &sequence : bitmap->bitmap_group_sequence) if(!sequence.sprites.empty())
                    throw std::runtime_error("Fixed interface atlas uses pixel-space sprite clips; no normalized-UV resample proof");
            decision.evidence.push_back("{\"method\":\"MCC_v13_960p_canvas_and_bitmap_half_hud_scale\","
                "\"source_bitmap\":" + quoted(use.bitmap) + ",\"source_half_hud_scale\":"
                + ((bitmap->flags & HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE) ? std::string("true") : "false")
                + ",\"divisor\":" + std::to_string(factor)
                + ",\"consumer\":" + quoted(use.hud) + ",\"consumer_geometry\":\"fixed_native_bitmap_pixels\","
                "\"requires_all_incoming_consumers_hud_only\":true}");
            if(factor > 1) {
                for(const auto &image : bitmap->bitmap_data)
                    if(image.type != HEK::BITMAP_DATA_TYPE_2D_TEXTURE || image.depth != 1 || image.mipmap_count != 0
                            || !image.width || !image.height || image.width % factor || image.height % factor)
                        throw std::runtime_error("Fixed HUD atlas requires unsupported resampling layout");
                if(physical.count(use.bitmap) && physical[use.bitmap] != factor) throw std::runtime_error("Conflicting fixed HUD atlas densities");
                physical[use.bitmap] = factor; decision.bitmap_divisor = factor;
                if(fs::path(use.hud).extension() == ".hud_number") {
                    auto &number_decision = decisions[use.hud];
                    number_decision.evidence.insert(number_decision.evidence.end(), decision.evidence.begin(), decision.evidence.end());
                }
            }
        }
        catch(const std::exception &error) { decision.failures.push_back(error.what()); }
    }
    for(const auto &use : uses) if(!use.physical) {
        auto &decision = decisions[use.hud];
        try {
            auto tag = index.load(use.hud), canonical_hud = index.load(use.hud, true);
            auto source = index.load(use.bitmap); auto *bitmap = dynamic_cast<Parser::Bitmap *>(source.get());
            if(!bitmap) throw std::runtime_error("HUD dependency has wrong bitmap class");
            unsigned highres = 0;
            if(!use.flags.empty()) highres = static_cast<unsigned>(numeric(field_at(*tag, use.flags).get_values().at(0))) & 4U;
            auto canonical = use.stock_bitmap.empty() ? index.load(use.bitmap, true) : index.load(use.stock_bitmap, true);
            auto *stock_bitmap = canonical ? dynamic_cast<Parser::Bitmap *>(canonical.get()) : nullptr;
            if(bitmap->flags & HEK::BITMAP_FLAGS_FLAG_FORCE_HUD_USE_HIGHRES_SCALE)
                throw std::runtime_error("Custom CE force_hud_use_highres_scale has no proven MCC v13 interpretation: " + use.bitmap);
            frames(*bitmap, use.sequence); // Validate every selected authored frame even without stock art.
            unsigned source_divisor = (bitmap->flags & HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE) ? 4 : 2;
            if(stock_bitmap) try {
                auto proof = density(*bitmap, *stock_bitmap, use.bitmap, use.stock_bitmap.empty() ? use.bitmap : use.stock_bitmap, use.sequence);
                decision.evidence.push_back(proof.evidence);
                if(proof.divisor != source_divisor) decision.warnings.push_back("Canonical footprint differs from MCC density: " + use.bitmap
                    + "; authored UV shape preserved using source-format canvas semantics");
            } catch(const std::exception &error) {
                decision.warnings.push_back("Canonical footprint crosscheck unavailable for " + use.bitmap + ": " + error.what()
                    + "; authored UV shape preserved using source-format canvas semantics");
            }
            decision.evidence.push_back("{\"method\":\"MCC_v13_960p_canvas_and_bitmap_half_hud_scale\","
                "\"source_bitmap\":" + quoted(use.bitmap) + ",\"source_sequence\":" + std::to_string(use.sequence)
                + ",\"source_half_hud_scale\":" + ((bitmap->flags & HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE) ? std::string("true") : "false")
                + ",\"divisor\":" + std::to_string(source_divisor) + ",\"artwork_and_sequence_uvs_preserved\":true}");
            unsigned divisor = physical.count(use.bitmap) ? 1 : source_divisor;
            for(const auto &field : {use.width, use.height}) {
                auto before = field_at(*tag, field).get_values();
                if(before.size() != 1) throw std::runtime_error("Placement scale cardinality mismatch");
                add_rule(decision, *tag, field, {numeric(before[0]) / divisor},
                    "MCC 960p to native 480p canvas plus optional bitmap half_hud_scale; preserve authored relative scale and UV shape");
            }
            if(highres) {
                auto flags = numeric(field_at(*tag, use.flags).get_values().at(0));
                add_rule(decision, *tag, use.flags, {double(static_cast<unsigned>(flags) & ~4U)},
                    "Xbox HUD does not support MCC high-resolution placement flag; bitmap density and independent offset proof recorded");
            }
        }
        catch(const std::exception &error) { decision.failures.push_back(error.what()); }
    }
    for(const auto &[name, decision] : decisions) emit_decision(decision);
}

struct FieldRule { std::string field; std::vector<double> before, after; };
static std::vector<double> rule_numbers(const std::string &text) {
    std::vector<double> result;
    for(const auto &part : split(text, ',')) {
        std::size_t end; double value = std::stod(part, &end);
        if(end != part.size() || !std::isfinite(value)) throw std::runtime_error("Rules require finite complete numeric values");
        result.push_back(value);
    }
    if(result.empty()) throw std::runtime_error("Empty numeric rule");
    return result;
}
static bool allowed_field(const std::string &name) {
    auto component = name.substr(name.rfind('.') == std::string::npos ? 0 : name.rfind('.') + 1);
    return component == "flags" || component == "bitmap_digit_width" || component == "screen_digit_width"
        || component == "x_offset" || component == "y_offset" || component == "decimal_point_width" || component == "colon_width"
        || component == "offset_from_reference_corner" || component == "width_scale" || component == "height_scale"
        || component == "scaling_flags" || component == "anchor_offset"
        || component == "width_offset" || component == "top_offset" || component == "bottom_offset"
        || component == "left_offset" || component == "right_offset" || component == "motion_sensor_scale"
        || component == "default_chapter_title_bounds" || component == "hud_damage_top_offset"
        || component == "hud_damage_bottom_offset" || component == "hud_damage_left_offset" || component == "hud_damage_right_offset"
        || ends_with(component, "_width_scale") || ends_with(component, "_height_scale")
        || ends_with(component, "_scaling_flags") || ends_with(component, "_anchor_offset");
}
struct Prepared {
    std::string name, record;
    std::vector<std::byte> original, output;
};
static void resize_bitmap(Parser::Bitmap &tag, unsigned divisor, const std::string &name) {
    if(divisor != 2 && divisor != 4) throw std::runtime_error("HUD resize divisor must be 2 or 4");
    if(tag.bitmap_data.empty()) throw std::runtime_error("Empty fixed HUD atlas");
    if(tag.type == HEK::BITMAP_TYPE_INTERFACE_BITMAPS)
        for(const auto &sequence : tag.bitmap_group_sequence) if(!sequence.sprites.empty())
            throw std::runtime_error("Fixed interface atlas with pixel-space sprite clips requires explicit coordinate normalization");
    std::vector<std::byte> result;
    for(auto &image : tag.bitmap_data) {
        std::size_t width = image.width, height = image.height;
        if(image.type != HEK::BITMAP_DATA_TYPE_2D_TEXTURE || image.depth != 1 || image.mipmap_count != 0
                || !width || !height || width % divisor || height % divisor || width * height > 16 * 1024 * 1024
                || image.registration_point.x.read() % divisor || image.registration_point.y.read() % divisor)
            throw std::runtime_error("Unsupported fixed HUD image layout or fractional registration: " + name);
        std::size_t size = BitmapEncode::bitmap_data_size(width, height, 1, 0, image.format, image.type), offset = image.pixel_data_offset;
        if(offset > tag.processed_pixel_data.size() || size > tag.processed_pixel_data.size() - offset
                || (image.flags & (HEK::BITMAP_DATA_FLAGS_FLAG_SWIZZLED | HEK::BITMAP_DATA_FLAGS_FLAG_PALETTIZED | HEK::BITMAP_DATA_FLAGS_FLAG_V16U16)))
            throw std::runtime_error("Invalid or unsupported HUD bitmap source layout");
        auto decoded = BitmapEncode::encode_bitmap(tag.processed_pixel_data.data() + offset, image.format,
            HEK::BITMAP_DATA_FORMAT_A8R8G8B8, width, height, false);
        if(decoded.size() != width * height * 4) throw std::runtime_error("HUD decoder returned inconsistent byte count");
        std::size_t new_width = width / divisor, new_height = height / divisor;
        std::vector<std::byte> pixels(new_width * new_height * 4);
        for(std::size_t y = 0; y < new_height; y++) for(std::size_t x = 0; x < new_width; x++) {
            unsigned alpha = 0, weighted[3] = {};
            for(unsigned dy = 0; dy < divisor; dy++) for(unsigned dx = 0; dx < divisor; dx++) {
                std::size_t source = ((y * divisor + dy) * width + x * divisor + dx) * 4;
                unsigned a = std::to_integer<unsigned>(decoded[source + 3]); alpha += a;
                for(unsigned channel = 0; channel < 3; channel++) weighted[channel] += std::to_integer<unsigned>(decoded[source + channel]) * a;
            }
            std::size_t output = (y * new_width + x) * 4;
            for(unsigned channel = 0; channel < 3; channel++) pixels[output + channel] = std::byte(alpha ? (weighted[channel] + alpha / 2) / alpha : 0);
            pixels[output + 3] = std::byte((alpha + divisor * divisor / 2) / (divisor * divisor));
        }
        image.width = new_width; image.height = new_height;
        image.registration_point.x = image.registration_point.x.read() / divisor;
        image.registration_point.y = image.registration_point.y.read() / divisor;
        image.format = HEK::BITMAP_DATA_FORMAT_A8R8G8B8;
        image.flags &= ~(HEK::BITMAP_DATA_FLAGS_FLAG_COMPRESSED | HEK::BITMAP_DATA_FLAGS_FLAG_PALETTIZED
            | HEK::BITMAP_DATA_FLAGS_FLAG_SWIZZLED | HEK::BITMAP_DATA_FLAGS_FLAG_V16U16);
        image.pixel_data_offset = result.size(); image.pixel_data_size = pixels.size();
        result.insert(result.end(), pixels.begin(), pixels.end());
    }
    tag.processed_pixel_data = std::move(result); tag.encoding_format = HEK::BITMAP_FORMAT_32_BIT;
    tag.flags &= ~(HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE | HEK::BITMAP_FLAGS_FLAG_FORCE_HUD_USE_HIGHRES_SCALE);
    tag.sprite_spacing = std::max<std::uint16_t>(tag.sprite_spacing / divisor, 1);
}
static void restore_bitmap_metadata(Parser::Bitmap &restored, const Parser::Bitmap &source) {
    if(restored.bitmap_data.size() != source.bitmap_data.size()) throw std::runtime_error("Resample changed bitmap image count");
    for(std::size_t i = 0; i < source.bitmap_data.size(); i++) {
        auto &a = restored.bitmap_data[i]; const auto &b = source.bitmap_data[i];
        a.width = b.width; a.height = b.height; a.registration_point = b.registration_point;
        a.format = b.format; a.flags = b.flags; a.pixel_data_offset = b.pixel_data_offset; a.pixel_data_size = b.pixel_data_size;
    }
    restored.processed_pixel_data = source.processed_pixel_data; restored.encoding_format = source.encoding_format;
    restored.flags = source.flags; restored.sprite_spacing = source.sprite_spacing;
}
static Prepared prepare(const fs::path &overlay, const std::string &name,
        const std::vector<FieldRule> &rules, unsigned divisor) {
    auto target = checked_file(overlay / "tags", name), snapshot = checked_file(overlay / "source-snapshots", name);
    if(fs::equivalent(target, snapshot)) throw std::runtime_error("Source snapshot and target must be independent");
    auto original = read_file(snapshot);
    if(read_file(target) != original) throw std::runtime_error("Target differs from immutable source snapshot");
    auto source = Parser::ParserStruct::parse_hek_tag_file(original.data(), original.size());
    auto tag = Parser::ParserStruct::parse_hek_tag_file(original.data(), original.size());
    std::map<std::string, Numbers> before_values, after_values;
    for(const auto &rule : rules) {
        if(!allowed_field(rule.field)) throw std::runtime_error("Field is outside the HUD normalization capability: " + rule.field);
        auto &value = field_at(*tag, rule.field); auto current = value.get_values();
        if(current.size() != rule.before.size() || current.size() != rule.after.size())
            throw std::runtime_error("Numeric rule cardinality mismatch");
        Numbers after;
        for(std::size_t i = 0; i < current.size(); i++) {
            // JSON preserves float32 values exactly; decimal TSV input may round only
            // to the same actual storage value, never to a different source field.
            if(current[i] != checked_target(value, rule.before[i])) throw std::runtime_error("Source field mismatch: " + rule.field);
            after.push_back(checked_target(value, rule.after[i]));
        }
        if(before_values.count(rule.field)) throw std::runtime_error("Duplicate field rule");
        before_values[rule.field] = current; after_values[rule.field] = after; value.set_values(after);
    }
    if(divisor) {
        auto *bitmap = dynamic_cast<Parser::Bitmap *>(tag.get());
        if(!bitmap) throw std::runtime_error("Physical HUD resampling requires a bitmap tag");
        resize_bitmap(*bitmap, divisor, name);
    }
    auto extension = fs::path(name).extension().string().substr(1);
    auto output = tag->generate_hek_tag_data(HEK::tag_extension_to_fourcc(extension.c_str()), false);
    auto verify = Parser::ParserStruct::parse_hek_tag_file(output.data(), output.size());
    for(const auto &[field, expected] : after_values)
        if(field_at(*verify, field).get_values() != expected) throw std::runtime_error("Stored field differs from reviewed target");
    if(!tag->compare(verify.get(), false)) throw std::runtime_error("Output parser roundtrip changed normalized tag");
    for(const auto &[field, original_values] : before_values) field_at(*verify, field).set_values(original_values);
    if(divisor) {
        auto *restored_bitmap = dynamic_cast<Parser::Bitmap *>(verify.get()), *source_bitmap = dynamic_cast<Parser::Bitmap *>(source.get());
        if(!restored_bitmap || !source_bitmap) throw std::runtime_error("Resampled tag class mismatch");
        restore_bitmap_metadata(*restored_bitmap, *source_bitmap);
    }
    if(!source->compare(verify.get(), false)) throw std::runtime_error("Unapproved authored HUD metadata changed");
    std::ostringstream record;
    record << "{\"tag\":" << quoted(name) << ",\"status\":\"converted\",\"source_formats\":[\"mcc_hud_density\"],"
              "\"target_format\":\"native_xbox_hud\",\"field_rules\":[";
    std::size_t count = 0;
    for(const auto &[field, expected] : after_values) {
        if(count++) record << ',';
        record << "{\"field\":" << quoted(field) << ",\"before\":" << numbers_json(before_values.at(field))
               << ",\"after\":" << numbers_json(expected) << '}';
    }
    record << ']';
    if(divisor) record << ",\"bitmap_divisor\":" << divisor
        << ",\"filter\":\"alpha_weighted_box\",\"pixel_resampling_lossy\":true,\"sequence_metadata_preserved\":true";
    record << ",\"input_bytes\":" << original.size() << ",\"output_bytes\":" << output.size()
           << ",\"authored_metadata_preserved\":true,\"source_snapshots_preserved\":true,\"visual_validation\":\"pending\"}";
    return {name, record.str(), std::move(original), std::move(output)};
}
static void convert(const fs::path &input) {
    auto overlay = regular_root(input); regular_root(overlay / "tags"); regular_root(overlay / "source-snapshots");
    auto marker = overlay / "conversion.completed";
    if(fs::exists(marker) || fs::is_symlink(fs::symlink_status(marker))) throw std::runtime_error("Use a fresh unconverted overlay");
    std::map<std::string, std::vector<FieldRule>> fields;
    std::map<std::string, unsigned> bitmaps; std::set<std::string> names;
    for(const auto &line : lines(overlay, "field-rules.tsv")) {
        auto parts = split(line, '\t');
        if(parts.size() != 4) throw std::runtime_error("Expected four columns in field-rules.tsv");
        if(!hud_tag(parts[0]) && fs::path(parts[0]).extension() != ".bitmap") throw std::runtime_error("Unsupported HUD field tag class");
        fields[parts[0]].push_back({parts[1], rule_numbers(parts[2]), rule_numbers(parts[3])}); names.insert(parts[0]);
    }
    for(const auto &line : lines(overlay, "bitmap-rules.tsv")) {
        auto parts = split(line, '\t');
        if(parts.size() != 2 || fs::path(parts[0]).extension() != ".bitmap" || (parts[1] != "2" && parts[1] != "4"))
            throw std::runtime_error("Expected bitmap path and divisor 2 or 4");
        if(!bitmaps.emplace(parts[0], std::stoul(parts[1])).second) throw std::runtime_error("Duplicate bitmap resampling rule");
        names.insert(parts[0]);
    }
    if(names.empty()) throw std::runtime_error("Empty HUD conversion plan");
    std::vector<Prepared> prepared;
    for(const auto &name : names) prepared.push_back(prepare(overlay, name, fields[name], bitmaps.count(name) ? bitmaps[name] : 0));
    // Plan and validate every output before writing any derivative.
    for(const auto &item : prepared) {
        if(read_file(checked_file(overlay / "tags", item.name)) != item.original
                || read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original)
            throw std::runtime_error("Input changed while preparing HUD normalization");
    }
    for(const auto &item : prepared)
        if(!File::save_file(checked_file(overlay / "tags", item.name), item.output)) throw std::runtime_error("Cannot write HUD derivative");
    for(const auto &item : prepared) {
        if(read_file(checked_file(overlay / "tags", item.name)) != item.output
                || read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original)
            throw std::runtime_error("Derivative or immutable snapshot verification failed");
    }
    std::ofstream completed(marker);
    completed << "{\"status\":\"converted\",\"actions\":[";
    for(std::size_t i = 0; i < prepared.size(); i++) { if(i) completed << ','; completed << prepared[i].record; }
    completed << "],\"authored_metadata_preserved\":true,\"source_snapshots_preserved\":true,\"visual_validation\":\"pending\"}\n";
    completed.flush(); if(!completed) throw std::runtime_error("Failed conversion receipt write");
    for(const auto &item : prepared) std::cout << item.record << '\n';
}
int main(int argc, char **argv) {
    if(argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "Usage: normalize-mcc-hud --audit INDEX_DIRECTORY | --convert FRESH_OVERLAY\n"
                     "Audit requires roots.txt, required-tags.txt and stock-root.txt. Conversion uses independent tags/ and source-snapshots/ plus field-rules.tsv and bitmap-rules.tsv.\n";
        return 0;
    }
    if(argc != 3) { std::cerr << "Expected --audit INDEX_DIRECTORY or --convert FRESH_OVERLAY\n"; return 2; }
    try {
        if(std::string(argv[1]) == "--audit") audit(argv[2]);
        else if(std::string(argv[1]) == "--convert") convert(argv[2]);
        else throw std::runtime_error("Unknown operation");
        return 0;
    }
    catch(const std::exception &error) { std::cerr << "MCC HUD normalization failed: " << error.what() << '\n'; return 1; }
}
