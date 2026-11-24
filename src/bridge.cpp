#include "bridge.h"

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace bridge {
namespace {

void (*g_log)(const char*) = nullptr;
void L(const char* fmt, ...) {
    if (!g_log) return;
    char buf[512];
    va_list a;
    va_start(a, fmt);
    vsnprintf(buf, sizeof buf, fmt, a);
    va_end(a);
    g_log(buf);
}

// IDs made up here. The lobby's looks like the ones in the log (universe 1, type lobby); the host's is an ordinary user's.
constexpr uint64_t kLobbyBase = 0x01860000B1D60000ull;  // + hub index
constexpr uint64_t kHostId = 0x0110000100000000ull | 0x4B1D0000ull;
constexpr uint64_t kQuestLobby = kLobbyBase + 32;  // the PC's quest in a Switch room (create_quest_lobby)
uint64_t (*g_own_id)() = nullptr;  // the game's own Steam ID (set by netlog)
bool g_calibrate = false;          // rise_bridge_calibrate.txt: learn the hello this game expects (see send_to_host)
uint8_t g_hello[15] = {};          // rise_hello.txt: the hello the game expects from a peer (what it sends to its own ID)
bool g_have_hello = false;

std::string game_file(const char* name) {
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (char* slash = strrchr(path, '\\')) slash[1] = 0;
    return std::string(path) + name;
}

// In calibration mode the stand-in for the Switch host has the player's own Steam ID. The game's hello to a peer is a
// fixed value for the recipient's ID, so the hello it sends to "the host" is then the one it expects to receive.
uint64_t host_id() {
    if (g_calibrate && g_own_id)
        if (uint64_t me = g_own_id()) return me;
    return kHostId;
}

// A hello: 15 bytes, [3 bytes][mask]..., whose unmasked body starts 00 01 03 02
bool is_hello(const uint8_t* p) { return (p[4] ^ p[3]) == 1 && (p[5] ^ p[3]) == 3 && (p[6] ^ p[3]) == 2; }
bool is_hello_message(const uint8_t* d, size_t n) {  // with the 6-byte header (u16 length, u32 length)
    return n == 21 && d[0] == 0 && d[1] == 15 && d[2] == 0 && d[3] == 0 && d[4] == 0 && d[5] == 15 && is_hello(d + 6);
}

constexpr int kDefaultChannel = -110265462;  // what the game's messages used in rise_netlog.txt

struct Lobby {
    std::string name;
    int players = 1;
    std::string adv_b64;
    int adv_size = 0;
};

std::mutex g_m;
bool g_on = false, g_checked = false;
SOCKET g_sock = INVALID_SOCKET;
sockaddr_in g_daemon{};
std::vector<Lobby> g_lobbies;
struct Result {
    int cb;
    std::vector<uint8_t> data;
};
std::map<uint64_t, Result> g_results;
struct Cb {
    int id;
    std::vector<uint8_t> data;
};
std::deque<Cb> g_cbs;
std::deque<std::vector<uint8_t>> g_inbox;
Cb g_current;
bool g_have_current = false;
uint64_t g_next_handle = 0xB1D6000000000001ull;
uint64_t g_list_handle = 0, g_join_handle = 0, g_join_lobby = 0;
DWORD g_list_deadline = 0;
int g_channel = kDefaultChannel;
std::map<std::string, std::string> g_strings;  // returned const char*s point in here (std::map nodes don't move)
bool g_in_room = false;                         // joined a Switch session (JOINED) and not left it
uint64_t g_quest_owner = 0;                     // who made the quest lobby: the PC itself, or the Switch host
std::map<std::string, std::string> g_quest_data;  // what the game set on the quest lobby

template <typename T>
std::vector<uint8_t> bytes_of(const T& v) {
    const auto* p = reinterpret_cast<const uint8_t*>(&v);
    return std::vector<uint8_t>(p, p + sizeof v);
}

// A call result is announced with SteamAPICallCompleted_t (703), then read with GetAPICallResult
void complete(uint64_t handle, int cb, std::vector<uint8_t> data) {  // g_m held
#pragma pack(push, 4)
    struct Completed {
        uint64_t handle;
        int cb;
        uint32_t size;
    } c{handle, cb, static_cast<uint32_t>(data.size())};
#pragma pack(pop)
    g_results[handle] = {cb, std::move(data)};
    g_cbs.push_back({703, bytes_of(c)});
}

void lobby_entered(uint64_t lobby, uint32_t response) {  // g_m held
    std::vector<uint8_t> enter(20, 0);  // LobbyEnter_t: lobby u64, permissions u32, locked u8, response u32 (pack 4)
    memcpy(enter.data(), &lobby, 8);
    memcpy(enter.data() + 16, &response, 4);
    if (response == 1) {
        g_cbs.push_back({504, enter});  // also sent as a plain callback
        std::vector<uint8_t> upd(20, 0);  // LobbyDataUpdate_t: lobby, member (the lobby itself), success
        memcpy(upd.data(), &lobby, 8);
        memcpy(upd.data() + 8, &lobby, 8);
        upd[16] = 1;
        g_cbs.push_back({505, upd});
    }
    complete(g_join_handle, 504, enter);
}

int b64_size(const std::string& s) {
    int n = static_cast<int>(s.size()) / 4 * 3;
    if (s.size() >= 2 && s[s.size() - 1] == '=') n--;
    if (s.size() >= 2 && s[s.size() - 2] == '=') n--;
    return n;
}

std::string unhex_name(const std::string& h) {
    std::string out;
    for (size_t i = 0; i + 1 < h.size(); i += 2) out += static_cast<char>(strtol(h.substr(i, 2).c_str(), nullptr, 16));
    return out;
}

void on_hubs(const std::string& text) {  // "HUBS\nH <i> <hexname> <players> <b64>\n..."
    std::vector<Lobby> lobbies;
    size_t pos = 0;
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        std::string line = text.substr(pos, end - pos);
        pos = end + 1;
        char hex[256] = {}, b64[2048] = {};
        int idx = 0, players = 0;
        if (sscanf(line.c_str(), "H %d %255s %d %2047s", &idx, hex, &players, b64) >= 3) {
            Lobby l;
            l.name = unhex_name(hex);
            l.players = players;
            l.adv_b64 = b64;
            l.adv_size = b64_size(l.adv_b64);
            if (lobbies.size() <= static_cast<size_t>(idx)) lobbies.resize(idx + 1);
            lobbies[idx] = l;
        }
    }
    std::lock_guard lock(g_m);
    g_lobbies = lobbies;
    L("daemon: %zu hub(s)", g_lobbies.size());
    if (g_list_handle) {
        uint32_t n = static_cast<uint32_t>(g_lobbies.size());
        complete(g_list_handle, 510, bytes_of(n));  // LobbyMatchList_t
        g_list_handle = 0;
    }
}

void on_datagram(const std::string& s) {
    if (s.compare(0, 4, "HUBS") == 0) {
        on_hubs(s);
    } else if (s.compare(0, 6, "JOINED") == 0) {
        std::lock_guard lock(g_m);
        L("daemon: joined the Switch session");
        g_in_room = true;
        if (g_join_handle) lobby_entered(g_join_lobby, 1);
        g_join_handle = 0;
    } else if (s.compare(0, 3, "ERR") == 0) {
        std::lock_guard lock(g_m);
        L("daemon: %s", s.c_str());
        if (g_join_handle) {
            lobby_entered(g_join_lobby, 5);  // k_EChatRoomEnterResponseError
            g_join_handle = 0;
        } else if (g_list_handle) {
            uint32_t zero = 0;
            complete(g_list_handle, 510, bytes_of(zero));
            g_list_handle = 0;
        }
    } else if (s.compare(0, 5, "RECV ") == 0) {
        std::vector<uint8_t> d;
        for (size_t i = 5; i + 1 < s.size(); i += 2) d.push_back(static_cast<uint8_t>(strtol(s.substr(i, 2).c_str(), nullptr, 16)));
        std::lock_guard lock(g_m);
        g_inbox.push_back(std::move(d));
    } else if (s.compare(0, 4, "LEFT") == 0) {
        L("daemon: the Switch host left");
    }
}

void to_daemon(const std::string& s) {
    if (g_sock != INVALID_SOCKET)
        sendto(g_sock, s.data(), static_cast<int>(s.size()), 0, reinterpret_cast<sockaddr*>(&g_daemon), sizeof g_daemon);
}

void receiver() {
    std::vector<char> buf(65536);
    for (;;) {
        int n = recv(g_sock, buf.data(), static_cast<int>(buf.size()), 0);
        if (n <= 0) {
            Sleep(50);
            continue;
        }
        on_datagram(std::string(buf.data(), n));
    }
}

const char* keep(const std::string& v) {  // a string that stays valid for the caller
    std::lock_guard lock(g_m);
    return (g_strings[v] = v).c_str();
}

// The Switch's lobbies have no search keys of their own; these are the ones in rise_netlog.txt's first lobby, to be
// replaced once we know how the game reads them.
const char* kSearchKeys[15] = {"-2147483647", "-2147483648", "-2147483648", "-2147483647", "-2147483647",
                               "-2147482649", "-1181622463", "-2147483648", "-2147483648", "-2147483648",
                               "-2147483648", "-2147483648", "-2147483648", "-2147482649", "-1181622464"};

// SteamNetworkingMessage_t (216 bytes on 64-bit)
struct NetMessage {
    void* data;
    int size;
    uint32_t conn;
    struct {
        int type, size;
        uint64_t steam_id;
        uint8_t rest[120];
    } peer;
    int64_t conn_user_data, time_received, number;
    void (*free_data)(NetMessage*);
    void (*release)(NetMessage*);
    int channel, flags;
    int64_t user_data;
    uint16_t lane, pad;
};
static_assert(sizeof(NetMessage) == 216, "SteamNetworkingMessage_t layout");

void release_message(NetMessage* m) {
    delete[] static_cast<uint8_t*>(m->data);
    delete m;
}

}  // namespace

