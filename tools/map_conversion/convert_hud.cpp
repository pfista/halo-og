// SPDX-License-Identifier: GPL-3.0-only
// Authored HUD overlay converter, implemented against the reviewed Invader API.
// No Halo assets or Invader implementation code are embedded in this source.
// Writes only a fresh supplied overlay's tags/; source-snapshots/ stay immutable.
#include <invader/tag/parser/parser.hpp>
#include <invader/bitmap/bitmap_encode.hpp>
#include <invader/file/file.hpp>
#include <cmath>
#include <set>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
using namespace Invader;

static std::vector<std::string> split(const std::string &s, char delimiter) {
    std::vector<std::string> out;std::stringstream stream(s);std::string part;
    while(std::getline(stream,part,delimiter))out.push_back(part);return out;
}

static std::filesystem::path safe_tag_path(const std::filesystem::path &overlay,const std::string &name) {
    std::filesystem::path relative(name);
    if(name.empty()||relative.is_absolute()||name.find('\\')!=std::string::npos||relative.lexically_normal().generic_string()!=name)throw std::runtime_error("Tag path must be relative and normalized: "+name);
    for(const auto &part:relative)if(part=="."||part==".."||part.empty())throw std::runtime_error("Tag path contains traversal: "+name);
    auto path=overlay/"tags"/relative, snapshot=overlay/"source-snapshots"/relative;
    for(auto candidate:{path,snapshot}) {
        std::filesystem::path checked;
        for(const auto &part:candidate) {
            checked/=part;
            if(std::filesystem::is_symlink(std::filesystem::symlink_status(checked)))throw std::runtime_error("Symlinks are not permitted in overlay tag paths");
        }
        if(!std::filesystem::is_regular_file(candidate))throw std::runtime_error("Missing regular overlay tag: "+candidate.string());
    }
    if(std::filesystem::equivalent(path,snapshot))throw std::runtime_error("Output tag and source snapshot must be independent copies");
    return path;
}
static void validate_fresh_overlay(const std::filesystem::path &overlay) {
    if(std::filesystem::exists(overlay/"conversion.completed")||std::filesystem::is_symlink(std::filesystem::symlink_status(overlay/"conversion.completed")))throw std::runtime_error("Overlay was already converted; use a fresh output directory");
    if(!std::filesystem::is_directory(overlay/"tags")||!std::filesystem::is_directory(overlay/"source-snapshots"))throw std::runtime_error("Overlay requires tags/ and source-snapshots/");
    if(std::filesystem::is_symlink(std::filesystem::symlink_status(overlay/"tags"))||std::filesystem::is_symlink(std::filesystem::symlink_status(overlay/"source-snapshots")))throw std::runtime_error("Overlay directories must be independent regular directories");
    std::set<std::string> candidates,bitmaps;
    for(const auto &[filename,count]:std::vector<std::pair<std::string,size_t>>{{"field-rules.tsv",4},{"bitmap-rules.tsv",2}}) {
        if(std::filesystem::is_symlink(std::filesystem::symlink_status(overlay/filename)))throw std::runtime_error("Rules file must not be a symlink");
        std::ifstream rules(overlay/filename);if(!rules)throw std::runtime_error("Missing rules file: "+filename);std::string line;
        while(std::getline(rules,line)) {
            if(line.empty())continue;
            auto parts=split(line,'\t');if(parts.size()!=count)throw std::runtime_error("Invalid rule columns: "+filename);
            candidates.insert(parts[0]);
            if(filename=="bitmap-rules.tsv"&&!bitmaps.insert(parts[0]).second)throw std::runtime_error("Duplicate bitmap resample rule");
        }
    }
    for(const auto &name:candidates) {
        auto target=safe_tag_path(overlay,name),snapshot=overlay/"source-snapshots"/name;
        auto a=File::open_file(target),b=File::open_file(snapshot);
        if(!a||!b||*a!=*b)throw std::runtime_error("Target differs from its source snapshot before conversion: "+name);
    }
}

