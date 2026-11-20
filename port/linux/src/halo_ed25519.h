/* Ed25519 signature verification for signed update records.

The arithmetic is TweetNaCl 20140427 (public domain; Bernstein, van Gastel,
Janssen, Lange, Schwabe, Smetsers; https://tweetnacl.cr.yp.to), reduced to what
crypto_sign_open needs: the field and group operations, SHA-512 and the scalar
reduction. Its functions are static and every name carries an ed25519_ prefix;
the code is otherwise unchanged. Only public values pass through it. */
#ifndef HALO_ED25519_H
#define HALO_ED25519_H

#include <stddef.h>
#include <string.h>

#define HALO_ED25519_MAXIMUM_MESSAGE 1024

#define ED25519_FOR(i,n) for (i = 0;i < n;++i)

typedef unsigned char ed25519_u8;
typedef unsigned long ed25519_u32;
typedef unsigned long long ed25519_u64;
typedef long long ed25519_i64;
typedef ed25519_i64 ed25519_gf[16];

/* TweetNaCl compares its loop counters with sizes of the other signedness. */
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-compare"
#endif

static const ed25519_gf
  ed25519_gf0,
  ed25519_gf1 = {1},
  ed25519_D = {0x78a3, 0x1359, 0x4dca, 0x75eb, 0xd8ab, 0x4141, 0x0a4d, 0x0070, 0xe898, 0x7779, 0x4079, 0x8cc7, 0xfe73, 0x2b6f, 0x6cee, 0x5203},
  ed25519_D2 = {0xf159, 0x26b2, 0x9b94, 0xebd6, 0xb156, 0x8283, 0x149a, 0x00e0, 0xd130, 0xeef3, 0x80f2, 0x198e, 0xfce7, 0x56df, 0xd9dc, 0x2406},
  ed25519_X = {0xd51a, 0x8f25, 0x2d60, 0xc956, 0xa7b2, 0x9525, 0xc760, 0x692c, 0xdc5c, 0xfdd6, 0xe231, 0xc0a4, 0x53fe, 0xcd6e, 0x36d3, 0x2169},
  ed25519_Y = {0x6658, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666},
  ed25519_I = {0xa0b0, 0x4a0e, 0x1b27, 0xc4ee, 0xe478, 0xad2f, 0x1806, 0x2f43, 0xd7a7, 0x3dfb, 0x0099, 0x2b4d, 0xdf0b, 0x4fc1, 0x2480, 0x2b83};

static ed25519_u64 ed25519_dl64(const ed25519_u8 *x)
{
  ed25519_u64 i,u=0;
  ED25519_FOR(i,8) u=(u<<8)|x[i];
  return u;
}

static void ed25519_ts64(ed25519_u8 *x,ed25519_u64 u)
{
  int i;
  for (i = 7;i >= 0;--i) { x[i] = u; u >>= 8; }
}

static int ed25519_vn(const ed25519_u8 *x,const ed25519_u8 *y,int n)
{
  ed25519_u32 i,d = 0;
  ED25519_FOR(i,n) d |= x[i]^y[i];
  return (1 & ((d - 1) >> 8)) - 1;
}

static int ed25519_crypto_verify_32(const ed25519_u8 *x,const ed25519_u8 *y)
{
  return ed25519_vn(x,y,32);
}

static void ed25519_set25519(ed25519_gf r, const ed25519_gf a)
{
  int i;
  ED25519_FOR(i,16) r[i]=a[i];
}

static void ed25519_car25519(ed25519_gf o)
{
  int i;
  ed25519_i64 c;
  ED25519_FOR(i,16) {
    o[i]+=(1LL<<16);
    c=o[i]>>16;
    o[(i+1)*(i<15)]+=c-1+37*(c-1)*(i==15);
    o[i]-=c<<16;
  }
}

static void ed25519_sel25519(ed25519_gf p,ed25519_gf q,int b)
{
  ed25519_i64 t,i,c=~(b-1);
  ED25519_FOR(i,16) {
    t= c&(p[i]^q[i]);
    p[i]^=t;
    q[i]^=t;
  }
}

static void ed25519_pack25519(ed25519_u8 *o,const ed25519_gf n)
{
  int i,j,b;
  ed25519_gf m,t;
  ED25519_FOR(i,16) t[i]=n[i];
  ed25519_car25519(t);
  ed25519_car25519(t);
  ed25519_car25519(t);
  ED25519_FOR(j,2) {
    m[0]=t[0]-0xffed;
    for(i=1;i<15;i++) {
      m[i]=t[i]-0xffff-((m[i-1]>>16)&1);
      m[i-1]&=0xffff;
    }
    m[15]=t[15]-0x7fff-((m[14]>>16)&1);
    b=(m[15]>>16)&1;
    m[14]&=0xffff;
    ed25519_sel25519(t,m,1-b);
  }
  ED25519_FOR(i,16) {
    o[2*i]=t[i]&0xff;
    o[2*i+1]=t[i]>>8;
  }
}

