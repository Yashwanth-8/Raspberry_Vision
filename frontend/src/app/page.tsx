"use client";

import { motion, AnimatePresence } from "framer-motion";
import { useAppStore } from "@/lib/store";
import LandingScreen from "@/components/screens/LandingScreen";
import CalibrationScreen from "@/components/screens/CalibrationScreen";
import IPDScreen from "@/components/screens/IPDScreen";
import MobileCalibrationScreen from "@/components/screens/MobileCalibrationScreen";
import CameraSetupScreen from "@/components/screens/CameraSetupScreen";
import TestScreen from "@/components/screens/TestScreen";
import ResultsScreen from "@/components/screens/ResultsScreen";

const screenVariants = {
  initial: { opacity: 0, y: 20, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -20, scale: 0.98 },
};

export default function Home() {
  const screen = useAppStore((s) => s.screen);

  return (
    <main className="relative z-10 min-h-screen">
      <AnimatePresence mode="wait">
        <motion.div
          key={screen}
          variants={screenVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          className="min-h-screen"
        >
          {screen === "landing" && <LandingScreen />}
          {screen === "calibration" && <CalibrationScreen />}
          {screen === "ipd" && <IPDScreen />}
          {screen === "mobile-calibration" && <MobileCalibrationScreen />}
          {screen === "camera-setup" && <CameraSetupScreen />}
          {screen === "test" && <TestScreen />}
          {screen === "results" && <ResultsScreen />}
        </motion.div>
      </AnimatePresence>
    </main>
  );
}
