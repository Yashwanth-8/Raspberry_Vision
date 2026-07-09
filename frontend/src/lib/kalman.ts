/**
 * Simple 1D Kalman Filter for smoothing distance measurements.
 */
export class KalmanFilter {
    private x: number; // state estimate
    private P: number; // estimate covariance
    private Q: number; // process noise
    private R: number; // measurement noise

    constructor(initialEstimate: number, processNoise = 0.01, measurementNoise = 0.1) {
        this.x = initialEstimate;
        this.P = 1;
        this.Q = processNoise;
        this.R = measurementNoise;
    }

    update(measurement: number): number {
        // Prediction step (constant model — position doesn't change on its own)
        this.P = this.P + this.Q;

        // Update step
        const K = this.P / (this.P + this.R);
        this.x = this.x + K * (measurement - this.x);
        this.P = (1 - K) * this.P;

        return this.x;
    }

    get estimate(): number {
        return this.x;
    }

    reset(value: number) {
        this.x = value;
        this.P = 1;
    }
}
