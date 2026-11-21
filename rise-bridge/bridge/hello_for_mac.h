// The hello value for a MAC: the 8 bytes after 00 01 03 02 in the game's first game message.
// Found by measurement (see bridge/hello.py); valid for MACs whose first byte is 0x02.
#pragma once
#include <cstdint>

// Returns false if the MAC doesn't start with 0x02. out[0..7] is the value in message byte order.
inline bool hello_for_mac(const uint8_t mac[6], uint8_t out[8]) {
    static const uint64_t kConst = 0x172d56fb96bf482dULL;
    static const uint64_t kColumns[40] = {
        0x0192e7f11264cddfULL,
        0x0325cfe224c99bbfULL,
        0x064b9fc44993377fULL,
        0x0c973f8893266efeULL,
        0x192e7f11264cddfdULL,
        0x325cfe224c99bbfbULL,
        0x64b9fc44993377f7ULL,
        0x00d60aee8251d794ULL,
        0x01ac15dd04a3af29ULL,
        0x03582bba09475e52ULL,
        0x06b05774128ebca4ULL,
        0x0d60aee8251d7949ULL,
        0x1ac15dd04a3af292ULL,
        0x3582bba09475e525ULL,
        0x6b05774128ebca4aULL,
        0x1faf1ce5e1e0acefULL,
        0x602b986a4528f3a2ULL,
        0x09f2c2b33a66df3eULL,
        0x13e5856674cdbe7cULL,
        0x27cb0acce99b7cf8ULL,
        0x4f961599d336f9f1ULL,
        0x5689d954165acb98ULL,
        0x64b640cf9c82af4aULL,
        0x00c973f8893266efULL,
        0x3f5e39cbc3c159dfULL,
        0x7ebc73978782b3bfULL,
        0x34dd1548bf325f04ULL,
        0x69ba2a917e64be08ULL,
        0x1ad1a7454cfe446bULL,
        0x35a34e8a99fc88d6ULL,
        0x6b469d1533f911adULL,
        0x1f28c84dd7c51b20ULL,
        0x608384e7b9cf88a4ULL,
        0x08a2fba8c3a82932ULL,
        0x1145f75187505264ULL,
        0x228beea30ea0a4c8ULL,
        0x4517dd461d414991ULL,
        0x438a48eb8ab5ab58ULL,
        0x4eb163b0a55c6ecbULL,
        0x54c73506fa8fe5ecULL
    };
    if (mac[0] != 0x02) return false;
    uint64_t x = 0;
    for (int i = 1; i < 6; i++) x = (x << 8) | mac[i];
    uint64_t h = kConst;
    for (int i = 0; i < 40; i++)
        if ((x >> i) & 1) h ^= kColumns[i];
    for (int i = 0; i < 8; i++) out[i] = static_cast<uint8_t>(h >> (56 - 8 * i));
    return true;
}

// The whole 15-byte hello message for a MAC (what a station sends as its first game message). Valid for MACs starting 0x02.
inline bool hello_message_for_mac(const uint8_t mac[6], uint8_t out[15]) {
    // each value is 120 bits, held as {high 56 bits, low 64 bits}
    static const uint64_t kConst[2] = {0x00965561adacaeafULL, 0xba80fb563b12e580ULL};
    static const uint64_t kColumns[40][2] = {
        {0x00beb1af1c1c1c1cULL, 0x1d8efbed0e78d1c3ULL},
        {0x00ea14e5dfdfdfdfULL, 0xdcfa103dfb164460ULL},
        {0x00089645d7d7d7d7ULL, 0xd19c48139e44e0a8ULL},
        {0x00618b4163636363ULL, 0x6ff45cebf0450d9dULL},
        {0x0094fc4a95959595ULL, 0x8cbbea84b3d94868ULL},
        {0x0085e0d18f8f8f8fULL, 0xbdd371adc3163474ULL},
        {0x009873d7cacacacaULL, 0xae73368e53f9bd3dULL},
        {0x000c84e3e2e2e2e2ULL, 0xe234e80c60b33576ULL},
        {0x002152d5adadadadULL, 0xac01b870a90e0284ULL},
        {0x0029d1be52525252ULL, 0x510a79e85b150c00ULL},
        {0x001cae8619191919ULL, 0x1fa94e6d0b97a5bdULL},
        {0x000426d0f5f5f5f5ULL, 0xf8955b1dd0e88cbcULL},
        {0x00af5fd21b1b1b1bULL, 0x01da46cb5121e989ULL},
        {0x0021d7969c9c9c9cULL, 0xa91e273c08e979b9ULL},
        {0x008ae9856f6f6f6fULL, 0x046a182e4784a525ULL},
        {0x00614c9e0d0d0d0dULL, 0x12a211e8eceda1e2ULL},
        {0x00fe4d3447474747ULL, 0x276cdf2d026fb4e5ULL},
        {0x00aeadff5f5f5f5fULL, 0x56ad9dec65398061ULL},
        {0x00d32e762a2a2a2aULL, 0x39cfaf4c5ee79456ULL},
        {0x00b0912741414141ULL, 0x668a4b8da8da3db9ULL},
        {0x003bd69201010101ULL, 0x4e971498d237f8f0ULL},
        {0x0059c66c52525252ULL, 0x04db8b06440899caULL},
        {0x00a76d6e2a2a2a2aULL, 0x4e9c6ae5b6a88560ULL},
        {0x0074adb3a7a7a7a7ULL, 0xa76ed45f2e95c148ULL},
        {0x002d77974e4e4e4eULL, 0x711077858d8f1791ULL},
        {0x0046cdd340404040ULL, 0x3efc33d7c7c2f3ffULL},
        {0x00744557ececececULL, 0xd831f9a453deb3e8ULL},
        {0x00e96fae44444444ULL, 0x2dfe6ed53a20fa4cULL},
        {0x00a2850769696969ULL, 0x73b8ce2c25972d02ULL},
        {0x003c761ffcfcfcfcULL, 0xc95fb2766500742aULL},
        {0x00970294adadadadULL, 0xc6eb30b89e54bc00ULL},
        {0x00c436dd8d8d8d8dULL, 0x92a545c05a4896adULL},
        {0x00d7ad5513131313ULL, 0x739097f4aadc9bb7ULL},
        {0x0064307febebebebULL, 0xe34910432843c2d9ULL},
        {0x00b9223486868686ULL, 0x97c371d701d6d4e2ULL},
        {0x00dd68c082828282ULL, 0xa0096c218c22264aULL},
        {0x00fa1383dedededeULL, 0x9bc90398c39f974fULL},
        {0x00c9a14a57575757ULL, 0x14dd1fbcdde2fc0fULL},
        {0x00a935fb5d5d5d5dULL, 0x13ec3eedf8013396ULL},
        {0x00c91ac93d3d3d3dULL, 0x69fa083bc7b2d8d1ULL}
    };
    if (mac[0] != 0x02) return false;
    uint64_t x = 0;
    for (int i = 1; i < 6; i++) x = (x << 8) | mac[i];
    uint64_t hi = kConst[0], lo = kConst[1];
    for (int i = 0; i < 40; i++)
        if ((x >> i) & 1) { hi ^= kColumns[i][0]; lo ^= kColumns[i][1]; }
    for (int i = 0; i < 7; i++) out[i] = static_cast<uint8_t>(hi >> (48 - 8 * i));
    for (int i = 0; i < 8; i++) out[7 + i] = static_cast<uint8_t>(lo >> (56 - 8 * i));
    return true;
}
