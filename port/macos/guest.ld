/* Mac desktop guest image, above OpenCE's 512 MB game memory window.
 * Android and iOS retain port/android/guest/guest.ld at 0x88000000. */
ENTRY(__guest_header)

SECTIONS
{
	. = 0xa0000000;
	.guest_header : { KEEP(*(.guest_header)) }
	.text : { *(.text .text.*) }
	.rodata : { *(.rodata .rodata.*) }
	. = ALIGN(0x10000);
	.data : { *(.data .data.*) }
	.guest_init : {
		__guest_init_start = .;
		KEEP(*(.guest_init))
		__guest_init_end = .;
	}
	.bss : { *(.bss .bss.*) *(COMMON) }
	. = ALIGN(0x1000);
	__guest_image_end = .;
	ASSERT(__guest_image_end <= 0xa8000000, "Mac guest image exceeds its 128 MB arena")
	/DISCARD/ : { *(.comment) *(.note.*) *(.guest_fini) *(.eh_frame) }
}
