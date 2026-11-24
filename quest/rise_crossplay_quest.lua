-- Crossplay quests: the PC side of a quest in a Switch Local Play room.
--
-- On PC online, posting a quest opens a quest session of its own (a Steam lobby, CreateLobby type 3) and the others
-- join it through the lobby ID in the room answer (snow.LobbyManager.QuestIdentifier._sessionID). In Switch Local Play
-- a quest stays in the room's session. Bridged into a Switch room, the PC's quest went to a Steam lobby the Switch
-- can't see ("the quest has already ended"), and a Switch quest gave the PC no lobby to join ("failed to join the quest
-- session"). The game has both ways in it, chosen by snow.SnowSessionManager.IsInternet / isLocalnet, so while the PC
-- is in a room this script has the game take the Local Play way.
--
-- Only for crossplay: with the bridge (RiseBridge, rise_bridge.txt) every room the PC sees is a Switch room. Turn it off
-- in REFramework's menu (Script Generated UI → Crossplay quests) to play online with PC players.
--
-- It also logs the quest calls (lines start with [xquest], in re2_framework_log.txt): which way the game took, and the
-- session IDs in the room answers.

local TAG = "[xquest] "
local function say(text) log.info(TAG .. text) end

local function try(f, ...)
    local ok, value = pcall(f, ...)
    if ok then return value end
    return nil
end

local local_quests = true  -- the menu's checkbox
local mgr_name = "snow.SnowSessionManager"

-- Whether the PC is in a room now. Read without the override (the check itself may ask IsInternet).
local checking = false
local function in_room()
    local mgr = sdk.get_managed_singleton(mgr_name)
    if mgr == nil then return false end
    checking = true
    local yes = try(mgr.call, mgr, "isInAnySession")
    checking = false
    return yes == true
end

local overridden = 0
local function override(want)
    return function(retval)
        if not local_quests or checking or not in_room() then return retval end
        overridden = overridden + 1
        if overridden == 1 then say("in a room: the game takes the Local Play way for quests from now on") end
        return sdk.to_ptr(want and 1 or 0)
    end
end

local mgr_type = sdk.find_type_definition(mgr_name)
for name, want in pairs({ IsInternet = false, isLocalnet = true }) do
    local m = mgr_type and mgr_type:get_method(name)
    if m then
        local ok, err = pcall(sdk.hook, m, nil, override(want))
        say(name .. (ok and ": hooked" or (": couldn't hook: " .. tostring(err))))
    else
        say("no " .. mgr_name .. "." .. name)
    end
end

-- The quest calls, logged: the first time each one happens, then every 100th
local counts = {}
local function counted(key)
    local n = (counts[key] or 0) + 1
    counts[key] = n
    if n == 1 or n % 100 == 0 then say(key .. " #" .. n) end
end

local function watch(type_name, pick)
    local td = sdk.find_type_definition(type_name)
    local hooked = 0
    for _, m in ipairs(td and try(td.get_methods, td) or {}) do
        local name = try(m.get_name, m) or ""
        if pick(name) then
            local ok = pcall(sdk.hook, m, function() counted(type_name:match("[^.]+$") .. "." .. name) end, nil)
            if ok then hooked = hooked + 1 end
        end
    end
    say(type_name .. ": " .. hooked .. " quest calls watched")
end

local function quest_call(name)
    if name:find("^get_") or name:find("^set_") or name:find("^is") then return false end
    return name:find("Room") or name:find("Quest") or name:find("Session")
end
watch("snow.LobbyManager", quest_call)
watch(mgr_name, function(name) return name:find("^req") and (name:find("Quest") or name:find("Session")) end)

-- The session ID a quest carries (the quest's lobby on PC; what the Switch puts there is what this is for): from every
-- QuestIdentifier copied (copyFrom), and from any watched call that takes one
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

re.on_draw_ui(function()
    if imgui.tree_node("Crossplay quests") then
        local changed, value = imgui.checkbox("Quests as Local Play (only for Switch rooms)", local_quests)
        if changed then
            local_quests = value
            say("Local Play quests " .. (value and "on" or "off"))
        end
        imgui.text("Overrides so far: " .. overridden)
        imgui.tree_pop()
    end
end)

say("ready (Local Play quests " .. (local_quests and "on" or "off") .. ")")