static Parser::ParserStructValue &field_at(Parser::ParserStruct &root,const std::string &path) {
    auto parts=split(path,'.');auto *object=&root;
    for(size_t i=0;i<parts.size();i++) {
        auto opening=parts[i].find('[');std::string name=parts[i].substr(0,opening);
        auto &values=object->get_values();auto it=std::find_if(values.begin(),values.end(),[&](auto &v){return v.get_member_name()&&name==v.get_member_name();});
        if(it==values.end())throw std::runtime_error("Missing field: "+path);
        if(opening!=std::string::npos) {
            size_t index=std::stoull(parts[i].substr(opening+1));
            if(it->get_type()!=Parser::ParserStructValue::VALUE_TYPE_REFLEXIVE||index>=it->get_array_size())throw std::runtime_error("Invalid array field: "+path);
            object=&it->get_object_in_array(index);
        } else if(i+1==parts.size())return *it;
        else throw std::runtime_error("Non-array intermediate field: "+path);
    }
    throw std::runtime_error("Missing final field: "+path);
}
using NumericValues = std::vector<Parser::ParserStructValue::Number>;

static Parser::ParserStructValue::Number checked_target(const Parser::ParserStructValue &field,double target,const std::string &name) {
    using Value = Parser::ParserStructValue;
    if(field.get_number_format()==Value::NUMBER_FORMAT_INT) {
        if(target!=std::round(target))throw std::runtime_error("Nonintegral integer field: "+name);
        double minimum,maximum;
        switch(field.get_type()) {
            case Value::VALUE_TYPE_INT8: minimum=std::numeric_limits<std::int8_t>::min();maximum=std::numeric_limits<std::int8_t>::max();break;
            case Value::VALUE_TYPE_UINT8:
            case Value::VALUE_TYPE_COLORARGBINT: minimum=0;maximum=std::numeric_limits<std::uint8_t>::max();break;
            case Value::VALUE_TYPE_INT16:
            case Value::VALUE_TYPE_POINT2DINT:
            case Value::VALUE_TYPE_RECTANGLE2D: minimum=std::numeric_limits<std::int16_t>::min();maximum=std::numeric_limits<std::int16_t>::max();break;
            case Value::VALUE_TYPE_UINT16:
            case Value::VALUE_TYPE_INDEX: minimum=0;maximum=std::numeric_limits<std::uint16_t>::max();break;
            case Value::VALUE_TYPE_INT32: minimum=std::numeric_limits<std::int32_t>::min();maximum=std::numeric_limits<std::int32_t>::max();break;
            case Value::VALUE_TYPE_UINT32: minimum=0;maximum=std::numeric_limits<std::uint32_t>::max();break;
            default: throw std::runtime_error("Unsupported numeric field type: "+name);
        }
        if(target<minimum||target>maximum)throw std::runtime_error("Integer target exceeds field storage range: "+name);
        return static_cast<std::int64_t>(target);
    }
    if(field.get_number_format()!=Value::NUMBER_FORMAT_FLOAT)throw std::runtime_error("Unsupported numeric field type: "+name);
    if(std::abs(target)>std::numeric_limits<float>::max())throw std::runtime_error("Float target exceeds field storage range: "+name);
    float stored=static_cast<float>(target);
    if(!std::isfinite(stored)||(target!=0&&stored==0))throw std::runtime_error("Float target exceeds field storage range: "+name);
    // HEK numeric float fields use float32; check the value they can actually store.
    return static_cast<double>(stored);
}

static void verify_fields(Parser::ParserStruct &tag,const std::map<std::string,NumericValues> &expected) {
    for(const auto &[name,values]:expected) {
        if(field_at(tag,name).get_values()!=values)throw std::runtime_error("Stored field differs from target: "+name);
    }
}