void set_log(void (*fn)(const char*)) { g_log = fn; }

bool on() {
    if (!g_checked) {
        g_checked = true;
        char path[MAX_PATH];
        GetModuleFileNameA(nullptr, path, MAX_PATH);
        if (char* slash = strrchr(path, '\\')) slash[1] = 0;
        strcat_s(path, "rise_bridge.txt");
        g_on = GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
    }
    return g_on;
}

void start() {
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    g_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    g_daemon.sin_family = AF_INET;
    g_daemon.sin_port = htons(39600);
    inet_pton(AF_INET, "127.0.0.1", &g_daemon.sin_addr);
    L("bridge mode: the daemon is expected on 127.0.0.1:39600");
    L("build 5: manual-dispatch call results, CSteamID returned through a hidden pointer, member and leave logging, hello swap");
    g_calibrate = GetFileAttributesA(game_file("rise_bridge_calibrate.txt").c_str()) != INVALID_FILE_ATTRIBUTES;
    if (FILE* f = fopen(game_file("rise_hello.txt").c_str(), "r")) {
        char hex[64] = {};
        if (fgets(hex, sizeof hex, f) && strlen(hex) >= 30) {
            g_have_hello = true;
            for (int i = 0; i < 15; i++) {
                unsigned v = 0;
                sscanf_s(hex + 2 * i, "%2x", &v);
                g_hello[i] = static_cast<uint8_t>(v);
            }
        }
        fclose(f);
    }
    if (g_calibrate)
        L("CALIBRATION: the host stands in with your own Steam ID; join a hub once and rise_hello.txt gets written");
    else
        L("hello for the game: %s", g_have_hello ? "rise_hello.txt loaded" : "no rise_hello.txt (run once with rise_bridge_calibrate.txt)");
    std::thread(receiver).detach();
}

