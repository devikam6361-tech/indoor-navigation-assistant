from ultralytics import YOLO
import cv2
import win32com.client
import time


# ==========================================
# 1. LOAD YOLO MODEL
# ==========================================

model = YOLO("yolo11n.pt")


# ==========================================
# 2. WINDOWS VOICE
# ==========================================

voice = win32com.client.Dispatch("SAPI.SpVoice")

voice.Rate = 0
voice.Volume = 100


# ==========================================
# 3. OPEN CAMERA
# ==========================================

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("ERROR: Camera could not be opened.")
    exit()


# ==========================================
# 4. VOICE SETTINGS
# ==========================================

last_spoken = {}

# Same object will not be spoken again
# until 3 seconds have passed
speak_delay = 3


# ==========================================
# 5. CONFIDENCE THRESHOLD
# ==========================================

confidence_threshold = 0.50


# ==========================================
# 6. START DETECTION
# ==========================================

while True:

    # Read camera frame
    ret, frame = cap.read()

    if not ret:
        print("ERROR: Could not read camera.")
        break


    # ======================================
    # RUN YOLO
    # ======================================

    results = model(
        frame,
        conf=confidence_threshold,
        verbose=False
    )


    current_time = time.time()

    detected_objects = []


    # ======================================
    # PROCESS DETECTED OBJECTS
    # ======================================

    for result in results:

        for box in result.boxes:

            # --------------------------------
            # Confidence
            # --------------------------------

            confidence = float(box.conf[0])


            # --------------------------------
            # Object class
            # --------------------------------

            class_id = int(box.cls[0])

            object_name = model.names[class_id]


            # --------------------------------
            # Bounding box
            # --------------------------------

            x1, y1, x2, y2 = box.xyxy[0]

            x1 = int(x1)
            y1 = int(y1)
            x2 = int(x2)
            y2 = int(y2)


            # --------------------------------
            # Object center
            # --------------------------------

            center_x = (x1 + x2) / 2


            # --------------------------------
            # Camera width
            # --------------------------------

            frame_width = frame.shape[1]


            # --------------------------------
            # Find object position
            # --------------------------------

            if center_x < frame_width / 3:

                position = "left"

            elif center_x > (2 * frame_width / 3):

                position = "right"

            else:

                position = "center"


            # =================================
            # SAVE OBJECT INFORMATION
            # =================================

            detected_objects.append({
                "name": object_name,
                "confidence": confidence,
                "position": position
            })


            # =================================
            # PRINT TO TERMINAL
            # =================================

            print(
                f"Detected: {object_name} | "
                f"Confidence: {confidence * 100:.1f}% | "
                f"Position: {position}"
            )


            # =================================
            # VOICE MESSAGE
            # =================================

            message = (
                f"{object_name} detected "
                f"on your {position}"
            )


            # Unique object + position
            detection_key = f"{object_name}_{position}"


            # =================================
            # PREVENT TOO MUCH VOICE
            # =================================

            if (
                detection_key not in last_spoken
                or
                current_time - last_spoken[detection_key]
                > speak_delay
            ):

                print("VOICE:", message)

                voice.Speak(message)

                last_spoken[detection_key] = current_time


    # ======================================
    # TOTAL OBJECT COUNT
    # ======================================

    total_objects = len(detected_objects)

    print(
        f"Total objects detected: {total_objects}"
    )


    # ======================================
    # DRAW YOLO BOXES
    # ======================================

    frame = results[0].plot()


    # ======================================
    # DRAW INFORMATION ON SCREEN
    # ======================================

    cv2.putText(
        frame,
        f"Objects: {total_objects}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2
    )


    # ======================================
    # DRAW LEFT / CENTER / RIGHT LINES
    # ======================================

    frame_height, frame_width = frame.shape[:2]

    # Left boundary
    cv2.line(
        frame,
        (frame_width // 3, 0),
        (frame_width // 3, frame_height),
        (255, 255, 255),
        1
    )

    # Right boundary
    cv2.line(
        frame,
        ((frame_width * 2) // 3, 0),
        ((frame_width * 2) // 3, frame_height),
        (255, 255, 255),
        1
    )


    # ======================================
    # POSITION LABELS
    # ======================================

    cv2.putText(
        frame,
        "LEFT",
        (30, frame_height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        "CENTER",
        (frame_width // 2 - 50, frame_height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        "RIGHT",
        (frame_width - 100, frame_height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )


    # ======================================
    # SHOW CAMERA
    # ======================================

    cv2.imshow(
        "AI Navigation - All Object Detection",
        frame
    )


    # ======================================
    # PRESS Q TO EXIT
    # ======================================

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


# ==========================================
# 7. CLOSE CAMERA
# ==========================================

cap.release()

cv2.destroyAllWindows()

print("AI Object Detection stopped.")