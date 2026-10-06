"""Native fixtures for the compatibility branch's shared transport/config APIs."""
import os
import hashlib
import hmac
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_input_bindings import PREFIX, PORT, ROOT, SDL
from tools.test_performance_variants import block

SDL_INCLUDE = next((base for base in (SDL / "include", Path("/usr/include"), Path("/usr/local/include"))
                    if (base / "SDL3/SDL.h").exists()), None)


CRYPTO = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "posix.h"
#include "p2p_internal.h"
void posix_random_bytes(void *out, posix_ulong size) {
    unsigned char *bytes=out;
    for(posix_ulong i=0;i<size;i++) bytes[i]=(unsigned char)(i*19+7);
}
static void from_hex(const char *text,unsigned char *out,int size) {
    assert(strlen(text)==(size_t)size*2);
    for(int i=0;i<size;i++) { unsigned byte;assert(sscanf(text+2*i,"%2x",&byte)==1);out[i]=(unsigned char)byte; }
}
static struct {
    unsigned char token[P2P_TOKEN_SIZE];
    int has_token, token_listed;
    char invite[P2P_LINK_SIZE];
} p2p;
const unsigned char *p2p_public_key(void) { static unsigned char key[32];return key; }
void p2p_key_hash(const unsigned char *key,unsigned char *hash) {
    (void)key;for(int i=0;i<P2P_KEY_HASH_SIZE;i++) hash[i]=(unsigned char)i;
}
void p2p_hex(const unsigned char *bytes,int size,char *text) {
    for(int i=0;i<size;i++) sprintf(text+i*2,"%02x",bytes[i]);
}
/* PRODUCTION_INVITE_PARSER */
int main(void) {
    unsigned char seed[32],public_key[32],secret[32],signature[64],expected[64],xpublic[32],converted[32];
    from_hex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",seed,32);
    p2p_ed25519_public(seed,public_key,secret);
    from_hex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",expected,32);
    assert(!memcmp(public_key,expected,32));
    p2p_ed25519_sign(seed,public_key,"",0,signature);
    /* RFC 8032 section 7.1, test 1: https://www.rfc-editor.org/rfc/rfc8032#section-7.1 */
    from_hex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
             "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",expected,64);
    assert(!memcmp(signature,expected,64));
    assert(p2p_ed25519_verify(public_key,"",0,signature));
    assert(!p2p_ed25519_verify(public_key,"modified",8,signature));
    p2p_x25519(xpublic,secret,NULL);
    assert(p2p_ed25519_to_x25519(public_key,converted) && !memcmp(xpublic,converted,32));
    unsigned char zero[32]={0};assert(!p2p_ed25519_to_x25519(zero,converted));
    unsigned char key[32],same[32],wrong[32],token[16],opened[16],sealed[P2P_SEALED_TOKEN_SIZE];
    p2p_password_key("shared password",public_key,key);
    p2p_password_key("shared password",public_key,same);assert(!memcmp(key,same,32));
    p2p_password_key("wrong password",public_key,wrong);assert(memcmp(key,wrong,32));
    for(int i=0;i<16;i++) token[i]=(unsigned char)i;
    p2p_seal_token(key,public_key,token,sealed);
    assert(p2p_unseal_token(key,public_key,sealed,opened) && !memcmp(token,opened,16));
    assert(!p2p_unseal_token(wrong,public_key,sealed,opened));
    sealed[25]^=1;assert(!p2p_unseal_token(key,public_key,sealed,opened));
    assert(!strcmp(P2P_INVITE_SCHEME,"halo-og-opence"));
    assert(!strcmp(P2P_INVITE_PREFIX,"halo://join/"));
    assert(p2p_invite_prefix_length("HALO://JOIN/abc")==strlen(P2P_INVITE_PREFIX));
    assert(p2p_invite_prefix_length("halo-og://join/abc")==strlen(P2P_LEGACY_INVITE_PREFIX));
    assert(p2p_invite_prefix_length("halo-og-opence://join/abc")==strlen(P2P_PRIVATE_INVITE_PREFIX));
    assert(!p2p_invite_prefix_length("https://join/abc"));
    assert(sizeof(((struct p2p_listing *)0)->invite)==P2P_SHARED_LINK_SIZE);
    make_invite();assert(p2p.has_token && !p2p.token_listed);
    assert(!strncmp(p2p.invite,P2P_INVITE_PREFIX,strlen(P2P_INVITE_PREFIX)));
    assert(strlen(p2p.invite)==strlen(P2P_INVITE_PREFIX)+64);
    unsigned char parsed_host[16],parsed_token[16],expected_host[16];
    p2p_key_hash(NULL,expected_host);
    assert(parse_invite(p2p.invite,parsed_host,parsed_token)==1);
    assert(!memcmp(parsed_host,expected_host,16) && !memcmp(parsed_token,p2p.token,16));
    char alternate[160];
    snprintf(alternate,sizeof(alternate),"Join %s%s now",P2P_PRIVATE_INVITE_PREFIX,p2p.invite+strlen(P2P_INVITE_PREFIX));
    assert(parse_invite(alternate,parsed_host,parsed_token)==1 && !memcmp(parsed_token,p2p.token,16));
    char delivered[P2P_LINK_SIZE];
    snprintf(delivered,sizeof(delivered),"%s%s",P2P_PRIVATE_INVITE_PREFIX,p2p.invite+strlen(P2P_INVITE_PREFIX));
    assert(strlen(delivered)+1==P2P_LINK_SIZE && parse_invite(delivered,parsed_host,parsed_token)==1);
    assert(!memcmp(parsed_token,p2p.token,16));
    snprintf(alternate,sizeof(alternate),"%s%s",P2P_LEGACY_INVITE_PREFIX,p2p.invite+strlen(P2P_INVITE_PREFIX));
    assert(parse_invite(alternate,parsed_host,parsed_token)==1 && !memcmp(parsed_host,expected_host,16));
    assert(parse_invite(p2p.invite+strlen(P2P_INVITE_PREFIX),parsed_host,parsed_token)==1);
    assert(parse_invite("halo://join/0123456789abcdef",parsed_host,parsed_token)==0);
    puts("signed listings, locked invites and shared URL text passed");
}
'''

CONFIG = r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "port_config.h"
void platform_log(const char *format,...) { (void)format; }
const char *platform_data_root(void) { return getenv("HALO_DATA_ROOT"); }
/* PRODUCTION_BROKERS */
int main(void) {
    char text[1024],folder[1024];
    assert(!strcmp(config_string("display.menus"),"xbox"));
    assert(!config_boolean("display.high_res_hud") && !config_boolean("display.interpolation"));
    assert(config_boolean("network.public_lobby") && !config_boolean("network.host_public"));
    assert(!strcmp(config_string("network.coop_enemies_mode"),"none"));
    assert(!strcmp(config_string("network.brokers_file"),"brokers.txt"));
    assert(config_default("network.coop_friendly_fire",text,sizeof(text)) && !strcmp(text,"on"));
    unsigned long changes=config_changes();
    const char *old=config_string("network.coop_friendly_fire");
    assert(config_write("network.coop_friendly_fire","shields_only"));
    assert(config_changes()==changes+1 && !strcmp(old,"on"));
    assert(config_text("network.coop_friendly_fire",text,sizeof(text)) && !strcmp(text,"shields_only"));
    assert(config_write("network.coop_enemies","75"));
    assert(config_integer("network.coop_enemies")==75);
    assert(config_write("network.coop_player_collisions","false"));
    changes=config_changes();
    assert(!config_write("network.coop_enemies","12.5") && !config_write("network.coop_enemies","75oops"));
    assert(!config_write("network.coop_player_collisions","invalid") && !config_write(NULL,"true"));
    assert(!config_write("unknown","1") && config_changes()==changes);
    assert(!config_text(NULL,text,sizeof(text)) && !config_default(NULL,text,sizeof(text)));
    config_folder(folder,sizeof(folder));
    snprintf(text,sizeof(text),"%s/",getenv("HALO_SAVE_ROOT"));assert(!strcmp(folder,text));
    snprintf(text,sizeof(text),"%sconfig.toml",folder);size_t size=0;
    char *file=config_file_read(text,&size);assert(file && size && strstr(file,"shields_only"));free(file);
    assert(!config_file_read(NULL,&size) && !config_file_read(text,NULL));
    brokers_list(text,sizeof(text));assert(strstr(text,"one.example:1883") && strstr(text,"two.example:1883"));
    assert(!strstr(text,"ignored"));
    assert(config_write("network.brokers_file","missing-custom.txt"));
    brokers_list(text,sizeof(text));assert(!*text);
    puts("original defaults and upstream config APIs passed");
}
'''

