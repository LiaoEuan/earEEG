import math
import unittest

import numpy as np

from upper_machine.impedance import (
    adc_volts_per_count,
    calculate_impedance,
    classify_impedance,
    openbci_impedance_command,
    parse_channels,
    tone_rms_counts,
)


class ImpedanceTest(unittest.TestCase):
    def test_tone_rms_counts(self):
        sample_rate = 250.0
        frequency = 31.25
        expected_rms = 1000.0
        t = np.arange(750) / sample_rate
        samples = expected_rms * math.sqrt(2.0) * np.sin(2 * np.pi * frequency * t)
        self.assertAlmostEqual(tone_rms_counts(samples, sample_rate, frequency), expected_rms, places=3)

    def test_calculate_impedance(self):
        sample_rate = 250.0
        frequency = 31.25
        total_ohm = 12200.0
        rms_volts = total_ohm * 6e-9 / math.sqrt(2.0)
        rms_counts = rms_volts / adc_volts_per_count(24.0)
        t = np.arange(750) / sample_rate
        samples = rms_counts * math.sqrt(2.0) * np.sin(2 * np.pi * frequency * t)

        _, total_kohm, electrode_kohm = calculate_impedance(samples)
        self.assertAlmostEqual(total_kohm, 12.2, places=3)
        self.assertAlmostEqual(electrode_kohm, 10.0, places=3)

    def test_commands_and_channel_parsing(self):
        self.assertEqual(openbci_impedance_command(1, True), "z110Z")
        self.assertEqual(openbci_impedance_command(9, False), "zQ00Z")
        self.assertEqual(parse_channels("1-3,5"), [1, 2, 3, 5])

    def test_quality_thresholds(self):
        self.assertEqual(classify_impedance(9.9, 10.0, 20.0), "good")
        self.assertEqual(classify_impedance(10.0, 10.0, 20.0), "acceptable")
        self.assertEqual(classify_impedance(20.0, 10.0, 20.0), "adjust-electrode")


if __name__ == "__main__":
    unittest.main()