static int ed25519_neq25519(const ed25519_gf a, const ed25519_gf b)
{
  ed25519_u8 c[32],d[32];
  ed25519_pack25519(c,a);
  ed25519_pack25519(d,b);
  return ed25519_crypto_verify_32(c,d);
}

static ed25519_u8 ed25519_par25519(const ed25519_gf a)
{
  ed25519_u8 d[32];
  ed25519_pack25519(d,a);
  return d[0]&1;
}

static void ed25519_unpack25519(ed25519_gf o, const ed25519_u8 *n)
{
  int i;
  ED25519_FOR(i,16) o[i]=n[2*i]+((ed25519_i64)n[2*i+1]<<8);
  o[15]&=0x7fff;
}

static void ed25519_A(ed25519_gf o,const ed25519_gf a,const ed25519_gf b)
{
  int i;
  ED25519_FOR(i,16) o[i]=a[i]+b[i];
}

static void ed25519_Z(ed25519_gf o,const ed25519_gf a,const ed25519_gf b)
{
  int i;
  ED25519_FOR(i,16) o[i]=a[i]-b[i];
}

static void ed25519_M(ed25519_gf o,const ed25519_gf a,const ed25519_gf b)
{
  ed25519_i64 i,j,t[31];
  ED25519_FOR(i,31) t[i]=0;
  ED25519_FOR(i,16) ED25519_FOR(j,16) t[i+j]+=a[i]*b[j];
  ED25519_FOR(i,15) t[i]+=38*t[i+16];
  ED25519_FOR(i,16) o[i]=t[i];
  ed25519_car25519(o);
  ed25519_car25519(o);
}

static void ed25519_S(ed25519_gf o,const ed25519_gf a)
{
  ed25519_M(o,a,a);
}

static void ed25519_inv25519(ed25519_gf o,const ed25519_gf i)
{
  ed25519_gf c;
  int a;
  ED25519_FOR(a,16) c[a]=i[a];
  for(a=253;a>=0;a--) {
    ed25519_S(c,c);
    if(a!=2&&a!=4) ed25519_M(c,c,i);
  }
  ED25519_FOR(a,16) o[a]=c[a];
}

static void ed25519_pow2523(ed25519_gf o,const ed25519_gf i)
{
  ed25519_gf c;
  int a;
  ED25519_FOR(a,16) c[a]=i[a];
  for(a=250;a>=0;a--) {
    ed25519_S(c,c);
    if(a!=1) ed25519_M(c,c,i);
  }
  ED25519_FOR(a,16) o[a]=c[a];
}

static ed25519_u64 ed25519_R(ed25519_u64 x,int c) { return (x >> c) | (x << (64 - c)); }

static ed25519_u64 ed25519_Ch(ed25519_u64 x,ed25519_u64 y,ed25519_u64 z) { return (x & y) ^ (~x & z); }

static ed25519_u64 ed25519_Maj(ed25519_u64 x,ed25519_u64 y,ed25519_u64 z) { return (x & y) ^ (x & z) ^ (y & z); }

static ed25519_u64 ed25519_Sigma0(ed25519_u64 x) { return ed25519_R(x,28) ^ ed25519_R(x,34) ^ ed25519_R(x,39); }

static ed25519_u64 ed25519_Sigma1(ed25519_u64 x) { return ed25519_R(x,14) ^ ed25519_R(x,18) ^ ed25519_R(x,41); }

static ed25519_u64 ed25519_sigma0(ed25519_u64 x) { return ed25519_R(x, 1) ^ ed25519_R(x, 8) ^ (x >> 7); }

static ed25519_u64 ed25519_sigma1(ed25519_u64 x) { return ed25519_R(x,19) ^ ed25519_R(x,61) ^ (x >> 6); }

