from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import uuid

from app.database import get_db
from app.models import User, Voice, AudioFile
from app.websockets import manager, audio_stream_manager
from app.services.tts_engine import tts_service
from app.services.storage import storage_service

router = APIRouter(prefix="/ws", tags=["WebSocket"])


async def get_current_user_ws_token(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    from jose import jwt
    from app.config import get_settings

    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            await websocket.close(code=4001)
            return None
    except:
        await websocket.close(code=4001)
        return None

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        await websocket.close(code=4001)
        return None

    return user


@router.websocket("/connect")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user_ws_token(websocket, token, db)
    if not user:
        return

    await manager.connect(websocket, user.id)

    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "user_id": user.id,
            "message": "WebSocket connected successfully"
        }))

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif message.get("type") == "join_room":
                room = message.get("room")
                if room:
                    await manager.join_room(user.id, room)
                    await websocket.send_text(json.dumps({
                        "type": "room_joined",
                        "room": room
                    }))

            elif message.get("type") == "leave_room":
                room = message.get("room")
                if room:
                    await manager.leave_room(user.id, room)
                    await websocket.send_text(json.dumps({
                        "type": "room_left",
                        "room": room
                    }))

            elif message.get("type") == "generate_stream":
                await handle_stream_generation(websocket, user, message, db)

            elif message.get("type") == "get_stream_status":
                stream_id = message.get("stream_id")
                stream = audio_stream_manager.get_stream(stream_id)
                if stream:
                    await websocket.send_text(json.dumps({
                        "type": "stream_status",
                        "stream_id": stream_id,
                        "status": stream.get("status"),
                        "current_chunk": stream.get("current_chunk"),
                        "total_chunks": len(stream.get("chunks", [])),
                        "audio_urls": stream.get("audio_urls", []),
                        "error": stream.get("error")
                    }))
                else:
                    await websocket.send_text(json.dumps({
                        "type": "stream_status",
                        "stream_id": stream_id,
                        "status": "not_found"
                    }))

    except WebSocketDisconnect:
        manager.disconnect(websocket, user.id)
    except Exception as e:
        manager.disconnect(websocket, user.id)
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": str(e)
            }))
        except:
            pass


async def handle_stream_generation(
    websocket: WebSocket,
    user: User,
    message: dict,
    db: AsyncSession
):
    text = message.get("text", "")
    voice_key = message.get("voice_key", "aria")
    language = message.get("language", "en")
    stream_id = str(uuid.uuid4())

    if not text:
        await websocket.send_text(json.dumps({
            "type": "stream_error",
            "stream_id": stream_id,
            "error": "Missing text"
        }))
        return

    chunk_size = 2500
    text_chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    await audio_stream_manager.start_stream(stream_id, user.id, 0, text_chunks)

    await websocket.send_text(json.dumps({
        "type": "stream_started",
        "stream_id": stream_id,
        "total_chunks": len(text_chunks)
    }))

    audio_urls = []
    for i, chunk in enumerate(text_chunks):
        try:
            audio_bytes = await tts_service.generate_audio(
                text=chunk,
                voice_id=voice_key,
                language=language,
                temperature=message.get("temperature", 0.7),
                speed=message.get("speed", 1.0),
            )

            filename = f"stream_{user.id}/{stream_id}_chunk_{i}.mp3"
            audio_url = await storage_service.upload_audio(audio_bytes, filename)
            audio_urls.append(audio_url)

            await audio_stream_manager.update_stream(stream_id, i, audio_url)

            await websocket.send_text(json.dumps({
                "type": "stream_progress",
                "stream_id": stream_id,
                "chunk_index": i,
                "total_chunks": len(text_chunks),
                "audio_url": audio_url,
                "progress": ((i + 1) / len(text_chunks)) * 100
            }))

        except Exception as e:
            await audio_stream_manager.update_stream(stream_id, i, error=str(e))
            await websocket.send_text(json.dumps({
                "type": "stream_error",
                "stream_id": stream_id,
                "chunk_index": i,
                "error": str(e)
            }))
            return

    audio_file = AudioFile(
        filename=f"stream_{stream_id}.mp3",
        url=audio_urls[-1] if audio_urls else "",
        duration=len(text) // 15,
        text_content=text,
        voice_id=0,
        owner_id=user.id,
        language=language,
        settings={"stream_id": stream_id, "chunks": len(text_chunks)}
    )
    db.add(audio_file)

    user.total_credits_used += 1

    await db.commit()
    await db.refresh(audio_file)

    audio_stream_manager.complete_stream(stream_id)

    await websocket.send_text(json.dumps({
        "type": "stream_completed",
        "stream_id": stream_id,
        "audio_file_id": audio_file.id,
        "audio_urls": audio_urls,
        "duration": audio_file.duration,
        "remaining_credits": user.credits
    }))
