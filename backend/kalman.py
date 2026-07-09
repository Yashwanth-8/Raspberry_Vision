"""
Port of src/lib/kalman.ts — 1D Kalman filter for distance smoothing.
"""


class KalmanFilter1D:
    """
    Simple 1D Kalman Filter for smoothing noisy distance measurements.
    Mirrors the KalmanFilter class in kalman.ts exactly.
    """

    def __init__(
        self,
        initial_estimate: float = 2.0,
        process_noise: float = 0.01,
        measurement_noise: float = 0.1,
    ) -> None:
        self._x = initial_estimate   # state estimate
        self._P = 1.0                # estimate covariance
        self._Q = process_noise      # process noise
        self._R = measurement_noise  # measurement noise

    def update(self, measurement: float) -> float:
        # Prediction step — constant model
        self._P = self._P + self._Q

        # Update step
        K = self._P / (self._P + self._R)
        self._x = self._x + K * (measurement - self._x)
        self._P = (1 - K) * self._P

        return self._x

    @property
    def estimate(self) -> float:
        return self._x

    def reset(self, value: float) -> None:
        self._x = value
        self._P = 1.0
