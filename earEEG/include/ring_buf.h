#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

typedef struct {
    uint8_t *buffer;
    size_t   capacity;
    volatile size_t head;  // producer index
    volatile size_t tail;  // consumer index
} ring_buf_t;

// Initialize a ring buffer, allocating `capacity` bytes from PSRAM.
// Returns NULL on failure.
ring_buf_t *ring_buf_create(size_t capacity);

// Free the ring buffer and its backing memory.
void ring_buf_destroy(ring_buf_t *rb);

// Producer: write `len` bytes. Returns bytes actually written (0 = full).
// Thread-safe for exactly one ISR/task producer.
size_t ring_buf_write(ring_buf_t *rb, const uint8_t *data, size_t len);

// Consumer: read up to `max_len` bytes. Returns bytes actually read.
// Thread-safe for exactly one task consumer.
size_t ring_buf_read(ring_buf_t *rb, uint8_t *out, size_t max_len);

// Consumer: peek at data without consuming. Returns bytes available.
size_t ring_buf_peek(const ring_buf_t *rb, uint8_t *out, size_t max_len);

// Free space available for writing.
size_t ring_buf_free(const ring_buf_t *rb);

// Occupied bytes available for reading.
size_t ring_buf_avail(const ring_buf_t *rb);

// Reset buffer to empty.
void ring_buf_reset(ring_buf_t *rb);