void set_own_id(uint64_t (*fn)()) { g_own_id = fn; }

bool fake_lobby(uint64_t id) { return on() && id >= kLobbyBase && id < kLobbyBase + 64; }
bool fake_user(uint64_t id) { return on() && id == host_id(); }

uint64_t request_list() {
    std::lock_guard lock(g_m);
    g_list_handle = g_next_handle++;
    g_list_deadline = GetTickCount() + 4000;
    L("RequestLobbyList: asking the daemon (handle %llx)", static_cast<unsigned long long>(g_list_handle));
    to_daemon("LIST");
    return g_list_handle;
}

uint64_t lobby_by_index(int i) {
    std::lock_guard lock(g_m);
    const uint64_t r = i >= 0 && static_cast<size_t>(i) < g_lobbies.size() ? kLobbyBase + i : 0;
    L("GetLobbyByIndex(%d) -> %llx", i, static_cast<unsigned long long>(r));
    return r;
}

const char* lobby_data_impl(uint64_t lobby, const char* key) {
    if (lobby == kQuestLobby) {
        std::lock_guard lock(g_m);
        auto it = g_quest_data.find(key ? key : "");
        return it != g_quest_data.end() ? it->second.c_str() : "";
    }
    Lobby l;
    {
        std::lock_guard lock(g_m);
        size_t i = static_cast<size_t>(lobby - kLobbyBase);
        if (i >= g_lobbies.size()) return "";
        l = g_lobbies[i];
    }
    const std::string k = key ? key : "";
    if (k == "OwnerId") return keep(std::to_string(host_id()));
    if (k == "Name") return keep(l.name);
    if (k == "P2pVersion" || k == "Attribute" || k == "Group") return "0";
    if (k == "IsPrivate" || k == "IsClose") return "false";
    if (k == "IsEnableAuth") return "true";
    if (k == "SlotTotalUse") return keep(std::to_string(l.players));
    if (k == "BinaryData") return keep(l.adv_b64);
    if (k == "BinarySize") return keep(std::to_string(l.adv_size));
    if (k == "SearchKeyNum") return "15";
    if (k.compare(0, 9, "SearchKey") == 0) {
        int n = atoi(k.c_str() + 9);
        if (n >= 0 && n < 15) return kSearchKeys[n];
    }
    return "";
}

