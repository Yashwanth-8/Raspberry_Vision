"""
Face detection and landmark extraction using MediaPipe Face Mesh (Python).
Mirrors the @mediapipe/face_mesh JS usage in CameraSetupScreen.tsx and TestScreen.tsx.
"""

import mediapipe as mp
import numpy as np
from typing import Optional


class FaceDetector:
    """
    Wraps MediaPipe FaceMesh with refineLandmarks=True (iris landmarks included).
    Processes BGR frames from PiCamera and returns landmark lists.
    """

    def __init__(
        self,
        max_num_faces: int = 1,
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        self._mp_face_mesh = mp.solutions.face_mesh
        self._face_mesh = self._mp_face_mesh.FaceMesh(
            max_num_faces=max_num_faces,
            refine_landmarks=refine_landmarks,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def process(self, bgr_frame: np.ndarray) -> dict:
        """
        Process a single BGR frame.

        Returns:
            {
                "face_detected": bool,
                "face_count": int,
                "landmarks": list | None,   # list of landmark objects with .x .y .z
            }
        """
        # MediaPipe expects RGB
        rgb = bgr_frame[:, :, ::-1].copy()
        rgb.flags.writeable = False
        results = self._face_mesh.process(rgb)

        face_count = (
            len(results.multi_face_landmarks)
            if results.multi_face_landmarks
            else 0
        )
        face_detected = face_count > 0
        landmarks = (
            list(results.multi_face_landmarks[0].landmark)
            if face_detected
            else None
        )

        return {
            "face_detected": face_detected,
            "face_count": face_count,
            "landmarks": landmarks,
        }

    def close(self) -> None:
        self._face_mesh.close()