static void write_tag(const std::filesystem::path &path,Parser::ParserStruct &tag,const std::map<std::string,NumericValues> &expected) {
    auto extension=path.extension().string().substr(1);
    auto bytes=tag.generate_hek_tag_data(HEK::tag_extension_to_fourcc(extension.c_str()),true);
    auto parsed=Parser::ParserStruct::parse_hek_tag_file(bytes.data(),bytes.size());
    verify_fields(*parsed,expected);
    if(!File::save_file(path,bytes))throw std::runtime_error("Failed derivative write: "+path.string());
}
static void fields(const std::filesystem::path &revision) {
    std::ifstream rules(revision/"field-rules.tsv");std::string line;
    struct Rule{std::string field,before,after;};std::map<std::string,std::vector<Rule>> by_tag;
    while(std::getline(rules,line)) {if(line.empty())continue;auto parts=split(line,'\t');if(parts.size()!=4)throw std::runtime_error("Invalid field rule");by_tag[parts[0]].push_back({parts[1],parts[2],parts[3]});}
    for(const auto &[name,changes]:by_tag) {
        auto path=safe_tag_path(revision,name);auto bytes=File::open_file(path);if(!bytes)throw std::runtime_error("Missing derivative tag: "+name);
        auto tag=Parser::ParserStruct::parse_hek_tag_file(bytes->data(),bytes->size());
        std::map<std::string,NumericValues> expected;
        for(const auto &rule:changes) {
            auto &value=field_at(*tag,rule.field);auto current=value.get_values();auto before=split(rule.before,','),after=split(rule.after,',');
            if(current.size()!=before.size()||current.size()!=after.size())throw std::runtime_error("Field cardinality mismatch: "+rule.field);
            NumericValues updated;
            for(size_t i=0;i<current.size();i++) {
                double actual=std::visit([](auto n){return static_cast<double>(n);},current[i]),expected=std::stod(before[i]),target=std::stod(after[i]);
                if(!std::isfinite(actual)||!std::isfinite(expected)||!std::isfinite(target))throw std::runtime_error("Numeric fields must be finite: "+rule.field);
                if(std::abs(actual-expected)>1e-5)throw std::runtime_error("Source field mismatch: "+name+" "+rule.field);
                updated.push_back(checked_target(value,target,rule.field));
            }
            value.set_values(updated);
            expected[rule.field]=updated;
            verify_fields(*tag,expected);
            std::cout<<"Field "<<name<<" | "<<rule.field<<" | "<<rule.before<<" -> "<<rule.after<<'\n';
        }
        write_tag(path,*tag,expected);
    }
}
static void resample(const std::filesystem::path &revision) {
    std::ifstream rules(revision/"bitmap-rules.tsv");std::string line;
    while(std::getline(rules,line)) {
        if(line.empty())continue;
        auto parts=split(line,'\t');if(parts.size()!=2)throw std::runtime_error("Invalid bitmap rule");
        const auto name=parts[0];size_t divisor=std::stoull(parts[1]);if(divisor!=2&&divisor!=4)throw std::runtime_error("Unsupported divisor");
        auto path=safe_tag_path(revision,name);auto bytes=File::open_file(path);if(!bytes)throw std::runtime_error("Missing bitmap: "+name);
        auto tag=Parser::Bitmap::parse_hek_tag_file(bytes->data(),bytes->size());auto sequences=tag.bitmap_group_sequence;auto count=tag.bitmap_data.size();std::vector<std::byte> result;
        for(size_t index=0;index<tag.bitmap_data.size();index++) {
            auto &image=tag.bitmap_data[index];size_t width=image.width,height=image.height;
            if(image.type!=HEK::BITMAP_DATA_TYPE_2D_TEXTURE||image.depth!=1||image.mipmap_count!=0||width%divisor||height%divisor)throw std::runtime_error("Unsupported fixed HUD image layout: "+name);
            size_t size=BitmapEncode::bitmap_data_size(width,height,1,0,image.format,image.type),offset=image.pixel_data_offset;
            if(offset>tag.processed_pixel_data.size()||size>tag.processed_pixel_data.size()-offset)throw std::runtime_error("Bitmap source range error");
            auto decoded=BitmapEncode::encode_bitmap(tag.processed_pixel_data.data()+offset,image.format,HEK::BITMAP_DATA_FORMAT_A8R8G8B8,width,height,false);
            size_t new_width=width/divisor,new_height=height/divisor;std::vector<std::byte> pixels(new_width*new_height*4);
            for(size_t y=0;y<new_height;y++)for(size_t x=0;x<new_width;x++) {
                unsigned alpha=0;unsigned weighted[3]={};
                for(size_t dy=0;dy<divisor;dy++)for(size_t dx=0;dx<divisor;dx++) {
                    size_t source=((y*divisor+dy)*width+x*divisor+dx)*4;unsigned a=std::to_integer<unsigned>(decoded[source+3]);alpha+=a;
                    for(size_t channel=0;channel<3;channel++)weighted[channel]+=std::to_integer<unsigned>(decoded[source+channel])*a;
                }
                size_t output=(y*new_width+x)*4;
                for(size_t channel=0;channel<3;channel++)pixels[output+channel]=std::byte(alpha?(weighted[channel]+alpha/2)/alpha:0);
                pixels[output+3]=std::byte((alpha+divisor*divisor/2)/(divisor*divisor));
            }
            if(image.registration_point.x.read()%divisor||image.registration_point.y.read()%divisor)throw std::runtime_error("Nonintegral pixel registration scaling");
            image.width=new_width;image.height=new_height;image.registration_point.x=image.registration_point.x.read()/divisor;image.registration_point.y=image.registration_point.y.read()/divisor;
            image.format=HEK::BITMAP_DATA_FORMAT_A8R8G8B8;image.flags&=~(HEK::BITMAP_DATA_FLAGS_FLAG_COMPRESSED|HEK::BITMAP_DATA_FLAGS_FLAG_PALETTIZED|HEK::BITMAP_DATA_FLAGS_FLAG_SWIZZLED|HEK::BITMAP_DATA_FLAGS_FLAG_V16U16);
            image.pixel_data_offset=result.size();image.pixel_data_size=pixels.size();result.insert(result.end(),pixels.begin(),pixels.end());
            std::cout<<"Authored bitmap "<<name<<" image "<<index<<" | "<<width<<'x'<<height<<" -> "<<new_width<<'x'<<new_height<<" | alpha-aware box filter | sequence UVs retained\n";
        }
        tag.processed_pixel_data=std::move(result);tag.encoding_format=HEK::BITMAP_FORMAT_32_BIT;tag.flags&=~(HEK::BITMAP_FLAGS_FLAG_HALF_HUD_SCALE|HEK::BITMAP_FLAGS_FLAG_FORCE_HUD_USE_HIGHRES_SCALE);
        tag.sprite_spacing=std::max<std::uint16_t>(tag.sprite_spacing/divisor,1);
        auto output=tag.generate_hek_tag_data(HEK::TAG_FOURCC_BITMAP,true);auto verify=Parser::Bitmap::parse_hek_tag_file(output.data(),output.size());
        if(verify.bitmap_data.size()!=count||verify.bitmap_group_sequence.size()!=sequences.size())throw std::runtime_error("Sequence or image count changed");
        for(size_t i=0;i<sequences.size();i++) {
            const auto &a=sequences[i],&b=verify.bitmap_group_sequence[i];
            if(std::string(a.name.string)!=b.name.string||a.first_bitmap_index!=b.first_bitmap_index||a.bitmap_count!=b.bitmap_count||a.sprites.size()!=b.sprites.size())throw std::runtime_error("Sequence metadata changed");
            for(size_t j=0;j<a.sprites.size();j++) {
                const auto &x=a.sprites[j],&y=b.sprites[j];
                if(x.bitmap_index!=y.bitmap_index||x.left!=y.left||x.top!=y.top||x.right!=y.right||x.bottom!=y.bottom||x.registration_point.x.read()!=y.registration_point.x.read()||x.registration_point.y.read()!=y.registration_point.y.read())throw std::runtime_error("Sprite metadata changed");
            }
        }
        if(!File::save_file(path,output))throw std::runtime_error("Failed normalized bitmap write");
    }
}
int main(int argc,char **argv) {
    if(argc!=2||std::string(argv[1])=="--help") {
        std::cout<<"Usage: convert-hud OVERLAY_DIRECTORY\n"
                 <<"The fresh overlay must contain independent source-snapshots/ and tags/ copies, field-rules.tsv, and bitmap-rules.tsv.\n";
        return argc==2?0:2;
    }
    try {
        auto overlay=std::filesystem::canonical(argv[1]);
        validate_fresh_overlay(overlay);
        fields(overlay);resample(overlay);
        std::ofstream marker(overlay/"conversion.completed");
        marker<<"Converted once. Source snapshots remain immutable; inspect the orchestration hash manifest.\n";
        if(!marker)throw std::runtime_error("Failed to write conversion completion marker");
        std::cout<<"PASS: explicit fields checked, output tags reparsed, image and sprite identities preserved.\n";
        return 0;
    } catch(const std::exception &error) {
        std::cerr<<"HUD conversion failed: "<<error.what()<<"\n";
        return 1;
    }
}
