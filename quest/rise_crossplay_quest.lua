-- Crossplay quests: what each game does with a quest in a Switch Local Play room.
--
-- On PC online a quest has a session of its own (a Steam lobby); in Switch Local Play it stays in the room's session.
-- The PC plugin (rise_crossplay.dll) keeps the PC's quest in the Switch session. This script shows the game's side of
-- it, on PC (REFramework, reframework/autorun) and on the port (Settings → Mods & cheats → Add a mod):
--   * the quest calls of snow.LobbyManager and snow.SnowSessionManager, the first time each one happens (then every
--     100th), with the text arguments of the session requests (the session IDs a quest is joined by)
--   * the session ID each quest carries (QuestIdentifier._sessionID): on PC a short code for its lobby, on the Switch
--     empty
-- Lines start with [xquest]: re2_framework_log.txt on PC, log.txt on the port.
-- On PC it also lets the PC join a Switch quest (at the end).
--
-- 2026-11-25: having the game take its Local Play way (IsInternet / isLocalnet answered for it) did nothing: neither
-- is asked when a quest is posted or joined.

local TAG = "[xquest] "
local function say(text) log.info(TAG .. text) end

local function try(f, ...)
    local ok, value = pcall(f, ...)
    if ok then return value end
    return nil
end

local mgr_name = "snow.SnowSessionManager"

local counts = {}
local function counted(key, detail)
    local n = (counts[key] or 0) + 1
    counts[key] = n
    if n == 1 or n % 100 == 0 then say(key .. " #" .. n .. (detail or "")) end
end

-- A call's text arguments, as ("...", ...)
local function text_args(args, types, first)
    local out = {}
    for i, t in ipairs(types) do
        if try(t.get_full_name, t) == "System.String" then
            local s = try(sdk.to_managed_object, args[first + i])
            out[#out + 1] = "\"" .. tostring(s and try(s.call, s, "ToString") or "") .. "\""
        end
    end
    return #out > 0 and (" (" .. table.concat(out, ", ") .. ")") or ""
end

local function watch(type_name, pick)
    local td = sdk.find_type_definition(type_name)
    local hooked = 0
    for _, m in ipairs(td and try(td.get_methods, td) or {}) do
        local name = try(m.get_name, m) or ""
        if pick(name) then
            local key = type_name:match("[^.]+$") .. "." .. name
            local types = try(m.get_param_types, m) or {}
            local first = try(m.is_static, m) and 1 or 2
            local ok = pcall(sdk.hook, m, function(args) counted(key, text_args(args, types, first)) end, nil)
            if ok then hooked = hooked + 1 end
        end
    end
    say(type_name .. ": " .. hooked .. " quest calls watched")
end

watch("snow.LobbyManager", function(name)
    if name:find("^get") or name:find("^set_") or name:find("^is") then return false end
    return name:find("Room") or name:find("Quest") or name:find("Session")
end)
watch(mgr_name, function(name) return name:find("^req") and (name:find("Quest") or name:find("Session")) end)

-- The session ID a quest carries: from every QuestIdentifier copied (copyFrom), and from any watched call taking one
local ident_type = "snow.LobbyManager.QuestIdentifier"
local seen_ids = {}
local function note_identifier(where, ident)
    if ident == nil then return end
    local id = try(ident.get_field, ident, "_sessionID")
    local key = where .. tostring(id)
    if seen_ids[key] then return end
    seen_ids[key] = true
    say(where .. ": quest " .. tostring(try(ident.get_field, ident, "_QuestNo")) .. ", session ID \"" .. tostring(id) .. "\"")
end

local ident_td = sdk.find_type_definition(ident_type)
local copy = ident_td and ident_td:get_method("copyFrom")
if copy then
    pcall(sdk.hook, copy, function(args)
        note_identifier("QuestIdentifier.copyFrom (from)", try(sdk.to_managed_object, args[3]))
    end, nil)
end
for _, tn in ipairs({ "snow.LobbyManager", mgr_name }) do
    local td = sdk.find_type_definition(tn)
    for _, m in ipairs(td and try(td.get_methods, td) or {}) do
        local types = try(m.get_param_types, m) or {}
        for i, t in ipairs(types) do
            if try(t.get_full_name, t) == ident_type then
                local name = tn:match("[^.]+$") .. "." .. (try(m.get_name, m) or "?")
                local first = try(m.is_static, m) and 1 or 2
                pcall(sdk.hook, m, function(args)
                    note_identifier(name, try(sdk.to_managed_object, args[first + i]))
                end, nil)
            end
        end
    end
end

-- The PC joining a Switch quest. A Switch quest has no session ID (Local Play has no session of its own), and with
-- an empty one the PC gave up before asking Steam for anything. It gets the ID of the plugin's quest lobby instead,
-- which stands for the Switch session the PC is already in: this is the ID the PC itself made for that lobby
-- (rise_crossplay.dll's kQuestLobby, 0x01860000B1D60020) on 2026-11-25, and the PC reads its lobby back out of it.
-- Only on PC (the port has no quest sessions to join).
local QUEST_LOBBY_ID = "LYAfTFFEXeFFEAJG"
local on_pc = try(function() return package.config:sub(1, 1) == "\\" end) or false
local kept = nil
local join = sdk.find_type_definition(mgr_name)
join = join and join:get_method("reqSessionJoinFromSessionID")
if on_pc and join then
    local types = try(join.get_param_types, join) or {}
    local at = nil
    for i, t in ipairs(types) do
        if try(t.get_full_name, t) == "System.String" then at = 2 + i break end
    end
    if at then
        pcall(sdk.hook, join, function(args)
            local s = try(sdk.to_managed_object, args[at])
            local id = s and try(s.call, s, "ToString") or ""
            if id ~= "" then return end
            if kept == nil then
                kept = sdk.create_managed_string(QUEST_LOBBY_ID)
                if kept then try(kept.add_ref, kept) end
            end
            if kept then
                args[at] = sdk.to_ptr(kept)
                say("joining a Switch quest: its empty session ID swapped for the plugin's quest lobby")
            end
        end, nil)
        say("reqSessionJoinFromSessionID: Switch quests joined through the plugin's quest lobby")
    end
end

say("ready")
