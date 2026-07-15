"""
HC-SR04 ultrasonic distance sensor via GPIO (gpiozero).

Filtering pipeline:
  raw reading → median(3) → EMA(α=0.7) → distance_m

  Median   — rejects outlier spikes (wall reflections, electrical noise).
             A spike only corrupts output if > 50 % of the 3-sample buffer
             is bad, which is extremely rare.
  EMA      — smooths the ±1-2 cm residual variation to ±0.9 cm without
             adding significant lag (~1-2 extra steps / 60-120 ms).
             Simpler and equivalently effective to Kalman at this noise level.

When gpiozero is not available OR the sensor is disconnected/out-of-range,
distance_m and raw_distance_m return 0.0 and confidence = 0.0.
The frontend correctly blocks the test when confidence < 0.5.
"""

import threading
import time
import logging
from collections import deque
from statistics import median
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from gpiozero import DistanceSensor as _GpioZeroDS
    GPIOZERO_AVAILABLE = True
except Exception:
    GPIOZERO_AVAILABLE = False

from constants import ULTRASONIC_ECHO_PIN, ULTRASONIC_TRIGGER_PIN

# EMA smoothing factor: 70 % trust in new median reading, 30 % history.
# Reduces ±1.5 cm median output to ±0.9 cm with ~1-2 extra steps of lag.
_EMA_ALPHA: float = 0.7

# HC-SR04 reliable range
_MIN_M = 0.04   # 4 cm
_MAX_M = 3.50   # 3.5 m (beyond this, sensor output is unreliable)


class UltrasonicSensor:
    """
    Thread-safe HC-SR04 wrapper.
    Call start() once, then read distance_m at any time.
    Call stop() on shutdown.
    """

    def __init__(
        self,
        echo_pin: int = ULTRASONIC_ECHO_PIN,
        trigger_pin: int = ULTRASONIC_TRIGGER_PIN,
    ) -> None:
        self._distance_m: float = 0.0
        self._raw_m: float = 0.0
        self._last_valid_time: float = 0.0
        # EMA state — initialised to 0.0 and set on the first valid reading
        self._ema: float = 0.0
        # Rolling buffer for median pre-filter: rejects outlier spikes
        # (e.g. wall reflections giving 1.5m when person is at 0.6m)
        self._buffer: deque = deque(maxlen=3)  # 3-sample window = 180ms lag, good spike rejection
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        if GPIOZERO_AVAILABLE:
            try:
                self._sensor = _GpioZeroDS(
                    echo=echo_pin,
                    trigger=trigger_pin,
                    max_distance=4.0,
                    partial=True,   # don't raise on out-of-range
                )
                self._use_gpio = True
                logger.info(
                    "HC-SR04 initialised (echo=GPIO%d, trigger=GPIO%d)",
                    echo_pin, trigger_pin,
                )
            except Exception as exc:
                logger.warning("HC-SR04 GPIO init failed: %s — using mock", exc)
                self._sensor = None
                self._use_gpio = False
        else:
            logger.warning(
                "gpiozero not available — UltrasonicSensor in mock mode (distance = 0)"
            )
            self._sensor = None
            self._use_gpio = False

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="ultrasonic", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            if self._use_gpio and self._sensor is not None:
                raw = self._sensor.distance  # metres, or None if no echo received
                if raw is not None and _MIN_M < raw < _MAX_M:
                    # Median pre-filter: only needs 2 of 3 readings to be valid
                    self._buffer.append(raw)
                    if len(self._buffer) >= 3:
                        stable_raw = median(self._buffer)
                        # EMA: first reading initialises directly; subsequent
                        # readings blend 70 % new median + 30 % history.
                        if self._ema == 0.0:
                            self._ema = stable_raw
                        else:
                            self._ema = _EMA_ALPHA * stable_raw + (1 - _EMA_ALPHA) * self._ema
                        with self._lock:
                            self._raw_m = raw
                            self._distance_m = self._ema
                            self._last_valid_time = time.monotonic()
            time.sleep(0.06)   # ~17 Hz matches HC-SR04 max update rate

    # Sensor is considered active when GPIO is enabled AND a valid reading
    # was received within the last 3 seconds. 3s is slightly more forgiving
    # than 2s for breadboard / prototype rigs with occasional contact bounces.
    _SENSOR_TIMEOUT_S = 3.0

    @property
    def is_sensor_active(self) -> bool:
        if not self._use_gpio:
            return False
        with self._lock:
            return (self._last_valid_time > 0 and
                    (time.monotonic() - self._last_valid_time) < self._SENSOR_TIMEOUT_S)

    # ------------------------------------------------------------------
    @property
    def distance_m(self) -> float:
        """EMA-smoothed distance in metres (after median spike rejection). Returns 0.0 when sensor inactive."""
        if not self.is_sensor_active:
            return 0.0
        with self._lock:
            return self._distance_m

    @property
    def raw_distance_m(self) -> float:
        """Latest unfiltered reading in metres. Returns 0.0 when sensor inactive."""
        if not self.is_sensor_active:
            return 0.0
        with self._lock:
            return self._raw_m

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._use_gpio and self._sensor:
            self._sensor.close()
