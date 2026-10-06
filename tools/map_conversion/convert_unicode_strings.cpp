// SPDX-License-Identifier: GPL-3.0-only
// Explicit map-local text compatibility. Entry indices and wording require review.
#include <invader/tag/parser/parser.hpp>
#include <invader/file/file.hpp>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
using namespace Invader;
namespace fs = std::filesystem;

static fs::path checked_file(const fs::path &root, const std::string &name) {
    fs::path relative = name, at = root;
    if(name.empty() || relative.is_absolute() || relative.extension() != ".unicode_string_list" ||
       relative.lexically_normal().generic_string() != name ||
       name.find_first_of("\t\r\n\\") != std::string::npos || fs::is_symlink(fs::symlink_status(root)))
        throw std::runtime_error("Invalid Unicode tag path or symlink root");
    for(const auto &part : relative) {
        if(part == "." || part == "..") throw std::runtime_error("Traversal refused");
        at /= part;
        if(fs::is_symlink(fs::symlink_status(at))) throw std::runtime_error("Symlink input refused");
    }
    if(!fs::is_regular_file(at) || fs::hard_link_count(at) != 1)
        throw std::runtime_error("Missing or hard-linked Unicode input refused");
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
        throw std::runtime_error("Invalid entry/count expectation");
    std::size_t read = 0, result = std::stoul(value, &read);
    if(read != value.size() || result > limit) throw std::runtime_error("Entry/count exceeds Unicode tag limit");
    return result;
}
static std::vector<std::byte> utf16_hex(const std::string &hex) {
    if(hex.size() < 4 || hex.size() > 65536 || hex.size() % 4 ||
       hex.find_first_not_of("0123456789abcdef") != std::string::npos)
        throw std::runtime_error("Expected bounded lowercase UTF-16LE hex including null terminator");
    std::vector<std::byte> bytes;
    for(std::size_t i=0;i<hex.size();i+=2)
        bytes.push_back(static_cast<std::byte>(std::stoul(hex.substr(i,2),nullptr,16)));
    bool high = false;
    for(std::size_t i=0;i<bytes.size();i+=2) {
        auto c=std::to_integer<unsigned>(bytes[i])|(std::to_integer<unsigned>(bytes[i+1])<<8);
        if(c==0) {
            if(i+2 != bytes.size() || high) throw std::runtime_error("Interior null or incomplete surrogate refused");
        }
        else if(c>=0xD800 && c<=0xDBFF) {
            if(high) throw std::runtime_error("Invalid UTF-16 surrogate pair"); high=true;
        }
        else if(c>=0xDC00 && c<=0xDFFF) {
            if(!high) throw std::runtime_error("Invalid UTF-16 surrogate pair"); high=false;
        }
        else if(high) throw std::runtime_error("Invalid UTF-16 surrogate pair");
    }
    if(bytes[bytes.size()-1]!=std::byte{0} || bytes[bytes.size()-2]!=std::byte{0})
        throw std::runtime_error("Missing UTF-16 null terminator");
    return bytes;
}
struct Rule {std::size_t count,index;std::vector<std::byte> before,after;};
static void convert(const fs::path &overlay) {
    if(fs::is_symlink(fs::symlink_status(overlay))) throw std::runtime_error("Symlink overlay refused");
    auto action_path=overlay/"unicode-strings.tsv";
    if(fs::is_symlink(fs::symlink_status(action_path)) || !fs::is_regular_file(action_path) || fs::hard_link_count(action_path)!=1)
        throw std::runtime_error("Unsafe or missing unicode-strings.tsv");
    std::ifstream config(action_path);std::string line;std::map<std::string,std::vector<Rule>> groups;
    while(std::getline(config,line)) {
        auto fields=split(line);if(fields.size()!=5)throw std::runtime_error("Expected tag, count, index and UTF-16LE before/after");
        Rule rule{number(fields[1],800),number(fields[2],799),utf16_hex(fields[3]),utf16_hex(fields[4])};
        if(!rule.count || rule.index>=rule.count || rule.before==rule.after)throw std::runtime_error("Invalid count/index or unchanged replacement");
        auto &rules=groups[fields[0]];
        for(const auto &other:rules)if(other.count!=rule.count || other.index==rule.index)throw std::runtime_error("Conflicting count or duplicate entry rule");
        rules.push_back(std::move(rule));
    }
    if(groups.empty())throw std::runtime_error("Empty Unicode action selection");
    for(const auto &[name,rules]:groups) {
        auto source=File::open_file(checked_file(overlay/"source-snapshots",name));
        if(!source)throw std::runtime_error("Missing Unicode source snapshot");
        auto input=Parser::UnicodeStringList::parse_hek_tag_file(source->data(),source->size());
        if(input.strings.size()!=rules.front().count)throw std::runtime_error("Reviewed Unicode entry count changed");
        auto output=input;
        for(const auto &rule:rules) {
            if(output.strings[rule.index].string!=rule.before)throw std::runtime_error("Reviewed UTF-16 entry before value changed");
            output.strings[rule.index].string=rule.after;
        }
        auto bytes=output.generate_hek_tag_data(HEK::TAG_FOURCC_UNICODE_STRING_LIST,false);
        auto parsed=Parser::UnicodeStringList::parse_hek_tag_file(bytes.data(),bytes.size());
        if(!output.compare(&parsed,false))throw std::runtime_error("Unicode output reparse mismatch");
        for(const auto &rule:rules) {
            if(parsed.strings[rule.index].string!=rule.after)throw std::runtime_error("UTF-16 after value changed during storage");
            parsed.strings[rule.index].string=input.strings[rule.index].string;
        }
        if(!input.compare(&parsed,false))throw std::runtime_error("An unselected Unicode field or entry changed");
        fs::path destination=overlay/"tags"/name;
        if(fs::exists(destination)||fs::is_symlink(fs::symlink_status(destination)))throw std::runtime_error("Existing Unicode output refused");
        fs::path at=overlay/"tags";
        if(fs::is_symlink(fs::symlink_status(at)))throw std::runtime_error("Symlink output root refused");
        for(const auto &part:fs::path(name).parent_path()) {at/=part;if(fs::is_symlink(fs::symlink_status(at)))throw std::runtime_error("Symlink output refused");}
        fs::create_directories(destination.parent_path());std::ofstream out(destination,std::ios::binary|std::ios::out);
        if(!out)throw std::runtime_error("Unable to create Unicode output");
        out.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());if(!out)throw std::runtime_error("Unable to write Unicode output");
        std::cout<<name<<": replaced "<<rules.size()<<" entries; preserved "<<input.strings.size()-rules.size()<<" unselected entries and every other field; reparsed\n";
    }
}
int main(int argc,char **argv) {
    if(argc!=2 || std::string(argv[1])=="--help") {
        std::cout<<"Usage: convert-unicode-strings FRESH_OVERLAY\nRequires reviewed UTF-16LE unicode-strings.tsv and independent source snapshots.\n";return argc==2?0:2;
    }
    try{convert(argv[1]);return 0;}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
