import subprocess

subprocess.run([
    "powershell",
    "-Command",
    "Add-Type -AssemblyName System.Speech; "
    "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$speak.Speak('Hello. Voice is working.')"
])

print("Voice test completed")