static const ed25519_u64 ed25519_K[80] = 
{
  0x428a2f98d728ae22ULL, 0x7137449123ef65cdULL, 0xb5c0fbcfec4d3b2fULL, 0xe9b5dba58189dbbcULL,
  0x3956c25bf348b538ULL, 0x59f111f1b605d019ULL, 0x923f82a4af194f9bULL, 0xab1c5ed5da6d8118ULL,
  0xd807aa98a3030242ULL, 0x12835b0145706fbeULL, 0x243185be4ee4b28cULL, 0x550c7dc3d5ffb4e2ULL,
  0x72be5d74f27b896fULL, 0x80deb1fe3b1696b1ULL, 0x9bdc06a725c71235ULL, 0xc19bf174cf692694ULL,
  0xe49b69c19ef14ad2ULL, 0xefbe4786384f25e3ULL, 0x0fc19dc68b8cd5b5ULL, 0x240ca1cc77ac9c65ULL,
  0x2de92c6f592b0275ULL, 0x4a7484aa6ea6e483ULL, 0x5cb0a9dcbd41fbd4ULL, 0x76f988da831153b5ULL,
  0x983e5152ee66dfabULL, 0xa831c66d2db43210ULL, 0xb00327c898fb213fULL, 0xbf597fc7beef0ee4ULL,
  0xc6e00bf33da88fc2ULL, 0xd5a79147930aa725ULL, 0x06ca6351e003826fULL, 0x142929670a0e6e70ULL,
  0x27b70a8546d22ffcULL, 0x2e1b21385c26c926ULL, 0x4d2c6dfc5ac42aedULL, 0x53380d139d95b3dfULL,
  0x650a73548baf63deULL, 0x766a0abb3c77b2a8ULL, 0x81c2c92e47edaee6ULL, 0x92722c851482353bULL,
  0xa2bfe8a14cf10364ULL, 0xa81a664bbc423001ULL, 0xc24b8b70d0f89791ULL, 0xc76c51a30654be30ULL,
  0xd192e819d6ef5218ULL, 0xd69906245565a910ULL, 0xf40e35855771202aULL, 0x106aa07032bbd1b8ULL,
  0x19a4c116b8d2d0c8ULL, 0x1e376c085141ab53ULL, 0x2748774cdf8eeb99ULL, 0x34b0bcb5e19b48a8ULL,
  0x391c0cb3c5c95a63ULL, 0x4ed8aa4ae3418acbULL, 0x5b9cca4f7763e373ULL, 0x682e6ff3d6b2b8a3ULL,
  0x748f82ee5defb2fcULL, 0x78a5636f43172f60ULL, 0x84c87814a1f0ab72ULL, 0x8cc702081a6439ecULL,
  0x90befffa23631e28ULL, 0xa4506cebde82bde9ULL, 0xbef9a3f7b2c67915ULL, 0xc67178f2e372532bULL,
  0xca273eceea26619cULL, 0xd186b8c721c0c207ULL, 0xeada7dd6cde0eb1eULL, 0xf57d4f7fee6ed178ULL,
  0x06f067aa72176fbaULL, 0x0a637dc5a2c898a6ULL, 0x113f9804bef90daeULL, 0x1b710b35131c471bULL,
  0x28db77f523047d84ULL, 0x32caab7b40c72493ULL, 0x3c9ebe0a15c9bebcULL, 0x431d67c49c100d4cULL,
  0x4cc5d4becb3e42b6ULL, 0x597f299cfc657e2aULL, 0x5fcb6fab3ad6faecULL, 0x6c44198c4a475817ULL
};

static int ed25519_crypto_hashblocks(ed25519_u8 *x,const ed25519_u8 *m,ed25519_u64 n)
{
  ed25519_u64 z[8],b[8],a[8],w[16],t;
  int i,j;

  ED25519_FOR(i,8) z[i] = a[i] = ed25519_dl64(x + 8 * i);

  while (n >= 128) {
    ED25519_FOR(i,16) w[i] = ed25519_dl64(m + 8 * i);

    ED25519_FOR(i,80) {
      ED25519_FOR(j,8) b[j] = a[j];
      t = a[7] + ed25519_Sigma1(a[4]) + ed25519_Ch(a[4],a[5],a[6]) + ed25519_K[i] + w[i%16];
      b[7] = t + ed25519_Sigma0(a[0]) + ed25519_Maj(a[0],a[1],a[2]);
      b[3] += t;
      ED25519_FOR(j,8) a[(j+1)%8] = b[j];
      if (i%16 == 15)
        ED25519_FOR(j,16)
          w[j] += w[(j+9)%16] + ed25519_sigma0(w[(j+1)%16]) + ed25519_sigma1(w[(j+14)%16]);
    }

    ED25519_FOR(i,8) { a[i] += z[i]; z[i] = a[i]; }

    m += 128;
    n -= 128;
  }

  ED25519_FOR(i,8) ed25519_ts64(x+8*i,z[i]);

  return n;
}

