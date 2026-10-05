// SPDX-License-Identifier: GPL-3.0-only
// Community compatibility conversion; stock Xbox sound playback is unchanged.
// Uses the reviewed Invader API. Input HEK PCM is signed 16-bit big endian.
#include <invader/tag/parser/parser.hpp>
#include <invader/sound/sound_reader.hpp>
#include <invader/sound/sound_encoder.hpp>
#include <invader/file/file.hpp>
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace Invader;
namespace fs = std::filesystem;

static fs::path checked_file(const fs::path &root, const fs::path &relative) {
    if(relative.empty() || relative.is_absolute() || relative.extension() != ".sound")
        throw std::runtime_error("Expected a relative .sound path");
    auto at = root;
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

static void convert(const fs::path &overlay, const std::string &name) {
    auto input = checked_file(overlay / "source-snapshots", name);
    auto target = checked_file(overlay / "tags", name);
    auto bytes = File::open_file(input), target_bytes = File::open_file(target);
    if(!bytes || !target_bytes || *bytes != *target_bytes)
        throw std::runtime_error("Source snapshot differs from output input; repeat conversion refused");
    auto source = Parser::Sound::parse_hek_tag_file(bytes->data(), bytes->size());
    auto tag = source;
    if(tag.format != HEK::SOUND_FORMAT_16_BIT_PCM)
        throw std::runtime_error("Only reviewed 16-bit PCM input is supported");
    const size_t channels = tag.channel_count == HEK::SOUND_CHANNEL_COUNT_MONO ? 1 :
        tag.channel_count == HEK::SOUND_CHANNEL_COUNT_STEREO ? 2 : 0;
    const size_t rate = tag.sample_rate == HEK::SOUND_SAMPLE_RATE_22050_HZ ? 22050 :
        tag.sample_rate == HEK::SOUND_SAMPLE_RATE_44100_HZ ? 44100 : 0;
    if(!channels || !rate || (channels == 1 && rate != 22050))
        throw std::runtime_error("Source rate/channels do not satisfy the native Xbox gate");
    size_t permutations = 0;
    for(size_t r = 0; r < tag.pitch_ranges.size(); r++) {
        auto &range = tag.pitch_ranges[r];
        for(size_t i = 0; i < range.permutations.size(); i++) {
            auto &p = range.permutations[i];
            if(p.format != HEK::SOUND_FORMAT_16_BIT_PCM || p.samples.empty() || p.buffer_size != p.samples.size())
                throw std::runtime_error("Unexpected permutation codec, empty PCM, or buffer length");
            auto decoded = SoundReader::sound_from_16_bit_pcm_big_endian(p.samples.data(), p.samples.size(), channels, rate);
            const size_t frames = decoded.pcm.size() / (2 * channels);
            const size_t padding = (64 - frames % 64) % 64;
            decoded.pcm.resize(decoded.pcm.size() + padding * channels * 2, std::byte{0});
            auto encoded = SoundEncoder::encode_to_xbox_adpcm(decoded.pcm, 16, channels);
            if(encoded.size() != ((frames + padding) / 64) * 36 * channels)
                throw std::runtime_error("ADPCM frame/block size mismatch");
            auto roundtrip = SoundReader::sound_from_xbox_adpcm(encoded.data(), encoded.size(), channels, rate);
            if(roundtrip.pcm.size() != decoded.pcm.size()) throw std::runtime_error("Decoded frame count changed");
            double signal = 0, error = 0, maximum_error = 0;
            for(size_t s = 0; s < frames * channels; s++) {
                double a = SoundEncoder::read_sample(decoded.pcm.data() + s * 2, 16);
                double b = SoundEncoder::read_sample(roundtrip.pcm.data() + s * 2, 16);
                signal += a * a; error += (a - b) * (a - b);
                maximum_error = std::max(maximum_error, std::abs(a - b));
            }
            std::cout << "permutation\t" << name << '\t' << r << '\t' << i << '\t'
                << channels << '\t' << rate << '\t' << frames << '\t' << padding << '\t'
                << encoded.size() << '\t' << std::setprecision(10)
                << (error > 0 && signal > 0 ? 10 * std::log10(signal / error) : 0) << '\t'
                << maximum_error << '\n';
            p.samples = std::move(encoded);
            p.format = HEK::SOUND_FORMAT_XBOX_ADPCM;
            p.buffer_size = 0;
            permutations++;
        }
    }
    if(!permutations) throw std::runtime_error("No permutations");
    tag.format = HEK::SOUND_FORMAT_XBOX_ADPCM;
    auto output = tag.generate_hek_tag_data(HEK::TAG_FOURCC_SOUND, false);
    auto reparsed = Parser::Sound::parse_hek_tag_file(output.data(), output.size());
    if(!tag.compare(&reparsed)) throw std::runtime_error("Output did not reparse identically");
    // Restore only the three intentionally changed audio fields before comparing
    // every authored playback field: rate, pitch, gain, distance, class and chains.
    reparsed.format = source.format;
    for(size_t r = 0; r < reparsed.pitch_ranges.size(); r++) {
        for(size_t i = 0; i < reparsed.pitch_ranges[r].permutations.size(); i++) {
            auto &p = reparsed.pitch_ranges[r].permutations[i];
            const auto &old = source.pitch_ranges[r].permutations[i];
            p.samples = old.samples; p.format = old.format; p.buffer_size = old.buffer_size;
        }
    }
    if(!source.compare(&reparsed)) throw std::runtime_error("Authored playback metadata changed");
    if(!File::save_file(target, output)) throw std::runtime_error("Output write failed");
    std::cout << "sound\t" << name << '\t' << permutations << '\t' << bytes->size()
        << '\t' << output.size() << "\tmetadata_preserved\n";
}

int main(int argc, char **argv) {
    if(argc != 2 || std::string(argv[1]) == "--help") {
        std::cout << "Usage: convert-sounds FRESH_OVERLAY\n"
            "Requires sound-paths.txt and independent identical source-snapshots/ and tags/ files.\n";
        return argc == 2 ? 0 : 2;
    }
    try {
        fs::path overlay = argv[1];
        if(fs::is_symlink(fs::symlink_status(overlay))) throw std::runtime_error("Symlink overlay refused");
        std::ifstream paths(overlay / "sound-paths.txt");
        if(!paths) throw std::runtime_error("Missing reviewed sound-paths.txt");
        std::vector<std::string> names;
        for(std::string name; std::getline(paths, name);) {
            if(name.empty() || name.find_first_of("\t\r\\") != std::string::npos)
                throw std::runtime_error("Invalid sound path delimiter");
            if(std::find(names.begin(), names.end(), name) != names.end()) throw std::runtime_error("Duplicate sound path");
            // Check every selected input before the first write.
            auto a = checked_file(overlay / "source-snapshots", name), b = checked_file(overlay / "tags", name);
            auto x = File::open_file(a), y = File::open_file(b);
            if(!x || !y || *x != *y) throw std::runtime_error("Source snapshot differs from output input");
            names.push_back(name);
        }
        if(names.empty()) throw std::runtime_error("Empty sound profile");
        for(const auto &name : names) convert(overlay, name);
        std::cout << "summary\t" << names.size() << "\t0\n";
        return 0;
    }
    catch(const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
