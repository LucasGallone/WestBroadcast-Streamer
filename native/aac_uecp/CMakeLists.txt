# aac_uecp.dll - UECP-from-AAC extractor used by app.py's UECP forwarding.
#
# decoders/ is copied from UecpBridge's src/decoders (AAC only). The only local changes are in
# decoders/Audio.h and decoders/Arduino.h: decoder logging is compiled out unless AAC_UECP_LOG is
# defined.
#
# Build (from a VS developer prompt or with VS Build Tools' cmake.exe):
#   cmake -S . -B build -A x64
#   cmake --build build --config Release
# The DLL is written next to app.py as aac_uecp_x64.dll (aac_uecp_x86.dll for -A Win32).
#
# License: the FAAD2 code is GPLv2+ (see decoders/aac_decoder/libfaad/neaacdec.cpp header).

cmake_minimum_required(VERSION 3.20)
project(aac_uecp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Static CRT so the DLL needs no VC++ redistributable.
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

add_library(aac_uecp SHARED
    aac_uecp.cpp
    decoders/aac_decoder/aac_decoder.cpp
    decoders/aac_decoder/libfaad/neaacdec.cpp
)

target_include_directories(aac_uecp PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/decoders)

# Enables SBR + PS (HE-AAC v1/v2) in aac_settings.h, as in UecpBridge.
target_compile_definitions(aac_uecp PRIVATE CONFIG_IDF_TARGET_ESP32S3)

if(MSVC)
    target_compile_options(aac_uecp PRIVATE /W3 /wd4996 /wd4702 /bigobj /utf-8)
else()
    target_compile_options(aac_uecp PRIVATE -Wno-register -Wno-format-security)
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(AAC_UECP_NAME aac_uecp_x64)
else()
    set(AAC_UECP_NAME aac_uecp_x86)
endif()

set_target_properties(aac_uecp PROPERTIES
    OUTPUT_NAME ${AAC_UECP_NAME}
    PREFIX ""
    RUNTIME_OUTPUT_DIRECTORY_RELEASE ${CMAKE_CURRENT_SOURCE_DIR}/../..
    RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO ${CMAKE_CURRENT_SOURCE_DIR}/../..
)
