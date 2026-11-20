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
// data and calls the original. Nothing is changed: no app IDs, ownership or tickets, only networking, read-only.
// Which interfaces the game asks for is logged too, so we learn which of Steam's networking APIs Rise uses.
//
// Hooks with MinHook (Tsuda Kageyu, BSD 2-clause). The interface layouts are those of Valve's public Steamworks SDK
// headers (ISteamClient 017+, ISteamNetworking 006, ISteamNetworkingMessages 002, ISteamNetworkingSockets 012).

#include <windows.h>
#include <objbase.h>
#include <share.h>

#include <MinHook.h>

#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
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
    log_packet('>', "SendMessageToUser", identity_id(to), channel, data, size);
    return g_send_user(self, to, data, size, flags, channel);
}

int __fastcall receive_channel(void* self, int channel, Message** out, int max) {
    const int n = g_receive_channel(self, channel, out, max);
    for (int k = 0; k < n && out; k++)
        if (out[k]) log_packet('<', "ReceiveMessagesOnChannel", out[k]->peer.steam_id, out[k]->channel, out[k]->data, out[k]->size);
    return n;
}

void wrap_messages(void* m) {
    if (!m) return;
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
    if (!strncmp(version, "SteamNetworkingMessages", 23)) wrap_messages(itf);
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
}

using LoadLibraryExWFn = HMODULE(WINAPI*)(LPCWSTR, HANDLE, DWORD);
LoadLibraryExWFn g_load_library = nullptr;

HMODULE WINAPI load_library(LPCWSTR name, HANDLE file, DWORD flags) {
    HMODULE m = g_load_library(name, file, flags);
    if (m && !(flags & (LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE | LOAD_LIBRARY_AS_IMAGE_RESOURCE)))
        check_module(m);
    return m;
}

void start() {
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
