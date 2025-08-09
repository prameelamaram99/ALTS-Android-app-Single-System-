import tkinter as tk
from tkinter import messagebox
import sounddevice as sd
import numpy as np
import soundfile as sf
import whisper
import litellm
from TTS.api import TTS
import tempfile
import os
import yaml
from dotenv import load_dotenv
import requests
import threading
import queue
import time
import re
from simpleaudio import WaveObject

# Load configuration
load_dotenv()
with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

# Initialize AI models
stt = whisper.load_model(config["whisper"]["model"])
tts = TTS(model_name=config["tts"]["model"], progress_bar=False)
llm_config = config["llm"]

# Audio settings
RECORD_SECONDS = 5

SENTENCE_DELIMITERS = (".", "?", "!", ";", ":", ": ", " (", ")", "\n-", "\n- ", " -", "- ", "\n–", "\n– ", " –", "– ")

class ALTSClient:
    def __init__(self, root):
        self.root = root
        self.root.title("ALTS Client")
        self.is_recording = False
        self.audio_data = None
        self.current_lang = None
        self.llm_messages = [{"role": "system", "content": llm_config["system"]}] if llm_config["system"] else []

        # GUI elements
        self.url_label = tk.Label(root, text="Server URL (e.g., http://172.22.64.1:8000 ")
        self.url_label.pack(pady=5)
        self.server_url = tk.Entry(root, width=40)
        self.server_url.insert(0, "http://172.22.64.1:8000")
        self.server_url.pack(pady=5)

        self.record_button = tk.Button(root, text="Start Recording", command=self.toggle_recording, bg="green")
        self.record_button.pack(pady=10)

        self.text_input = tk.Entry(root, width=40)
        self.text_input.pack(pady=5)
        self.text_button = tk.Button(root, text="Submit Text", command=self.process_text)
        self.text_button.pack(pady=5)

        self.device_button = tk.Button(root, text="List Audio Devices", command=self.list_audio_devices)
        self.device_button.pack(pady=5)

        self.response_text = tk.Text(root, height=10, width=50)
        self.response_text.pack(pady=10)
        self.response_text.insert(tk.END, "LLM Response will appear here")

        self.status_label = tk.Label(root, text="Status: Ready")
        self.status_label.pack(pady=5)

        self.device_index = self.get_default_input_device()

    def get_default_input_device(self):
        try:
            devices = sd.query_devices()
            print("\n=== Available Audio Devices ===")
            device_info = []
            for i, device in enumerate(devices):
                info = f"Index {i}: {device['name']} - Input Channels: {device['max_input_channels']}"
                print(info)
                device_info.append(info)

            # Prefer a real microphone first
            for i, device in enumerate(devices):
                if "RDPSource" in device['name'] and device['max_input_channels'] > 0:
                    print(f"Using RDPSource as input device (Index {i})")
                    return i

            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    print(f"Using fallback device: {device['name']} (Index {i})")
                    return i

            self.update_status("No usable audio input device found.")
            messagebox.showwarning("Warning", "No usable audio input device found:\n" + "\n".join(device_info))
            return None

        except Exception as e:
            self.update_status(f"Device detection error: {str(e)}")
            messagebox.showerror("Error", f"Device detection error: {str(e)}")
            return None

    def list_audio_devices(self):
        try:
            devices = sd.query_devices()
            info = "\n".join([f"Index {i}: {d['name']}, Input: {d['max_input_channels']}" for i, d in enumerate(devices)])
            messagebox.showinfo("Audio Devices", info or "No devices found.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def toggle_recording(self):
        if not self.is_recording:
            if self.device_index is None:
                messagebox.showerror("Error", "No audio input device available.")
                return
            self.is_recording = True
            self.record_button.config(text="Stop Recording", bg="red")
            self.status_label.config(text="Status: Recording...")
            threading.Thread(target=self.record_audio, daemon=True).start()
        else:
            self.is_recording = False
            self.record_button.config(text="Start Recording", bg="green")
            self.status_label.config(text="Status: Processing...")

    def record_audio(self):
        try:
            mic_queue = queue.Queue()
            filename = tempfile.mktemp(suffix='.wav', dir='')
            samplerate = 16000  # Standard for Whisper
            channels = 1  # Mono

            def callback(indata, frames, time_info, status):
                if status:
                    print(status)
                mic_queue.put(indata.copy())

            def write_audio_file():
                with sf.SoundFile(filename, mode='x', samplerate=samplerate, channels=channels,
                                  subtype='PCM_16') as file:
                    start_time = time.time()
                    while time.time() - start_time < RECORD_SECONDS:
                        try:
                            file.write(mic_queue.get(timeout=0.1))
                        except queue.Empty:
                            continue

            stream = sd.InputStream(samplerate=samplerate, channels=channels, callback=callback,
                                    device=self.device_index)
            stream.start()
            writer = threading.Thread(target=write_audio_file, daemon=True)
            writer.start()
            writer.join()
            stream.stop()
            stream.close()
            self.process_audio(filename)
        except Exception as e:
            self.update_status(f"Error recording: {str(e)}")
        finally:
            self.is_recording = False
            self.record_button.config(text="Start Recording", bg="green")



    def process_text(self):
        text = self.text_input.get().strip()
        if text:
            self.process_input(text)

    def process_audio(self, audio_path):
        try:
            converted_path = tempfile.mktemp(suffix='.wav', dir='')
            os.system(f"ffmpeg -i {audio_path} -ar 16000 -ac 1 -c:a pcm_s16le {converted_path} -y")
            transcription_data = self.transcribe(converted_path)
            text = transcription_data["text"]
            self.current_lang = transcription_data["language"]
            self.update_status(f"Transcribed: {text}")
            self.process_input(text)
            os.remove(audio_path)
            os.remove(converted_path)
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            print(f"Audio file retained for debugging: {audio_path}")

    def transcribe(self, audio):
        import torch
        try:
            print(f"Attempting to transcribe: {audio}")
            result = stt.transcribe(audio, fp16=torch.cuda.is_available())
            print(f"Transcription result: {result}")
            return result
        except Exception as e:
            print(f"Transcription error: {str(e)}")
            return {"text": f"Transcription error: {str(e)}", "language": "en"}

    def process_input(self, text):
        try:
            if "smart home" in text.lower() or "lights" in text.lower():
                text += f"\nDevice Status: {self.query_server(text)}"

            full_response = ""
            self.llm_messages.append({"role": "user", "content": text})
            for sentence in self.think(text):
                full_response += sentence
                self.response_text.delete(1.0, tk.END)
                self.response_text.insert(tk.END, full_response)
                synth_data = self.synthesize(sentence)
                self.speak(synth_data["audio"], synth_data["text"])
            self.llm_messages.append({"role": "assistant", "content": full_response})
            self.update_status("Status: Ready")
        except Exception as e:
            self.update_status(f"Processing error: {str(e)}")

    def think(self, query):
        try:
            response = litellm.completion(
                model=llm_config["model"],
                messages=self.llm_messages,
                api_base=llm_config["url"],
                stream=True
            )
            buffer = ""
            for chunk in response:
                token = chunk['choices'][0]['delta']['content'] or ""
                if token.startswith(SENTENCE_DELIMITERS):
                    yield buffer + token[0]
                    buffer = token[1:]
                else:
                    buffer += token
            if buffer:
                yield buffer
        except Exception as e:
            yield f"LLM error: {str(e)}"

    def synthesize(self, text):
        try:
            cleaned_text = re.sub(r'[\*_\`\[\\]', '', text).replace(']', '').strip()
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            print(f"Synthesizing text: {cleaned_text}")
            speaker = config["tts"]["speakerId"] if tts.is_multi_speaker else None
            language = self.current_lang if tts.is_multi_lingual and self.current_lang in tts.languages else None
            audio_path = tempfile.mktemp(suffix='.wav', dir='')
            tts.tts_to_file(text=cleaned_text, speaker=speaker, language=language, file_path=audio_path)
            print(f"TTS output saved to: {audio_path}")
            return {"audio": audio_path, "text": cleaned_text}
        except Exception as e:
            print(f"TTS error: {str(e)}")
            return {"audio": None, "text": f"TTS failed: {str(e)}"}

    def speak(self, audio, text):
        try:
            if audio:
                wave_obj = WaveObject.from_wave_file(audio)
                play_obj = wave_obj.play()
                play_obj.wait_done()
                os.remove(audio)
            self.update_status(f"Speaking: {text}")
        except Exception as e:
            self.update_status(f"Speak error: {str(e)}")

    def query_server(self, text):
        try:
            url = f"{self.server_url.get()}/get_device_status"
            response = requests.post(url, json={"query": text}, timeout=5)
            return response.json().get("status", "Unknown")
        except Exception as e:
            return f"Mock device status: {str(e)}"

    def update_status(self, text):
        self.status_label.config(text=text)


if __name__ == "__main__":
    root = tk.Tk()
    app = ALTSClient(root)
    root.mainloop()
