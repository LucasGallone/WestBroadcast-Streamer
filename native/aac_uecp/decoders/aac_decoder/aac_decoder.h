/*
 *  aac_decoder.h
 *  faad2 - ESP32 adaptation
 *  Created on: 12.09.2023
 *  Updated on: 13.06.2026
 */

#pragma once

#include "../Audio.h"
#include "libfaad/aac_settings.h"
#include "libfaad/aac_structs.h"
#include "libfaad/aac_defines.h"
#include "libfaad/aac_tables.h"
#include "libfaad/neaacdec.h"

#pragma GCC diagnostic warning "-Wunused-function"

class AACDecoder : public Decoder {

  public:
    enum : int8_t {
        AAC_ID3_HDR = 100,
        AAC_NONE = 0,
        AAC_ERR = -1,
    };

    AACDecoder(Audio& audioRef);
    ~AACDecoder() { reset(); }
    bool                  init() override;
    void                  clear() override;
    void                  reset() override;
    bool                  isValid() override;
    int32_t               findSyncWord(uint8_t* buf, int32_t nBytes) override;
    uint8_t               getChannels() override;
    uint32_t              getSampleRate() override;
    uint32_t              getOutputSamples();
    uint8_t               getBitsPerSample() override;
    uint32_t              getBitRate() override;
    uint32_t              getAudioDataStart() override;
    uint32_t              getAudioFileDuration() override;
    const char*           getStreamTitle() override;
    const char*           whoIsIt() override;
    int32_t               decode(uint8_t* inbuf, int32_t* bytesLeft, int32_t* outbuf) override;
    void                  setRawBlockParams(uint8_t channels, uint32_t sampleRate, uint8_t BPS, uint32_t tsis, uint32_t AuDaLength) override;
    std::vector<uint32_t> getMetadataBlockPicture() override;
    const char*           arg1() override;
    const char*           arg2() override;
    virtual int32_t       val1() override; // Paramertric Stereo
    virtual int32_t       val2() override; // SBR
    bool                  isLatm() override { return m_f_latm; }

  private:
    Audio&       audio;
    ps_ptr<char> m_arg1;
    void         createAudioSpecificConfig(uint8_t* config, uint8_t audioObjectType, uint8_t samplingFrequencyIndex, uint8_t channelConfiguration);
    error_info_t getErrorMessage(int8_t err);

    // ——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
    // LATM / LOAS support (AAC-LATM over live HTTP/Icecast streaming, no ADTS framing).
    // Ported field-by-field from TVHeadend's src/parsers/parser_latm.c (a proven, production reference),
    // deliberately restricted to the simple case: one program, one layer, audioMuxVersion 0, 1024-sample
    // frames only (frameLengthFlag rejected), variable-length PayloadLengthInfo framing (frameLengthType 0).
    // ——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
    struct LatmBitReader {
        const uint8_t* data = nullptr;
        uint32_t       bitpos = 0; // current position, in bits
        uint32_t       bitlen = 0; // total available bits
        void           init(const uint8_t* buf, uint32_t nbytes) {
            data = buf;
            bitpos = 0;
            bitlen = nbytes * 8;
        }
        uint32_t bitsLeft() const { return (bitpos < bitlen) ? (bitlen - bitpos) : 0; }
        uint32_t read_bits(uint8_t n) {
            uint32_t r = 0;
            for (uint8_t i = 0; i < n; i++) {
                uint8_t bit = 0;
                if (bitpos < bitlen) { bit = (data[bitpos >> 3] >> (7 - (bitpos & 7))) & 1; }
                r = (r << 1) | bit;
                bitpos++;
            }
            return r;
        }
        uint8_t read_bit() { return (uint8_t)read_bits(1); }
        uint32_t peek_bits(uint8_t n) { // non-consuming; mirrors the reference's show_bits()
            uint32_t saved = bitpos;
            uint32_t r = read_bits(n);
            bitpos = saved;
            return r;
        }
    };

    bool     m_f_latm = false;          // true once findSyncWord() has locked onto LOAS (vs ADTS) framing
    bool     m_latmConfigured = false;  // StreamMuxConfig has been successfully parsed at least once (NOT cleared by reset()/init())
    uint8_t  m_latmAot = 0;             // cached audioObjectType
    uint8_t  m_latmSri = 0;             // cached samplingFrequencyIndex (0-11)
    uint8_t  m_latmChannelConfig = 0;   // cached channelConfiguration (1-7)
    uint8_t  m_latmFrameLengthType = 0; // cached frameLengthType (only 0 - PayloadLengthInfo framing - is supported for decode)
    static constexpr uint32_t LATM_MAX_PAYLOAD = 8192; // 13-bit LOAS AudioMuxLengthBytes field hard ceiling
    uint8_t  m_latmPayload[LATM_MAX_PAYLOAD];
    uint32_t m_latmPayloadLen = 0;

    uint8_t  latmReadAot(LatmBitReader& br);
    uint32_t latmReadSr(LatmBitReader& br, uint8_t& sri);
    bool     latmReadAudioSpecificConfig(LatmBitReader& br, uint8_t& aot, uint8_t& sri, uint8_t& channelConfig);
    bool     latmReadStreamMuxConfig(LatmBitReader& br);
    int32_t  latmReadPayloadLengthInfo(LatmBitReader& br);
    bool     latmParseFrame(uint8_t* frame, uint32_t muxlen);

    NeAACDecHandle                m_hAac;
    NeAACDecFrameInfo             m_frameInfo;
    NeAACDecConfigurationPtr      m_conf;
    const uint8_t                 SYNCWORDH = 0xff; /* 12-bit syncword */
    const uint8_t                 SYNCWORDL = 0xf0;
    bool                          m_f_decoderIsInit = false;
    bool                          m_f_firstCall = false;
    bool                          m_f_setRaWBlockParams = false;
    uint32_t                      m_aacSamplerate = 0;
    uint8_t                       m_aacChannels = 0;
    uint8_t                       m_aacProfile = 0;
    uint16_t                      m_validSamples = 0;
    float                         m_compressionRatio = 1;
    std::unique_ptr<NeaacDecoder> m_neaacdec;

    struct AudioSpecificConfig {
        uint8_t audioObjectType;
        uint8_t samplingFrequencyIndex;
        uint8_t channelConfiguration;
    };

// ——————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————

};