static const ed25519_u8 ed25519_iv[64] = {
  0x6a,0x09,0xe6,0x67,0xf3,0xbc,0xc9,0x08,
  0xbb,0x67,0xae,0x85,0x84,0xca,0xa7,0x3b,
  0x3c,0x6e,0xf3,0x72,0xfe,0x94,0xf8,0x2b,
  0xa5,0x4f,0xf5,0x3a,0x5f,0x1d,0x36,0xf1,
  0x51,0x0e,0x52,0x7f,0xad,0xe6,0x82,0xd1,
  0x9b,0x05,0x68,0x8c,0x2b,0x3e,0x6c,0x1f,
  0x1f,0x83,0xd9,0xab,0xfb,0x41,0xbd,0x6b,
  0x5b,0xe0,0xcd,0x19,0x13,0x7e,0x21,0x79
} ;

static int ed25519_crypto_hash(ed25519_u8 *out,const ed25519_u8 *m,ed25519_u64 n)
{
  ed25519_u8 h[64],x[256];
  ed25519_u64 i,b = n;

  ED25519_FOR(i,64) h[i] = ed25519_iv[i];

  ed25519_crypto_hashblocks(h,m,n);
  m += n;
  n &= 127;
  m -= n;

  ED25519_FOR(i,256) x[i] = 0;
  ED25519_FOR(i,n) x[i] = m[i];
  x[n] = 128;

  n = 256-128*(n<112);
  x[n-9] = b >> 61;
  ed25519_ts64(x+n-8,b<<3);
  ed25519_crypto_hashblocks(h,x,n);

  ED25519_FOR(i,64) out[i] = h[i];

  return 0;
}

static void ed25519_add(ed25519_gf p[4],ed25519_gf q[4])
{
  ed25519_gf a,b,c,d,t,e,f,g,h;
  
  ed25519_Z(a, p[1], p[0]);
  ed25519_Z(t, q[1], q[0]);
  ed25519_M(a, a, t);
  ed25519_A(b, p[0], p[1]);
  ed25519_A(t, q[0], q[1]);
  ed25519_M(b, b, t);
  ed25519_M(c, p[3], q[3]);
  ed25519_M(c, c, ed25519_D2);
  ed25519_M(d, p[2], q[2]);
  ed25519_A(d, d, d);
  ed25519_Z(e, b, a);
  ed25519_Z(f, d, c);
  ed25519_A(g, d, c);
  ed25519_A(h, b, a);

  ed25519_M(p[0], e, f);
  ed25519_M(p[1], h, g);
  ed25519_M(p[2], g, f);
  ed25519_M(p[3], e, h);
}

static void ed25519_cswap(ed25519_gf p[4],ed25519_gf q[4],ed25519_u8 b)
{
  int i;
  ED25519_FOR(i,4)
    ed25519_sel25519(p[i],q[i],b);
}

static void ed25519_pack(ed25519_u8 *r,ed25519_gf p[4])
{
  ed25519_gf tx, ty, zi;
  ed25519_inv25519(zi, p[2]); 
  ed25519_M(tx, p[0], zi);
  ed25519_M(ty, p[1], zi);
  ed25519_pack25519(r, ty);
  r[31] ^= ed25519_par25519(tx) << 7;
}

static void ed25519_scalarmult(ed25519_gf p[4],ed25519_gf q[4],const ed25519_u8 *s)
{
  int i;
  ed25519_set25519(p[0],ed25519_gf0);
  ed25519_set25519(p[1],ed25519_gf1);
  ed25519_set25519(p[2],ed25519_gf1);
  ed25519_set25519(p[3],ed25519_gf0);
  for (i = 255;i >= 0;--i) {
    ed25519_u8 b = (s[i/8]>>(i&7))&1;
    ed25519_cswap(p,q,b);
    ed25519_add(q,p);
    ed25519_add(p,p);
    ed25519_cswap(p,q,b);
  }
}

static void ed25519_scalarbase(ed25519_gf p[4],const ed25519_u8 *s)
{
  ed25519_gf q[4];
  ed25519_set25519(q[0],ed25519_X);
  ed25519_set25519(q[1],ed25519_Y);
  ed25519_set25519(q[2],ed25519_gf1);
  ed25519_M(q[3],ed25519_X,ed25519_Y);
  ed25519_scalarmult(p,q,s);
}

static const ed25519_u64 ed25519_L[32] = {0xed, 0xd3, 0xf5, 0x5c, 0x1a, 0x63, 0x12, 0x58, 0xd6, 0x9c, 0xf7, 0xa2, 0xde, 0xf9, 0xde, 0x14, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x10};

