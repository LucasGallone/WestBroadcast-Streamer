# WestBroadcast Streamer
WestBroadcast Streamer is more than just an audio-over-IP decoder. It transforms a computer into a full-fledged broadcasting tool with two backup sources, ensuring that a program is always broadcast over an FM transmitter, for example. Email alerts keep you informed of any potential issues with the sources in use.
<br>
<br>
This broadcasting solution is primarily suited for small radio stations that, for cost reasons, prefer to use a computer to receive their program via IP and broadcast it from a transmission site. It can also be used in a small store or even at home to provide continuous background music, without worrying about potential network or IP stream issues. 
<br>
<br>
Entirely open source, this solution is based on the FFmpeg and FFprobe audio engines, as well as a Python script. The decoder is configured and monitored via a secure web interface. 
<br>
<br>
WestBroadcast Streamer runs as a portable installer. This means you can use it anywhere, even from an external hard drive or a USB drive. 
<br>
<br>
<b>IMPORTANT NOTE: At this time, the decoder only works on Windows. Optimizations are needed so that the project can run on Linux.</b>
## 1. Installation instructions for Windows
• Install Python 3.10 or later on your computer from the official website [by clicking here](https://www.python.org/downloads/).
<br>
<br>
• [Download the entire content of the repository by clicking here.](https://github.com/LucasGallone/WestBroadcast-Streamer/archive/refs/heads/main.zip)
<br>
<br>
• <b>Important: When installing Python, be sure to check the "Add Python to PATH" box, otherwise the decoder will not work properly!</b>
<br>
<br>
• Ideally, as is customary, restart your computer after installing Python.
<br>
<br>
• Extract the content of the .zip file and place the files wherever you like.
<br>
<br>
• Run the Launcher.bat file.
<br>
-> When started for the first time, it will install the Python dependencies required for the decoder to work properly. This may take a few minutes.
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
You must configure the decoder via the web interface (Default login credentials: admin / admin).
<br>
For more details, visit the Wiki section by clicking here.
## 3. Starting the decoder after the initial setup
For the next startups, simply run Launch.bat as you did during the initial installation.
<br>
At each startup, the script checks that all required dependencies are present on your machine, then starts the audio engine and the webserver.
## Legal Notices and Licenses
### FFmpeg and FFprobe
This software uses the FFmpeg and FFprobe libraries and executables for processing and analyzing audio streams.
<br>
<br>
• License: FFmpeg is licensed under the GNU General Public License (GPL).
<br>
• Redistribution: The binaries provided in this repository are unmodified static versions compiled by [Gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
<br>
• Source Code: In accordance with the GPL license, the FFmpeg source code is available on [ffmpeg.org](https://ffmpeg.org/).
<br>
• Trademark: FFmpeg is a registered trademark of Fabrice Bellard, creator of the FFmpeg project.
<br>
<br>
For more details, please refer to the `ffmpeg-license.txt` file included in this repository.
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
