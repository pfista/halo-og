// SPDX-License-Identifier: GPL-3.0-only
// Offline authored-audio compatibility. No resampling or channel substitution.
#include <invader/tag/parser/parser.hpp>
#include <invader/sound/sound_reader.hpp>
#include <invader/sound/sound_encoder.hpp>
#include <invader/file/file.hpp>
#include <vorbis/vorbisfile.h>
#include <algorithm>
#include <cmath>
#include <cstring>
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

static std::string quote(const std::string &s) {
    std::ostringstream out;
    out << '"';
    for(unsigned char c : s) {
        switch(c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if(c < 32) out << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << unsigned(c) << std::dec;
                else out << c;
        }
    }
    out << '"';
    return out.str();
}

static std::string format_name(HEK::SoundFormat format) {
    switch(format) {
        case HEK::SOUND_FORMAT_16_BIT_PCM: return "16-bit_pcm";
        case HEK::SOUND_FORMAT_XBOX_ADPCM: return "xbox_adpcm";
        case HEK::SOUND_FORMAT_IMA_ADPCM: return "ima_adpcm";
        case HEK::SOUND_FORMAT_OGG_VORBIS: return "ogg_vorbis";
        default: return "unknown_" + std::to_string(static_cast<unsigned>(format));
    }
}

static void checked_root(const fs::path &root) {
    auto absolute = fs::absolute(root);
    fs::path at;
    for(const auto &part : absolute) {
        if(part == "..") throw std::runtime_error("Traversal in root refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink root or parent refused");
    }
    if(!fs::is_directory(root)) throw std::runtime_error("Missing tag/overlay directory");
}

