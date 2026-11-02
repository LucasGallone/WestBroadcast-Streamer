// Minimal stand-in for Arduino.h, resolved via the compiler's quoted-include
// search path (these vendored files sit in their own subdirectories and have
// no local Arduino.h, so the search falls back to this one). Only the handful
// of symbols the AAC/MP2/MP3 decoders and psram_unique_ptr.hpp actually touch
// on ESP32 - the PSRAM allocator, the esp32-hal-log.h logging macros, millis(),
// and the PROGMEM pgm_read_*() accessors (MP3's own fake-frame/network-error
// heuristic and Huffman table lookups are the first vendored code here to need
// the latter two) - are provided. No String/Serial/Stream: nothing calls them.
#pragma once

#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <limits>
#include <type_traits>

// arduino-esp32's Arduino.h defines these as global (non-std::) template functions;
// aac_settings.h deliberately skips its own min/max macro fallback in C++ mode
// (`#if !defined(max) && !defined(__cplusplus)`) expecting exactly this to exist.
//
// Return by value via common_type, NOT `decltype(a < b ? a : b)`: when a and b are
// same-typed lvalue parameters, that ternary is itself an lvalue, so decltype resolves
// to a reference - to a parameter that no longer exists once the function returns.
// That dangling reference doesn't crash at -O2 (aggressively inlined before it can
// matter) but is a real stack-use-after-return, confirmed by ASan under -O0.
template <typename T, typename U> inline typename std::common_type<T, U>::type min(T a, U b) { return (a < b) ? a : b; }
template <typename T, typename U> inline typename std::common_type<T, U>::type max(T a, U b) { return (a > b) ? a : b; }

#ifndef __unused
    // UecpBridge/MSVC compatibility shim (see Audio.h's UECP_WEAK comment): __attribute__((unused))
    // doesn't parse under MSVC; it's only a warning-suppression hint, so a no-op there is inert.
    #if defined(_MSC_VER) && !defined(__clang__)
        #define __unused
    #else
        #define __unused __attribute__((unused))
    #endif
#endif

#ifndef PROGMEM
    #define PROGMEM
#endif

// arduino-esp32's own pgm_read_byte()/pgm_read_word() are plain dereferences on ESP32 (a flat
// memory model with no AVR-style separate program-memory address space, unlike where PROGMEM
// actually matters) - matching that, not stubbing something more elaborate.
#ifndef pgm_read_byte
    #define pgm_read_byte(addr) (*reinterpret_cast<const uint8_t*>(addr))
#endif
#ifndef pgm_read_word
    #define pgm_read_word(addr) (*reinterpret_cast<const uint16_t*>(addr))
#endif

// Arduino's millis(): milliseconds since some fixed (here, process-start) reference point, same
// uint32_t-wraps-eventually contract real hardware has (MP3Decoder's own fake-frame/"network
// error" heuristic - the only caller - is designed for that on real hardware already, so wrapping
// here changes nothing it depends on).
inline uint32_t millis() {
    static const auto start = std::chrono::steady_clock::now();
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count());
}

inline void* ps_malloc(size_t size) { return std::malloc(size); }
inline void* ps_calloc(size_t count, size_t size) { return std::calloc(count, size); }
inline bool  psramFound() { return true; }

inline void esp32_hal_log_stub(const char* level, const char* fmt, va_list args) {
#ifndef AAC_UECP_LOG
    (void)level; (void)fmt; (void)args; // aac_uecp.dll: silent by default, see Audio.h
    return;
#endif
    std::fprintf(stderr, "[%s] ", level);
    std::vfprintf(stderr, fmt, args);
    std::fprintf(stderr, "\n");
}

#define ESP32_HAL_LOG_STUB_IMPL(level, fmt)                    \
    do {                                                       \
        va_list args;                                          \
        va_start(args, fmt);                                   \
        esp32_hal_log_stub(level, fmt, args);                   \
        va_end(args);                                           \
    } while (0)

inline void log_e(const char* fmt, ...) { ESP32_HAL_LOG_STUB_IMPL("E", fmt); }
inline void log_w(const char* fmt, ...) { ESP32_HAL_LOG_STUB_IMPL("W", fmt); }
inline void log_i(const char* fmt, ...) { ESP32_HAL_LOG_STUB_IMPL("I", fmt); }
inline void log_d(const char* fmt, ...) { ESP32_HAL_LOG_STUB_IMPL("D", fmt); }
inline void log_v(const char* fmt, ...) { ESP32_HAL_LOG_STUB_IMPL("V", fmt); }
