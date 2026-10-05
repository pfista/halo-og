// SPDX-License-Identifier: GPL-3.0-only
// Native guard tests use synthetic Unicode tags, never game assets.
#define main unicode_converter_main
#include "convert_unicode_strings.cpp"
#undef main
#include <cassert>

static std::vector<std::byte> text(const std::u16string &s) {
    std::vector<std::byte> v;
    for(char16_t c:s){v.push_back(static_cast<std::byte>(c&255));v.push_back(static_cast<std::byte>(c>>8));}
    v.push_back(std::byte{0});v.push_back(std::byte{0});return v;
}
static fs::path fixture(const fs::path &root,const std::string &name,const std::string &actions) {
    auto out=root/name;fs::create_directories(out/"source-snapshots");
    Parser::UnicodeStringList list;
    for(auto value:{u"untouched",u"old",u"supplementary \U0001F9EA"}){
        Parser::UnicodeStringListString s;s.string=text(value);list.strings.push_back(s);
    }
    auto bytes=list.generate_hek_tag_data(HEK::TAG_FOURCC_UNICODE_STRING_LIST,false);
    std::ofstream f(out/"source-snapshots/test.unicode_string_list",std::ios::binary);f.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());f.close();
    std::ofstream(out/"unicode-strings.tsv")<<actions;return out;
}
static void rejected(const fs::path &path,const std::string &message) {
    bool failed=false;
    try{convert(path);}catch(const std::exception &e){failed=true;assert(std::string(e.what()).find(message)!=std::string::npos);}
    assert(failed);assert(!fs::exists(path/"tags/test.unicode_string_list"));
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;fs::path root=argv[1];if(fs::exists(root))return 3;fs::create_directories(root);
    const std::string valid="test.unicode_string_list\t3\t1\t6f006c0064000000\t6e00650077000000\n";
    auto good=fixture(root,"success",valid);convert(good);
    auto result=File::open_file(good/"tags/test.unicode_string_list");assert(result);
    auto list=Parser::UnicodeStringList::parse_hek_tag_file(result->data(),result->size());
    assert(list.strings.size()==3);assert(list.strings[0].string==text(u"untouched"));assert(list.strings[1].string==text(u"new"));assert(list.strings[2].string==text(u"supplementary \U0001F9EA"));
    bool repeat=false;try{convert(good);}catch(const std::exception &e){repeat=std::string(e.what()).find("Existing")!=std::string::npos;}assert(repeat);
    rejected(fixture(root,"count","test.unicode_string_list\t2\t1\t6f006c0064000000\t6e00650077000000\n"),"entry count");
    rejected(fixture(root,"before","test.unicode_string_list\t3\t1\t78000000\t6e00650077000000\n"),"before value");
    rejected(fixture(root,"index","test.unicode_string_list\t3\t3\t6f006c0064000000\t6e00650077000000\n"),"count/index");
    rejected(fixture(root,"duplicate",valid+valid),"duplicate entry");
    rejected(fixture(root,"surrogate","test.unicode_string_list\t3\t1\t6f006c0064000000\t00d80000\n"),"surrogate");
    rejected(fixture(root,"interior_null","test.unicode_string_list\t3\t1\t6f006c0064000000\t000078000000\n"),"Interior null");
    rejected(fixture(root,"terminator","test.unicode_string_list\t3\t1\t6f006c0064000000\t6e0065007700\n"),"terminator");
    auto linked=fixture(root,"symlink",valid);auto input=linked/"source-snapshots/test.unicode_string_list";fs::rename(input,linked/"original");fs::create_symlink(linked/"original",input);rejected(linked,"Symlink");
    std::cout<<"Native Unicode entry/count/UTF-16/path/repeat guards and preservation tests passed\n";
}