static fs::path checked_file(const fs::path &root, const fs::path &relative, const std::string &extension) {
    if(relative.empty() || relative.is_absolute() || relative.extension() != extension)
        throw std::runtime_error("Expected a relative " + extension + " path");
    checked_root(root);
    auto at = root;
    for(const auto &part : relative) {
        if(part == "." || part == "..") throw std::runtime_error("Traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing, nonregular or hard-linked input refused");
    return at;
}

static std::vector<std::byte> read_file(const fs::path &file) {
    auto bytes = File::open_file(file);
    if(!bytes) throw std::runtime_error("Input read failed");
    return std::move(*bytes);
}

struct Metadata {
    std::set<std::string> formats;
    size_t channels = 0, rate = 0, ranges = 0, permutations = 0, conversions = 0;
    bool needs_conversion = false;
};

static Metadata metadata(const Parser::Sound &tag) {
    Metadata m;
    m.channels = tag.channel_count == HEK::SOUND_CHANNEL_COUNT_MONO ? 1 :
        tag.channel_count == HEK::SOUND_CHANNEL_COUNT_STEREO ? 2 : 0;
    m.rate = tag.sample_rate == HEK::SOUND_SAMPLE_RATE_22050_HZ ? 22050 :
        tag.sample_rate == HEK::SOUND_SAMPLE_RATE_44100_HZ ? 44100 : 0;
    m.ranges = tag.pitch_ranges.size();
    m.formats.insert(format_name(tag.format));
    m.needs_conversion = tag.format != HEK::SOUND_FORMAT_XBOX_ADPCM;
    for(const auto &range : tag.pitch_ranges) for(const auto &p : range.permutations) {
        m.formats.insert(format_name(p.format));
        m.permutations++;
        if(p.format != HEK::SOUND_FORMAT_XBOX_ADPCM) {
            m.conversions++;
            m.needs_conversion = true;
        }
    }
    return m;
}

static std::string formats_json(const Metadata &m) {
    std::ostringstream out;
    out << '[';
    bool first = true;
    for(const auto &f : m.formats) { if(!first) out << ','; first = false; out << quote(f); }
    out << ']';
    return out.str();
}

static std::string metadata_json(const Metadata &m) {
    return "{\"channels\":" + std::to_string(m.channels) + ",\"sample_rate\":" + std::to_string(m.rate) +
        ",\"pitch_ranges\":" + std::to_string(m.ranges) + ",\"permutations\":" + std::to_string(m.permutations) +
        ",\"permutations_to_convert\":" + std::to_string(m.conversions) + "}";
}

static std::string record_prefix(const std::string &name, const std::string &status, const Metadata &m) {
    return "{\"tag\":" + quote(name) + ",\"status\":" + quote(status) +
        ",\"source_formats\":" + formats_json(m) + ",\"metadata\":" + metadata_json(m);
}

static void native_gate(const Metadata &m) {
    if(!m.channels || !m.rate || (m.channels == 1 && m.rate != 22050))
        throw std::runtime_error("Native Xbox audio requires mono 22050 Hz, or stereo 22050/44100 Hz; no resampling/downmix policy is selected");
}

struct VorbisInput {
    const std::vector<std::byte> &bytes;
    size_t position = 0;
    static size_t read(void *out, size_t size, size_t count, void *context) {
        auto &in = *static_cast<VorbisInput *>(context);
        if(!size) return 0;
        const size_t taken = std::min(count, (in.bytes.size() - in.position) / size);
        std::memcpy(out, in.bytes.data() + in.position, taken * size);
        in.position += taken * size;
        return taken;
    }
    static int seek(void *context, ogg_int64_t offset, int whence) {
        auto &in = *static_cast<VorbisInput *>(context);
        if(in.bytes.size() > static_cast<size_t>(std::numeric_limits<ogg_int64_t>::max())) return -1;
        ogg_int64_t base = -1;
        if(whence == SEEK_SET) base = 0;
        else if(whence == SEEK_CUR) base = static_cast<ogg_int64_t>(in.position);
        else if(whence == SEEK_END) base = static_cast<ogg_int64_t>(in.bytes.size());
        if(base < 0 || (offset > 0 && offset > static_cast<ogg_int64_t>(in.bytes.size()) - base) ||
           (offset < 0 && offset < -base)) return -1;
        in.position = static_cast<size_t>(base + offset);
        return 0;
    }
    static long tell(void *context) {
        auto &in = *static_cast<VorbisInput *>(context);
        return in.position <= static_cast<size_t>(std::numeric_limits<long>::max()) ? static_cast<long>(in.position) : -1;
    }
};

static size_t vorbis_frames(const std::vector<std::byte> &bytes, const Metadata &m) {
    VorbisInput input{bytes};
    OggVorbis_File file{};
    ov_callbacks callbacks{VorbisInput::read, VorbisInput::seek, nullptr, VorbisInput::tell};
    if(ov_open_callbacks(&input, &file, nullptr, 0, callbacks) < 0)
        throw std::runtime_error("Invalid Vorbis container");
    struct Clear { OggVorbis_File &file; ~Clear() { ov_clear(&file); } } clear{file};
    if(ov_streams(&file) != 1) throw std::runtime_error("Chained Vorbis streams require a separately reviewed policy");
    const auto *info = ov_info(&file, -1);
    if(!info || info->channels != static_cast<int>(m.channels) || info->rate != static_cast<long>(m.rate))
        throw std::runtime_error("Vorbis payload rate/channels differ from authored tag metadata (payload " +
            std::to_string(info ? info->rate : 0) + " Hz/" + std::to_string(info ? info->channels : 0) +
            " channels, tag " + std::to_string(m.rate) + " Hz/" + std::to_string(m.channels) + " channels)");
    const auto frames = ov_pcm_total(&file, -1);
    if(frames <= 0 || static_cast<unsigned long long>(frames) > std::numeric_limits<size_t>::max() / (3 * m.channels))
        throw std::runtime_error("Invalid Vorbis frame count");
    return static_cast<size_t>(frames);
}

static SoundReader::Sound decode(const Parser::SoundPermutation &p, const Metadata &m) {
    if(p.samples.empty()) throw std::runtime_error("Empty audio permutation refused");
    SoundReader::Sound decoded;
    if(p.format == HEK::SOUND_FORMAT_16_BIT_PCM) {
        if(p.samples.size() != p.buffer_size)
            throw std::runtime_error("PCM buffer_size differs from authored payload length");
        decoded = SoundReader::sound_from_16_bit_pcm_big_endian(p.samples.data(), p.samples.size(), m.channels, m.rate);
    }
    else if(p.format == HEK::SOUND_FORMAT_OGG_VORBIS) {
        const size_t frames = vorbis_frames(p.samples, m);
        decoded = SoundReader::sound_from_ogg(p.samples.data(), p.samples.size());
        if(decoded.bits_per_sample != 24 || frames * m.channels * 3 != decoded.pcm.size())
            throw std::runtime_error("Vorbis decoded sample count differs from container duration");
    }
    else throw std::runtime_error("Unsupported permutation codec: " + format_name(p.format));
    if(decoded.channel_count != m.channels || decoded.sample_rate != m.rate)
        throw std::runtime_error("Decoded payload rate/channels differ from authored tag metadata (payload " +
            std::to_string(decoded.sample_rate) + " Hz/" + std::to_string(decoded.channel_count) +
            " channels, tag " + std::to_string(m.rate) + " Hz/" + std::to_string(m.channels) + " channels)");
    if((decoded.bits_per_sample != 16 && decoded.bits_per_sample != 24) || decoded.pcm.empty() ||
       decoded.pcm.size() % (m.channels * (decoded.bits_per_sample / 8)) != 0)
        throw std::runtime_error("Invalid decoded PCM frame layout");
    return decoded;
}

static void validate(const Parser::Sound &tag, const Metadata &m) {
    native_gate(m);
    if(tag.format != HEK::SOUND_FORMAT_XBOX_ADPCM && tag.format != HEK::SOUND_FORMAT_16_BIT_PCM &&
       tag.format != HEK::SOUND_FORMAT_OGG_VORBIS)
        throw std::runtime_error("Unsupported tag codec: " + format_name(tag.format));
    if(m.needs_conversion && !m.permutations) throw std::runtime_error("No audio permutations to convert");
    for(size_t r = 0; r < tag.pitch_ranges.size(); r++) {
        const auto &range = tag.pitch_ranges[r];
        for(size_t i = 0; i < range.permutations.size(); i++) {
            const auto &p = range.permutations[i];
            try {
                if(p.format == HEK::SOUND_FORMAT_XBOX_ADPCM) {
                    if(!p.samples.empty() && p.samples.size() % (36 * m.channels) != 0)
                        throw std::runtime_error("Native ADPCM payload has an incomplete channel block");
                }
                else decode(p, m);
            }
            catch(const std::exception &e) {
                throw std::runtime_error("pitch_range " + std::to_string(r) + ", permutation " + std::to_string(i) + ": " + e.what());
            }
        }
    }
}

static void audit(const fs::path &root) {
    checked_root(root);
    std::vector<std::string> names;
    for(const auto &entry : fs::recursive_directory_iterator(root)) {
        if(entry.path().extension() == ".sound" &&
           (entry.is_regular_file() || fs::is_symlink(entry.symlink_status())))
            names.push_back(entry.path().lexically_relative(root).generic_string());
    }
    std::sort(names.begin(), names.end());
    for(const auto &name : names) {
        Metadata m;
        try {
            auto bytes = read_file(checked_file(root, name, ".sound"));
            auto tag = Parser::Sound::parse_hek_tag_file(bytes.data(), bytes.size());
            m = metadata(tag);
            validate(tag, m);
            if(m.needs_conversion) std::cout << record_prefix(name, "convertible", m) << "}\n";
        }
        catch(const std::exception &e) {
            std::cout << record_prefix(name, "unsupported", m) << ",\"reason\":" << quote(e.what()) << "}\n";
        }
    }
}

static std::string convert(const fs::path &overlay, const std::string &name) {
    auto input = checked_file(overlay / "source-snapshots", name, ".sound");
    auto target = checked_file(overlay / "tags", name, ".sound");
    auto bytes = read_file(input), target_bytes = read_file(target);
    if(bytes != target_bytes) throw std::runtime_error("Source snapshot differs from output input; repeat conversion refused");
    auto source = Parser::Sound::parse_hek_tag_file(bytes.data(), bytes.size());
    auto tag = source;
    auto m = metadata(tag);
    validate(tag, m);
    if(!m.needs_conversion) throw std::runtime_error("Selected tag already uses native ADPCM; no conversion needed");
    std::ostringstream stats;
    stats << std::setprecision(12) << '[';
    size_t conversions = 0, padding_total = 0;
    for(size_t r = 0; r < tag.pitch_ranges.size(); r++) {
        auto &range = tag.pitch_ranges[r];
        for(size_t i = 0; i < range.permutations.size(); i++) {
            auto &p = range.permutations[i];
            if(p.format == HEK::SOUND_FORMAT_XBOX_ADPCM) continue;
            auto decoded = decode(p, m);
            const size_t bytes_per_sample = decoded.bits_per_sample / 8;
            const size_t frames = decoded.pcm.size() / (bytes_per_sample * m.channels);
            const size_t padding = (64 - frames % 64) % 64;
            if(decoded.pcm.size() > std::numeric_limits<size_t>::max() - padding * m.channels * bytes_per_sample)
                throw std::runtime_error("PCM padding overflow");
            decoded.pcm.resize(decoded.pcm.size() + padding * m.channels * bytes_per_sample, std::byte{0});
            auto encoded = SoundEncoder::encode_to_xbox_adpcm(decoded.pcm, decoded.bits_per_sample, m.channels);
            if(encoded.size() != ((frames + padding) / 64) * 36 * m.channels)
                throw std::runtime_error("ADPCM encoded block size mismatch");
            auto roundtrip = SoundReader::sound_from_xbox_adpcm(encoded.data(), encoded.size(), m.channels, m.rate);
            if(roundtrip.bits_per_sample != 16 || roundtrip.pcm.size() != (frames + padding) * m.channels * 2)
                throw std::runtime_error("ADPCM roundtrip frame count changed");
            double signal = 0, error = 0, maximum_error = 0;
            const double source_scale = std::ldexp(1.0, decoded.bits_per_sample - 1);
            for(size_t s = 0; s < frames * m.channels; s++) {
                const double a = SoundEncoder::read_sample(decoded.pcm.data() + s * bytes_per_sample, decoded.bits_per_sample) / source_scale;
                const double b = SoundEncoder::read_sample(roundtrip.pcm.data() + s * 2, 16) / 32768.0;
                signal += a * a;
                error += (a - b) * (a - b);
                maximum_error = std::max(maximum_error, std::abs(a - b));
            }
            if(conversions++) stats << ',';
            stats << "{\"pitch_range\":" << r << ",\"permutation\":" << i << ",\"source_format\":" << quote(format_name(p.format))
                << ",\"decoded_bits_per_sample\":" << decoded.bits_per_sample << ",\"frames\":" << frames
                << ",\"padding_frames\":" << padding << ",\"padding_ms\":" << (padding * 1000.0 / m.rate)
                << ",\"encoded_bytes\":" << encoded.size() << ",\"snr_db\":";
            if(error > 0 && signal > 0) stats << 10 * std::log10(signal / error);
            else stats << "null";
            stats << ",\"signal_is_silent\":" << (signal == 0 ? "true" : "false")
                << ",\"waveform_exact\":" << (error == 0 ? "true" : "false")
                << ",\"rms_error_normalized\":" << std::sqrt(error / (frames * m.channels))
                << ",\"peak_error_normalized\":" << maximum_error << '}';
            padding_total += padding;
            p.samples = std::move(encoded);
            p.format = HEK::SOUND_FORMAT_XBOX_ADPCM;
            p.buffer_size = 0;
        }
    }
    stats << ']';
    tag.format = HEK::SOUND_FORMAT_XBOX_ADPCM;
    auto output = tag.generate_hek_tag_data(HEK::TAG_FOURCC_SOUND, false);
    auto verify = Parser::Sound::parse_hek_tag_file(output.data(), output.size());
    if(!tag.compare(&verify)) throw std::runtime_error("Output did not reparse identically");
    for(const auto &range : verify.pitch_ranges) for(const auto &p : range.permutations)
        if(p.format != HEK::SOUND_FORMAT_XBOX_ADPCM) throw std::runtime_error("Output contains nonnative permutation codec");
    // Restore only the allowed audio edits, then compare every authored field.
    // Existing ADPCM payloads/buffers are compared without restoration.
    verify.format = source.format;
    for(size_t r = 0; r < verify.pitch_ranges.size(); r++) for(size_t i = 0; i < verify.pitch_ranges[r].permutations.size(); i++) {
        const auto &old = source.pitch_ranges[r].permutations[i];
        auto &p = verify.pitch_ranges[r].permutations[i];
        if(old.format == HEK::SOUND_FORMAT_XBOX_ADPCM) continue;
        p.samples = old.samples;
        p.format = old.format;
        p.buffer_size = old.buffer_size;
    }
    if(!source.compare(&verify)) throw std::runtime_error("Authored playback metadata or native ADPCM payload changed");
    // Recheck both independent inputs immediately before the only file mutation.
    if(read_file(checked_file(overlay / "source-snapshots", name, ".sound")) != bytes ||
       read_file(checked_file(overlay / "tags", name, ".sound")) != target_bytes)
        throw std::runtime_error("Input changed during conversion");
    if(!File::save_file(target, output)) throw std::runtime_error("Output write failed");
    return record_prefix(name, "converted", m) + ",\"target_format\":\"xbox_adpcm\",\"input_bytes\":" +
        std::to_string(bytes.size()) + ",\"output_bytes\":" + std::to_string(output.size()) +
        ",\"converted_permutations\":" + std::to_string(conversions) + ",\"preserved_adpcm_permutations\":" +
        std::to_string(m.permutations - conversions) + ",\"padding_frames_total\":" + std::to_string(padding_total) +
        ",\"authored_metadata_preserved\":true,\"permutations\":" + stats.str() + "}";
}

static void convert_overlay(const fs::path &overlay) {
    checked_root(overlay);
    auto list = checked_file(overlay, "asset-paths.txt", ".txt");
    std::ifstream paths(list);
    if(!paths) throw std::runtime_error("Missing asset-paths.txt");
    std::vector<std::string> names;
    std::set<std::string> unique;
    for(std::string name; std::getline(paths, name);) {
        if(name.empty() || name.find_first_of("\t\r\\") != std::string::npos || name.find('\0') != std::string::npos)
            throw std::runtime_error("Invalid asset path delimiter");
        if(!unique.insert(name).second) throw std::runtime_error("Duplicate asset path");
        auto a = read_file(checked_file(overlay / "source-snapshots", name, ".sound"));
        auto b = read_file(checked_file(overlay / "tags", name, ".sound"));
        if(a != b) throw std::runtime_error("Source snapshot differs from output input");
        auto source = Parser::Sound::parse_hek_tag_file(a.data(), a.size());
        auto m = metadata(source);
        validate(source, m);
        if(!m.needs_conversion) throw std::runtime_error("Selected tag already uses native ADPCM: " + name);
        names.push_back(name);
    }
    if(names.empty()) throw std::runtime_error("Empty asset selection");
    std::sort(names.begin(), names.end());
    for(const auto &name : names) {
        try { std::cout << convert(overlay, name) << '\n'; }
        catch(const std::exception &e) { throw std::runtime_error(name + ": " + e.what()); }
    }
}

int main(int argc, char **argv) {
    if(argc == 2 && std::string(argv[1]) == "--help") {
        std::cout << "Usage: convert-audio --audit TAG_ROOT | --convert FRESH_OVERLAY\n"
            "Audit emits JSONL convertible/unsupported sound records. Conversion requires asset-paths.txt\n"
            "and independent identical source-snapshots/ and tags/ files. No resampling or downmixing.\n";
        return 0;
    }
    if(argc != 3 || (std::string(argv[1]) != "--audit" && std::string(argv[1]) != "--convert")) {
        std::cerr << "Usage: convert-audio --audit TAG_ROOT | --convert FRESH_OVERLAY\n";
        return 2;
    }
    try {
        if(std::string(argv[1]) == "--audit") audit(argv[2]);
        else convert_overlay(argv[2]);
        return 0;
    }
    catch(const std::exception &e) {
        std::cerr << "{\"status\":\"failed\",\"reason\":" << quote(e.what()) << "}\n";
        return 1;
    }
}
