#include "protocol.h"
#include "crc16.h"
#include <string.h>

bool proto_build_frame(uint8_t type, uint64_t timestamp,
                       const uint8_t *payload, uint16_t payload_len,
                       uint8_t *out, size_t out_capacity, size_t *out_len)
{
    size_t frame_len = PROTO_FRAME_OVERHEAD + payload_len;
    if (!out || !out_len || out_capacity < frame_len ||
        (payload_len > 0 && !payload)) {
        return false;
    }

    out[0] = PROTO_SYNC_0;
    out[1] = PROTO_SYNC_1;
    out[2] = type;
    out[3] = (uint8_t)(payload_len >> 8);
    out[4] = (uint8_t)payload_len;
    for (int i = 0; i < 8; i++) {
        out[5 + i] = (uint8_t)(timestamp >> (i * 8));
    }
    if (payload_len > 0 && payload != out + PROTO_HEADER_SIZE) {
        memcpy(out + PROTO_HEADER_SIZE, payload, payload_len);
    }

    uint16_t crc = crc16_ibm(out, PROTO_HEADER_SIZE + payload_len);
    out[PROTO_HEADER_SIZE + payload_len] = (uint8_t)crc;
    out[PROTO_HEADER_SIZE + payload_len + 1] = (uint8_t)(crc >> 8);
    *out_len = frame_len;
    return true;
}
