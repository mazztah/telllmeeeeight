import socketio
import base64
from PIL import Image
import io
import cv2
import numpy as np
from bot_state import client as groq_client
from groq import Groq  # Reuse

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio)

@sio.event
async def connect(sid, environ):
    print(f'Client connected {sid}')

@sio.event
async def disconnect(sid):
    print(f'Client disconnected {sid}')

@sio.event
async def user_frame(sid, data):
    # data: {'frame': base64 jpeg, 'timestamp': ts}
    try:
        frame_bytes = base64.b64decode(data['frame'].split(',')[1])
        img = Image.open(io.BytesIO(frame_bytes))
        # Vision process
        prompt = "Describe this video frame briefly for chat."
        resp = groq_client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data['frame']}}]}]
        )
        vision_text = resp.choices[0].message.content
        # LLM answer + TTS stub
        answer = f"User frame analysis: {vision_text}"
        # Send back bot "video" (text overlay or avatar)
        sio.emit('bot_video', {'video': 'base64_avatar_frame', 'text': answer}, room=sid)
        sio.emit('transcript_update', {'text': vision_text}, room=sid)
    except Exception as e:
        print(f"Frame error: {e}")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

