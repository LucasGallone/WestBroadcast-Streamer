// Linux test-harness stand-in for ESP32-audioI2S's Audio.h.
//
// aac_decoder.h ("../Audio.h"), aac_decoder/libfaad/aac_defines.h ("../../Audio.h") and
// mp2_decoder.h ("../Audio.h") all pull in the real Audio.h purely to get two things:
// the abstract Decoder base class, and the static Audio::AUDIO_LOG_IMPL(...) logging
// helper the AAC_LOG_*/MP2_LOG_* macros expand to. Neither decoder .cpp dereferences
// any other Audio member, so this header intentionally provides only those two pieces
// instead of the full WiFi/SD/I2S-laden original.
#pragma once

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <utility>
#include <vector>

#include "psram_unique_ptr.hpp"

// UecpBridge/MSVC compatibility shim: __attribute__((weak)) is a GCC/Clang extension that
// plain MSVC (cl.exe) doesn't parse at all - a hard compile error, not just a warning. This
// project never relies on the weak *default* (a real audio_process_uecp() definition is always
// linked in from src/app/bridge_app.cpp), so dropping the attribute under MSVC changes nothing
// behaviorally; it's purely a parser compatibility shim. Same macro is reused by
// aac_decoder/libfaad/neaacdec.cpp's own re-declaration of this symbol below.
#if defined(_MSC_VER) && !defined(__clang__)
#define UECP_WEAK
#else
#define UECP_WEAK __attribute__((weak))
#endif

// One complete raw (still byte-stuffed) UECP frame, bytes between 0xFE and 0xFF exclusive.
// aac_decoder/libfaad/neaacdec.cpp self-declares its own copy of this (to avoid depending on
// Audio.h at all), but mp2_decoder.cpp relies on getting it from here, same as the real Audio.h.
extern UECP_WEAK void audio_process_uecp(const uint8_t* data, size_t len);

class Audio {
  public:
    // fmt uses ps_ptr<char>::appendf's "{}" placeholder style (see AAC_LOG_ERROR("{}", text) call
    // sites), NOT printf's "%s" - matching the real Audio::AUDIO_LOG_IMPL, which builds its message
    // the same way via logStr.appendf(fmt, ...). A naive std::fprintf(stderr, fmt, ...) here would
    // silently drop every argument, since "{}" isn't a printf conversion specifier.
    template <typename... Args>
    static void AUDIO_LOG_IMPL(uint8_t level, const char* path, int line, const char* func, const char* fmt, Args&&... args) {
#ifndef AAC_UECP_LOG
        // aac_uecp.dll: silent by default - the host (WestBroadcast Streamer) owns the console, and
        // the decoder logs on every mono frame. Build with -DAAC_UECP_LOG to get these back.
        (void)level; (void)path; (void)line; (void)func; (void)fmt; ((void)args, ...);
        return;
#endif
        static const char* const tag[6] = {"", "ERROR", "WARN", "INFO", "DEBUG", "VERBOSE"};
        const char* base = path;
        for (const char* p = path; *p; ++p) {
            if (*p == '/' || *p == '\\') base = p + 1;
        }
        ps_ptr<char> msg;
        msg.appendf(fmt, std::forward<Args>(args)...);
        std::fprintf(stderr, "[%s] %s:%d %s] %s\n", level <= 5 ? tag[level] : "", base, line, func ? func : "", msg.c_get() ? msg.c_get() : "");
    }
};

class Decoder {
  public:
    virtual ~Decoder() = default;
    virtual bool                  init() = 0;
    virtual void                  clear() = 0;
    virtual void                  reset() = 0;
    virtual bool                  isValid() = 0;
    virtual int32_t               findSyncWord(uint8_t* buf, int32_t nBytes) = 0;
    virtual uint8_t               getChannels() = 0;
    virtual uint32_t              getSampleRate() = 0;
    virtual uint8_t               getBitsPerSample() = 0;
    virtual uint32_t              getBitRate() = 0;
    virtual uint32_t              getAudioDataStart() = 0;
    virtual uint32_t              getAudioFileDuration() = 0;
    virtual uint32_t              getOutputSamples() = 0;
    virtual int32_t                decode(uint8_t* inbuf, int32_t* bytesLeft, int32_t* outbuf1) = 0;
    virtual void                  setRawBlockParams(uint8_t param1, uint32_t param2, uint8_t param3, uint32_t param4, uint32_t param5) = 0;
    virtual const char*           getStreamTitle() { return nullptr; }
    virtual const char*           whoIsIt() { return nullptr; }
    virtual bool                  isLatm() { return false; } // true only for AACDecoder when the current stream is LOAS/LATM framed
    virtual std::vector<uint32_t> getMetadataBlockPicture() = 0;
    virtual const char*           arg1() = 0; // decoder specific
    virtual const char*           arg2() = 0; // decoder specific
    virtual int32_t               val1() = 0; // decoder specific
    virtual int32_t               val2() = 0; // decoder specific

  protected:
    Decoder(Audio& audioRef) : audio(audioRef) {}
    Audio& audio;

  private:
    Decoder() = delete;
};
