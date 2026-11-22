// rise-bridge, the PC side: fake Steam lobbies and a fake peer standing for the Switch session, relayed through
// tools/bridge_daemon.py (UDP on 127.0.0.1). Active only when rise_bridge.txt is next to the game's exe.
#pragma once
#include <cstdint>

namespace bridge {

void set_log(void (*fn)(const char* line));
bool on();                       // rise_bridge.txt is there
void start();                    // open the socket to the daemon
void set_own_id(uint64_t (*fn)());  // how to read the game's own Steam ID (for calibration mode)

bool fake_lobby(uint64_t id);
bool fake_user(uint64_t id);     // the stand-in for the Switch host

// ISteamMatchmaking
uint64_t request_list();                         // a call-result handle
uint64_t lobby_by_index(int i);
const char* lobby_data(uint64_t lobby, const char* key);
uint64_t join(uint64_t lobby);                   // a call-result handle
void leave(uint64_t lobby);
int member_count(uint64_t lobby);
uint64_t member_by_index(uint64_t lobby, int i, uint64_t me);
uint64_t owner(uint64_t lobby);
const char* member_data(uint64_t lobby, uint64_t member, const char* key);

// ISteamNetworkingMessages
void send_to_host(const void* data, uint32_t size, int channel);
int receive(int channel, void** out, int max);   // appends SteamNetworkingMessage_t*; returns how many

// Steam callbacks (Steam_BGetCallback / ISteamUtils call results)
bool pop_callback(int* id, const uint8_t** data, int* size);  // a fake callback to hand the game, if one is due
void free_callback();
bool is_completed(uint64_t handle);
bool get_result(uint64_t handle, void* out, int cap, int expected, bool* failed);

}  // namespace bridge
