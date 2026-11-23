// rise-pc-netlog: logs what Monster Hunter Rise on PC sends and receives through Steam's networking, before Steam
// encrypts it, to rise_netlog.txt next to the game. For comparing with the Switch version's Local Play (the
// mhrise-recomp port's Debug → Capture Local Play): the same text format, a line per packet and its bytes in hex.
//
// How it gets in: the game loads dinput8.dll at start; this one is it. It loads the real one from System32 and passes
// its six functions through (exports.def), so input works as before.
//
// What it watches: every Steam call goes through the Steam client library's CreateInterface (steamclient64.dll, or a
// library in its place). LoadLibraryExW is hooked to catch that library the moment it's loaded, and its
// CreateInterface is hooked to wrap the ISteamClient the game gets. ISteamClient hands out the networking interfaces
// (GetISteamNetworking, GetISteamGenericInterface), and their send and receive functions get a wrapper that logs the
// data and calls the original. ISteamMatchmaking's lobby calls are logged as well (creating, searching, joining, the
// lobby's data and chat), since that's how players find each other online. Nothing is changed: no app IDs, ownership
// or tickets, only networking and lobbies, read-only.
// Which interfaces the game asks for is logged too, so we learn which of Steam's networking APIs Rise uses.
//
// Hooks with MinHook (Tsuda Kageyu, BSD 2-clause). The interface layouts are those of Valve's public Steamworks SDK
// headers (ISteamClient 017+, ISteamNetworking 006, ISteamNetworkingMessages 002, ISteamNetworkingSockets 012, ISteamMatchmaking 009).

#include <windows.h>
#include <objbase.h>
#include <share.h>

#include <MinHook.h>

#include "bridge.h"

#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <map>
#include <set>
#include <string>