# These contexts and packet bytes are from the stock OpenCE v20 transport at
# 76addf66, the compatibility branch's upstream baseline. They distinguish
# shared peer authentication from the intentionally private process handoff.
PROTOCOL = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <netinet/in.h>
#include "posix.h"
#include "p2p_internal.h"
/* PRODUCTION_CONSTANTS */
static unsigned char scalar[P2P_KEY_SIZE];
static unsigned char identifier[P2P_IDENTIFIER_SIZE];
static struct { int tunnel_socket; } p2p={1};
struct peer { unsigned char send_key[P2P_SHA256_SIZE];unsigned long long send_counter; };
static unsigned char captured[2048];
static int captured_size;
int posix_socket_sendto(int socket,const void *buffer,int size,int flags,const void *address,int address_size) {
    (void)flags;(void)address;(void)address_size;assert(socket==1 && size<2048);
    memcpy(captured,buffer,(size_t)size);captured_size=size;return size;
}
void posix_random_bytes(void *out,posix_ulong size) { memset(out,0x42,size); }
void p2p_hex(const unsigned char *bytes,int size,char *text) {
    for(int i=0;i<size;i++) sprintf(text+2*i,"%02x",bytes[i]);
}
int p2p_shared_secret(const unsigned char *key,unsigned char *shared) {
    unsigned char zero[P2P_KEY_SIZE]={0};
    p2p_x25519(shared,scalar,key);return !p2p_equal(shared,zero,sizeof(zero));
}
/* PRODUCTION_CONTEXTS */
static void output(const char *label,const unsigned char *data,int size) {
    char hex[1024];p2p_hex(data,size,hex);printf("%s=%s\n",label,hex);
}
int main(void) {
    unsigned char token[16],host_scalar[32],joiner_public[32],host_public[32];
    unsigned char base[32],secret[32],nonce[8],host_nonce[8],seal_key[32],key[32];
    unsigned char message[128],packet_iv[12],opened[128],shared[32];
    char topic[TOPIC_SIZE];
    for(int i=0;i<32;i++) { scalar[i]=(unsigned char)i;host_scalar[i]=(unsigned char)(i+32); }
    for(int i=0;i<16;i++) token[i]=(unsigned char)i;
    for(int i=0;i<6;i++) identifier[i]=(unsigned char)(i+16);
    for(int i=0;i<8;i++) { nonce[i]=(unsigned char)(i+64);host_nonce[i]=(unsigned char)(i+72); }
    p2p_x25519(joiner_public,scalar,NULL);p2p_x25519(host_public,host_scalar,NULL);
    p2p_x25519(shared,scalar,host_public);output("shared",shared,32);
    assert(pair_base(joiner_public,host_public,host_public,base));output("base",base,32);
    session_secret(base,nonce,host_nonce,secret);output("session",secret,32);
    make_topic(token,"host",identifier,topic);printf("host_topic=%s\n",topic);
    make_topic(token,"joiner",identifier,topic);printf("joiner_topic=%s\n",topic);
    derive(token,"seal",NULL,seal_key);output("seal_key",seal_key,32);
    p2p_hmac_sha256(secret,32,"joiner",6,key);output("joiner_key",key,32);
    p2p_hmac_sha256(secret,32,"host",4,key);output("host_key",key,32);
    /* A proven JOIN with no reachability candidates, authenticated as v3. */
    message[0]='J';message[1]=3;memcpy(message+2,joiner_public,32);
    memcpy(message+34,nonce,8);message[42]=0;memcpy(message+43,host_nonce,8);
    message_tag(base,"join",message,51,message+51);
    assert(tag_right(base,"join",message,67));assert(!tag_right(base,"accept",message,67));
    output("proven_join",message,67);
    message[0]='A';message_tag(base,"accept",message,51,message+51);
    assert(tag_right(base,"accept",message,67));output("accept",message,67);
    /* Capture the production sender's complete authenticated tunnel packet. */
    struct peer peer={0};struct p2p_candidate target={0};memcpy(peer.send_key,key,32);
    peer_send_to(&peer,&target,message,67);assert(captured_size==98 && peer.send_counter==1);
    output("tunnel_packet",captured,captured_size);packet_nonce(captured,packet_iv);
    assert(p2p_aead_open(key,packet_iv,captured,15,captured+15,83,opened)==67 && !memcmp(opened,message,67));
    captured[1]^=1;assert(p2p_aead_open(key,packet_iv,captured,15,captured+15,83,opened)==-1);
    printf("lobby_slot=%s\nlobby_query=%s\n",P2P_LOBBY_SLOT_PREFIX,P2P_LOBBY_QUERY_TOPIC);
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang required")
@unittest.skipIf(sys.platform == "win32", "POSIX transport/config fixtures require netinet and pthread headers")
class OpenCEPlatformTests(unittest.TestCase):
    @unittest.skipUnless((SDL / "include/SDL3/SDL.h").exists(), "SDL3 headers required")
    def test_host_scancode_bridge_round_trip_and_bounded_guest_buffer(self):
        from tools.macos_metal_imports import native_imports

        imports = (ROOT / "port/android/host_imports.list").read_text()
        native = native_imports(imports).splitlines()
        for name in ("host_sdl_scancode_name", "host_sdl_scancode_from_name"):
            self.assertIn(name, imports.splitlines())
            self.assertIn(name, native)
        self.assertIn('port/macos/host/*.c', (ROOT / "port/ios/CMakeLists.txt").read_text())
        guest = (ROOT / "port/android/guest/runtime/guest_sdl.c").read_text()
        wrappers = "\n".join(block(guest, name) for name in
                             ("const char *SDL_GetScancodeName(", "SDL_Scancode SDL_GetScancodeFromName("))
        fixture = r'''
#include <assert.h>
#include <string.h>
#include <SDL3/SDL.h>
#include "host.h"
#include "guest_host.h"
/* HOST_SCANCODE_BRIDGE */
#define SDL_GetScancodeName guest_scancode_name
#define SDL_GetScancodeFromName guest_scancode_from_name
/* GUEST_SCANCODE_WRAPPERS */
#undef SDL_GetScancodeName
#undef SDL_GetScancodeFromName
int main(void) {
    assert(guest_scancode_from_name("A")==SDL_SCANCODE_A);
    assert(!strcmp(guest_scancode_name(SDL_SCANCODE_A),"A"));
    assert(guest_scancode_from_name("Left Shift")==SDL_SCANCODE_LSHIFT);
    assert(guest_scancode_from_name("unknown fixture key")==SDL_SCANCODE_UNKNOWN);
    char bounded[5]={'x','x','x','x','!'};
    host_sdl_scancode_name(SDL_SCANCODE_LSHIFT,bounded,4);
    assert(!strcmp(bounded,"Lef") && bounded[4]=='!');
    assert(!*guest_scancode_name(SDL_SCANCODE_UNKNOWN));
}
'''
        for platform in ("macos", "android"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(prefix="halo-scancode-bridge-") as folder:
                directory = Path(folder)
                host = (ROOT / f"port/{platform}/host/host_sdl.c").read_text()
                adapters = "\n".join(block(host, name) for name in
                                     ("void host_sdl_scancode_name(", "int32_t host_sdl_scancode_from_name("))
                source = fixture.replace("/* HOST_SCANCODE_BRIDGE */", adapters)
                source = source.replace("/* GUEST_SCANCODE_WRAPPERS */", wrappers)
                (directory / "probe.c").write_text(source)
                executable = directory / "probe"
                subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                f"-I{ROOT / ('port/' + platform + '/host')}",
                                f"-I{ROOT / 'port/android/include'}", f"-I{ROOT / 'port/android/guest/runtime'}",
                                f"-I{SDL / 'include'}", str(directory / "probe.c"), f"-L{SDL / 'lib'}",
                                "-lSDL3", "-o", str(executable)], check=True)
                subprocess.run([str(executable)], check=True)

    def test_stock_opence_contexts_and_complete_tunnel_packet(self):
        signal = (PORT / "p2p_signal.c").read_text()
        transport = (PORT / "p2p.c").read_text()
        contexts = "\n".join(block(signal, name) for name in
                             ("static void derive(", "static void make_topic(", "static int pair_base(",
                              "static void session_secret(", "static void message_tag(", "static int tag_right("))
        contexts += "\n" + "\n".join(block(transport, name) for name in
                                     ("static void make_address(", "static void packet_nonce(", "static void peer_send_to("))
        constants = []
        for source, names in ((signal, ("TOPIC_SIZE", "NONCE_SIZE", "TAG_SIZE", "MAXIMUM_MESSAGE_SIZE")),
                              (transport, ("TUNNEL_MAGIC", "TUNNEL_HEADER_SIZE", "MAXIMUM_INNER_SIZE", "MAXIMUM_PACKET_SIZE"))):
            for name in names:
                constants.append(name + "=" + re.search(r"\b" + name + r"\s*=\s*([^,\n]+)", source).group(1))
        probe = PROTOCOL.replace("/* PRODUCTION_CONTEXTS */", contexts)
        probe = probe.replace("/* PRODUCTION_CONSTANTS */", "enum {" + ",".join(constants) + "};")
        with tempfile.TemporaryDirectory(prefix="halo-opence-protocol-") as folder:
            directory = Path(folder)
            (directory / "prefix.h").write_text("#define __HALO_LINUX_PLATFORM_H\n")
            (directory / "probe.c").write_text(probe)
            vendor = ROOT / "port/third_party/monocypher"
            executable = directory / "probe"
            subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                            "-include", str(directory / "prefix.h"), f"-I{PORT}", f"-I{vendor}",
                            str(directory / "probe.c"), str(PORT / "p2p_crypto.c"), str(vendor / "monocypher.c"),
                            str(vendor / "monocypher-ed25519.c"), "-o", str(executable)], check=True)
            values = dict(line.split("=", 1) for line in subprocess.check_output([str(executable)], text=True).splitlines())
        expected = {
            "shared": "9663aa1da97e848a914a436d04163dfbb89178f107f1b5b77ed3854203382854",
            "base": "77246e73c2c59cd7ba953c8cd299dfd968b2c9571da5cc483c03affe325bc390",
            "session": "ec3648fa9c19e7162d35d07178745b3d01cbe772dfe948add76858c6f79d0f17",
            "host_topic": "hceu/3/014711107ed02c645bdbb33c4b1e6ec4",
            "joiner_topic": "hceu/3/8089c49fd8e289d3cb910e81e5b085e1",
            "seal_key": "9198a35f6a96e4390ced01fbb42ccd2415ac2b9de5150c6f3c5638a8dcdde946",
            "joiner_key": "7ba19ea75c388d2d55d1c0fca1287f819706262755ceaeb5e17bd20c834d0557",
            "host_key": "60c989840f72b427ea2e8bb293bf823550ff096149318e2a8f9741c4502cd5a4",
            "proven_join": "4a038f40c5adb68f25624ae5b214ea767a6ec94d829d3d7b5e1ad1ba6f3e2138285f40414243444546470048494a4b4c4d4e4f67daa3211002c87222001b119dd0a5a9",
            "accept": "41038f40c5adb68f25624ae5b214ea767a6ec94d829d3d7b5e1ad1ba6f3e2138285f40414243444546470048494a4b4c4d4e4f75f736199a53bf3048390841a5d1814b",
            "tunnel_packet": "691011121314150100000000000000a5d1636dc1c6c9ab2dc282f05f8b9e0ebc700ca133ca6e8479857e1f85e3040fa5b1673814344651b45303cb481d7774321922eabb13af8b309d03c95367cec01ea2eafeeabc5049cbededccca2ca9fa8daba7",
            "lobby_slot": "hceu/3/lobby/s/", "lobby_query": "hceu/3/lobby/q",
        }
        self.assertEqual(values, expected)
        # Independent standard-library HMACs pin all public context labels.
        def digest(key, message):
            return hmac.new(bytes.fromhex(key), message, hashlib.sha256).hexdigest()
        token = bytes(range(16)).hex()
        for label in ("host", "joiner"):
            self.assertEqual(values[label + "_topic"], "hceu/3/" + digest(token, label.encode() + bytes(range(16, 22)))[:32])
        self.assertEqual(values["seal_key"], digest(token, b"seal"))
        self.assertEqual(values["session"], digest(values["base"], b"session" + bytes(range(64, 80))))
        for label in ("host", "joiner"):
            self.assertEqual(values[label + "_key"], digest(values["session"], label.encode()))
        for label, field in ((b"join", "proven_join"), (b"accept", "accept")):
            packet = bytes.fromhex(values[field])
            self.assertEqual(packet[-16:].hex(), digest(values["base"], label + packet[:-16])[:32])

    def test_signed_and_password_protected_invites(self):
        with tempfile.TemporaryDirectory(prefix="halo-opence-crypto-") as folder:
            directory = Path(folder)
            (directory / "platform.h").write_text("")
            (directory / "prefix.h").write_text("#define __HALO_LINUX_PLATFORM_H\n")
            source = (PORT / "p2p.c").read_text()
            parser = "\n".join(block(source, signature) for signature in
                               ("static int hex_value(", "static int parse_invite(", "static void make_invite("))
            (directory / "probe.c").write_text(CRYPTO.replace("/* PRODUCTION_INVITE_PARSER */", parser))
            vendor = ROOT / "port/third_party/monocypher"
            executable = directory / "probe"
            subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                            "-include", str(directory / "prefix.h"),
                            f"-I{directory}", f"-I{PORT}", f"-I{vendor}", str(directory / "probe.c"),
                            str(PORT / "p2p_crypto.c"), str(vendor / "monocypher.c"),
                            str(vendor / "monocypher-ed25519.c"), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

    @unittest.skipUnless(SDL_INCLUDE, "SDL3 headers required")
    def test_original_defaults_and_atomic_upstream_config_api(self):
        with tempfile.TemporaryDirectory(prefix="halo-opence-config-") as folder:
            directory = Path(folder)
            (directory / "prefix.h").write_text(PREFIX)
            broker_source = block((PORT / "p2p_signal.c").read_text(), "static void brokers_list(")
            (directory / "probe.c").write_text(CONFIG.replace("/* PRODUCTION_BROKERS */", broker_source))
            data = directory / "data"
            data.mkdir()
            (data / "brokers.txt").write_text("# ignored comment\none.example:1883\ntwo.example:1883 # ignored\n")
            executable = directory / "probe"
            subprocess.run(["clang", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                            "-DHALO_ANDROID=1", "-DHALO_MACOS=1", "-include", str(directory / "prefix.h"),
                            f"-I{PORT}", f"-I{SDL_INCLUDE}", f"-I{ROOT / 'port/third_party/tomlc17'}",
                            str(directory / "probe.c"), str(PORT / "port_config.c"),
                            str(ROOT / "port/third_party/tomlc17/tomlc17.c"), "-o", str(executable)], check=True)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
            environment["HALO_SAVE_ROOT"] = folder
            environment["HALO_DATA_ROOT"] = str(data)
            subprocess.run([str(executable)], env=environment, check=True)


if __name__ == "__main__":
    unittest.main()
