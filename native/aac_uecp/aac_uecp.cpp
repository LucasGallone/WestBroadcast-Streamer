// aac_uecp.dll - extracts UECP (RDS) frames carried in AAC Data Stream Elements.
//
// Wraps the AAC decoder from UecpBridge (ESP32-audioI2S FAAD2 fork with the DSE -> UECP state
// machine in neaacdec.cpp's data_stream_element(), plus the app-side LATM/LOAS demuxer in
// aac_decoder.cpp). Same three-function C ABI as SatRDS-Monitor's aac_uecp DLL:
//
//   void* aac_decoder_init(void (*cb)(const uint8_t* frame, size_t len));
//   void  aac_decoder_feed(void* handle, const uint8_t* data, size_t len);
//   void  aac_decoder_close(void* handle);
//
// Differences from SatRDS-Monitor's build:
//   - cb receives the complete wire frame INCLUDING the 0xFE start and 0xFF end markers (inner
//     bytes still byte-stuffed, CRC not checked), so it can be forwarded as-is.
//   - Every handle is independent: no global lock is needed, any number of streams may be fed
//     concurrently from different threads (one thread per handle at a time).
//   - Input may be ADTS or LOAS/LATM, auto-detected, in arbitrary chunk sizes. Only complete
//     frames are passed to the decoder, so no large pre-buffer is needed (UecpBridge's 18000-byte
//     kMinBufferBeforeDecode exists only because decode() treats a truncated LOAS frame as an error).
//
// cb is called synchronously from inside aac_decoder_feed(), on the caller's thread.

#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include <vector>

#include "Audio.h"
#include "aac_decoder/aac_decoder.h"

#if defined(_WIN32)
#define AAC_UECP_API extern "C" __declspec(dllexport)
#else
#define AAC_UECP_API extern "C" __attribute__((visibility("default")))
#endif

typedef void (*uecp_callback_t)(const uint8_t* frame, size_t len);

namespace {

constexpr size_t kMaxBuffered = 256 * 1024; // drop stale input if we can never find sync
constexpr size_t kKeepOnOverflow = 16 * 1024;
constexpr int    kResMonoStereoChange = -21;

struct Instance {
    Audio                       audio;
    std::unique_ptr<AACDecoder> dec;
    uecp_callback_t             cb = nullptr;
    std::vector<uint8_t>        buf;
    std::vector<int32_t>        pcm = std::vector<int32_t>(4608 * 2);
    std::vector<uint8_t>        frame;
    bool                        synced = false;
};

// The vendored decoder reports UECP through one global free function, so route it to whichever
// instance is currently inside aac_decoder_feed() on this thread.
thread_local Instance* t_current = nullptr;

// Length of the ADTS/LOAS frame at p, or 0 if p isn't at a frame header of the locked format.
size_t frameLength(const uint8_t* p, size_t avail, bool latm) {
    if (latm) {
        if (avail < 3 || p[0] != 0x56 || (p[1] & 0xE0) != 0xE0) return 0;
        size_t muxlen = (static_cast<size_t>(p[1] & 0x1F) << 8) | p[2];
        return muxlen ? 3 + muxlen : 0;
    }
    if (avail < 7 || p[0] != 0xFF || (p[1] & 0xF6) != 0xF0) return 0;
    size_t len = (static_cast<size_t>(p[3] & 0x03) << 11) | (static_cast<size_t>(p[4]) << 3) | (p[5] >> 5);
    return len >= 7 ? len : 0;
}

void restartDecoder(Instance& in) {
    in.dec->reset();
    in.dec->init();
    in.synced = false;
}

void process(Instance& in) {
    size_t pos = 0;
    for (;;) {
        uint8_t* p = in.buf.data() + pos;
        size_t   avail = in.buf.size() - pos;

        if (!in.synced) {
            // findSyncWord() also returns -1 when it found a candidate but the confirming next
            // header isn't buffered yet, so keep the data and wait for more.
            int32_t s = in.dec->findSyncWord(p, static_cast<int32_t>(avail));
            if (s < 0) break;
            pos += static_cast<size_t>(s);
            in.synced = true;
            continue;
        }

        bool   latm = in.dec->isLatm();
        size_t flen = frameLength(p, avail, latm);
        if (flen == 0) {
            if (avail < (latm ? 3u : 7u)) break; // header not complete yet
            in.synced = false;                     // lost sync
            pos += 1;
            continue;
        }
        if (avail < flen) break; // wait for the rest of this frame

        int32_t left = static_cast<int32_t>(flen);
        int32_t res = in.dec->decode(p, &left, in.pcm.data());
        if (res == kResMonoStereoChange) {
            restartDecoder(in); // decoder can't switch channel layout in place; re-decode this frame
            continue;
        }
        if (res < 0 || res == AACDecoder::AAC_ID3_HDR) {
            in.synced = false;
            pos += 1;
            continue;
        }
        pos += flen;
    }

    if (pos) in.buf.erase(in.buf.begin(), in.buf.begin() + static_cast<std::ptrdiff_t>(pos));
    if (in.buf.size() > kMaxBuffered) {
        in.buf.erase(in.buf.begin(), in.buf.end() - kKeepOnOverflow);
        in.synced = false;
    }
}

} // namespace

// Strong definition of the hook the vendored decoder declares (see Audio.h / neaacdec.cpp).
// data/len are the still byte-stuffed bytes between 0xFE and 0xFF; restore the wire framing.
void audio_process_uecp(const uint8_t* data, size_t len) {
    Instance* in = t_current;
    if (!in || !in->cb) return;
    in->frame.resize(len + 2);
    in->frame[0] = 0xFE;
    if (len) std::memcpy(in->frame.data() + 1, data, len);
    in->frame[len + 1] = 0xFF;
    in->cb(in->frame.data(), in->frame.size());
}

AAC_UECP_API void* aac_decoder_init(uecp_callback_t cb) {
    try {
        auto in = std::make_unique<Instance>();
        in->cb = cb;
        in->dec = std::make_unique<AACDecoder>(in->audio);
        if (!in->dec->init()) return nullptr;
        return in.release();
    } catch (...) {
        return nullptr;
    }
}

AAC_UECP_API void aac_decoder_feed(void* handle, const uint8_t* data, size_t len) {
    if (!handle || !data || !len) return;
    Instance* in = static_cast<Instance*>(handle);
    Instance* prev = t_current;
    t_current = in;
    try {
        in->buf.insert(in->buf.end(), data, data + len);
        process(*in);
    } catch (...) {
        in->buf.clear();
        try { restartDecoder(*in); } catch (...) {}
    }
    t_current = prev;
}

AAC_UECP_API void aac_decoder_close(void* handle) {
    delete static_cast<Instance*>(handle); // ~AACDecoder() closes the FAAD handle
}
