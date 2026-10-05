// SPDX-License-Identifier: GPL-3.0-only
// Imported community shader compatibility; never modifies the stock renderer.
// Removes one extra layer only after proving all shader parameters and bitmap
// bytes are identical. Removing a repeated blend pass can change brightness.
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
    std::replace(value.begin(), value.end(), '\\', '/');
    return value;
}

static fs::path checked_file(const fs::path &root, const std::string &name) {
    fs::path relative = name;
    if(name.empty() || relative.is_absolute() || name.find_first_of("\t\r\n\\") != std::string::npos)
        throw std::runtime_error("Invalid relative tag path");
    fs::path at = root;
    if(fs::is_symlink(fs::symlink_status(root))) throw std::runtime_error("Symlink root refused");
    for(const auto &part : relative) {
        if(part == "." || part == "..") throw std::runtime_error("Traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing or hard-linked tag refused");
    return at;
}

struct Prepared {
    std::string parent;
    std::vector<std::byte> original;
    std::vector<std::byte> output;
};

static Prepared prepare(const fs::path &overlay, const std::string &parent_name,
                        const std::string &child_name) {
    const fs::path root = overlay / "source-snapshots";
    constexpr auto chicago = HEK::TAG_FOURCC_SHADER_TRANSPARENT_CHICAGO;
    const std::string extension = ".shader_transparent_chicago";
    if(fs::path(parent_name).extension() != extension || fs::path(child_name).extension() != extension)
        throw std::runtime_error("Only Chicago parent/child shader paths are supported");
    auto parent_bytes = File::open_file(checked_file(root, parent_name));
    auto child_bytes = File::open_file(checked_file(root, child_name));
    auto target_bytes = File::open_file(checked_file(overlay / "tags", parent_name));
    if(!parent_bytes || !child_bytes || !target_bytes || *parent_bytes != *target_bytes)
        throw std::runtime_error("Snapshot/output input differs; repeat conversion refused");
    auto parent = Parser::ShaderTransparentChicago::parse_hek_tag_file(parent_bytes->data(), parent_bytes->size());
    auto child = Parser::ShaderTransparentChicago::parse_hek_tag_file(child_bytes->data(), child_bytes->size());
    if(parent.extra_layers.size() != 1 || !child.extra_layers.empty() || parent.maps.empty()
        || parent.maps.size() != child.maps.size())
        throw std::runtime_error("Expected exactly one terminal duplicate layer and matching maps");
    const auto &reference = parent.extra_layers.front().shader;
    if(reference.tag_fourcc != chicago || normalized(reference.path) + extension != child_name)
        throw std::runtime_error("Reviewed duplicate shader reference differs");
    // Prove map art equality before normalizing only dependency identity for
    // the full parser comparison. Entire bitmap files must be byte-identical,
    // a stricter requirement than just equal decoded pixels.
    for(size_t i = 0; i < parent.maps.size(); i++) {
        const auto &a = parent.maps[i].map;
        const auto &b = child.maps[i].map;
        if(a.tag_fourcc != HEK::TAG_FOURCC_BITMAP || b.tag_fourcc != HEK::TAG_FOURCC_BITMAP
            || a.path.empty() || b.path.empty())
            throw std::runtime_error("Non-bitmap or empty map reference refused");
        auto a_bytes = File::open_file(checked_file(root, normalized(a.path) + ".bitmap"));
        auto b_bytes = File::open_file(checked_file(root, normalized(b.path) + ".bitmap"));
        if(!a_bytes || !b_bytes || *a_bytes != *b_bytes)
            throw std::runtime_error("Layer bitmap bytes differ; nonredundant layer refused");
        child.maps[i].map = a;
    }
    auto output_tag = parent;
    output_tag.extra_layers.clear();
    if(!output_tag.compare(&child, false))
        throw std::runtime_error("Shader parameters differ; nonredundant layer refused");
    auto output = output_tag.generate_hek_tag_data(chicago, false);
    auto reparsed = Parser::ShaderTransparentChicago::parse_hek_tag_file(output.data(), output.size());
    if(!output_tag.compare(&reparsed, false)) throw std::runtime_error("Output did not reparse identically");
    reparsed.extra_layers = parent.extra_layers;
    if(!parent.compare(&reparsed, false)) throw std::runtime_error("A primary shader parameter changed");
    return {parent_name, *parent_bytes, std::move(output)};
}

int main(int argc, char **argv) {
    if(argc != 2 || std::string(argv[1]) == "--help") {
        std::cout << "Usage: convert-chicago-layers FRESH_OVERLAY\n"
                  << "Requires guarded shader-actions.tsv, snapshots and identical parent tags.\n";
        return argc == 2 ? 0 : 2;
    }
    try {
        fs::path overlay = argv[1];
        if(fs::is_symlink(fs::symlink_status(overlay))) throw std::runtime_error("Symlink overlay refused");
        std::ifstream actions(overlay / "shader-actions.tsv");
        if(!actions) throw std::runtime_error("Missing shader-actions.tsv");
        std::vector<Prepared> prepared;
        for(std::string line; std::getline(actions, line);) {
            auto delimiter = line.find('\t');
            if(delimiter == std::string::npos || line.find('\t', delimiter + 1) != std::string::npos)
                throw std::runtime_error("Expected parent and duplicate-layer columns");
            auto parent = line.substr(0, delimiter), child = line.substr(delimiter + 1);
            if(std::any_of(prepared.begin(), prepared.end(), [&](const auto &item){return item.parent == parent;}))
                throw std::runtime_error("Duplicate parent action");
            prepared.push_back(prepare(overlay, parent, child));
        }
        if(prepared.empty()) throw std::runtime_error("Empty shader profile");
        // Prove every action before writing any converted tag.
        for(const auto &item : prepared) {
            auto destination = checked_file(overlay / "tags", item.parent);
            auto current = File::open_file(destination);
            if(!current || *current != item.original) throw std::runtime_error("Output input changed");
            if(!File::save_file(destination, item.output)) throw std::runtime_error("Output write failed");
            std::cout << "shader\t" << item.parent << "\t1\t0\t" << item.original.size()
                      << '\t' << item.output.size() << "\tall_primary_parameters_preserved\n";
        }
        return 0;
    }
    catch(const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
