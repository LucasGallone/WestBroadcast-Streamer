# WestBroadcast Streamer
WestBroadcast Streamer is more than a simple Audio over IP decoder. It transforms a computer into a full-fledged broadcasting tool with two backup sources, ensuring that a program is always broadcast over an FM transmitter, for example. Email alerts keep you informed of any potential issues with the sources in use.
<br>
<br>
This broadcasting solution is primarily suited for small radio stations that, for cost reasons, prefer to use a computer to receive their audio stream via IP in order to broadcast from a transmitter site. It can also be used in a small store or even at home to provide continuous background music, without worrying about potential network or IP stream issues. 
<br>
<br>
Entirely open source, this solution is based on the FFmpeg audio engine and FFprobe, as well as a Python script.
<br>
The decoder is configured and monitored via a secure web interface. 
<br>
<br>
WestBroadcast Streamer runs as a portable installer. This means you can use it anywhere, even from an external hard drive or a USB drive. 
<br>
<br>
<b>IMPORTANT NOTE: At this time, the decoder only works on Windows. Optimizations are needed so that the project can run on Linux.</b>
<br>
<br>
This software has been tested on several computers running Windows 10 and 11, with success.
<br>
Any quality feedback regarding other operating systems is welcome!
<br>
<br>
![wbcast-streamer-1](https://github.com/user-attachments/assets/2e544432-b65b-4c47-a677-1f6f809fbac9)
![interface-readme-2](https://github.com/user-attachments/assets/732b4156-a544-4d11-8df0-16429662a0f5)
## What this tool offers
• Full control over the reception and playback of audio sources via a secure and remotely controllable webserver with two different accounts (Administrator and Operator). Monitoring of input and output audio thanks to VU meters.
<br>
<br>
• Two backup sources that are automatically triggered if silence is detected on the main audio stream (or in case the streaming server becomes inaccessible). The rules for detecting silence and restoring audio can be configured according to the user’s preferences.
<br>
<br>
• Playback of IP streams (HTTP and HTTPS), RTP streams, audio input devices, local files (such as backup loops), and tests tones thanks to a generator.
<br>
<br>
• A server for uploading backup files remotely.
<br>
<br>
• Full control over input and output gain (dB), as well as buffer sizes.
<br>
<br>
• Export of metadata (Current song title), if available on the IP stream, to a text file on the host machine, with the option to convert letters to uppercase and remove accents. This is useful for displaying songs titles on Radiotext (RDS).
<br>
<br>
• Alert mails being sent via SMTP in case of anomalies detected on one of your sources, to keep you informed of the decoder and broadcast status.
<br>
<br>
• The ability to analyze the audio output in various ways, view system/authentication logs, and much more...
<br>
<br>
For further details, [visit the Wiki section by clicking here.](https://github.com/LucasGallone/WestBroadcast-Streamer/wiki)
## 1. Installation instructions for Windows
-> [Download the entire content of the repository by clicking here.](https://github.com/LucasGallone/WestBroadcast-Streamer/archive/refs/heads/main.zip)
<br>
<br>
-> Extract the content of the .zip file and place the files wherever you like.
<br>
<br>
-> Install Python 3.10 or newer on your computer from the official website [by clicking here.](https://www.python.org/downloads/)
<br>
<b>IMPORTANT: When installing Python, make sure to check the "Add Python to PATH" box, otherwise the decoder will not work properly!</b>
<br>
<br>
-> Ideally, as is customary, restart your computer after installing Python.
<br>
<br>
-> Go back to the folder containing the decoder files, and run `Launcher.bat`.
<br>
When started for the first time, it will install the Python dependencies required for the decoder to work properly. This may take a few minutes.
<br>
Even if nothing appears to be happening on the terminal, please wait until the process is complete.
<br>
<br>
-> Once the installation is complete, the audio engine and web server will start up.
<br>
A Python window will open, displaying your machine's IP address, the port used by the webserver, and the default login credentials.
<br>
Be sure to keep this window open on the host machine (it's used for audio output), as well as the terminal!
## 2. Configuration
You must configure the decoder via the web interface.
<br>
The default port is 8090 and the credentials are admin / admin.
<br>
(Changing the credentials at first use is STRONGLY recommended to prevent any unauthorized access!)
<br>
<br>
For more details, [visit the Wiki section by clicking here.](https://github.com/LucasGallone/WestBroadcast-Streamer/wiki)
## 3. Starting the decoder after the initial setup
For the next startups, simply run `Launch.bat` as you did during the initial installation.
<br>
At each startup, the script checks that all required dependencies are present on your machine, then starts the audio engine and the webserver.
## 💡 Troubleshooting
Having trouble with the software? [Check out this Wiki section to see if that helps.](https://github.com/LucasGallone/WestBroadcast-Streamer/wiki/%F0%9F%92%A1-Troubleshooting)
<br>
If not, feel free to open an "issue" with as much detail as possible.
## Legal Notices and Licenses
### WestBroadcast Streamer
This project is licensed under the GNU General Public License (GPL) v3.0.
<br>
Please refer to the `LICENSE` file for more details.
### FFmpeg and FFprobe
This project uses the FFmpeg and FFprobe libraries and executables for processing and analyzing audio streams.
<br>
<br>
• License: FFmpeg is licensed under the GNU General Public License (GPL) v3.0.
<br>
• Redistribution: The binaries provided in this repository are unmodified static versions compiled by [Gyan.dev.](https://www.gyan.dev/ffmpeg/builds/)
<br>
• Source Code: In accordance with the GPL license, the FFmpeg source code is available on [ffmpeg.org.](https://ffmpeg.org/)
<br>
• Trademark: FFmpeg is a registered trademark of Fabrice Bellard, creator of the FFmpeg project.
<br>
<br>
For more details, please refer to the `FFmpeg-LICENSE.txt` file included in this repository.
### Socket.io (JavaScript Client)
The socket.io.js file included in the /static folder is part of the Socket.io library.
<br>
<br>
License: MIT License.
<br>
Copyright (c) 2014-2025 Automattic.
### Python Dependencies
This project uses the following libraries, automatically installed by the Launcher script:
<br>
<br>
• Flask / Werkzeug: BSD-3-Clause License.
<br>
• Flask-SocketIO: MIT License.
<br>
• Sounddevice / PortAudio: MIT License.
<br>
• NumPy: BSD-3-Clause License.
