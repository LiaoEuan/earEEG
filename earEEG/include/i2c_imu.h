#pragma once

#include <stdint.h>
#include <stdbool.h>

// Latest IMU data (updated by BNO085 polling task)
typedef struct {
    float    quat_w, quat_x, quat_y, quat_z;  // unit quaternion
    int16_t  gyro_x, gyro_y, gyro_z;          // raw calibrated gyro
    int16_t  accel_x, accel_y, accel_z;        // raw accelerometer
    uint64_t timestamp;                        // cycle count when read
    bool     valid;                            // true after first valid read
} imu_sample_t;

extern imu_sample_t g_imu_latest;

// Initialize BNO085 I2C bus and start polling task.
bool imu_bno085_init(void);

// Start 250Hz polling.
void imu_bno085_start(void);

// Stop polling.
void imu_bno085_stop(void);
