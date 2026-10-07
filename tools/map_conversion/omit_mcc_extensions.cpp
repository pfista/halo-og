// SPDX-License-Identifier: GPL-3.0-only
// Offline omission of one proven MCC-only field ignored by the native Xbox HUD.
// Links the reviewed Invader decoder/encoder; writes only copied overlay tags.
#include <invader/tag/parser/parser.hpp>
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
            || (tag && relative.extension() != ".hud_globals"))
        throw std::runtime_error("Expected a normalized relative HUDGlobals path");
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

// This list is deliberately one source-backed target capability, not a generic
// rule to delete every field whose schema has an engine annotation or warning.
// Pinned Invader emits this array and its bitmap dependencies even for Xbox.
// Native hud_globals_definition calls these bytes unused2[24], starting 0x3F0.
static std::string decision_json(std::size_t count) {
    std::ostringstream out;
    out << "\"source_formats\":[\"mcc_anniversary_hud_remaps\"],"
           "\"target_format\":\"native_xbox_fields\","
           "\"fields\":[\"anniversary_hud_remaps\"],"
           "\"counts_before\":{\"anniversary_hud_remaps\":" << count
        << "},\"counts_after\":{\"anniversary_hud_remaps\":0},"
           "\"target_capability\":\"xbox_v5_no_anniversary_hud_remaps\","
           "\"reason\":\"MCC-only Anniversary HUD bitmap remaps have no consumer in the native Xbox-v5 HUDGlobals; omitting this field removes its compiler-only dependency edges\","
           "\"evidence\":{"
           "\"invader_source_commit\":\"7d25a855f5ef9e4ab8407abf490b21f8780abf27\","
           "\"definition\":\"invader/src/tag/hek/definition/hud_globals.json\","
           "\"definition_engines\":[\"mcc\"],\"legacy_maximum\":0,"
           "\"compiler\":\"invader/build/parser-cache-format.cpp\","
           "\"compiler_serializes_for_xbox\":true,"
           "\"native_definition\":\"source/interface/hud_definitions.h\","
           "\"native_member\":\"hud_globals_definition.unused2[24]\","
           "\"native_unused_offset\":1008,\"native_unused_bytes\":96,"
           "\"omitted_reflexive_bytes\":12}";
    return out.str();
}

static void audit(const fs::path &input) {
    const auto root = regular_root(input);
    std::vector<std::string> names;
    for(const auto &entry : fs::recursive_directory_iterator(root))
        if(entry.path().extension() == ".hud_globals")
            names.push_back(entry.path().lexically_relative(root).generic_string());
    std::sort(names.begin(), names.end());
    for(const auto &name : names) {
        try {
            auto bytes = read_file(checked_file(root, name));
            auto tag = Parser::HUDGlobals::parse_hek_tag_file(bytes.data(), bytes.size());
            if(tag.anniversary_hud_remaps.empty()) continue;
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"convertible\","
                << decision_json(tag.anniversary_hud_remaps.size())
                << ",\"metadata\":{\"tag_bytes\":" << bytes.size()
                << ",\"anniversary_hud_remaps\":" << tag.anniversary_hud_remaps.size() << "}}\n";
        }
        catch(const std::exception &error) {
            std::cout << "{\"tag\":" << quoted(name) << ",\"status\":\"unsupported\","
                         "\"source_formats\":[\"mcc_anniversary_hud_remaps\"],"
                         "\"target_format\":\"native_xbox_fields\",\"reason\":"
                << quoted(error.what()) << ",\"metadata\":{}}\n";
        }
    }
}

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
    auto source = Parser::HUDGlobals::parse_hek_tag_file(original.data(), original.size());
    const auto count = source.anniversary_hud_remaps.size();
    if(!count) throw std::runtime_error("Selected HUDGlobals has no Anniversary HUD remaps");
    auto converted = source;
    converted.anniversary_hud_remaps.clear();
    auto output = converted.generate_hek_tag_data(HEK::TAG_FOURCC_HUD_GLOBALS, false);
    auto reparsed = Parser::HUDGlobals::parse_hek_tag_file(output.data(), output.size());
    if(!reparsed.anniversary_hud_remaps.empty())
        throw std::runtime_error("Output still contains Anniversary HUD remaps");
    if(!converted.compare(&reparsed, false))
        throw std::runtime_error("Converted HUDGlobals did not reparse identically");
    // Only this vector may differ. Active native fonts, bitmaps, messaging,
    // waypoint/timer/default declarations and all other authored fields remain.
    auto restored = reparsed;
    restored.anniversary_hud_remaps = source.anniversary_hud_remaps;
    if(!source.compare(&restored, false))
        throw std::runtime_error("Other authored HUDGlobals metadata changed");
    std::ostringstream record;
    record << "{\"tag\":" << quoted(name) << ",\"status\":\"converted\","
        << decision_json(count) << ",\"input_bytes\":" << original.size()
        << ",\"output_bytes\":" << output.size()
        << ",\"authored_metadata_preserved\":true,\"metadata_preserved\":true}";
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
    // Complete every proof and verify every independent input before writing.
    for(const auto &item : prepared)
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original ||
           read_file(checked_file(overlay / "tags", item.name)) != item.original)
            throw std::runtime_error("Input changed during conversion preparation");
    for(const auto &item : prepared) {
        auto target = checked_file(overlay / "tags", item.name);
        if(!File::save_file(target, item.output) || read_file(target) != item.output)
            throw std::runtime_error("Output write verification failed");
        if(read_file(checked_file(overlay / "source-snapshots", item.name)) != item.original)
            throw std::runtime_error("Source snapshot changed during output writing");
        std::cout << item.record << '\n';
    }
}

int main(int argc, char **argv) {
    if(argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "Usage: omit-mcc-extensions --audit TAG_ROOT | --convert FRESH_OVERLAY\n"
                     "Clears only HUDGlobals.anniversary_hud_remaps for the native Xbox-v5 target.\n"
                     "Requires asset-paths.txt and independent identical source-snapshots/ and tags/.\n";
        return 0;
    }
    if(argc != 3) { std::cerr << "Expected --audit TAG_ROOT or --convert FRESH_OVERLAY\n"; return 2; }
    try {
        const std::string mode = argv[1];
        if(mode == "--audit") audit(argv[2]);
        else if(mode == "--convert") convert(argv[2]);
        else throw std::runtime_error("Unknown MCC extension helper operation");
        return 0;
    }
    catch(const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
