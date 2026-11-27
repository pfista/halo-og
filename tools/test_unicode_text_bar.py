"""A bar in wide text is a line break only before an n, and never eats the character after it.

`parse_unicode_string` comes from production `draw_string.c`.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
DRAW = ROOT / "source/text/draw_string.c"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte;
typedef unsigned short word;
typedef unsigned int pixel32;
typedef struct { short y0,x0,y1,x1; } rectangle2d;
struct font_header;
#define wchar_t unsigned short   /* the game's wide character is 16 bits */
#define long int
enum {
    _parsed_end_of_string=0,_parsed_end_of_line=1,_parsed_end_of_word=2,_parsed_end_of_column=3,
    _parsed_justification_change=4,_parsed_color_change=5,_parsed_character=6,_parsed_style_change=7
};
'''

HARNESS = r'''
#undef long
/* Parses `count` wide characters copied to the very end of a heap block, so the
   address sanitizer stops any read past the terminator. */
static int parse(const char *text,short *results,word *characters) {
    size_t count=strlen(text)+1;
    unsigned short *wide=malloc(count*sizeof(*wide));
    struct parse_string_state state;
    int parsed=0;

    for (size_t index=0;index<count;index++) wide[index]=(unsigned char)text[index];
    memset(&state,0,sizeof(state));
    state.string=(byte *)wide;
    state.result=_parsed_style_change;   /* a stale result must never be reported for a bar */
    do {
        assert(parsed<32);
        results[parsed]=(short)parse_unicode_string(&state);
        characters[parsed++]=state.character;
        assert(state.string_index<=(short)count);
    } while (results[parsed-1]!=_parsed_end_of_string);
    free(wide);
    return parsed;
}
int main(void) {
    short results[32];
    word characters[32];

    /* "|n" is a line break. */
    assert(parse("a|nb",results,characters)==4);
    assert(results[0]==_parsed_character && characters[0]=='a');
    assert(results[1]==_parsed_end_of_line && characters[1]=='\r');
    assert(results[2]==_parsed_character && characters[2]=='b');
    assert(results[3]==_parsed_end_of_string);

    /* A bar before anything else is a bar, and the character after it is kept. */
    assert(parse("|X|ame",results,characters)==7);
    assert(results[0]==_parsed_character && characters[0]=='|');
    assert(results[1]==_parsed_character && characters[1]=='X');
    assert(results[2]==_parsed_character && characters[2]=='|');
    assert(results[3]==_parsed_character && characters[3]=='a');
    assert(results[6]==_parsed_end_of_string);

    /* Text ending in a bar ends at its terminator. */
    assert(parse("gg|",results,characters)==4);
    assert(results[2]==_parsed_character && characters[2]=='|');
    assert(results[3]==_parsed_end_of_string);
    assert(parse("|",results,characters)==2 && results[0]==_parsed_character && results[1]==_parsed_end_of_string);

    /* The other separators are as before. */
    assert(parse("a\tb\rc",results,characters)==6);
    assert(results[1]==_parsed_end_of_column && results[3]==_parsed_end_of_line);
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class UnicodeTextBarTests(unittest.TestCase):
    def test_a_bar_is_a_line_break_only_before_n(self):
        source = DRAW.read_text()
        production = block(source[source.index("struct parse_string_state\n"):], "struct parse_string_state\n") + ";\n"
        production += function(source, "static word parse_unicode_string(")
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-text-bar-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "bar"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=undefined", str(harness), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
