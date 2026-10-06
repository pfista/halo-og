// SPDX-License-Identifier: GPL-3.0-only
// Map-local community adaptation: keep the original weapon bytes and stock
// globals/remap rule; redirect explicitly reviewed authored owner references.
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

static std::string normalized(std::string value) {
    std::replace(value.begin(), value.end(), '\\', '/'); return value;
}
static std::string halo_path(std::string value) {
    std::replace(value.begin(), value.end(), '/', '\\'); return value;
}
static fs::path checked_file(const fs::path &root, const std::string &name) {
    fs::path relative = name, at = root;
    if(name.empty() || relative.is_absolute() || name.find_first_of("\t\r\n\\") != std::string::npos)
        throw std::runtime_error("Invalid relative tag path");
    if(fs::is_symlink(fs::symlink_status(root))) throw std::runtime_error("Symlink root refused");
    for(const auto &part : relative) {
        if(part == "." || part == "..") throw std::runtime_error("Traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing or hard-linked input refused");
    return at;
}
static std::vector<std::string> split(const std::string &value) {
    std::vector<std::string> fields; size_t at = 0;
    do {auto next = value.find('\t', at); fields.push_back(value.substr(at, next - at));
        if(next == std::string::npos) break; at = next + 1;} while(true);
    return fields;
}
static void inventory(const Parser::ParserStruct &tag, const std::string &owner,
                      const std::string &wanted, const std::string &prefix = "") {
    using Value = Parser::ParserStructValue;
    for(const auto &value : tag.get_values()) {
        if(!value.get_member_name()) continue;
        auto field = prefix + value.get_member_name();
        if(value.get_type() == Value::VALUE_TYPE_DEPENDENCY) {
            const auto &dep = value.get_dependency();
            if(dep.tag_fourcc == HEK::TAG_FOURCC_WEAPON && normalized(dep.path) == wanted)
                std::cout << "reference\t" << owner << '\t' << field << '\n';
        }
        else if(value.get_type() == Value::VALUE_TYPE_REFLEXIVE) {
            for(size_t i = 0; i < value.get_array_size(); i++)
                inventory(value.get_object_in_array(i), owner, wanted,
                          field + "[" + std::to_string(i) + "].");
        }
    }
}
struct Prepared {std::string path; std::vector<std::byte> input, output; size_t replacements;};

static void convert(const fs::path &overlay) {
    auto snapshots = overlay / "source-snapshots";
    std::ifstream config(overlay / "weapon-alias.tsv"); std::string line;
    if(!std::getline(config, line)) throw std::runtime_error("Missing weapon-alias.tsv");
    auto fields = split(line);
    if(fields.size() != 4 || std::getline(config, line)) throw std::runtime_error("Expected one alias rule");
    const auto &source_name = fields[0], &alias_name = fields[1], &globals_name = fields[2];
    if(fs::path(source_name).extension() != ".weapon" || fs::path(alias_name).extension() != ".weapon"
        || source_name == alias_name || alias_name.rfind("community/", 0) != 0
        || globals_name != "globals/globals.globals")
        throw std::runtime_error("Expected an explicit community weapon alias and original globals");
    auto source_bytes = File::open_file(checked_file(snapshots, source_name));
    auto alias_bytes = File::open_file(checked_file(overlay / "tags", alias_name));
    if(!source_bytes || !alias_bytes || *source_bytes != *alias_bytes)
        throw std::runtime_error("Alias weapon must be byte-identical to its original");
    Parser::Weapon::parse_hek_tag_file(source_bytes->data(), source_bytes->size());
    auto globals_bytes = File::open_file(checked_file(snapshots, globals_name));
    if(!globals_bytes) throw std::runtime_error("Missing original globals proof");
    auto globals = Parser::Globals::parse_hek_tag_file(globals_bytes->data(), globals_bytes->size());
    size_t parsed = 0, slot = std::stoul(fields[3], &parsed);
    if(parsed != fields[3].size() || slot >= globals.weapon_list.size()) throw std::runtime_error("Invalid reserved slot");
    const std::string from = fs::path(source_name).replace_extension().generic_string();
    const std::string to = fs::path(alias_name).replace_extension().generic_string();
    if(globals.weapon_list[slot].weapon.tag_fourcc != HEK::TAG_FOURCC_WEAPON
        || normalized(globals.weapon_list[slot].weapon.path) != from)
        throw std::runtime_error("Original reserved globals slot does not match source weapon");
    for(const auto &entry : globals.weapon_list)
        if(normalized(entry.weapon.path) == to) throw std::runtime_error("Alias already occupies a reserved globals slot");
    const auto from_halo = halo_path(from), to_halo = halo_path(to);
    std::ifstream rules(overlay / "reference-rules.tsv");
    if(!rules) throw std::runtime_error("Missing reference-rules.tsv");
    std::vector<Prepared> prepared;
    while(std::getline(rules, line)) {
        auto values = split(line);
        if(values.size() != 2) throw std::runtime_error("Expected owner and replacement-count columns");
        const auto &name = values[0]; auto extension = fs::path(name).extension().string();
        if(extension != ".scenario" && extension != ".item_collection")
            throw std::runtime_error("Only reviewed scenario/item-collection references may change");
        if(std::any_of(prepared.begin(), prepared.end(), [&](const auto &item){return item.path == name;}))
            throw std::runtime_error("Duplicate reference owner");
        size_t consumed = 0, expected = std::stoul(values[1], &consumed);
        if(!expected || consumed != values[1].size()) throw std::runtime_error("Invalid replacement count");
        auto original = File::open_file(checked_file(snapshots, name));
        auto current = File::open_file(checked_file(overlay / "tags", name));
        if(!original || !current || *original != *current) throw std::runtime_error("Owner input changed; repeat conversion refused");
        auto source = Parser::ParserStruct::parse_hek_tag_file(original->data(), original->size());
        auto tag = Parser::ParserStruct::parse_hek_tag_file(original->data(), original->size());
        // Refuse a pre-existing alias identity; reverse comparison must not
        // collapse another author-defined dependency into this source weapon.
        if(tag->refactor_reference(to_halo.c_str(), HEK::TAG_FOURCC_WEAPON,
                                   from_halo.c_str(), HEK::TAG_FOURCC_WEAPON))
            throw std::runtime_error("Owner already references alias");
        auto changed = tag->refactor_reference(from_halo.c_str(), HEK::TAG_FOURCC_WEAPON,
                                              to_halo.c_str(), HEK::TAG_FOURCC_WEAPON);
        if(changed != expected) throw std::runtime_error("Reviewed reference count differs");
        auto output = tag->generate_hek_tag_data(HEK::tag_extension_to_fourcc(extension.c_str() + 1), false);
        auto reparsed = Parser::ParserStruct::parse_hek_tag_file(output.data(), output.size());
        if(!tag->compare(reparsed.get(), false)) throw std::runtime_error("Converted owner did not reparse exactly");
        if(reparsed->refactor_reference(to_halo.c_str(), HEK::TAG_FOURCC_WEAPON,
                                       from_halo.c_str(), HEK::TAG_FOURCC_WEAPON) != expected
            || !source->compare(reparsed.get(), false))
            throw std::runtime_error("Owner changed beyond the reviewed weapon dependencies");
        prepared.push_back({name, *original, std::move(output), expected});
    }
    // A map with no authored production references may still create the
    // exact alias for an explicitly separate diagnostic fixture.
    for(const auto &item : prepared) {
        auto path = checked_file(overlay / "tags", item.path);
        auto current = File::open_file(path);
        if(!current || *current != item.input) throw std::runtime_error("Owner output changed");
        if(!File::save_file(path, item.output)) throw std::runtime_error("Owner output write failed");
        std::cout << "owner\t" << item.path << '\t' << item.replacements << "\tall_other_parameters_preserved\n";
    }
    std::cout << "alias\t" << source_name << '\t' << alias_name << "\tbyte_identical\n";
    std::cout << "globals\t" << globals_name << '\t' << slot << "\tunchanged\n";
}
int main(int argc, char **argv) {
    try {
        if(argc == 5 && std::string(argv[1]) == "--inventory") {
            fs::path root = argv[2]; std::ifstream names(argv[3]);
            if(!names) throw std::runtime_error("Missing inventory path list");
            std::string wanted = fs::path(argv[4]).replace_extension().generic_string();
            for(std::string name; std::getline(names, name);) {
                auto bytes = File::open_file(checked_file(root, name));
                auto tag = Parser::ParserStruct::parse_hek_tag_file(bytes->data(), bytes->size());
                inventory(*tag, name, wanted);
            }
            return 0;
        }
        if(argc != 2 || std::string(argv[1]) == "--help") {
            std::cout << "Usage: convert-weapon-alias FRESH_OVERLAY\n"
                      << "Inventory: convert-weapon-alias --inventory ROOT PATHS_FILE SOURCE_WEAPON\n";
            return argc == 2 ? 0 : 2;
        }
        if(fs::is_symlink(fs::symlink_status(argv[1]))) throw std::runtime_error("Symlink overlay refused");
        convert(argv[1]); return 0;
    }
    catch(const std::exception &error) {std::cerr << error.what() << '\n'; return 1;}
}
