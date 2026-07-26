from typing import Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect
import json
import asyncio


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.user_rooms: Dict[int, Set[str]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        
        if user_id not in self.user_rooms:
            self.user_rooms[user_id] = set()

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                if user_id in self.user_rooms:
                    del self.user_rooms[user_id]

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except:
                    disconnected.append(connection)
            
            for conn in disconnected:
                self.disconnect(conn, user_id)

    async def broadcast(self, message: dict, room: str = None):
        for user_id, connections in self.active_connections.items():
            if room is None or room in self.user_rooms.get(user_id, set()):
                disconnected = []
                for connection in connections:
                    try:
                        await connection.send_text(json.dumps(message))
                    except:
                        disconnected.append(connection)
                
                for conn in disconnected:
                    self.disconnect(conn, user_id)

    async def join_room(self, user_id: int, room: str):
        if user_id in self.user_rooms:
            self.user_rooms[user_id].add(room)

    async def leave_room(self, user_id: int, room: str):
        if user_id in self.user_rooms:
            self.user_rooms[user_id].discard(room)


manager = ConnectionManager()


class AudioStreamManager:
    def __init__(self):
        self.active_streams: Dict[str, Dict] = {}

    async def start_stream(self, stream_id: str, user_id: int, voice_id: int, text_chunks: List[str]):
        self.active_streams[stream_id] = {
            "user_id": user_id,
            "voice_id": voice_id,
            "chunks": text_chunks,
            "current_chunk": 0,
            "status": "processing"
        }

    async def update_stream(self, stream_id: str, chunk_index: int, audio_url: str = None, error: str = None):
        if stream_id in self.active_streams:
            stream = self.active_streams[stream_id]
            stream["current_chunk"] = chunk_index
            if audio_url:
                stream.setdefault("audio_urls", []).append(audio_url)
            if error:
                stream["error"] = error
                stream["status"] = "error"

    def get_stream(self, stream_id: str):
        return self.active_streams.get(stream_id)

    def complete_stream(self, stream_id: str):
        if stream_id in self.active_streams:
            self.active_streams[stream_id]["status"] = "completed"
            return self.active_streams.pop(stream_id)
        return None


audio_stream_manager = AudioStreamManager()