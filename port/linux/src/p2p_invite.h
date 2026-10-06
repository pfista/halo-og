#ifndef HALO_P2P_INVITE_H
#define HALO_P2P_INVITE_H

/* OS routing stays separate from Halo OG and OpenCE installs. Shared invite
 * text uses OpenCE's prefix so unmodified upstream clients can consume it. */
#define P2P_INVITE_SCHEME "halo-og-opence"
#define P2P_INVITE_PREFIX "halo://join/"
#define P2P_LEGACY_INVITE_PREFIX "halo-og://join/"
#define P2P_PRIVATE_INVITE_PREFIX P2P_INVITE_SCHEME "://join/"
enum
{
	/* the host's key hash and token in hexadecimal */
	P2P_INVITE_CODE_SIZE = 64,
	/* Generated shared text and incoming private/legacy links both include
	 * their terminator. Delivery buffers must hold the longest accepted URI. */
	P2P_SHARED_LINK_SIZE = sizeof(P2P_INVITE_PREFIX) + P2P_INVITE_CODE_SIZE,
	P2P_LINK_SIZE = sizeof(P2P_PRIVATE_INVITE_PREFIX) + P2P_INVITE_CODE_SIZE,
};

static inline unsigned p2p_invite_prefix_length(const char *text)
{
	const char *const prefixes[] = { P2P_INVITE_PREFIX, P2P_LEGACY_INVITE_PREFIX, P2P_PRIVATE_INVITE_PREFIX };
	unsigned prefix;
	if (!text) return 0;
	for (prefix = 0; prefix < sizeof(prefixes) / sizeof(prefixes[0]); prefix++)
	{
		unsigned length = 0;
		while (prefixes[prefix][length] && text[length] &&
			(text[length] | 0x20) == prefixes[prefix][length]) length++;
		if (!prefixes[prefix][length]) return length;
	}
	return 0;
}

#endif
