-- Crossplay probe: what each game does with the other side's hunter.
--
-- The same script runs on PC (REFramework, reframework/autorun) and on the Android port (Settings -> Mods & cheats ->
-- Add a mod, with the zip from this folder). It only reads and counts; it doesn't change anything in the game.
-- Lines start with [xprobe] and go to REFramework's log on PC and to log.txt on the port.
--
-- It logs:
--   * the PlayerManager calls that create a hunter (createPlayer, setPlayerCreateBaseData, instantiatePlayerParts)
--   * once a second, a line per player slot whenever that slot changes: is there a hunter, is it drawn, is it ours,
--     and its RemoteGameObject (network name, master index, message version, prefab, instance)
--   * the PlayerNetwork.receive overloads and the PlayerBase deserialize calls, the first time each one happens for a
--     player and then every 200 calls. The port has some overloads as one function: a call to any of them counts for
--     each overload in that group (they go up together)
--   * PlayerNetwork's other packet and state functions (names with Packet, Fsm, Recv, Receive, Sync or Periodic), the
--     same way
--   * every 10 s, how many calls each of those had per player since the last time

local TAG = "[xprobe] "
local function say(text) log.info(TAG .. text) end

local function try(f, ...)
    local ok, value = pcall(f, ...)
    if ok then return value end
    return nil
end

local function call(obj, name, ...)
    if obj == nil then return nil end
    return try(obj.call, obj, name, ...)
end

local function text(value)
    if value == nil then return "nil" end
    local kind = type(value)
    if kind == "userdata" then
        local td = try(value.get_type_definition, value)
        local name = td and try(td.get_full_name, td)
        return name and ("<" .. name .. ">") or "<object>"
    end
    return tostring(value)
end

local function player_index(obj)
    local index = call(obj, "getPlayerIndex")
    return index ~= nil and tostring(index) or "?"
end

-- hooks ---------------------------------------------------------------------------------------------------------------

local counts = {}
local recent = {}  -- calls since the last summary
local function counted(key, detail)
    local n = (counts[key] or 0) + 1
    counts[key] = n
    recent[key] = (recent[key] or 0) + 1
    if n == 1 or n % 200 == 0 then
        say(key .. " #" .. n .. (detail and (" " .. detail) or ""))
    end
end

