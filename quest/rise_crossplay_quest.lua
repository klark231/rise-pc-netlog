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
-- Also written to reframework/data/rise_xquest_log.txt, one line at a time (opened and closed per line, so it is on disk
-- even if the game is killed): re2_framework_log.txt is only complete once REFramework shuts down cleanly, and a run
-- that ends in a crash or a task kill leaves the old file. (On the port there's no such folder: the open just fails.)
local XLOG = "reframework/data/rise_xquest_log.txt"
pcall(function() local f = io.open(XLOG, "w") if f then f:write("[xquest] log started\n") f:close() end end)
local function say(text)
    log.info(TAG .. text)
    pcall(function()
        local f = io.open(XLOG, "a")
        if f then f:write(os.date("%H:%M:%S ") .. TAG .. text .. "\n") f:close() end
    end)
end

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

-- Who the game takes for whom in a quest, whenever it changes: its own index (LobbyManager._myselfIndex and
-- getMyQuestIndex), the quest host's (getQuestHostIndex) and the quest member list (its session type and join, ready
-- and prepare flags per slot). On 2026-11-25 the phone joined the PC's quest, waited a few seconds while loading and
-- retired; the PC as the quest's maker had Index 0 in its quest lobby, the phone's slot in the room.
local function list_text(arr)
    if arr == nil then return "nil" end
    local n = try(arr.call, arr, "get_Count") or try(arr.get_size, arr) or try(arr.call, arr, "get_Length")
    if n == nil then return "?" end
    local out = {}
    for i = 0, math.min(n, 8) - 1 do
        local v = try(arr.call, arr, "get_Item", i) or try(arr.get_element, arr, i)
        if type(v) == "userdata" then v = try(v.call, v, "ToString") or "obj" end
        out[#out + 1] = tostring(v)
    end
    return "[" .. table.concat(out, " ") .. "]"
end

-- A quest index as the game returns it (a small struct or an enum, not a plain number)
local function index_text(v)
    if type(v) ~= "userdata" then return tostring(v) end
    for _, f in ipairs({ "value__", "_Value", "_value", "value", "mValue" }) do
        local x = try(v.get_field, v, f)
        if x ~= nil and type(x) ~= "userdata" then return tostring(x) end
    end
    return tostring(try(v.call, v, "ToString") or "?")
end

local last_state, next_state = nil, 0
re.on_frame(function()
    local now = os.clock()
    if now < next_state then return end
    next_state = now + 0.5
    local lm = sdk.get_managed_singleton("snow.LobbyManager")
    if lm == nil then return end
    local ml = try(lm.get_field, lm, "_questMemberList")
    local state = "myself " .. tostring(try(lm.get_field, lm, "_myselfIndex")) ..
        ", my quest index " .. index_text(try(lm.call, lm, "getMyQuestIndex")) ..
        ", quest host " .. index_text(try(lm.call, lm, "getQuestHostIndex")) ..
        ", member list " .. (ml and ("type " .. tostring(try(ml.get_field, ml, "_SessionType")) ..
            " join " .. list_text(try(ml.get_field, ml, "_join")) ..
            " ready " .. list_text(try(ml.get_field, ml, "_ready")) ..
            " prepare " .. list_text(try(ml.get_field, ml, "_prepare"))) or "none")
    if state ~= last_state then
        last_state = state
        say("state: " .. state)
    end
end)

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

-- 2026-11-26: which fields hold the quest slots? The PC's "my quest index 0 / quest host 0" stayed 0 through a whole quest
-- even though its quest lobby Index was handed back as its room slot (1), so the game keeps a copy of the first read.
-- This lists the LobbyManager's index/host fields (and the quest member list's) a second after a quest is created or
-- entered, and again 5 s and 10 s later, as "[xquest] fields". Read only.
-- Setting _myselfQuestIndex to the room slot (1) on the PC (an experiment, 2026-11-26) made Depart impossible there:
-- the game still counts the PC as quest host 0. Removed; this part only reads.
-- (This part is loaded from text, so a mistake in it is logged and the rest of the script still runs.)
local fields_code = [==[
local say, try, on_pc = ...
local lm_type = sdk.find_type_definition("snow.LobbyManager")
local dumps_left, next_dump = 0, 0

local function val_text(v)
    if v == nil then return "nil" end
    if type(v) ~= "userdata" then return tostring(v) end
    for _, f in ipairs({ "value__", "_Value", "_value", "value" }) do
        local x = try(v.get_field, v, f)
        if x ~= nil and type(x) ~= "userdata" then return tostring(x) end
    end
    return tostring(try(v.call, v, "ToString") or "?")
end

local function arr_text(v)
    local n = try(v.call, v, "get_Length") or try(v.call, v, "get_Count")
    if n == nil then return nil end
    local out = {}
    for i = 0, math.min(n, 8) - 1 do
        local e = try(v.call, v, "get_Item", i) or try(v.get_element, v, i)
        out[#out + 1] = type(e) == "userdata" and "obj" or tostring(e)
    end
    return "[" .. table.concat(out, " ") .. "]"
end

local function dump(where)
    local lm = sdk.get_managed_singleton("snow.LobbyManager")
    if lm == nil or lm_type == nil then return end
    say("fields (" .. where .. "):")
    local n = 0
    for _, f in ipairs(try(lm_type.get_fields, lm_type) or {}) do
        local name = try(f.get_name, f) or "?"
        if not try(f.is_static, f) and not name:find("Action") then
            local ft = try(f.get_type, f)
            local tn = tostring(ft and try(ft.get_full_name, ft))
            local v = try(f.get_data, f, lm)
            local text = (type(v) == "userdata" and tn:find("%[%]$") and arr_text(v)) or val_text(v)
            say("  " .. name .. " : " .. tn .. " = " .. text)
            n = n + 1
            if n >= 250 then break end
        end
    end
    local ml = try(lm.get_field, lm, "_questMemberList")
    local mtd = ml and try(ml.get_type_definition, ml)
    for _, f in ipairs(mtd and try(mtd.get_fields, mtd) or {}) do
        local name = try(f.get_name, f) or "?"
        if not try(f.is_static, f) then
            local v = try(f.get_data, f, ml)
            say("  _questMemberList." .. name .. " = " .. ((type(v) == "userdata" and arr_text(v)) or val_text(v)))
        end
    end
end

for _, mname in ipairs({ "getMyQuestIndex", "getQuestHostIndex" }) do
    local m = lm_type and lm_type:get_method(mname)
    local rt = m and try(m.get_return_type, m)
    say(mname .. " returns " .. tostring(rt and try(rt.get_full_name, rt)) .. ", value type " ..
        tostring(rt and try(rt.is_value_type, rt)) .. ", size " .. tostring(rt and try(rt.get_valuetype_size, rt)))
end

local function trigger(name)
    local m = lm_type and lm_type:get_method(name)
    if m then
        pcall(sdk.hook, m, function() dumps_left, next_dump = 2, os.clock() + 1 end, nil)
    end
end
trigger("createRoom")
trigger("requestEnterRoom")
trigger("goQuest")


re.on_frame(function()
    local now = os.clock()
    if dumps_left > 0 and now >= next_dump then
        dumps_left = dumps_left - 1
        next_dump = now + 6
        dump("after a quest call, " .. dumps_left .. " more")
    end
end)
say("fields probe ready")
]==]
local fields_fn, fields_err = load(fields_code, "xquest_fields")
if fields_fn then
    local ok, err = pcall(fields_fn, say, try, on_pc)
    if not ok then say("fields probe failed: " .. tostring(err)) end
else
    say("fields probe not loaded: " .. tostring(fields_err))
end

say("ready")
