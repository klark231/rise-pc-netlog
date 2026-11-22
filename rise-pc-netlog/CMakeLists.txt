cmake_minimum_required(VERSION 3.20)
project(rise_pc_netlog CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")  # static CRT: no redistributable needed

include(FetchContent)
if(POLICY CMP0169)
    cmake_policy(SET CMP0169 OLD)  # (FetchContent_Populate: MinHook is built from its sources here, not its own CMake)
endif()
FetchContent_Declare(minhook
    GIT_REPOSITORY https://github.com/TsudaKageyu/minhook.git
    GIT_TAG v1.3.3)
FetchContent_GetProperties(minhook)
if(NOT minhook_POPULATED)
    FetchContent_Populate(minhook)
endif()
add_library(minhook STATIC
    ${minhook_SOURCE_DIR}/src/buffer.c
    ${minhook_SOURCE_DIR}/src/hook.c
    ${minhook_SOURCE_DIR}/src/trampoline.c
    ${minhook_SOURCE_DIR}/src/hde/hde64.c)
target_include_directories(minhook PUBLIC ${minhook_SOURCE_DIR}/include)

add_library(dinput8 SHARED src/netlog.cpp src/bridge.cpp src/exports.def)
target_link_libraries(dinput8 PRIVATE minhook ws2_32)
target_compile_definitions(dinput8 PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
set_target_properties(dinput8 PROPERTIES OUTPUT_NAME dinput8)