local function params(method)
    local types = try(method.get_param_types, method)
    if not types then return "" end
    local names = {}
    for _, t in ipairs(types) do names[#names + 1] = try(t.get_full_name, t) or "?" end
    return table.concat(names, ",")
end

local function hook_all(type_name, method_name, make_pre)
    local td = sdk.find_type_definition(type_name)
    if not td then
        say("no type " .. type_name)
        return
    end
    local methods = try(td.get_methods, td) or {}
    local hooked = 0
    for _, method in ipairs(methods) do
        if try(method.get_name, method) == method_name then
            local signature = method_name .. "(" .. params(method) .. ")"
            local ok, err = pcall(sdk.hook, method, make_pre(signature), function(retval) return retval end)
            if ok then hooked = hooked + 1 else say("could not hook " .. type_name .. "." .. signature .. ": " .. tostring(err)) end
        end
    end
    say(type_name .. "." .. method_name .. ": " .. hooked .. " hooked")
end

local function this_object(args)
    return try(sdk.to_managed_object, args[2])
end

local function raw_args(args, count)
    local out = {}
    for i = 3, 2 + count do
        local v = args[i]
        out[#out + 1] = v ~= nil and string.format("%x", try(sdk.to_int64, v) or 0) or "-"
    end
    return table.concat(out, " ")
end

for _, name in ipairs({ "createPlayer", "setPlayerCreateBaseData", "instantiatePlayerParts" }) do
    hook_all("snow.player.PlayerManager", name, function(signature)
        return function(args)
            say("PlayerManager." .. signature .. " args " .. raw_args(args, 4))
        end
    end)
end

local function network_player(args)
    return player_index(call(this_object(args), "get_RefPlayerBase"))
end

hook_all("snow.PlayerNetwork", "receive", function(signature)
    return function(args)
        counted(signature .. " player " .. network_player(args))
    end
end)

for _, name in ipairs({ "deserializeNetworkCommonFlags", "deserializeNetworkPlAttr" }) do
    hook_all("snow.player.PlayerBase", name, function(signature)
        return function(args)
            counted(signature .. " player " .. player_index(this_object(args)))
        end
    end)
end

-- PlayerNetwork's other packet and state functions
do
    local td = sdk.find_type_definition("snow.PlayerNetwork")
    local names = {}
    for _, method in ipairs(td and try(td.get_methods, td) or {}) do
        local name = try(method.get_name, method) or ""
        if name ~= "receive" and not names[name] and not try(method.is_static, method) then
            for _, word in ipairs({ "Packet", "Fsm", "Recv", "Receive", "Sync", "Periodic" }) do
                if name:find(word) then names[name] = true break end
            end
        end
    end
    local list = {}
    for name in pairs(names) do list[#list + 1] = name end
    table.sort(list)
    for _, name in ipairs(list) do
        hook_all("snow.PlayerNetwork", name, function(signature)
            return function(args)
                counted(signature .. " player " .. network_player(args))
            end
        end)
    end
end

hook_all("via.puppet.RemoteGameObject", "instantiate", function(signature)
    return function(args)
        local rgo = this_object(args)
        say("RemoteGameObject." .. signature .. " " .. tostring(call(rgo, "get_NetworkName")))
    end
end)

-- slots ---------------------------------------------------------------------------------------------------------------

local last = {}
local next_check = 0

local function describe(manager, index)
    local player = call(manager, "getPlayer", index)
    if player == nil then return "empty" end
    local parts = {
        "hunter " .. text(player),
        "index " .. player_index(player),
        "master " .. tostring(call(player, "isMasterPlayer")),
        "drawn " .. tostring(call(player, "isDrawPlayer")),
    }
    local network = call(player, "get_RefNetwork")
    local rgo = call(network, "get_RefRemoteGameObject")
    if network == nil then
        parts[#parts + 1] = "no PlayerNetwork"
    elseif rgo == nil then
        parts[#parts + 1] = "no RemoteGameObject"
    else
        parts[#parts + 1] = "net name " .. tostring(call(rgo, "get_NetworkName"))
        parts[#parts + 1] = "net master " .. tostring(call(rgo, "get_MasterIndex"))
        parts[#parts + 1] = "is master " .. tostring(call(rgo, "get_IsMaster"))
        parts[#parts + 1] = "message version " .. tostring(call(rgo, "get_MessageVersion"))
        parts[#parts + 1] = "sync mode " .. tostring(call(rgo, "get_SyncMode"))
        parts[#parts + 1] = "first fsm packet " .. tostring(call(network, "get_FirstFsmPacketReceived"))
        parts[#parts + 1] = "prefab " .. text(call(rgo, "get_CurrentPrefab"))
        parts[#parts + 1] = "instance " .. text(call(rgo, "get_Instance"))
    end
    return table.concat(parts, ", ")
end

local next_summary = 0

re.on_frame(function()
    local wall = os.time()
    if wall >= next_summary then
        next_summary = wall + 10
        local keys = {}
        for key in pairs(recent) do keys[#keys + 1] = key end
        if #keys > 0 then
            table.sort(keys)
            local parts = {}
            for _, key in ipairs(keys) do parts[#parts + 1] = key .. " " .. recent[key] end
            say("last 10 s: " .. table.concat(parts, "; "))
            recent = {}
        end
    end
    local now = os.clock()
    if now < next_check then return end
    next_check = now + 1
    local manager = sdk.get_managed_singleton("snow.player.PlayerManager")
    if manager == nil then return end
    for index = 0, 3 do
        local line = describe(manager, index)
        if line ~= last[index] then
            last[index] = line
            say("slot " .. index .. ": " .. line)
        end
    end
end)

say("ready")