const char* lobby_data(uint64_t lobby, const char* key) {
    const char* v = lobby_data_impl(lobby, key);
    static std::set<std::string> seen;  // log each key/value once, the game asks a lot
    static std::mutex seen_m;
    std::lock_guard<std::mutex> lk(seen_m);
    std::string line = std::string(key ? key : "") + "=" + std::string(v).substr(0, 60);
    if (seen.insert(line).second) L("GetLobbyData(%s) -> \"%s\"", key ? key : "", std::string(v).substr(0, 60).c_str());
    return v;
}

uint64_t join(uint64_t lobby) {
    std::lock_guard lock(g_m);
    g_join_handle = g_next_handle++;
    g_join_lobby = lobby;
    if (lobby == kQuestLobby) {  // the quest of the room the PC is in: already in its session
        L("JoinLobby: the quest lobby, in the Switch session already");
        if (!g_quest_owner) g_quest_owner = host_id();
        const uint64_t h = g_join_handle;
        lobby_entered(lobby, 1);
        g_join_handle = 0;
        return h;
    }
    L("JoinLobby: asking the daemon to join hub %d", static_cast<int>(lobby - kLobbyBase));
    to_daemon("JOIN " + std::to_string(lobby - kLobbyBase));
    return g_join_handle;
}

void leave(uint64_t lobby) {
    if (lobby == kQuestLobby) {  // the quest is over; the room (the Switch session) stays
        std::lock_guard lock(g_m);
        L("LeaveLobby: the quest lobby (the PC stays in the Switch session)");
        g_quest_owner = 0;
        g_quest_data.clear();
        return;
    }
    L("LeaveLobby: telling the daemon");
    {
        std::lock_guard lock(g_m);
        g_in_room = false;
    }
    to_daemon("LEAVE");
}

bool in_room() {
    std::lock_guard lock(g_m);
    return g_in_room;
}

