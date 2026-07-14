"""
HC-SR04 ultrasonic distance sensor via GPIO (gpiozero).

Runs a background thread that polls the sensor at ~17 Hz and applies
a 1-D Kalman filter to smooth out noise.

Falls back to a static mock (0.6 m) when gpiozero is not available so
the rest of the backend works unchanged on a development laptop.
"""

import threading
import time
import logging
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
        self._distance_m: float = 0.6        # sensible default until first read
        self._raw_m: float = 0.6
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Tighter noise model for a static sensor measuring a seated person
        self._kalman = KalmanFilter1D(
            initial_estimate=0.6,
            process_noise=0.002,
            measurement_noise=0.015,
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
                "gpiozero not available — UltrasonicSensor running in mock mode (0.6 m)"
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
                raw = self._sensor.distance  # metres (None if out-of-range)
                if raw is not None and _MIN_M < raw < _MAX_M:
                    filtered = self._kalman.update(raw)
                    with self._lock:
                        self._raw_m = raw
                        self._distance_m = filtered
            time.sleep(0.06)   # ~17 Hz matches HC-SR04 max update rate

    # ------------------------------------------------------------------
    @property
    def distance_m(self) -> float:
        """Kalman-filtered distance in metres."""
        with self._lock:
            return self._distance_m

    @property
    def raw_distance_m(self) -> float:
        """Latest unfiltered reading in metres."""
        with self._lock:
            return self._raw_m

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._use_gpio and self._sensor:
            self._sensor.close()
