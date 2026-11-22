#!/usr/bin/env python3
"""Reads the two kinds of capture side by side:

  rise_netlog.txt          MH Rise on PC (this repo's dinput8.dll): Steam lobby calls and Steam messages
  local_play_<date>.txt    MH Rise on Switch, through mhrise-recomp (Debug -> Capture Local Play): Pia packets

  python3 rise_net.py pc LOG [--all]             the PC session: lobbies, then each game message decoded
  python3 rise_net.py switch LOG [--all]         the Switch session: Pia decrypted, its messages one per line
  python3 rise_net.py compare SWITCH_LOG PC_LOG  the game's messages on both, what they share
  python3 rise_net.py verify LOG                 checks every Pia packet's GCM tag

Needs Python 3.8+ and `cryptography` (pip install cryptography) for the Switch side.

What's known (see NOTES.md):
 - Pia (Switch): "32 ab 98 64", version 0x89 (encrypted). AES-128-GCM's counter mode: key from Pia's key schedule
   (logged in the capture), nonce = CRC32(session id[4] + sender's MAC)[first 3 bytes, big endian] + header[0x0c] +
   header[0x10:0x18], tag = header[0x18:0x20] (8 bytes, no additional data), ciphertext from 0x20 to the trailer
   (header[0x0f] bytes: the receivers' keys, 16 bits each). That's plain AES-128-GCM. The decrypted body is a list of
   messages, each with a field mask; 0xff ends it.
 - Game messages: Pia protocol type 0x68 on the Switch; Steam's SendMessageToUser on PC, behind a 6-byte header
   (u16 + u32, both the length, big endian). Byte for byte the same on both.
 - A game message: 3 bytes that follow from its content, then the rest XORed with one byte (the first of it is 0).
"""
import base64
import collections
import re
import struct
import sys
import zlib

# ---- PC: rise_netlog.txt ---------------------------------------------------------------------------------------------

PC_PACKET = re.compile(r'^(\S+) ([<>]) (\w+) peer (\S+) channel (-?\d+)\s+(\d+) bytes')
HEX_ROW = re.compile(r'^  [0-9a-f]{4}  ((?:[0-9a-f]{2} ?)+)')


def read_pc(path):
    """Lines: ('packet', dict) for messages, ('call', text) for the rest (lobby calls, interfaces)"""
    out, cur = [], None
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.rstrip('\n')
        m = PC_PACKET.match(line)
        if m:
            cur = {'t': m[1], 'dir': m[2], 'fn': m[3], 'peer': m[4], 'channel': int(m[5]), 'size': int(m[6]),
                   'data': bytearray()}
            out.append(('packet', cur))
            continue
        m = HEX_ROW.match(line)
        if m and cur is not None:
            cur['data'] += bytes.fromhex(m[1].replace(' ', ''))
            continue
        cur = None
        if line.strip():
            out.append(('call', line))
    return out


def pc_game_message(data):
    """The game message in a Steam message (None for SteamConReq / SteamConAns and the like)"""
    if len(data) < 6 or data.startswith(b'SteamCon'):
        return None
    n = struct.unpack('>H', data[:2])[0]
    if n + 6 != len(data) or struct.unpack('>I', data[2:6])[0] != n:
        return None
    return bytes(data[6:])


def unscramble(msg):
    """(prefix, body): the 3 bytes in front, and the rest with its XOR byte taken off"""
    if len(msg) < 4:
        return msg[:3], b''
    return msg[:3], bytes(b ^ msg[3] for b in msg[3:])


def short_id(s):
    """A Steam ID or lobby shortened to its last 4 digits, so a log can be shared"""
    return '…' + s[-4:] if s.isdigit() and len(s) > 8 else s


def binary_data(b64):
    try:
        d = base64.b64decode(b64)
    except Exception:
        return None
    return d


def cmd_pc(path, everything):
    lines = read_pc(path)
    last = None
    for kind, x in lines:
        if kind == 'call':
            text = re.sub(r'\b(\d{13,})\b', lambda m: short_id(m[1]), x)
            print(text)
            m = re.search(r'"BinaryData" = "([A-Za-z0-9+/=]+)"', x)
            if m:
                d = binary_data(m[1])
                if d:
                    for i in range(0, len(d), 16):
                        print('      %04x  %s' % (i, d[i:i + 16].hex(' ')))
            continue
        d = bytes(x['data'])
        g = pc_game_message(d)
        head = '%s %s %s' % (x['t'], x['dir'], short_id(x['peer']))
        if g is None:
            print(head, repr(d.rstrip(b'\0')))
            continue
        prefix, body = unscramble(g)
        key = (x['dir'], x['peer'], len(g))
        if not everything and key == last:
            continue
        last = key
        print(head, '%4d' % len(g), prefix.hex(), body[:64].hex())


