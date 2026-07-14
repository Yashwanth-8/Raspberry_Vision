export interface DeviceConfig {
    mmPerPx: number;
    deviceLabel: string;
    provisioned: boolean;
}

export async function loadDeviceConfig(): Promise<DeviceConfig | null> {
    try {
        const response = await fetch("/device-config.json", { cache: "no-store" });
        if (!response.ok) return null;
        const cfg = await response.json();
        if (typeof cfg?.mmPerPx !== "number" || cfg.mmPerPx <= 0) return null;
        return {
            mmPerPx: cfg.mmPerPx,
            deviceLabel: typeof cfg.deviceLabel === "string" ? cfg.deviceLabel : "Device config",
            provisioned: Boolean(cfg.provisioned),
        };
    } catch {
        return null;
    }
}