// CreateLobby for a quest while in a Switch room: no Steam lobby. Steam's own order: LobbyCreated_t (513) as the call
// result, then LobbyEnter_t (504) and LobbyDataUpdate_t (505).
uint64_t create_quest_lobby() {
    std::lock_guard lock(g_m);
    const uint64_t handle = g_next_handle++;
    g_quest_owner = g_own_id ? g_own_id() : 0;
    g_quest_data.clear();
    std::vector<uint8_t> created(16, 0);  // LobbyCreated_t: result u32 (1, OK), lobby u64 at 8
    created[0] = 1;
    memcpy(created.data() + 8, &kQuestLobby, 8);
    complete(handle, 513, created);
    std::vector<uint8_t> enter(20, 0);
    memcpy(enter.data(), &kQuestLobby, 8);
    const uint32_t ok = 1;
    memcpy(enter.data() + 16, &ok, 4);
    g_cbs.push_back({504, enter});
    std::vector<uint8_t> upd(20, 0);
    memcpy(upd.data(), &kQuestLobby, 8);
    memcpy(upd.data() + 8, &kQuestLobby, 8);
    upd[16] = 1;
    g_cbs.push_back({505, upd});
    L("CreateLobby for a quest in a Switch room: lobby %llx, in the Switch session (no Steam lobby)",
      static_cast<unsigned long long>(kQuestLobby));
    return handle;
}

void set_lobby_data(uint64_t lobby, const char* key, const char* value) {
    if (lobby != kQuestLobby || !key) return;
    std::lock_guard lock(g_m);
    g_quest_data[key] = value ? value : "";
}
int member_count(uint64_t) { L("GetNumLobbyMembers -> 2"); return 2; }
uint64_t member_by_index(uint64_t, int i, uint64_t me) {
    L("GetLobbyMemberByIndex(%d)", i);
    return i == 0 ? host_id() : me;
}
uint64_t owner(uint64_t lobby) {
    std::lock_guard lock(g_m);
    return lobby == kQuestLobby && g_quest_owner ? g_quest_owner : host_id();
}
// What the game set as its own member data. Steam hands it back to everyone, the game included, and the game waits for
// that: after SetLobbyMemberData("Index", "3") it read its own Index every frame until it said 3 (2026-11-24 test,
// stuck after joining with only pings going both ways).
// Per lobby: in a quest the PC sets its Index there too, and the room's must stay as it was.
std::map<std::pair<uint64_t, std::string>, std::string> g_own_member;

const char* member_data(uint64_t lobby, uint64_t member, const char* key) {
    const bool host = member == host_id();
    static std::set<std::string> logged;
    std::lock_guard lock(g_m);
    if (!host && key) {
        auto it = g_own_member.find({lobby, key});
        if (it != g_own_member.end()) return it->second.c_str();
    }
    if (logged.insert(std::string(host ? "host " : "us ") + (key ? key : "")).second)
        L("GetLobbyMemberData(%s) for %s", key ? key : "", host ? "the host" : "us");
    if (key && !strcmp(key, "Index")) return host ? "0" : "1";
    return "";
}

void set_member_data(uint64_t lobby, const char* key, const char* value) {
    if (!key) return;
    std::lock_guard lock(g_m);
    g_own_member[{lobby, key}] = value ? value : "";
    L("SetLobbyMemberData(%s, %s): kept as ours, LobbyDataUpdate queued", key, value ? value : "");
    // LobbyDataUpdate_t for our member (lobby, member, success), as Steam sends when member data changes
    const uint64_t me = g_own_id ? g_own_id() : 0;
    std::vector<uint8_t> upd(20, 0);
    memcpy(upd.data(), &lobby, 8);
    memcpy(upd.data() + 8, &me, 8);
    upd[16] = 1;
    g_cbs.push_back({505, upd});
}

