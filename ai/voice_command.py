import speech_recognition as sr

recognizer = sr.Recognizer()

with sr.Microphone() as source:

    print("Listening...")
    
    recognizer.adjust_for_ambient_noise(source, duration=1)

    audio = recognizer.listen(source)

try:
    command = recognizer.recognize_google(audio)

    print("You said:", command)

except sr.UnknownValueError:
    print("Sorry, I could not understand.")

except sr.RequestError:
    print("Speech recognition service is unavailable.")