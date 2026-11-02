/*
 *  aac_decoder.cpp
 *  faad2 - ESP32 adaptation
 *  Created on: 12.09.2023
 *  Updated on: 18.07.2026
 */

#include "aac_decoder.h"
#include "Arduino.h"
#include "libfaad/neaacdec.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static uint32_t latmSampleRateFromSri(uint8_t sri); // defined near the other LATM helpers below, forward-declared for use in decode()

// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
AACDecoder::AACDecoder(Audio& audioRef) : Decoder(audioRef), audio(audioRef), m_neaacdec(std::make_unique<NeaacDecoder>()) {}

// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
bool AACDecoder::init() {
    m_hAac = m_neaacdec->NeAACDecOpen();
    m_conf = m_neaacdec->NeAACDecGetCurrentConfiguration(m_hAac);
    if (m_conf) { m_conf->outputFormat = FAAD_FMT_32BIT; }

    if (m_hAac && m_conf) m_f_decoderIsInit = true;
    m_f_firstCall = false;
    m_f_setRaWBlockParams = false;
    return m_f_decoderIsInit;
}
void AACDecoder::clear() {
    return; // nothing todo
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
void AACDecoder::reset() {
    m_neaacdec->NeAACDecClose(m_hAac);
    m_hAac = NULL;
    m_f_decoderIsInit = false;
    m_f_firstCall = false;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
bool AACDecoder::isValid() {
    return m_f_decoderIsInit;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
int32_t AACDecoder::findSyncWord(uint8_t* buf, int32_t nBytes) {
    const int MIN_ADTS_HEADER_SIZE = 7;
    if (buf == nullptr || nBytes < MIN_ADTS_HEADER_SIZE) { return -1; }

    auto validate = [MIN_ADTS_HEADER_SIZE](const uint8_t* buf, int32_t bytesAvailable) -> bool { // check the ADTS header for validity
        if (bytesAvailable < MIN_ADTS_HEADER_SIZE) { return false; }

        // Layer (bits 14-15) must be 00
        if ((buf[1] & 0x06) != 0x00) { return false; }

        // Sampling Frequency Index (Bits 18-21) cannot be invalid
        uint8_t sampling_frequency_index = (buf[2] & 0x3C) >> 2;
        if (sampling_frequency_index > 12) { return false; }

        // Frame length (bits 30-42) must be at least the header size
        int frame_length = ((buf[3] & 0x03) << 11) | (buf[4] << 3) | ((buf[5] & 0xE0) >> 5);
        if (frame_length < MIN_ADTS_HEADER_SIZE) { return false; }

        return true;
    };

    /* find byte-aligned syncword (12 bits = 0xFFF) */
    for (int32_t i = 0; i <= nBytes - MIN_ADTS_HEADER_SIZE; i++) {
        if ((buf[i + 0] & SYNCWORDH) == SYNCWORDH && (buf[i + 1] & SYNCWORDL) == SYNCWORDL) {
            int32_t bytesAvailable = nBytes - i;
            if (!validate(&buf[i], bytesAvailable)) { continue; }

            int frame_length = ((buf[i + 3] & 0x03) << 11) | (buf[i + 4] << 3) | ((buf[i + 5] & 0xE0) >> 5);
            if (i + frame_length + 1 >= nBytes) {
                return -1; // Puffergrenze überschritten, kein gültiger Header
            }
            /* find a second byte-aligned syncword (12 bits = 0xFFF) */
            if ((buf[i + frame_length + 0] & SYNCWORDH) == SYNCWORDH && (buf[i + frame_length + 1] & SYNCWORDL) == SYNCWORDL) {
                m_f_latm = false;
                return i;
            }
        }

        /* find LOAS/LATM syncword (11 bits = 0x2B7, i.e. 0x56 followed by top 3 bits of next byte = 111) */
        if (i + 4 <= nBytes && buf[i + 0] == 0x56 && (buf[i + 1] & 0xE0) == 0xE0) {
            uint32_t muxlen = ((uint32_t)(buf[i + 1] & 0x1F) << 8) | buf[i + 2];
            if (muxlen == 0 || muxlen > LATM_MAX_PAYLOAD) continue; // sanity bound
            if (i + 3 + (int32_t)muxlen + 1 >= nBytes) return -1;   // not enough data buffered yet, wait for more
            if ((buf[i + 3] & 0x80) != 0) continue;                // require useSameStreamMux==0: first frame must carry a full StreamMuxConfig
            /* confirm a second LOAS syncword follows immediately after this frame */
            if (buf[i + 3 + muxlen] == 0x56 && (buf[i + 3 + muxlen + 1] & 0xE0) == 0xE0) {
                m_f_latm = true;
                return i;
            }
        }
    }

    return -1;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint8_t AACDecoder::getChannels() {
    return m_aacChannels;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint32_t AACDecoder::getSampleRate() {
    return m_aacSamplerate;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint32_t AACDecoder::getOutputSamples() {
    return m_validSamples;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint8_t AACDecoder::getBitsPerSample() {
    return 32;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint32_t AACDecoder::getBitRate() {
    uint32_t br = getBitsPerSample() * getChannels() * getSampleRate();
    return (br / m_compressionRatio);
    ;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint32_t AACDecoder::getAudioDataStart() {
    return 0; // nothing todo
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint32_t AACDecoder::getAudioFileDuration() {
    return 0; // nothing todo
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
const char* AACDecoder::getStreamTitle() {
    return nullptr; // nothing todo
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
const char* AACDecoder::whoIsIt() {
    return "AAC";
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
error_info_t AACDecoder::getErrorMessage(int8_t err) {
    return m_neaacdec->NeAACDecGetErrorMessage(abs(err));
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
int32_t AACDecoder::decode(uint8_t* inbuf, int32_t* bytesLeft, int32_t* outbuf) {

    void*    sample_buffer = outbuf;
    uint8_t* decIn = inbuf;
    int32_t  decAvail = *bytesLeft;
    int32_t  latmFrameBytes = 0;

    if (m_f_latm) {
        if (*bytesLeft < 3) return AAC_ERR;
        uint32_t muxlen = ((uint32_t)(inbuf[1] & 0x1F) << 8) | inbuf[2];
        if ((int32_t)(3 + muxlen) > *bytesLeft) return AAC_ERR; // truncated at chunk tail: mirror the existing ADTS truncation precedent (generic decodeError() reseek), not a new "wait for more data" mechanism
        if (!latmParseFrame(inbuf + 3, muxlen)) return AAC_ERR;
        latmFrameBytes = 3 + (int32_t)muxlen;
        decIn = m_latmPayload;
        decAvail = (int32_t)m_latmPayloadLen;
        if (!m_f_firstCall && !m_f_setRaWBlockParams) { setRawBlockParams(m_latmChannelConfig, latmSampleRateFromSri(m_latmSri), 0, m_latmAot, 0); }
    }

    if (m_f_firstCall == false) {
        if (m_f_setRaWBlockParams) { // set raw AAC values, e.g. for M4A config, or LATM's per-stream config
            m_f_setRaWBlockParams = false;
            m_conf->defSampleRate = m_aacSamplerate;
            m_conf->outputFormat = FAAD_FMT_32BIT;
            m_conf->useOldADTSFormat = 1;
            m_conf->defObjectType = 2;
            int8_t ret = m_neaacdec->NeAACDecSetConfiguration(m_hAac, m_conf);
            (void)ret;

            uint8_t specificInfo[2];
            createAudioSpecificConfig(specificInfo, m_aacProfile, m_neaacdec->get_sr_index(m_aacSamplerate), m_aacChannels);
            int8_t err = m_neaacdec->NeAACDecInit2(m_hAac, specificInfo, 2, &m_aacSamplerate, &m_aacChannels);
            (void)err;
        } else {
            m_neaacdec->NeAACDecSetConfiguration(m_hAac, m_conf);
            int8_t err = m_neaacdec->NeAACDecInit(m_hAac, decIn, decAvail, &m_aacSamplerate, &m_aacChannels);
            (void)err;
        }
        m_f_firstCall = true;
    }

    m_neaacdec->NeAACDecDecode2(m_hAac, &m_frameInfo, decIn, decAvail, &sample_buffer, 4608 * 2 * sizeof(int32_t));
    // m_frameInfo.bytesconsumed refers to decIn (the LATM scratch buffer when m_f_latm, otherwise inbuf itself) - the
    // caller-visible *bytesLeft must always be decremented by the true on-wire byte count, which for LATM is the whole
    // LOAS frame (3-byte header + muxlen), NOT whatever the scratch-buffer decode reports consuming.
    if (m_f_latm) *bytesLeft -= latmFrameBytes;
    else *bytesLeft -= m_frameInfo.bytesconsumed;
    m_validSamples = m_frameInfo.samples;
    int8_t err = 0 - m_frameInfo.error;
    m_compressionRatio = (float)m_frameInfo.samples * 2 / m_frameInfo.bytesconsumed;
    if (err < 0) {
        if (err == -100) return AAC_ID3_HDR; // ID3 header found
        else{
            if(getErrorMessage(abs(err)).level == AAC_ERROR) AAC_LOG_ERROR("{}", getErrorMessage(abs(err)).text);
            if(getErrorMessage(abs(err)).level == AAC_WARN) AAC_LOG_WARN("{}", getErrorMessage(abs(err)).text);
            if(getErrorMessage(abs(err)).level == AAC_INFO) AAC_LOG_INFO("{}", getErrorMessage(abs(err)).text);
            if(getErrorMessage(abs(err)).level == AAC_DEBUG) AAC_LOG_DEBUG("{}", getErrorMessage(abs(err)).text);
            if(getErrorMessage(abs(err)).level == AAC_VERBOSE) AAC_LOG_VERBOSE("{}", getErrorMessage(abs(err)).text);
        }
    } else {
        if (m_aacChannels == 1 && !m_frameInfo.isPS) { // ESP32-S3 and -P4 has ParametricStereo activated
            AAC_LOG_ERROR("1");
            for (int32_t i = m_validSamples - 1; i >= 0; i--) {
                int32_t sample = outbuf[i];
                outbuf[i * 2] = sample;
                outbuf[i * 2 + 1] = sample;
            }
        }
    }
    return err;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
void AACDecoder::setRawBlockParams(uint8_t channels, uint32_t sampleRate, uint8_t dummy1, uint32_t profile, uint32_t dummy2) {
    m_f_setRaWBlockParams = true;
    m_aacChannels = channels;     // 1: Mono, 2: Stereo
    m_aacSamplerate = sampleRate; // 8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000
    m_aacProfile = profile;       // 1: AAC Main, 2: AAC LC (Low Complexity), 3: AAC SSR (Scalable Sample Rate), 4: AAC LTP (Long Term Prediction)
    return;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
std::vector<uint32_t> AACDecoder::getMetadataBlockPicture() {
    std::vector<uint32_t> a;
    return a;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
const char* AACDecoder::arg1() { // AAC format
    m_arg1.assign("AAC HeaderFormat: ");
    if (m_frameInfo.header_type == 0)
        m_arg1.append("RAW");
    else if (m_frameInfo.header_type == 1)
        m_arg1.append("ADIF"); /* single ADIF header at the beginning of the file */
    else if (m_frameInfo.header_type == 2)
        m_arg1.append("ADTS"); /* ADTS header at the beginning of each frame */
    else
        m_arg1.append("unknown");
    return m_arg1.c_get();
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
const char* AACDecoder::arg2() {
    if (m_frameInfo.sbr == 1) return "upsampled SBR";
    if (m_frameInfo.sbr == 2) return "downsampled SBR";
    if (m_frameInfo.sbr == 3) return "no SBR used, but file is upsampled by a factor 2";
    return "without SBR";
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
int32_t AACDecoder::val1() { // Parametric Stereo
    return m_frameInfo.isPS;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
int32_t AACDecoder::val2() { // Spectral Band Replication
    return m_frameInfo.sbr;  // NO_SBR           0 /* no SBR used in this file */
                             // SBR_UPSAMPLED    1 /* upsampled SBR used */
                             // SBR_DOWNSAMPLED  2 /* downsampled SBR used */
                             // NO_SBR_UPSAMPLED 3 /* no SBR used, but file is upsampled by a factor 2 anyway */
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
void AACDecoder::createAudioSpecificConfig(uint8_t* config, uint8_t audioObjectType, uint8_t samplingFrequencyIndex, uint8_t channelConfiguration) {
    config[0] = (audioObjectType << 3) | (samplingFrequencyIndex >> 1);
    config[1] = (samplingFrequencyIndex << 7) | (channelConfiguration << 3);
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
// extern uint8_t NeaacDecoder::get_sr_index(const uint32_t samplerate);
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
/* L A T M  /  L O A S   -   ported field-by-field from TVHeadend's src/parsers/parser_latm.c              */
/* (Copyright (C) 2009 Andreas Öman, based on a LATM parser patch for ffmpeg by Paul Kendall, LGPL-2.1+)    */
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
static const uint32_t LATM_SAMPLE_RATES[12] = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000};

static uint32_t latmSampleRateFromSri(uint8_t sri) { return (sri < 12) ? LATM_SAMPLE_RATES[sri] : 0; }

static int32_t latmRateToSri(uint32_t rate) {
    for (int32_t i = 0; i < 12; i++) {
        if (LATM_SAMPLE_RATES[i] == rate) return i;
    }
    return -1;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint8_t AACDecoder::latmReadAot(LatmBitReader& br) {
    uint8_t aot = (uint8_t)br.read_bits(5);
    if (aot == 28) aot = (uint8_t)br.read_bits(6); // AOT_ESCAPE=28 per reference; replaces (not +32) - ported as-is
    return aot;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
uint32_t AACDecoder::latmReadSr(LatmBitReader& br, uint8_t& sri) {
    sri = (uint8_t)br.read_bits(4);
    if (sri == 0x0F) return br.read_bits(24); // explicit sample rate - bits must still be consumed correctly even though out of scope
    return latmSampleRateFromSri(sri);
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
bool AACDecoder::latmReadAudioSpecificConfig(LatmBitReader& br, uint8_t& aot, uint8_t& sri, uint8_t& channelConfig) {
    aot = latmReadAot(br);
    uint32_t sr = latmReadSr(br, sri);
    channelConfig = (uint8_t)br.read_bits(4);

    if (sr < 7350 || sr > 96000 || channelConfig == 0 || channelConfig > 7) return false;

    bool extSriSet = false;
    if (aot == 5 /* AOT_SBR */ || (aot == 26 /* AOT_PS */ && !(br.peek_bits(3) & 3 && !(br.peek_bits(9) & 0x3F)))) {
        uint8_t   extSri;
        uint32_t  extSr = latmReadSr(br, extSri);
        if (extSr < 7350 || extSr > 96000) return false;
        extSriSet = true;
        aot = latmReadAot(br); // this is the main (non-extended) object type
    }

    if (!extSriSet && sr <= 24000) {
        if (latmRateToSri(sr * 2) < 0) return false; // "assume SBR extension" guess, per reference - no bits consumed, validation only
    }

    if (br.read_bit()) return false; // framelen_flag - 960-sample frames not supported (user-confirmed out of scope)
    if (br.read_bit()) br.read_bits(14); // depends_on_coder -> coreCoderDelay
    if (br.read_bit()) br.read_bits(1);  // ext_flag -> ext3_flag (NOT a reject - just consume one more bit)
    return true;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
bool AACDecoder::latmReadStreamMuxConfig(LatmBitReader& br) {
    uint8_t audioMuxVersion = br.read_bit();
    if (audioMuxVersion) return false; // audioMuxVersion==1 (and versionA variants) always end in rejection in the reference too; short-circuit

    br.read_bit();  // allStreamsSameTimeFraming - reference only skips this, does not validate it
    br.read_bits(6); // numSubFrames - reference only skips this, does not validate it
    if (br.read_bits(4)) return false; // numPrograms must be the raw value 0 (i.e. exactly one program)
    if (br.read_bits(3)) return false; // numLayer must be the raw value 0 (i.e. exactly one layer)

    uint8_t aot, sri, channelConfig;
    if (!latmReadAudioSpecificConfig(br, aot, sri, channelConfig)) return false;

    uint8_t frameLengthType = (uint8_t)br.read_bits(3);
    switch (frameLengthType) {
        case 0: br.read_bits(8); break;
        case 1: br.read_bits(9); break;
        case 3:
        case 4:
        case 5: br.read_bits(6); break; // celp_table_index
        case 6:
        case 7: br.read_bits(1); break; // hvxc_table_index
        default: break;
    }

    if (br.read_bit()) { // otherDataPresent
        uint8_t esc;
        do {
            esc = br.read_bit();
            br.read_bits(8);
        } while (esc);
    }

    if (br.read_bit()) br.read_bits(8); // crcCheckPresent -> config_crc

    m_latmAot = aot;
    m_latmSri = sri;
    m_latmChannelConfig = channelConfig;
    m_latmFrameLengthType = frameLengthType;
    m_latmConfigured = true;
    return true;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
int32_t AACDecoder::latmReadPayloadLengthInfo(LatmBitReader& br) {
    uint32_t slot_len = 0;
    uint8_t  tmp;
    do {
        tmp = (uint8_t)br.read_bits(8);
        slot_len += tmp;
        if (slot_len > LATM_MAX_PAYLOAD) return -1; // defensive bound, in addition to natural termination
    } while (tmp == 0xFF);
    return (int32_t)slot_len;
}
// —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
bool AACDecoder::latmParseFrame(uint8_t* frame, uint32_t muxlen) {
    LatmBitReader br;
    br.init(frame, muxlen); // frame points at byte 3 of the LOAS header (sync+length already validated by findSyncWord())

    uint8_t useSameStreamMux = br.read_bit();
    if (!useSameStreamMux) {
        if (!latmReadStreamMuxConfig(br)) return false;
    } else if (!m_latmConfigured) {
        return false; // should not happen at initial lock-on (findSyncWord requires useSameStreamMux==0 there), but guard anyway
    }

    if (m_latmFrameLengthType != 0) return false; // only PayloadLengthInfo (variable-length) framing is supported

    int32_t slot_len = latmReadPayloadLengthInfo(br);
    if (slot_len < 0) return false;
    if ((br.bitsLeft() / 8) < (uint32_t)slot_len) return false; // not enough bits left for the declared payload

    for (int32_t i = 0; i < slot_len; i++) { m_latmPayload[i] = (uint8_t)br.read_bits(8); }
    m_latmPayloadLen = (uint32_t)slot_len;
    return true;
}