void send_to_host(const void* data, uint32_t size, int channel) {
    {
        std::lock_guard lock(g_m);
        g_channel = channel;
    }
    static const char* hex = "0123456789abcdef";
    std::string s = "SEND ";
    const auto* b = static_cast<const uint8_t*>(data);
    for (uint32_t i = 0; i < size; i++) {
        s += hex[b[i] >> 4];
        s += hex[b[i] & 15];
    }
    if (g_calibrate && is_hello_message(b, size)) {
        char hex15[32] = {};
        for (int i = 0; i < 15; i++) snprintf(hex15 + 2 * i, 3, "%02x", b[6 + i]);
        if (FILE* f = fopen(game_file("rise_hello.txt").c_str(), "w")) {
            fprintf(f, "%s\n", hex15);
            fclose(f);
        }
        L("CALIBRATION: the game's hello for its own Steam ID is %s (saved to rise_hello.txt). Now delete "
          "rise_bridge_calibrate.txt and restart the game.", hex15);
    }
    to_daemon(s);
}

int receive(int channel, void** out, int max) {
    std::lock_guard lock(g_m);
    int n = 0;
    if (channel != g_channel) return 0;
    while (n < max && !g_inbox.empty()) {
        auto d = std::move(g_inbox.front());
        g_inbox.pop_front();
        if (!g_calibrate && g_have_hello && is_hello_message(d.data(), d.size())) {
            memcpy(d.data() + 6, g_hello, 15);
            L("the Switch host's hello replaced with the one this game expects");
        }
        auto* m = new NetMessage{};
        m->data = new uint8_t[d.size() ? d.size() : 1];
        memcpy(m->data, d.data(), d.size());
        m->size = static_cast<int>(d.size());
        m->peer.type = 16;  // k_ESteamNetworkingIdentityType_SteamID
        m->peer.size = 8;
        m->peer.steam_id = host_id();
        m->time_received = static_cast<int64_t>(GetTickCount64()) * 1000;
        m->release = &release_message;
        m->channel = channel;
        out[n++] = m;
    }
    return n;
}

// The game checks every member's Steam auth ticket (BeginAuthSession), and Steam answers with ValidateAuthTicketResponse_t
// (143) later. A Switch player has no ticket and Steam doesn't know the made-up ID, so for that ID the answer is OK,
// from here.
void auth_ok(uint64_t id) {
    std::lock_guard lock(g_m);
#pragma pack(push, 4)
    struct Validate {
        uint64_t id;
        int response;  // k_EAuthSessionResponseOK
        uint64_t owner;
    } v{id, 0, id};
#pragma pack(pop)
    g_cbs.push_back({143, bytes_of(v)});
    L("BeginAuthSession for the Switch host's ID: answered OK, callback 143 queued");
}

bool pop_callback(int* id, const uint8_t** data, int* size) {
    std::lock_guard lock(g_m);
    if (g_list_handle && static_cast<int>(GetTickCount() - g_list_deadline) > 0) {  // the daemon never answered
        uint32_t zero = 0;
        complete(g_list_handle, 510, bytes_of(zero));
        g_list_handle = 0;
        L("the daemon didn't answer the lobby search: is tools/bridge_daemon.py running?");
    }
    if (g_cbs.empty()) return false;
    g_current = std::move(g_cbs.front());
    g_cbs.pop_front();
    g_have_current = true;
    *id = g_current.id;
    *data = g_current.data.data();
    *size = static_cast<int>(g_current.data.size());
    L("handing the game callback %d (%d bytes)", *id, *size);
    return true;
}

void free_callback() {
    std::lock_guard lock(g_m);
    g_have_current = false;
}

bool is_completed(uint64_t handle) {
    std::lock_guard lock(g_m);
    return g_results.count(handle) != 0;
}

bool get_result(uint64_t handle, void* out, int cap, int expected, bool* failed) {
    std::lock_guard lock(g_m);
    auto it = g_results.find(handle);
    if (it == g_results.end()) return false;
    if (failed) *failed = false;
    if (expected != it->second.cb) L("GetAPICallResult: the game expected callback %d, we have %d", expected, it->second.cb);
    memcpy(out, it->second.data.data(), std::min<size_t>(cap, it->second.data.size()));
    L("GetAPICallResult: gave the game callback %d (%zu bytes)", it->second.cb, it->second.data.size());
    g_results.erase(it);
    return true;
}

}  // namespace bridge