namespace {

// ---- the log ----------------------------------------------------------------------------------------------------------

std::mutex g_log_m;
FILE* g_log = nullptr;

void log_open(HMODULE self) {
    char path[MAX_PATH];
    // Next to the game's exe, not this DLL (the same folder anyway)
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (char* slash = strrchr(path, '\\')) slash[1] = 0;
    strcat_s(path, "rise_netlog.txt");
    g_log = _fsopen(path, "w", _SH_DENYWR);
    (void)self;
}

void log_line(const char* fmt, ...) {
    std::lock_guard lock(g_log_m);
    if (!g_log) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(g_log, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list a;
    va_start(a, fmt);
    vfprintf(g_log, fmt, a);
    va_end(a);
    fflush(g_log);
}

// A packet: the header line (time, direction, peer, channel, size), then its bytes in hex with ASCII beside them
void log_packet(char dir, const char* api, uint64_t peer, int channel, const void* data, size_t size) {
    std::lock_guard lock(g_log_m);
    if (!g_log) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(g_log, "\n%02d:%02d:%02d.%03d %c %s peer %llu channel %d  %zu bytes\n", t.wHour, t.wMinute, t.wSecond,
            t.wMilliseconds, dir, api, static_cast<unsigned long long>(peer), channel, size);
    const auto* b = static_cast<const uint8_t*>(data);
    for (size_t row = 0; b && row < size; row += 16) {
        char line[96];
        int n = snprintf(line, sizeof line, "  %04zx ", row);
        for (size_t k = 0; k < 16; k++)
            n += row + k < size ? snprintf(line + n, sizeof line - n, " %02x", b[row + k])
                                : snprintf(line + n, sizeof line - n, "   ");
        n += snprintf(line + n, sizeof line - n, "  ");
        for (size_t k = 0; k < 16 && row + k < size; k++) line[n++] = b[row + k] >= 32 && b[row + k] < 127 ? b[row + k] : '.';
        line[n] = 0;
        fprintf(g_log, "%s\n", line);
    }
    fflush(g_log);
}

// ---- patching a vtable entry ------------------------------------------------------------------------------------------

// Puts fn in slot i of obj's vtable and returns what was there (nullptr if it already was fn)
void* swap_slot(void* obj, int i, void* fn) {
    void** vt = *static_cast<void***>(obj);
    if (vt[i] == fn) return nullptr;
    DWORD old;
    if (!VirtualProtect(&vt[i], sizeof(void*), PAGE_READWRITE, &old)) return nullptr;
    void* was = vt[i];
    vt[i] = fn;
    VirtualProtect(&vt[i], sizeof(void*), old, &old);
    return was;
}

// ---- ISteamNetworking (old P2P): SendP2PPacket 0, ReadP2PPacket 2 -------------------------------------------------------

using SendP2P = bool(__fastcall*)(void*, uint64_t, const void*, uint32_t, int, int);
using ReadP2P = bool(__fastcall*)(void*, void*, uint32_t, uint32_t*, uint64_t*, int);
SendP2P g_send_p2p = nullptr;
ReadP2P g_read_p2p = nullptr;

bool __fastcall send_p2p(void* self, uint64_t to, const void* data, uint32_t size, int type, int channel) {
    log_packet('>', "SendP2PPacket", to, channel, data, size);
    return g_send_p2p(self, to, data, size, type, channel);
}

bool __fastcall read_p2p(void* self, void* dest, uint32_t cap, uint32_t* size, uint64_t* from, int channel) {
    const bool ok = g_read_p2p(self, dest, cap, size, from, channel);
    if (ok && size) log_packet('<', "ReadP2PPacket", from ? *from : 0, channel, dest, *size);
    return ok;
}

void wrap_networking(void* n) {
    if (!n) return;
    if (void* was = swap_slot(n, 0, reinterpret_cast<void*>(&send_p2p))) g_send_p2p = reinterpret_cast<SendP2P>(was);
    if (void* was = swap_slot(n, 2, reinterpret_cast<void*>(&read_p2p))) g_read_p2p = reinterpret_cast<ReadP2P>(was);
}

// ---- ISteamNetworkingMessages: SendMessageToUser 0, ReceiveMessagesOnChannel 1 ------------------------------------------

// SteamNetworkingMessage_t, the fields read here
struct Message {
    void* data;
    int size;
    uint32_t conn;
    struct {
        int type, size;
        uint64_t steam_id;  // (a union; the Steam ID when type is 16)
        uint8_t rest[120];
    } peer;
    int64_t conn_user_data, time_received, number;
    void* free_data;
    void* release;
    int channel;
};

using SendToUser = int(__fastcall*)(void*, const void*, const void*, uint32_t, int, int);
using ReceiveOnChannel = int(__fastcall*)(void*, int, Message**, int);
SendToUser g_send_user = nullptr;
ReceiveOnChannel g_receive_channel = nullptr;

// SteamNetworkingIdentity: type, size, then the Steam ID
uint64_t identity_id(const void* identity) {
    return identity ? *reinterpret_cast<const uint64_t*>(static_cast<const uint8_t*>(identity) + 8) : 0;
}

int __fastcall send_user(void* self, const void* to, const void* data, uint32_t size, int flags, int channel) {
    if (bridge::fake_user(identity_id(to))) {  // the Switch host's stand-in: goes to the daemon, not to Steam
        log_packet('>', "SendMessageToUser(bridge)", identity_id(to), channel, data, size);
        bridge::send_to_host(data, size, channel);
        return 1;  // k_EResultOK
    }
    log_packet('>', "SendMessageToUser", identity_id(to), channel, data, size);
    return g_send_user(self, to, data, size, flags, channel);
}

int __fastcall receive_channel(void* self, int channel, Message** out, int max) {
    int n = g_receive_channel(self, channel, out, max);
    if (bridge::on() && out && n < max) n += bridge::receive(channel, reinterpret_cast<void**>(out + n), max - n);
    for (int k = 0; k < n && out; k++)
        if (out[k]) log_packet('<', "ReceiveMessagesOnChannel", out[k]->peer.steam_id, out[k]->channel, out[k]->data, out[k]->size);
    return n;
}

using SessionFn = bool(__fastcall*)(void*, const void*);
SessionFn g_accept_session = nullptr, g_close_session = nullptr;

bool __fastcall accept_session(void* self, const void* who) {
    if (bridge::fake_user(identity_id(who))) return true;
    return g_accept_session(self, who);
}

bool __fastcall close_session(void* self, const void* who) {
    if (bridge::fake_user(identity_id(who))) return true;
    return g_close_session(self, who);
}

void wrap_messages(void* m) {
    if (!m) return;
    if (bridge::on()) {
        if (void* was = swap_slot(m, 2, reinterpret_cast<void*>(&accept_session))) g_accept_session = reinterpret_cast<SessionFn>(was);
        if (void* was = swap_slot(m, 3, reinterpret_cast<void*>(&close_session))) g_close_session = reinterpret_cast<SessionFn>(was);
    }
    if (void* was = swap_slot(m, 0, reinterpret_cast<void*>(&send_user))) g_send_user = reinterpret_cast<SendToUser>(was);
    if (void* was = swap_slot(m, 1, reinterpret_cast<void*>(&receive_channel)))
        g_receive_channel = reinterpret_cast<ReceiveOnChannel>(was);
}

// ---- ISteamNetworkingSockets: SendMessageToConnection 11, ReceiveMessagesOnConnection 14 --------------------------------

using SendToConnection = int(__fastcall*)(void*, uint32_t, const void*, uint32_t, int, int64_t*);
using ReceiveOnConnection = int(__fastcall*)(void*, uint32_t, Message**, int);
SendToConnection g_send_conn = nullptr;
ReceiveOnConnection g_receive_conn = nullptr;

int __fastcall send_conn(void* self, uint32_t conn, const void* data, uint32_t size, int flags, int64_t* number) {
    log_packet('>', "SendMessageToConnection", conn, -1, data, size);
    return g_send_conn(self, conn, data, size, flags, number);
}

int __fastcall receive_conn(void* self, uint32_t conn, Message** out, int max) {
    const int n = g_receive_conn(self, conn, out, max);
    for (int k = 0; k < n && out; k++)
        if (out[k]) log_packet('<', "ReceiveMessagesOnConnection", out[k]->peer.steam_id, out[k]->channel, out[k]->data, out[k]->size);
    return n;
}

void wrap_sockets(void* s) {
    if (!s) return;
    if (void* was = swap_slot(s, 11, reinterpret_cast<void*>(&send_conn))) g_send_conn = reinterpret_cast<SendToConnection>(was);
    if (void* was = swap_slot(s, 14, reinterpret_cast<void*>(&receive_conn)))
        g_receive_conn = reinterpret_cast<ReceiveOnConnection>(was);
}

// ---- ISteamMatchmaking 009: lobbies (how players find and join each other) ----------------------------------------------
// Slots: RequestLobbyList 4, string filter 5, numerical filter 6, CreateLobby 13, JoinLobby 14, LeaveLobby 15,
// GetLobbyData 19, SetLobbyData 20, GetLobbyMemberData 24, SetLobbyMemberData 25, SendLobbyChatMsg 26,
// GetLobbyChatEntry 27. A CSteamID goes by value as its 64 bits. Reads are logged when the value differs from the last
// one read for that lobby (and member) and key, since the game polls them.

using RequestLobbyList = uint64_t(__fastcall*)(void*);
using StringFilter = void(__fastcall*)(void*, const char*, const char*, int);
using NumericalFilter = void(__fastcall*)(void*, const char*, int, int);
using CreateLobby = uint64_t(__fastcall*)(void*, int, int);
using JoinLobby = uint64_t(__fastcall*)(void*, uint64_t);
using LeaveLobby = void(__fastcall*)(void*, uint64_t);
using GetLobbyData = const char*(__fastcall*)(void*, uint64_t, const char*);
using SetLobbyData = bool(__fastcall*)(void*, uint64_t, const char*, const char*);
using GetMemberData = const char*(__fastcall*)(void*, uint64_t, uint64_t, const char*);
using SetMemberData = void(__fastcall*)(void*, uint64_t, const char*, const char*);
using SendChat = bool(__fastcall*)(void*, uint64_t, const void*, int);
using GetChatEntry = int(__fastcall*)(void*, uint64_t, int, uint64_t*, void*, int, int*);
RequestLobbyList g_request_list = nullptr;
StringFilter g_string_filter = nullptr;
NumericalFilter g_numerical_filter = nullptr;
CreateLobby g_create_lobby = nullptr;
JoinLobby g_join_lobby = nullptr;
LeaveLobby g_leave_lobby = nullptr;
GetLobbyData g_get_lobby_data = nullptr;
SetLobbyData g_set_lobby_data = nullptr;
GetMemberData g_get_member_data = nullptr;
SetMemberData g_set_member_data = nullptr;
SendChat g_send_chat = nullptr;
GetChatEntry g_get_chat_entry = nullptr;

std::mutex g_reads_m;
std::map<std::string, std::string> g_reads;  // "lobby member key" -> the value last logged

void log_read(const char* what, uint64_t lobby, uint64_t member, const char* key, const char* value) {
    char k[256];
    snprintf(k, sizeof k, "%llu %llu %s", static_cast<unsigned long long>(lobby), static_cast<unsigned long long>(member),
             key ? key : "");
    const std::string v = value ? value : "(null)";
    {
        std::lock_guard lock(g_reads_m);
        auto it = g_reads.find(k);
        if (it != g_reads.end() && it->second == v) return;
        g_reads[k] = v;
    }
    if (member) log_line("%s lobby %llu member %llu \"%s\" = \"%s\"\n", what, static_cast<unsigned long long>(lobby),
                         static_cast<unsigned long long>(member), key ? key : "", v.c_str());
    else log_line("%s lobby %llu \"%s\" = \"%s\"\n", what, static_cast<unsigned long long>(lobby), key ? key : "", v.c_str());
}

uint64_t __fastcall request_list(void* self) {
    log_line("RequestLobbyList\n");
    if (bridge::on()) return bridge::request_list();
    return g_request_list(self);
}

void __fastcall string_filter(void* self, const char* key, const char* value, int cmp) {
    log_line("lobby filter \"%s\" %d \"%s\"\n", key ? key : "", cmp, value ? value : "");
    g_string_filter(self, key, value, cmp);
}

void __fastcall numerical_filter(void* self, const char* key, int value, int cmp) {
    log_line("lobby filter \"%s\" %d %d\n", key ? key : "", cmp, value);
    g_numerical_filter(self, key, value, cmp);
}

uint64_t __fastcall create_lobby(void* self, int type, int max) {
    log_line("CreateLobby type %d, up to %d\n", type, max);
    return g_create_lobby(self, type, max);
}

uint64_t __fastcall join_lobby(void* self, uint64_t lobby) {
    log_line("JoinLobby %llu\n", static_cast<unsigned long long>(lobby));
    if (bridge::fake_lobby(lobby)) return bridge::join(lobby);
    return g_join_lobby(self, lobby);
}

void __fastcall leave_lobby(void* self, uint64_t lobby) {
    log_line("LeaveLobby %llu\n", static_cast<unsigned long long>(lobby));
    if (bridge::fake_lobby(lobby)) return bridge::leave(lobby);
    g_leave_lobby(self, lobby);
}

const char* __fastcall get_lobby_data(void* self, uint64_t lobby, const char* key) {
    const char* v = bridge::fake_lobby(lobby) ? bridge::lobby_data(lobby, key) : g_get_lobby_data(self, lobby, key);
    log_read("GetLobbyData", lobby, 0, key, v);
    return v;
}

bool __fastcall set_lobby_data(void* self, uint64_t lobby, const char* key, const char* value) {
    log_line("SetLobbyData lobby %llu \"%s\" = \"%s\"\n", static_cast<unsigned long long>(lobby), key ? key : "",
             value ? value : "");
    if (bridge::fake_lobby(lobby)) return true;
    return g_set_lobby_data(self, lobby, key, value);
}

const char* __fastcall get_member_data(void* self, uint64_t lobby, uint64_t member, const char* key) {
    const char* v = bridge::fake_lobby(lobby) ? bridge::member_data(lobby, member, key) : g_get_member_data(self, lobby, member, key);
    log_read("GetLobbyMemberData", lobby, member, key, v);
    return v;
}

void __fastcall set_member_data(void* self, uint64_t lobby, const char* key, const char* value) {
    log_line("SetLobbyMemberData lobby %llu \"%s\" = \"%s\"\n", static_cast<unsigned long long>(lobby), key ? key : "",
             value ? value : "");
    if (bridge::fake_lobby(lobby)) return;
    g_set_member_data(self, lobby, key, value);
}

bool __fastcall send_chat(void* self, uint64_t lobby, const void* data, int size) {
    log_packet('>', "SendLobbyChatMsg", lobby, -1, data, size > 0 ? static_cast<size_t>(size) : 0);
    if (bridge::fake_lobby(lobby)) return true;
    return g_send_chat(self, lobby, data, size);
}

int __fastcall get_chat_entry(void* self, uint64_t lobby, int id, uint64_t* user, void* data, int cap, int* type) {
    if (bridge::fake_lobby(lobby)) return 0;
    const int n = g_get_chat_entry(self, lobby, id, user, data, cap, type);
    if (n > 0) log_packet('<', "GetLobbyChatEntry", user ? *user : 0, type ? *type : -1, data, static_cast<size_t>(n));
    return n;
}

// Puts hook in slot i and keeps what was there in original
template <typename F>
void wrap_slot(void* obj, int i, F hook, F& original) {
    if (void* was = swap_slot(obj, i, reinterpret_cast<void*>(hook))) original = reinterpret_cast<F>(was);
}

// ---- bridge mode: the rest of the lobby calls the game makes on a lobby that isn't Steam's -------------------------------
// ISteamMatchmaking: GetLobbyByIndex 12, GetNumLobbyMembers 17, GetLobbyMemberByIndex 18, GetLobbyMemberLimit 32,
// GetLobbyOwner 35. ISteamUser: GetSteamID 2.
void* g_user = nullptr;
uint64_t my_id() {
    if (!g_user) return 0;
    // A CSteamID is returned through a hidden pointer (it has constructors, so it isn't returned in RAX on Windows x64)
    auto fn = reinterpret_cast<uint64_t*(__fastcall*)(void*, uint64_t*)>((*static_cast<void***>(g_user))[2]);
    uint64_t id = 0;
    fn(g_user, &id);
    return id;
}

// The ones that return a CSteamID (GetLobbyByIndex, GetLobbyMemberByIndex, GetLobbyOwner) take a hidden result pointer
// as the 2nd argument and give it back in RAX; the other arguments move up one place.
using ByIndex = uint64_t*(__fastcall*)(void*, uint64_t*, int);
using NumMembers = int(__fastcall*)(void*, uint64_t);
using MemberByIndex = uint64_t*(__fastcall*)(void*, uint64_t*, uint64_t, int);
using LobbyOwner = uint64_t*(__fastcall*)(void*, uint64_t*, uint64_t);
ByIndex g_by_index = nullptr;
NumMembers g_num_members = nullptr, g_member_limit = nullptr;
MemberByIndex g_member_by_index = nullptr;
LobbyOwner g_lobby_owner = nullptr;

uint64_t* __fastcall by_index(void* self, uint64_t* ret, int i) {
    if (bridge::on()) {
        *ret = bridge::lobby_by_index(i);
        return ret;
    }
    return g_by_index(self, ret, i);
}
int __fastcall num_members(void* self, uint64_t lobby) {
    return bridge::fake_lobby(lobby) ? bridge::member_count(lobby) : g_num_members(self, lobby);
}
int __fastcall member_limit(void* self, uint64_t lobby) {
    return bridge::fake_lobby(lobby) ? 4 : g_member_limit(self, lobby);
}
uint64_t* __fastcall member_by_index(void* self, uint64_t* ret, uint64_t lobby, int i) {
    if (!bridge::fake_lobby(lobby)) return g_member_by_index(self, ret, lobby, i);
    *ret = bridge::member_by_index(lobby, i, my_id());
    return ret;
}
uint64_t* __fastcall lobby_owner(void* self, uint64_t* ret, uint64_t lobby) {
    if (!bridge::fake_lobby(lobby)) return g_lobby_owner(self, ret, lobby);
    *ret = bridge::owner(lobby);
    return ret;
}

// ISteamUtils: IsAPICallCompleted 11, GetAPICallFailureReason 12, GetAPICallResult 13
using IsCompleted = bool(__fastcall*)(void*, uint64_t, bool*);
using FailureReason = int(__fastcall*)(void*, uint64_t);
using GetResult = bool(__fastcall*)(void*, uint64_t, void*, int, int, bool*);
IsCompleted g_is_completed = nullptr;
FailureReason g_failure_reason = nullptr;
GetResult g_get_result = nullptr;

bool __fastcall is_completed(void* self, uint64_t h, bool* failed) {
    if (bridge::is_completed(h)) {
        if (failed) *failed = false;
        return true;
    }
    return g_is_completed(self, h, failed);
}
int __fastcall failure_reason(void* self, uint64_t h) {
    return bridge::is_completed(h) ? -1 : g_failure_reason(self, h);  // -1: none
}
bool __fastcall get_result(void* self, uint64_t h, void* out, int cap, int expected, bool* failed) {
    if (bridge::get_result(h, out, cap, expected, failed)) return true;
    return g_get_result(self, h, out, cap, expected, failed);
}

void wrap_utils(void* u) {
    if (!u || !bridge::on()) return;
    wrap_slot(u, 11, &is_completed, g_is_completed);
    wrap_slot(u, 12, &failure_reason, g_failure_reason);
    wrap_slot(u, 13, &get_result, g_get_result);
    log_line("bridge: ISteamUtils call results wrapped\n");
}

void wrap_matchmaking(void* m) {
    if (!m) return;
    wrap_slot(m, 4, &request_list, g_request_list);
    wrap_slot(m, 5, &string_filter, g_string_filter);
    wrap_slot(m, 6, &numerical_filter, g_numerical_filter);
    wrap_slot(m, 13, &create_lobby, g_create_lobby);
    wrap_slot(m, 14, &join_lobby, g_join_lobby);
    wrap_slot(m, 15, &leave_lobby, g_leave_lobby);
    wrap_slot(m, 19, &get_lobby_data, g_get_lobby_data);
    wrap_slot(m, 20, &set_lobby_data, g_set_lobby_data);
    wrap_slot(m, 24, &get_member_data, g_get_member_data);
    wrap_slot(m, 25, &set_member_data, g_set_member_data);
    wrap_slot(m, 26, &send_chat, g_send_chat);
    wrap_slot(m, 27, &get_chat_entry, g_get_chat_entry);
    if (bridge::on()) {
        wrap_slot(m, 12, &by_index, g_by_index);
        wrap_slot(m, 17, &num_members, g_num_members);
        wrap_slot(m, 18, &member_by_index, g_member_by_index);
        wrap_slot(m, 32, &member_limit, g_member_limit);
        wrap_slot(m, 35, &lobby_owner, g_lobby_owner);
    }
}

// ---- ISteamUser 021: the Steam auth tickets players swap in the lobby ---------------------------------------------------
// Slots: GetAuthSessionTicket 13, BeginAuthSession 14, EndAuthSession 15. Each player's lobby record carries a ticket
// (234 bytes, for app 480), and the others check it with BeginAuthSession; logged to see what the game does when a
// check fails. In bridge mode the check of the Switch host's made-up ID passes without asking Steam.

using GetTicket = uint32_t(__fastcall*)(void*, void*, int, uint32_t*);
using BeginAuth = int(__fastcall*)(void*, const void*, int, uint64_t);
using EndAuth = void(__fastcall*)(void*, uint64_t);
GetTicket g_get_ticket = nullptr;
BeginAuth g_begin_auth = nullptr;
EndAuth g_end_auth = nullptr;

uint32_t __fastcall get_ticket(void* self, void* out, int cap, uint32_t* size) {
    const uint32_t h = g_get_ticket(self, out, cap, size);
    log_line("GetAuthSessionTicket -> handle %u, %u bytes\n", h, size ? *size : 0);
    return h;
}

int __fastcall begin_auth(void* self, const void* ticket, int size, uint64_t id) {
    if (bridge::fake_user(id)) {
        bridge::auth_ok(id);
        return 0;  // k_EBeginAuthSessionResultOK
    }
    const int r = g_begin_auth(self, ticket, size, id);
    log_line("BeginAuthSession %llu, %d bytes -> %d\n", static_cast<unsigned long long>(id), size, r);
    return r;
}

void __fastcall end_auth(void* self, uint64_t id) {
    log_line("EndAuthSession %llu\n", static_cast<unsigned long long>(id));
    if (!bridge::fake_user(id)) g_end_auth(self, id);
}

void wrap_user(void* u) {
    if (!u) return;
    wrap_slot(u, 13, &get_ticket, g_get_ticket);
    wrap_slot(u, 14, &begin_auth, g_begin_auth);
    wrap_slot(u, 15, &end_auth, g_end_auth);
}

// ---- ISteamClient: GetISteamGenericInterface 12, GetISteamNetworking 16 -------------------------------------------------

using GetGeneric = void*(__fastcall*)(void*, int, int, const char*);
using GetNetworking = void*(__fastcall*)(void*, int, int, const char*);
GetGeneric g_get_generic = nullptr;
GetNetworking g_get_networking = nullptr;

std::mutex g_seen_m;
std::set<std::string> g_seen;

void note_interface(const char* how, const char* version) {
    std::lock_guard lock(g_seen_m);
    if (version && g_seen.insert(version).second) log_line("interface %s (%s)\n", version, how);
}

void wrap_by_name(const char* version, void* itf) {
    if (!version || !itf) return;
    if (!strncmp(version, "SteamMatchMaking0", 17)) wrap_matchmaking(itf);
    else if (!strncmp(version, "SteamUtils0", 11)) wrap_utils(itf);
    else if (!strncmp(version, "SteamUser0", 10)) {
        g_user = itf;
        wrap_user(itf);
    }
    else if (!strncmp(version, "SteamNetworkingMessages", 23)) wrap_messages(itf);
    else if (!strncmp(version, "SteamNetworkingSockets", 22)) wrap_sockets(itf);
    else if (!strncmp(version, "SteamNetworking", 15)) wrap_networking(itf);
}

void* __fastcall get_generic(void* self, int user, int pipe, const char* version) {
    void* itf = g_get_generic(self, user, pipe, version);
    note_interface("GetISteamGenericInterface", version);
    wrap_by_name(version, itf);
    return itf;
}

void* __fastcall get_networking(void* self, int user, int pipe, const char* version) {
    void* itf = g_get_networking(self, user, pipe, version);
    note_interface("GetISteamNetworking", version);
    wrap_by_name(version, itf);
    return itf;
}

void wrap_client(void* client) {
    if (!client) return;
    if (void* was = swap_slot(client, 12, reinterpret_cast<void*>(&get_generic))) g_get_generic = reinterpret_cast<GetGeneric>(was);
    if (void* was = swap_slot(client, 16, reinterpret_cast<void*>(&get_networking)))
        g_get_networking = reinterpret_cast<GetNetworking>(was);
}

// ---- the Steam client library -----------------------------------------------------------------------------------------

using CreateInterfaceFn = void*(__cdecl*)(const char*, int*);
CreateInterfaceFn g_create_interface = nullptr;

void* __cdecl create_interface(const char* version, int* rc) {
    void* itf = g_create_interface(version, rc);
    note_interface("CreateInterface", version);
    if (itf && version && !strncmp(version, "SteamClient", 11)) wrap_client(itf);
    else wrap_by_name(version, itf);
    return itf;
}

struct CallbackMsg {
    int user;
    int id;
    uint8_t* param;
    int size;
};
using BGetCallback = bool(__cdecl*)(int, CallbackMsg*);
using FreeLastCallback = bool(__cdecl*)(int);
BGetCallback g_bget_callback = nullptr;
FreeLastCallback g_free_last_callback = nullptr;
int g_last_user = 1;
bool g_fake_callback = false;

bool __cdecl bget_callback(int pipe, CallbackMsg* msg) {
    static bool first = true;
    if (first) {
        first = false;
        log_line("bridge: the game polls Steam_BGetCallback\n");
    }
    if (bridge::on() && msg) {
        int id, size;
        const uint8_t* data;
        if (bridge::pop_callback(&id, &data, &size)) {
            msg->user = g_last_user;
            msg->id = id;
            msg->param = const_cast<uint8_t*>(data);
            msg->size = size;
            g_fake_callback = true;
            return true;
        }
    }
    g_fake_callback = false;
    const bool ok = g_bget_callback(pipe, msg);
    if (ok && msg) g_last_user = msg->user;
    return ok;
}

bool __cdecl free_last_callback(int pipe) {
    if (g_fake_callback) {
        g_fake_callback = false;
        bridge::free_callback();
        return true;
    }
    return g_free_last_callback(pipe);
}

// The game polls Steam_BGetCallback itself (manual dispatch), so it also reads the call results itself, with
// Steam_GetAPICallResult (steamclient / what stands in for it) or its steam_api wrapper
// SteamAPI_ManualDispatch_GetAPICallResult, not through ISteamUtils. Both take (pipe, call, buffer, size, expected callback, failed*).
using ManualGetResult = bool(__cdecl*)(int, uint64_t, void*, int, int, bool*);
ManualGetResult g_client_get_result = nullptr;
ManualGetResult g_flat_get_result = nullptr;

bool manual_result(const char* who, int pipe, uint64_t h, void* out, int cap, int expected, bool* failed) {
    static bool first = true;
    if (first) {
        first = false;
        log_line("bridge: the game reads call results with %s\n", who);
    }
    return bridge::on() && bridge::get_result(h, out, cap, expected, failed);
}
bool __cdecl client_get_result(int pipe, uint64_t h, void* out, int cap, int expected, bool* failed) {
    if (manual_result("Steam_GetAPICallResult", pipe, h, out, cap, expected, failed)) return true;
    return g_client_get_result(pipe, h, out, cap, expected, failed);
}
bool __cdecl flat_get_result(int pipe, uint64_t h, void* out, int cap, int expected, bool* failed) {
    if (manual_result("SteamAPI_ManualDispatch_GetAPICallResult", pipe, h, out, cap, expected, failed)) return true;
    return g_flat_get_result(pipe, h, out, cap, expected, failed);
}

std::atomic<bool> g_hooked_flat{false};
// steam_api64.dll (or what stands in for it): the flat manual-dispatch wrapper
void check_flat(HMODULE m) {
    if (!m || g_hooked_flat || !bridge::on()) return;
    auto* f = reinterpret_cast<void*>(GetProcAddress(m, "SteamAPI_ManualDispatch_GetAPICallResult"));
    if (!f || g_hooked_flat.exchange(true)) return;
    char name[MAX_PATH] = "?";
    GetModuleFileNameA(m, name, MAX_PATH);
    if (MH_CreateHook(f, reinterpret_cast<void*>(&flat_get_result), reinterpret_cast<void**>(&g_flat_get_result)) == MH_OK &&
        MH_EnableHook(f) == MH_OK)
        log_line("bridge: hooked SteamAPI_ManualDispatch_GetAPICallResult in %s\n", name);
    else
        log_line("bridge: couldn't hook SteamAPI_ManualDispatch_GetAPICallResult in %s\n", name);
}

std::atomic<bool> g_hooked_client{false};

// A Steam client library: it exports CreateInterface and Steam_CreateSteamPipe (only steamclient64.dll and what stands
// in for it do)
void check_module(HMODULE m) {
    if (!m || g_hooked_client) return;
    auto* ci = reinterpret_cast<void*>(GetProcAddress(m, "CreateInterface"));
    if (!ci || !GetProcAddress(m, "Steam_CreateSteamPipe")) return;
    if (g_hooked_client.exchange(true)) return;
    char name[MAX_PATH] = "?";
    GetModuleFileNameA(m, name, MAX_PATH);
    if (MH_CreateHook(ci, reinterpret_cast<void*>(&create_interface), reinterpret_cast<void**>(&g_create_interface)) == MH_OK &&
        MH_EnableHook(ci) == MH_OK)
        log_line("Steam client library: %s\n", name);
    else
        log_line("couldn't hook CreateInterface in %s\n", name);
    if (bridge::on()) {
        auto* bg = reinterpret_cast<void*>(GetProcAddress(m, "Steam_BGetCallback"));
        auto* fl = reinterpret_cast<void*>(GetProcAddress(m, "Steam_FreeLastCallback"));
        if (bg && fl && MH_CreateHook(bg, reinterpret_cast<void*>(&bget_callback), reinterpret_cast<void**>(&g_bget_callback)) == MH_OK &&
            MH_CreateHook(fl, reinterpret_cast<void*>(&free_last_callback), reinterpret_cast<void**>(&g_free_last_callback)) == MH_OK &&
            MH_EnableHook(bg) == MH_OK && MH_EnableHook(fl) == MH_OK)
            log_line("bridge: hooked Steam_BGetCallback / Steam_FreeLastCallback in %s\n", name);
        else
            log_line("bridge: couldn't hook the callback functions in %s: lobby results can't be delivered\n", name);
        auto* gr = reinterpret_cast<void*>(GetProcAddress(m, "Steam_GetAPICallResult"));
        if (gr && MH_CreateHook(gr, reinterpret_cast<void*>(&client_get_result), reinterpret_cast<void**>(&g_client_get_result)) == MH_OK &&
            MH_EnableHook(gr) == MH_OK)
            log_line("bridge: hooked Steam_GetAPICallResult in %s\n", name);
        else
            log_line("bridge: no Steam_GetAPICallResult to hook in %s\n", name);
    }
}

using LoadLibraryExWFn = HMODULE(WINAPI*)(LPCWSTR, HANDLE, DWORD);
LoadLibraryExWFn g_load_library = nullptr;

HMODULE WINAPI load_library(LPCWSTR name, HANDLE file, DWORD flags) {
    HMODULE m = g_load_library(name, file, flags);
    if (m && !(flags & (LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE | LOAD_LIBRARY_AS_IMAGE_RESOURCE)))
    {
        check_module(m);
        check_flat(m);
    }
    return m;
}

void start() {
    bridge::set_log([](const char* line) { log_line("bridge: %s\n", line); });
    bridge::set_own_id(my_id);
    if (bridge::on()) bridge::start();
    log_line("rise-pc-netlog: logging Steam networking (> sent, < received; peer is the Steam ID, or the connection)\n");
    if (MH_Initialize() != MH_OK) {
        log_line("MinHook didn't start: nothing will be logged\n");
        return;
    }
    // Every LoadLibrary* ends up in KernelBase's LoadLibraryExW
    if (HMODULE kb = GetModuleHandleW(L"kernelbase.dll")) {
        void* fn = reinterpret_cast<void*>(GetProcAddress(kb, "LoadLibraryExW"));
        if (fn && MH_CreateHook(fn, reinterpret_cast<void*>(&load_library), reinterpret_cast<void**>(&g_load_library)) == MH_OK)
            MH_EnableHook(fn);
    }
    // Already loaded before us?
    for (const wchar_t* n : {L"steamclient64.dll", L"OnlineFix64.dll"}) check_module(GetModuleHandleW(n));
    for (const wchar_t* n : {L"steam_api64.dll", L"OnlineFix64.dll"}) check_flat(GetModuleHandleW(n));
}

}  // namespace

// ---- dinput8.dll: the real one's functions, passed through ------------------------------------------------------------

namespace {
HMODULE g_real = nullptr;

FARPROC real(const char* name) {
    if (!g_real) {
        wchar_t path[MAX_PATH];
        GetSystemDirectoryW(path, MAX_PATH);
        wcscat_s(path, L"\\dinput8.dll");
        g_real = LoadLibraryW(path);
    }
    return g_real ? GetProcAddress(g_real, name) : nullptr;
}
}  // namespace

extern "C" HRESULT WINAPI proxy_DirectInput8Create(HINSTANCE inst, DWORD version, REFIID riid, LPVOID* out, LPUNKNOWN outer) {
    auto fn = reinterpret_cast<HRESULT(WINAPI*)(HINSTANCE, DWORD, REFIID, LPVOID*, LPUNKNOWN)>(real("DirectInput8Create"));
    return fn ? fn(inst, version, riid, out, outer) : E_FAIL;
}

extern "C" HRESULT WINAPI proxy_DllCanUnloadNow() {
    auto fn = reinterpret_cast<HRESULT(WINAPI*)()>(real("DllCanUnloadNow"));
    return fn ? fn() : S_FALSE;
}

extern "C" HRESULT WINAPI proxy_DllGetClassObject(REFCLSID clsid, REFIID riid, LPVOID* out) {
    auto fn = reinterpret_cast<HRESULT(WINAPI*)(REFCLSID, REFIID, LPVOID*)>(real("DllGetClassObject"));
    return fn ? fn(clsid, riid, out) : E_FAIL;
}

extern "C" HRESULT WINAPI proxy_DllRegisterServer() {
    auto fn = reinterpret_cast<HRESULT(WINAPI*)()>(real("DllRegisterServer"));
    return fn ? fn() : E_FAIL;
}

extern "C" HRESULT WINAPI proxy_DllUnregisterServer() {
    auto fn = reinterpret_cast<HRESULT(WINAPI*)()>(real("DllUnregisterServer"));
    return fn ? fn() : E_FAIL;
}

extern "C" LPCVOID WINAPI proxy_GetdfDIJoystick() {
    auto fn = reinterpret_cast<LPCVOID(WINAPI*)()>(real("GetdfDIJoystick"));
    return fn ? fn() : nullptr;
}

BOOL WINAPI DllMain(HINSTANCE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        log_open(self);
        start();
    }
    return TRUE;
}
