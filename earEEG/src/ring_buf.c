#include "ring_buf.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "ring_buf";

ring_buf_t *ring_buf_create(size_t capacity)
{
    if (capacity == 0) return NULL;

    ring_buf_t *rb = heap_caps_malloc(sizeof(ring_buf_t),
                                      MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    if (!rb) {
        ESP_LOGE(TAG, "malloc ring_buf_t failed");
        return NULL;
    }

    // SPIRAM can be enabled at boot or at runtime. Try SPIRAM first,
    // fall back to internal DRAM if SPIRAM is not available.
    rb->buffer = heap_caps_malloc(capacity, MALLOC_CAP_SPIRAM);
    if (!rb->buffer) {
        ESP_LOGW(TAG, "SPIRAM alloc failed, falling back to DRAM");
        rb->buffer = heap_caps_malloc(capacity, MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    }
    if (!rb->buffer) {
        ESP_LOGE(TAG, "buffer alloc failed (%u bytes)", (unsigned)capacity);
        heap_caps_free(rb);
        return NULL;
    }

    rb->capacity = capacity;
    rb->head = 0;
    rb->tail = 0;
    return rb;
}

void ring_buf_destroy(ring_buf_t *rb)
{
    if (!rb) return;
    heap_caps_free(rb->buffer);
    heap_caps_free(rb);
}

static inline size_t _min(size_t a, size_t b) { return a < b ? a : b; }

size_t ring_buf_write(ring_buf_t *rb, const uint8_t *data, size_t len)
{
    if (!rb || !data || len == 0) return 0;

    size_t head = rb->head;
    size_t tail = rb->tail;
    size_t cap = rb->capacity;

    // Calculate available space (SPSC with one-slot margin)
    size_t free;
    if (head >= tail) {
        free = (cap - 1) - (head - tail);
    } else {
        free = (tail - head) - 1;
    }
    if (free == 0) return 0;

    size_t to_write = _min(free, len);

    size_t first_chunk = _min(to_write, cap - head);
    memcpy(rb->buffer + head, data, first_chunk);
    if (to_write > first_chunk) {
        memcpy(rb->buffer, data + first_chunk, to_write - first_chunk);
    }

    rb->head = (head + to_write) % cap;
    __sync_synchronize(); // ensure Core 1 sees updated head
    return to_write;
}

size_t ring_buf_read(ring_buf_t *rb, uint8_t *out, size_t max_len)
{
    if (!rb || !out || max_len == 0) return 0;

    size_t head = rb->head;
    size_t tail = rb->tail;
    size_t cap = rb->capacity;

    size_t avail = (head >= tail) ? (head - tail) : (cap - tail + head);
    if (avail == 0) return 0;

    size_t to_read = _min(avail, max_len);
    size_t first_chunk = _min(to_read, cap - tail);
    memcpy(out, rb->buffer + tail, first_chunk);
    if (to_read > first_chunk) {
        memcpy(out + first_chunk, rb->buffer, to_read - first_chunk);
    }

    rb->tail = (tail + to_read) % cap;
    __sync_synchronize(); // ensure Core 0 sees updated tail
    return to_read;
}

size_t ring_buf_peek(const ring_buf_t *rb, uint8_t *out, size_t max_len)
{
    if (!rb || !out || max_len == 0) return 0;

    size_t head = rb->head;
    size_t tail = rb->tail;
    size_t cap = rb->capacity;

    size_t avail = (head >= tail) ? (head - tail) : (cap - tail + head);
    if (avail == 0) return 0;

    size_t to_read = _min(avail, max_len);
    size_t first_chunk = _min(to_read, cap - tail);
    memcpy(out, rb->buffer + tail, first_chunk);
    if (to_read > first_chunk) {
        memcpy(out + first_chunk, rb->buffer, to_read - first_chunk);
    }
    return to_read;
}

size_t ring_buf_free(const ring_buf_t *rb)
{
    if (!rb) return 0;
    size_t head = rb->head;
    size_t tail = rb->tail;
    return (head >= tail) ? (rb->capacity - 1 - (head - tail))
                          : (tail - head - 1);
}

size_t ring_buf_avail(const ring_buf_t *rb)
{
    if (!rb) return 0;
    size_t head = rb->head;
    size_t tail = rb->tail;
    return (head >= tail) ? (head - tail) : (rb->capacity - tail + head);
}

void ring_buf_reset(ring_buf_t *rb)
{
    if (!rb) return;
    rb->head = 0;
    rb->tail = 0;
}