# ---- Switch: local_play_<date>.txt ------------------------------------------------------------------------------------

SW_PACKET = re.compile(r'^(\d\d:\d\d:\d\d\.\d+) ([<>]) ([\d.]+):(\d+) -> ([\d.]+):(\d+)\s+(\d+) bytes')
PIA_MAGIC = b'\x32\xab\x98\x64'


def read_switch(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    keys = re.findall(r'# AES key ([0-9a-f]{32}) \(16 bytes, mode 1, from main\+0x24d9', text)
    macs = {ip: bytes.fromhex(mac.replace(':', '')) for ip, mac in re.findall(r'# player \d+: (\S+) mac (\S+)', text)}
    adv = re.search(r'# advertise data[^\n]*\n#\s+0000  ((?:[0-9a-f]{2} ){4})', text)
    session = bytes.fromhex(adv[1].replace(' ', '')) if adv else None
    packets, cur = [], None
    for line in text.split('\n'):
        m = SW_PACKET.match(line)
        if m:
            cur = {'t': m[1], 'dir': m[2], 'src': m[3], 'dst': m[5], 'data': bytearray()}
            packets.append(cur)
            continue
        m = HEX_ROW.match(line)
        if m and cur is not None:
            cur['data'] += bytes.fromhex(m[1].replace(' ', ''))
        elif line.startswith('#') or not line.strip():
            cur = None
    return (bytes.fromhex(keys[-1]) if keys else None), macs, session, packets


class Pia:
    def __init__(self, key, macs, session):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        self.ecb = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        self.key, self.macs, self.session = key, macs, session

    def nonce(self, pk):
        d = bytes(pk['data'])
        mac = self.macs.get(pk['src'])
        if mac is None:
            return None
        return struct.pack('>I', zlib.crc32(self.session + mac))[:3] + bytes([d[0x0c]]) + d[0x10:0x18]

    def verify(self, pk):
        """True / False for an encrypted packet's tag, None if it can't be checked"""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        d = bytes(pk['data'])
        if not d.startswith(PIA_MAGIC) or len(d) < 0x20 or not d[4] & 0x80:
            return None
        nonce = self.nonce(pk)
        if nonce is None:
            return None
        try:
            dec = Cipher(algorithms.AES(self.key), modes.GCM(nonce, d[0x18:0x20], min_tag_length=8)).decryptor()
            dec.update(d[0x20:len(d) - d[0x0f]])
            dec.finalize()
            return True
        except Exception:
            return False

    def decrypt(self, pk):
        d = bytes(pk['data'])
        if not d.startswith(PIA_MAGIC) or len(d) < 0x20:
            return None
        if not d[4] & 0x80:
            return d[0x10:]  # not encrypted
        nonce = self.nonce(pk)
        if nonce is None:
            return None
        body = d[0x20:len(d) - d[0x0f]]
        out = bytearray()
        for i in range(0, len(body), 16):
            ks = self.ecb.update(nonce + struct.pack('>I', 2 + i // 16))
            out += bytes(a ^ b for a, b in zip(body[i:i + 16], ks))
        return bytes(out)


def _pia_messages(pt, out):
    """A decrypted Pia body's messages: a field mask, then the fields it names (the rest as in the one before)"""
    i, prev = 0, {'flags': 0, 'size': 0, 'ptype': 0, 'port': 0, 'dst': 0}
    while i < len(pt):
        mask = pt[i]
        i += 1
        if mask == 0xff:
            break
        m = dict(prev)
        if mask & 1:
            m['flags'] = pt[i]; i += 1
        if mask & 2:
            m['size'] = struct.unpack('>H', pt[i:i + 2])[0]; i += 2
        if mask & 4:
            m['ptype'] = pt[i]; m['port'] = int.from_bytes(pt[i + 1:i + 4], 'big'); i += 4
        if mask & 8:
            m['dst'] = struct.unpack('>Q', pt[i:i + 8])[0]; i += 8
        m['payload'] = pt[i:i + m['size']]
        i = (i + m['size'] + 3) & ~3
        out.append(m)
        prev = m


def pia_messages(pt):
    out = []
    try:
        _pia_messages(pt, out)
    except (struct.error, IndexError):
        pass  # trailing padding or a truncated tail: keep the messages parsed so far
    return out


PIA_TYPES = {0x08: 'leave', 0x14: 'connect', 0x18: 'session', 0x1c: 'clock', 0x24: 'mesh', 0x58: 'keepalive',
             0x68: 'game'}


def read_switch_all(path):
    """Every key, advertise-data session id and player/MAC table in a capture that holds several sessions"""
    text = open(path, encoding='utf-8', errors='replace').read()
    keys = list(dict.fromkeys(bytes.fromhex(k) for k in re.findall(r'# AES key ([0-9a-f]{32}) ', text)))
    sessions = list(dict.fromkeys(bytes.fromhex(a.replace(' ', ''))
                                  for a in re.findall(r'# advertise data[^\n]*\n#\s+0000  ((?:[0-9a-f]{2} ){4})', text)))
    tables, cur = [], {}
    for line in text.split('\n'):
        m = re.match(r'# player \d+: (\S+) mac (\S+)', line)
        if m:
            cur[m[1]] = bytes.fromhex(m[2].replace(':', ''))
        elif cur:
            if cur not in tables:
                tables.append(cur)
            cur = {}
    if cur and cur not in tables:
        tables.append(cur)
    return keys, sessions, tables, read_switch(path)[3]


def switch_messages(path):
    keys, sessions, tables, packets = read_switch_all(path)
    if not keys or not sessions:
        sys.exit('no Pia key or advertise data in %s (an older capture?)' % path)
    combos = [Pia(k, t, s) for k in keys for s in sessions for t in tables]
    last = None
    for pk in packets:
        pia = None
        for c in ([last] if last else []) + combos:
            if c.verify(pk):
                pia = last = c
                break
        if pia is None:
            continue
        pt = pia.decrypt(pk)
        if pt is None:
            continue
        for m in pia_messages(pt):
            yield pk, m


def cmd_switch(path, everything):
    seen = set()
    for pk, m in switch_messages(path):
        p = m['payload']
        name = PIA_TYPES.get(m['ptype'], '?')
        if m['ptype'] == 0x68:
            prefix, body = unscramble(p)
            line = '%4d %s %s' % (len(p), prefix.hex(), body[:64].hex())
        else:
            if not everything and m['ptype'] == 0x58:
                continue
            line = '%4d %s' % (len(p), p[:96].hex())
        k = (pk['src'], m['ptype'], len(p), bytes(p[:2]))
        if not everything and k in seen:
            continue
        seen.add(k)
        print(pk['t'], pk['dir'], pk['src'], '->', pk['dst'], 'type %02x %-9s flags %02x' % (m['ptype'], name, m['flags']),
              line)


def cmd_compare(sw_path, pc_path):
    sw = [bytes(m['payload']) for _, m in switch_messages(sw_path) if m['ptype'] == 0x68]
    pc = [g for kind, x in read_pc(pc_path) if kind == 'packet' for g in [pc_game_message(bytes(x['data']))] if g]
    print('game messages: Switch %d (%d different), PC %d (%d different)' % (len(sw), len(set(sw)), len(pc), len(set(pc))))
    print('the same bytes on both: %d different messages' % len(set(sw) & set(pc)))
    kinds = lambda L: collections.Counter(unscramble(g)[1][1:3].hex() for g in L)
    print('kinds (body bytes 1-2): Switch', kinds(sw).most_common(8), '\n                       PC    ', kinds(pc).most_common(8))
    s, p = collections.Counter(map(len, sw)), collections.Counter(map(len, pc))
    print('sizes only on PC    ', [(k, v) for k, v in p.most_common(40) if k not in s][:12])
    print('sizes only on Switch', [(k, v) for k, v in s.most_common(40) if k not in p][:12])


def cmd_verify(path):
    key, macs, session, packets = read_switch(path)
    if not key or session is None:
        sys.exit('no Pia key or advertise data in %s (an older capture?)' % path)
    pia = Pia(key, macs, session)
    c = collections.Counter(pia.verify(pk) for pk in packets)
    print('tags right: %d, wrong: %d, not checked (not Pia, not encrypted, unknown sender): %d' % (c[True], c[False], c[None]))


def main(a):
    if len(a) >= 2 and a[0] == 'pc':
        cmd_pc(a[1], '--all' in a)
    elif len(a) >= 2 and a[0] == 'switch':
        cmd_switch(a[1], '--all' in a)
    elif len(a) >= 2 and a[0] == 'verify':
        cmd_verify(a[1])
    elif len(a) >= 3 and a[0] == 'compare':
        cmd_compare(a[1], a[2])
    else:
        print(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
