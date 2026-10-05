// SPDX-License-Identifier: GPL-3.0-only
// Reviewed map-local compatibility: append selected source marker structs.
// Stock checkpoint reuse is an explicit content change, never an engine rule.
#include <invader/tag/parser/parser.hpp>
#include <invader/file/file.hpp>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace Invader;
namespace fs = std::filesystem;

static fs::path checked_file(const fs::path &root, const std::string &name) {
    fs::path relative = name, at = root;
    if(name.empty() || relative.is_absolute() || relative.extension() != ".scenario" ||
       name.find_first_of("\t\r\n\\") != std::string::npos || fs::is_symlink(fs::symlink_status(root)))
        throw std::runtime_error("Invalid scenario path or symlink root");
    for(const auto &part : relative) {
        if(part == "." || part == "..") throw std::runtime_error("Traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing or hard-linked scenario refused");
    return at;
}
static std::vector<std::string> split(const std::string &line) {
    std::vector<std::string> result; std::size_t start = 0;
    do {auto end = line.find('\t', start); result.push_back(line.substr(start, end-start));
        if(end == std::string::npos) break; start = end+1;} while(true);
    return result;
}
static std::size_t number(const std::string &value, std::size_t limit) {
    if(value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
        throw std::runtime_error("Invalid numeric expectation");
    std::size_t read = 0, result = std::stoul(value, &read);
    if(read != value.size() || result > limit) throw std::runtime_error("Numeric expectation exceeds native limit");
    return result;
}
static void convert(const fs::path &overlay) {
    if(fs::is_symlink(fs::symlink_status(overlay))) throw std::runtime_error("Symlink overlay refused");
    std::ifstream config(overlay / "netgame-flags.tsv"); std::string line;
    if(!std::getline(config, line)) throw std::runtime_error("Missing netgame-flags.tsv");
    auto fields = split(line);
    if(fields.size() != 6) throw std::runtime_error("Expected source/target paths, type and three counts");
    const auto &source_name = fields[0], &target_name = fields[1];
    auto type_id = number(fields[2], 8);
    // Only independently identified single markers are supported. A hill is a
    // polygon, and vehicle/vegas markers need their own reviewed semantics.
    if(type_id != 0 && type_id != 2 && type_id != 3 && type_id != 6 && type_id != 7)
        throw std::runtime_error("Unsupported marker type");
    auto expected_source_count = number(fields[3], 200);
    auto expected_target_count = number(fields[4], 200);
    auto expected_target_type_count = number(fields[5], 200);
    std::vector<std::size_t> ids;
    while(std::getline(config, line)) {
        auto id = number(line, type_id == 3 ? 31 : (type_id == 0 ? 1 : 65534));
        if(std::find(ids.begin(), ids.end(), id) != ids.end()) throw std::runtime_error("Duplicate selected ID");
        ids.push_back(id);
    }
    if(ids.empty() || ids.size() + expected_target_count > 200)
        throw std::runtime_error("Empty selection or too many netgame flags");
    auto source_bytes = File::open_file(checked_file(overlay / "source-snapshots/source", source_name));
    auto target_bytes = File::open_file(checked_file(overlay / "source-snapshots/target", target_name));
    if(!source_bytes || !target_bytes) throw std::runtime_error("Missing source snapshots");
    auto source = Parser::Scenario::parse_hek_tag_file(source_bytes->data(), source_bytes->size());
    auto input = Parser::Scenario::parse_hek_tag_file(target_bytes->data(), target_bytes->size());
    if(input.type != HEK::SCENARIO_TYPE_MULTIPLAYER) throw std::runtime_error("Target is not multiplayer");
    auto matching = [type_id](const auto &flags) {
        return std::count_if(flags.begin(), flags.end(), [type_id](const auto &flag) {return flag.type == type_id;});
    };
    if(source.netgame_flags.size() > 200 || input.netgame_flags.size() != expected_target_count ||
       matching(source.netgame_flags) != expected_source_count || matching(input.netgame_flags) != expected_target_type_count)
        throw std::runtime_error("Reviewed source/target flag counts changed");
    std::vector<Parser::ScenarioNetgameFlags> selected;
    for(auto id : ids) {
        std::size_t count = 0;
        for(const auto &flag : source.netgame_flags) {
            if(flag.type == type_id && flag.usage_id == id) {selected.push_back(flag); count++;}
        }
        if(count != 1) throw std::runtime_error("Selected marker is missing or has a duplicate ID");
        for(const auto &flag : input.netgame_flags)
            if(flag.type == type_id && flag.usage_id == id) throw std::runtime_error("Target already contains selected marker ID");
    }
    auto output = input;
    output.netgame_flags.insert(output.netgame_flags.end(), selected.begin(), selected.end());
    auto bytes = output.generate_hek_tag_data(HEK::TAG_FOURCC_SCENARIO, false);
    auto parsed = Parser::Scenario::parse_hek_tag_file(bytes.data(), bytes.size());
    if(!output.compare(&parsed, false)) throw std::runtime_error("Output reparse mismatch");
    for(std::size_t i=0; i<selected.size(); i++)
        if(!selected[i].compare(&parsed.netgame_flags[expected_target_count+i], false))
            throw std::runtime_error("A copied source marker field changed");
    parsed.netgame_flags.resize(expected_target_count);
    if(!input.compare(&parsed, false)) throw std::runtime_error("An original target field changed");
    fs::path destination = overlay / "tags" / target_name;
    if(fs::exists(destination) || fs::is_symlink(fs::symlink_status(destination)))
        throw std::runtime_error("Existing output refused");
    fs::path at = overlay / "tags";
    if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink output root refused");
    for(const auto &part : fs::path(target_name).parent_path()) {
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink output refused");
    }
    fs::create_directories(destination.parent_path());
    std::ofstream out(destination, std::ios::binary | std::ios::out);
    if(!out) throw std::runtime_error("Unable to create output scenario");
    out.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    if(!out) throw std::runtime_error("Unable to write output scenario");
    std::cout << "Appended " << selected.size() << " exact source markers; every original target field preserved\n";
}
int main(int argc, char **argv) {
    if(argc != 2 || std::string(argv[1]) == "--help") {
        std::cout << "Usage: append-netgame-flags FRESH_OVERLAY\nRequires guarded netgame-flags.tsv and separate source/target snapshots.\n";
        return argc == 2 ? 0 : 2;
    }
    try {convert(argv[1]); return 0;}
    catch(const std::exception &e) {std::cerr << e.what() << '\n'; return 1;}
}
