#!/usr/bin/env python3
"""Regression checks for literal data versus decorated symbol operands."""
import unittest

if __package__:
    from .android_asm_convert import Converter
else:
    from android_asm_convert import Converter


class AssemblyConversionTests(unittest.TestCase):
    def test_arsenal_strings_keep_exact_bytes(self):
        literals = [
            '.asciz "_fiesta_%s"',
            '.asciz "_fiestah_"',
            '.ascii "_fiesta_", "_suffix"',
            '.string "_literal\\\\path\\\"quote; // @PAGE"',
        ]
        converted = Converter([".cstring", *literals]).run().splitlines()
        self.assertEqual(converted[1:], ["\t" + literal for literal in literals])

    def test_symbol_decoration_is_still_converted(self):
        source = [
            '.globl "_quoted_symbol"',
            '"_quoted_symbol":',
            '.long "_quoted_symbol"',
            '.quad _external',
            'adrp x0, _external@PAGE',
            'add x0, x0, _external@PAGEOFF',
        ]
        self.assertEqual(Converter(source).run().splitlines(), [
            '\t.globl "quoted_symbol"',
            '"quoted_symbol":',
            '\t.long "quoted_symbol"',
            '\t.quad external',
            '\tadrp x0, external',
            '\tadd x0, x0, :lo12:external',
        ])

    def test_literal_comments_and_dropped_sections(self):
        source = [
            '.section __DWARF,__debug_str',
            '.asciz "_unused"',
            '.cstring',
            '.asciz "_fiesta_//;" // outside comment',
        ]
        self.assertEqual(Converter(source).run().splitlines(), [
            '\t.section .rodata,"a",@progbits',
            '\t.asciz "_fiesta_//;"',
        ])


if __name__ == "__main__":
    unittest.main()
