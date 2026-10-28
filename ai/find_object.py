from ultralytics import YOLO
import cv2
import win32com.client
import speech_recognition as sr
import time

# Load YOLO model
model = YOLO("yolo11n.pt")

# Windows voice
voice = win32com.client.Dispatch("SAPI.SpVoice")
voice.Rate = 0
voice.Volume = 100

# Speech recognizer
recognizer = sr.Recognizer()

# -----------------------------
# STEP 1: Listen to user
# -----------------------------

with sr.Microphone() as source:
    print("Listening...")
    voice.Speak("What object do you want to find?")
    
    recognizer.adjust_for_ambient_noise(source, duration=1)
    audio = recognizer.listen(source)

try:
    command = recognizer.recognize_google(audio).lower()

    print("You said:", command)

except sr.UnknownValueError:
    print("Could not understand your voice.")
    voice.Speak("Sorry, I could not understand.")
    exit()

except sr.RequestError:
    print("Speech recognition service is unavailable.")
    voice.Speak("Speech recognition is unavailable.")
    exit()


# -----------------------------
# STEP 2: Get object name
# -----------------------------

if "find " in command:
    target = command.split("find ", 1)[1].strip()
else:
    target = command.strip()

print("Searching for:", target)
voice.Speak(f"Searching for {target}")


# -----------------------------
# STEP 3: Start camera
# -----------------------------

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Camera could not be opened.")
    voice.Speak("Camera could not be opened.")
    exit()


last_voice_time = 0
voice_delay = 3
found_before = False


# -----------------------------
# STEP 4: Detect object
# -----------------------------

while True:

    ret, frame = cap.read()

    if not ret:
        print("Could not read camera.")
        break

    results = model(frame, verbose=False)

    found = False
    found_position = ""

    frame_height, frame_width = frame.shape[:2]

    for result in results:

        for box in result.boxes:

            confidence = float(box.conf[0])

            if confidence < 0.50:
                continue

            class_id = int(box.cls[0])
            object_name = model.names[class_id].lower()

            # Check target object
            if object_name == target:

                found = True

                # Get object position
                x1, y1, x2, y2 = box.xyxy[0]

                x1 = int(x1)
                x2 = int(x2)

                center_x = (x1 + x2) / 2

                if center_x < frame_width / 3:
                    found_position = "left"

                elif center_x > (frame_width * 2 / 3):
                    found_position = "right"

                else:
                    found_position = "center"

                print(
                    f"FOUND: {object_name} | "
                    f"Confidence: {confidence * 100:.1f}% | "
                    f"Position: {found_position}"
                )


    # -----------------------------
    # STEP 5: Voice result
    # -----------------------------

    current_time = time.time()

    if found and not found_before:

        message = f"{target} found on your {found_position}"

        print("VOICE:", message)

        voice.Speak(message)

        last_voice_time = current_time

    found_before = found


    # -----------------------------
    # STEP 6: Show camera
    # -----------------------------

    frame = results[0].plot()

    if found:

        cv2.putText(
            frame,
            f"{target.upper()} FOUND - {found_position.upper()}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2
        )

    else:

        cv2.putText(
            frame,
            f"SEARCHING: {target}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            2
        )


    cv2.imshow("AI Object Finder", frame)


    # Press Q to stop
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


# -----------------------------
# STEP 7: Close
# -----------------------------

cap.release()
cv2.destroyAllWindows()

print("Object finder stopped.")