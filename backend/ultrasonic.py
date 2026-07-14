"""
HC-SR04 ultrasonic distance sensor via GPIO (gpiozero).

Runs a background thread that polls the sensor at ~17 Hz and applies
a 1-D Kalman filter to smooth out noise.

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
from kalman import KalmanFilter1D

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
        # Rolling buffer for median pre-filter: rejects outlier spikes
        # (e.g. wall reflections giving 1.5m when person is at 0.6m)
        self._buffer: deque = deque(maxlen=5)
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._kalman = KalmanFilter1D(
            initial_estimate=0.6,
            process_noise=0.01,    # moderate — median filter already removes spikes
            measurement_noise=0.02,
        )

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
                    # Add to rolling buffer and compute median to reject outlier spikes
                    # (e.g. wall reflections, electrical noise bursts)
                    self._buffer.append(raw)
                    if len(self._buffer) >= 3:
                        stable_raw = median(self._buffer)
                        filtered = self._kalman.update(stable_raw)
                        with self._lock:
                            self._raw_m = raw         # actual sensor reading for diagnostics
                            self._distance_m = filtered
                            self._last_valid_time = time.monotonic()
            time.sleep(0.06)   # ~17 Hz matches HC-SR04 max update rate

    # Sensor is considered active when GPIO is enabled AND a valid reading
    # was received within the last 2 seconds. If the sensor is unplugged or
    # out of range, this returns False and distance properties return 0.0.
    _SENSOR_TIMEOUT_S = 2.0

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
        """Kalman-filtered distance in metres. Returns 0.0 when sensor inactive."""
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