static void ed25519_modL(ed25519_u8 *r,ed25519_i64 x[64])
{
  ed25519_i64 carry,i,j;
  for (i = 63;i >= 32;--i) {
    carry = 0;
    for (j = i - 32;j < i - 12;++j) {
      x[j] += carry - 16 * x[i] * ed25519_L[j - (i - 32)];
      carry = (x[j] + 128) >> 8;
      x[j] -= carry << 8;
    }
    x[j] += carry;
    x[i] = 0;
  }
  carry = 0;
  ED25519_FOR(j,32) {
    x[j] += carry - (x[31] >> 4) * ed25519_L[j];
    carry = x[j] >> 8;
    x[j] &= 255;
  }
  ED25519_FOR(j,32) x[j] -= carry * ed25519_L[j];
  ED25519_FOR(i,32) {
    x[i+1] += x[i] >> 8;
    r[i] = x[i] & 255;
  }
}

static void ed25519_reduce(ed25519_u8 *r)
{
  ed25519_i64 x[64],i;
  ED25519_FOR(i,64) x[i] = (ed25519_u64) r[i];
  ED25519_FOR(i,64) r[i] = 0;
  ed25519_modL(r,x);
}

static int ed25519_unpackneg(ed25519_gf r[4],const ed25519_u8 p[32])
{
  ed25519_gf t, chk, num, den, den2, den4, den6;
  ed25519_set25519(r[2],ed25519_gf1);
  ed25519_unpack25519(r[1],p);
  ed25519_S(num,r[1]);
  ed25519_M(den,num,ed25519_D);
  ed25519_Z(num,num,r[2]);
  ed25519_A(den,r[2],den);

  ed25519_S(den2,den);
  ed25519_S(den4,den2);
  ed25519_M(den6,den4,den2);
  ed25519_M(t,den6,num);
  ed25519_M(t,t,den);

  ed25519_pow2523(t,t);
  ed25519_M(t,t,num);
  ed25519_M(t,t,den);
  ed25519_M(t,t,den);
  ed25519_M(r[0],t,den);

  ed25519_S(chk,r[0]);
  ed25519_M(chk,chk,den);
  if (ed25519_neq25519(chk, num)) ed25519_M(r[0],r[0],ed25519_I);

  ed25519_S(chk,r[0]);
  ed25519_M(chk,chk,den);
  if (ed25519_neq25519(chk, num)) return -1;

  if (ed25519_par25519(r[0]) == (p[31]>>7)) ed25519_Z(r[0],ed25519_gf0,r[0]);

  ed25519_M(r[3],r[0],r[1]);
  return 0;
}

static int ed25519_crypto_sign_open(ed25519_u8 *m,ed25519_u64 *mlen,const ed25519_u8 *sm,ed25519_u64 n,const ed25519_u8 *pk)
{
  int i;
  ed25519_u8 t[32],h[64];
  ed25519_gf p[4],q[4];

  *mlen = -1;
  if (n < 64) return -1;

  if (ed25519_unpackneg(q,pk)) return -1;

  ED25519_FOR(i,n) m[i] = sm[i];
  ED25519_FOR(i,32) m[i+32] = pk[i];
  ed25519_crypto_hash(h,m,n);
  ed25519_reduce(h);
  ed25519_scalarmult(p,q,h);

  ed25519_scalarbase(q,sm + 32);
  ed25519_add(p,q);
  ed25519_pack(t,p);

  n -= 64;
  if (ed25519_crypto_verify_32(sm, t)) {
    ED25519_FOR(i,n) m[i] = 0;
    return -1;
  }

  ED25519_FOR(i,n) m[i] = sm[i + 64];
  *mlen = n;
  return 0;
}

#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif

/* 1 when signature is public_key's Ed25519 signature of the size bytes at
message. Messages longer than HALO_ED25519_MAXIMUM_MESSAGE are refused. */
static int halo_ed25519_verify(const unsigned char public_key[32], const void *message, size_t size,
	const unsigned char signature[64])
{
	unsigned char signed_message[64 + HALO_ED25519_MAXIMUM_MESSAGE];
	unsigned char opened[64 + HALO_ED25519_MAXIMUM_MESSAGE];
	ed25519_u64 opened_size = 0;

	if (!public_key || !message || !signature || size > HALO_ED25519_MAXIMUM_MESSAGE)
		return 0;
	memcpy(signed_message, signature, 64);
	memcpy(signed_message + 64, message, size);
	return ed25519_crypto_sign_open(opened, &opened_size, signed_message, 64 + size, public_key) == 0 &&
		opened_size == size;
}

#undef ED25519_FOR

#endif
