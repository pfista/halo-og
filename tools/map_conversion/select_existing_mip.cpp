// SPDX-License-Identifier: GPL-3.0-only
// Reviewed community texture-cache adaptation, independent of the stock engine.
// Selects an existing compressed mip; never decodes, resamples or recompresses.
#include <invader/tag/parser/parser.hpp>
#include <invader/file/file.hpp>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
using namespace Invader;
namespace fs = std::filesystem;

static fs::path checked_file(const fs::path &root, const std::string &name) {
    const fs::path relative(name);
    if(name.empty() || relative.is_absolute() || relative.lexically_normal().generic_string() != name
       || name.find_first_of("\t\r\n\\") != std::string::npos)
        throw std::runtime_error("Invalid normalized relative input path");
    for(const auto &part : relative)
        if(part.empty() || part == "." || part == "..") throw std::runtime_error("Traversal refused");
    auto path = fs::absolute(root / relative);
    fs::path at;
    for(const auto &part : path) {
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(path) || fs::hard_link_count(path) != 1)
        throw std::runtime_error("Missing or hard-linked input refused");
    return path;
}

static std::size_t dxt5_mip_bytes(std::size_t width, std::size_t height) {
    return std::max<std::size_t>(1, (width + 3) / 4) * std::max<std::size_t>(1, (height + 3) / 4) * 16;
}

struct Prepared {
    std::string name;
    std::vector<std::byte> original, output;
    std::size_t removed, old_bytes, new_bytes;
};

static Prepared prepare(const fs::path &overlay, const std::string &name) {
    if(fs::path(name).extension() != ".bitmap") throw std::runtime_error("Only bitmap tag paths supported");
    auto snapshot = checked_file(overlay / "source-snapshots", name);
    auto target = checked_file(overlay / "tags", name);
    if(fs::equivalent(snapshot, target)) throw std::runtime_error("Snapshot/output must be independent copies");
    auto source_bytes = File::open_file(snapshot), initial_bytes = File::open_file(target);
    if(!source_bytes || !initial_bytes || *source_bytes != *initial_bytes)
        throw std::runtime_error("Snapshot/output input differs; repeat conversion refused");
    auto original = Parser::Bitmap::parse_hek_tag_file(source_bytes->data(), source_bytes->size());
    if(original.type != HEK::BITMAP_TYPE_2D_TEXTURES || original.bitmap_data.size() != 1
        || !original.compressed_color_plate_data.empty())
        throw std::runtime_error("Expected exactly one processed 2D image without a source color plate");
    const auto &image = original.bitmap_data.front();
    if(image.width != 2048 || image.height != 2048 || image.depth != 1
        || image.type != HEK::BITMAP_DATA_TYPE_2D_TEXTURE || image.format != HEK::BITMAP_DATA_FORMAT_DXT5
        || image.mipmap_count != 11 || image.pixel_data_offset != 0
        || image.flags != (HEK::BITMAP_DATA_FLAGS_FLAG_POWER_OF_TWO_DIMENSIONS | HEK::BITMAP_DATA_FLAGS_FLAG_COMPRESSED))
        throw std::runtime_error("Expected reviewed unswizzled 2048-square DXT5 image with eleven lower mips");
    // Model textures have no HUD registration placement. Retain the authored
    // registration point, top-level mip generation setting, sequences and flags.
    std::size_t expected = 0, width = image.width, height = image.height;
    for(unsigned i = 0; i <= image.mipmap_count; i++) {
        expected += dxt5_mip_bytes(width, height);
        width = std::max<std::size_t>(1, width / 2);
        height = std::max<std::size_t>(1, height / 2);
    }
    const auto removed = dxt5_mip_bytes(image.width, image.height);
    if(expected != 5592432 || original.processed_pixel_data.size() != expected || removed != 4194304)
        throw std::runtime_error("Authored mip chain payload size differs from reviewed DXT5 layout");
    auto converted = original;
    converted.bitmap_data.front().width /= 2;
    converted.bitmap_data.front().height /= 2;
    converted.bitmap_data.front().mipmap_count--;
    converted.processed_pixel_data.erase(converted.processed_pixel_data.begin(),
                                         converted.processed_pixel_data.begin() + removed);
    auto output = converted.generate_hek_tag_data(HEK::TAG_FOURCC_BITMAP, false);
    auto reparsed = Parser::Bitmap::parse_hek_tag_file(output.data(), output.size());
    if(!converted.compare(&reparsed, false)) throw std::runtime_error("Output did not reparse identically");
    if(reparsed.processed_pixel_data.size() != expected - removed
        || !std::equal(reparsed.processed_pixel_data.begin(), reparsed.processed_pixel_data.end(),
                       original.processed_pixel_data.begin() + removed))
        throw std::runtime_error("Retained authored compressed mip bytes changed");
    reparsed.bitmap_data.front().width = image.width;
    reparsed.bitmap_data.front().height = image.height;
    reparsed.bitmap_data.front().mipmap_count = image.mipmap_count;
    reparsed.processed_pixel_data = original.processed_pixel_data;
    if(!original.compare(&reparsed, false)) throw std::runtime_error("An unreviewed bitmap parameter changed");
    return {name, *source_bytes, std::move(output), removed, expected, expected - removed};
}

int main(int argc, char **argv) {
    if(argc != 2 || std::string(argv[1]) == "--help") {
        std::cout << "Usage: convert-existing-mip FRESH_OVERLAY\n"
                     "Requires mip-actions.tsv and independent byte-identical snapshots/tags.\n";
        return argc == 2 ? 0 : 2;
    }
    try {
        const fs::path overlay(argv[1]);
        auto actions_path = checked_file(overlay, "mip-actions.tsv");
        std::ifstream actions(actions_path);
        if(!actions) throw std::runtime_error("Missing mip-actions.tsv");
        std::vector<Prepared> prepared;
        std::set<std::string> names;
        for(std::string line; std::getline(actions, line);) {
            const auto first = line.find('\t'), second = line.find('\t', first == std::string::npos ? 0 : first + 1);
            if(first == std::string::npos || second == std::string::npos
                || line.find('\t', second + 1) != std::string::npos
                || line.substr(first + 1, second - first - 1) != "0" || line.substr(second + 1) != "1")
                throw std::runtime_error("Expected tag, bitmap index zero and one top mip columns");
            auto name = line.substr(0, first);
            if(!names.insert(name).second) throw std::runtime_error("Duplicate bitmap action");
            prepared.push_back(prepare(overlay, name));
        }
        if(prepared.empty()) throw std::runtime_error("Empty mip selection profile");
        // Validate every input again before the first write, then write only tags/.
        for(const auto &item : prepared) {
            auto current = File::open_file(checked_file(overlay / "tags", item.name));
            auto snapshot = File::open_file(checked_file(overlay / "source-snapshots", item.name));
            if(!current || !snapshot || *current != item.original || *snapshot != item.original)
                throw std::runtime_error("Input changed after preparation");
        }
        for(const auto &item : prepared) {
            auto destination = checked_file(overlay / "tags", item.name);
            if(!File::save_file(destination, item.output)) throw std::runtime_error("Output write failed");
            std::cout << "bitmap\t" << item.name << "\t0\t1\t2048\t1024\t" << item.removed
                      << '\t' << item.old_bytes << '\t' << item.new_bytes
                      << "\tlower_mip_bytes_preserved\tall_other_parameters_preserved\n";
        }
        return 0;
    }
    catch(const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
