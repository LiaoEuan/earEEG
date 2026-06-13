"""NPZ session loader.

Reads recordings/*.npz files and returns structured NPZSession objects.
This module handles pure I/O — no unit conversion, no filtering.

EEG data is returned as-is from the NPZ (typically float32 raw ADC counts).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import NPZSession

# Default sample rates matching the earEEG device configuration.
DEFAULT_EEG_SAMPLE_RATE = 250.0
DEFAULT_MIC_SAMPLE_RATE = 16000.0


def load_npz_session(path: str | Path) -> NPZSession:
    """Load an NPZ recording session.

    Reads the NPZ file and returns a structured NPZSession.
    No unit conversion is performed — EEG remains in raw ADC counts.

    Args:
        path: Path to the .npz file.

    Returns:
        NPZSession with:
            - eeg: shape (channels, samples), float32
            - mic: shape (samples,), float32, or None if missing
            - stimuli: original shape or None
            - eeg_sample_rate: from file or default 250.0
            - mic_sample_rate: from file or default 16000.0

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If NPZ contains no 'eeg' key.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"NPZ file not found: {path}")

    npz = np.load(path, allow_pickle=True)

    if "eeg" not in npz:
        raise ValueError(f"NPZ file missing 'eeg' key: {path}")

    eeg = npz["eeg"]

    # Ensure EEG is (channels, samples)
    if eeg.ndim != 2:
        raise ValueError(
            f"EEG must be 2D (channels, samples), got shape {eeg.shape}"
        )

    # Load optional MIC, squeeze (M,1) -> (M,)
    mic = None
    if "mic" in npz:
        mic = npz["mic"]
        if mic.ndim == 2 and mic.shape[1] == 1:
            mic = mic.squeeze(axis=1)

    # Load optional stimuli
    stimuli = npz.get("stimuli", None)

    # Load sample rates with defaults
    eeg_sample_rate = _load_scalar(npz, "eeg_sample_rate", DEFAULT_EEG_SAMPLE_RATE)
    mic_sample_rate = _load_scalar(npz, "mic_sample_rate", DEFAULT_MIC_SAMPLE_RATE)

    # Collect remaining metadata
    metadata_keys = [
        k for k in npz.files
        if k not in ("eeg", "mic", "stimuli", "eeg_sample_rate", "mic_sample_rate")
    ]
    metadata = {k: npz[k] for k in metadata_keys}

    return NPZSession(
        path=path,
        eeg=eeg,
        mic=mic,
        stimuli=stimuli,
        eeg_sample_rate=float(eeg_sample_rate),
        mic_sample_rate=float(mic_sample_rate) if mic_sample_rate is not None else None,
        metadata=metadata,
    )


def _load_scalar(npz: np.lib.npyio.NpzFile, key: str, default: float) -> float:
    """Load a scalar value from NPZ, returning default if missing."""
    if key in npz:
        val = npz[key]
        return float(val)
    return default
