from cache import media_cache
import logging
import mimetypes
from fastapi import FastAPI, Request, HTTPException, status, Header, BackgroundTasks, Response
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from config import API_BASE_URL, CF_DOMAIN, BOT_USERNAME
from utility import (
    is_user_authorized,
    build_search_pipeline,
    generate_otp,
    verify_otp,
    decode_file_link,
)
from db import (
    files_col,
    comments_col,
    users_col,
)
from app import bot
from config import LOG_CHANNEL_ID
from datetime import datetime, timezone
from handlers.admin import router as admin_router
from bson.objectid import ObjectId
from pydantic import BaseModel
import json
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.staticfiles import StaticFiles

ENCODERS_BY_TYPE[ObjectId] = str


api = FastAPI()

api.include_router(admin_router)

api.add_middleware(
    CORSMiddleware,
    allow_origins=[f"{CF_DOMAIN}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHUNK_SIZE = 1024 * 1024  # 1MB

async def get_file_properties(message):
    channel_id = message.chat.id
    message_id = message.id

    # Try to get file doc from DB
    file_doc = await files_col.find_one({"channel_id": channel_id, "message_id": message_id})
    file_name = file_doc.get("file_name") if file_doc else None

    # Extract file info from Telegram message
    media = message.document or message.video or message.audio
    
    if not media:
        raise HTTPException(
            status_code=404,
            detail="Unsupported file type"
        )

    # If DB doesn't have a name, fall back to Telegram-provided file_name
    actual_file_name = file_name or getattr(media, "file_name", "Unknown")

    return actual_file_name, media.file_size

async def get_file_stream(channel_id, message_id, request: Request):
    try:
        message = await bot.get_messages(chat_id=channel_id, message_ids=message_id)
    except Exception as e:
        logging.error(f"Error fetching message: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch file from Telegram.")

    if not message:
        raise HTTPException(status_code=404, detail="File not found")

    file_name, file_size = await get_file_properties(message)
    range_header = request.headers.get("range")
    start, end = 0, file_size - 1

    if range_header:
        try:
            range_value = range_header.strip().split("=")[1]
            start_str, end_str = range_value.split("-")[:2]
            start = int(start_str)
            if end_str:
                end = int(end_str)
        except Exception:
            pass

    # Ensure end does not exceed file_size
    end = min(end, file_size - 1)
    bytes_to_send = end - start + 1

    # Pyrogram stream_media offset is in chunks of 1MB
    chunk_offset = start // (1024 * 1024)
    byte_offset_in_first_chunk = start % (1024 * 1024)

    async def media_streamer():
        bytes_sent = 0
        is_first_chunk = True
        try:
            async for chunk in bot.stream_media(message, offset=chunk_offset):
                if is_first_chunk:
                    chunk = chunk[byte_offset_in_first_chunk:]
                    is_first_chunk = False

                if not chunk:
                    continue

                remaining_bytes = bytes_to_send - bytes_sent
                if len(chunk) > remaining_bytes:
                    chunk = chunk[:remaining_bytes]

                yield chunk
                bytes_sent += len(chunk)

                if bytes_sent >= bytes_to_send:
                    break
        except Exception as e:
            logging.error(f"Streaming error: {e}")

    return media_streamer, start, end, file_size, file_name

class TrackPlayRequest(BaseModel):
    file_id: str

@api.post("/api/track_play")
async def track_play(request: TrackPlayRequest):
    try:
        file = await files_col.find_one({"_id": ObjectId(request.file_id)})
        if not file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        
        file_id_str = str(file["_id"])
        # Using 0 and "public" for unauthenticated stream
        stream_url = f"{API_BASE_URL}/stream/{bot.encode_file_link(file_id_str, 0, 'public')}"
        
        return JSONResponse(content={"message": "Play tracked successfully", "stream_url": stream_url})
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to track play: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to track play")


@api.get("/stream/{file_link}")
@api.head("/stream/{file_link}")
async def stream_file(file_link: str, request: Request):
    try:
        _id, user_id, session_token = await decode_file_link(file_link)
    except Exception:
         raise HTTPException(status_code=400, detail="Invalid stream link")

    # Bypass auth if user_id is 0 and session_token is 'public'
    if not (user_id == 0 and session_token == 'public'):
        if not await is_user_authorized(user_id, session_token):
            raise HTTPException(status_code=403, detail="Unauthorized user or session expired")

    file_doc = await files_col.find_one({"_id": ObjectId(_id)})

    if not file_doc:
        raise HTTPException(status_code=404, detail="File Not Found")

    if request.method == "HEAD":
        try:
            message = await bot.get_messages(chat_id=file_doc['channel_id'], message_ids=file_doc['message_id'])
        except Exception as e:
            logging.error(f"Error fetching message for HEAD: {e}")
            raise HTTPException(status_code=500, detail="Telegram error")

        if not message:
            raise HTTPException(status_code=404, detail="File not found on Telegram.")

        _, file_size = await get_file_properties(message)
        return Response(status_code=200, headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"})

    media_streamer, start, end, file_size, file_name = await get_file_stream(file_doc['channel_id'], file_doc['message_id'], request)

    mime_type, _ = mimetypes.guess_type(file_name)
    if mime_type is None:
        mime_type = "video/mp4"

    headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Disposition": f'attachment; filename="{file_name}"'
    }

    return StreamingResponse(media_streamer(), status_code=206 if start > 0 else 200, headers=headers)

@api.get("/")
async def root():
    return JSONResponse({"message": "👋 Hola Amigo!"})

@api.post("/api/request-otp")
async def request_otp(request: Request):
    data = await request.json()
    user_id = data.get("user_id")

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid User ID format.",
        )

    user = await users_col.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please start the bot first.",
        )

    otp = await generate_otp(user_id)

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"Your OTP for login is: <code>{otp}</code>\nValid for 10 minutes."
        )
        return JSONResponse(content={"status": "sent"})
    except Exception as e:
        logging.error(f"Failed to send OTP to {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not send OTP. Please make sure you have started the bot."
        )

async def send_auth_notification(user_id: int):
    try:
        user = await bot.get_users(user_id)
        first_name = user.first_name
        username = f" @{user.username}" if user.username else ""
        log_msg = f"User {first_name} ({user_id}){username} just authorized via {BOT_USERNAME}"
        await bot.send_message(LOG_CHANNEL_ID, log_msg)
    except Exception as e:
        logging.error(f"Error sending auth log: {e}")

@api.post("/api/verify-otp")
async def api_verify_otp(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    user_id = data.get("user_id")
    otp = data.get("otp")

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid User ID format.",
        )

    if not otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP is required.",
        )

    session_token = await verify_otp(user_id, otp)
    if session_token:
        background_tasks.add_task(send_auth_notification, user_id)
        return JSONResponse(content={"token": f"{user_id}:{session_token}"})
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP.",
        )

@api.get("/api/user/verify")
async def verify_user(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401)
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401)
    
    token = parts[1]
    if ":" not in token:
        raise HTTPException(status_code=401)
    
    user_id_str, session_token = token.split(":", 1)
    user_id = int(user_id_str)
    
    if await is_user_authorized(user_id, session_token):
        return {"status": "authorized", "user_id": user_id}
    raise HTTPException(status_code=401)

@api.get("/api/others")
async def get_others(page: int = 1, search: str = None, sort: str = "newest"):
    cache_key = f"others:{page}:{search}:{sort}"
    cached_data = media_cache.get(cache_key)
    if cached_data:
        return JSONResponse(content=cached_data, headers={"Cache-Control": "public, max-age=300"})

    page_size = 12
    skip = (page - 1) * page_size

    sort_order = [("_id", -1)] if sort == "newest" else [("_id", 1)]

    base_query = {
        "file_name": {"$not": {"$regex": r"\.srt$", "$options": "i"}}
    }

    if search:
        sanitized_search = bot.sanitize_query(search)
        pipeline = build_search_pipeline(sanitized_search, 'file_name', base_query, skip, page_size, sort_order=sort_order)
        result = await files_col.aggregate(pipeline).to_list(length=None)
        files = result[0]['results'] if result and 'results' in result[0] else []
        total_files = result[0]['totalCount'][0]['total'] if result and 'totalCount' in result[0] and result[0]['totalCount'] else 0
    else:
        files = await files_col.find(base_query).sort(sort_order).skip(skip).limit(page_size).to_list(length=page_size)
        total_files = await files_col.count_documents(base_query)

    for file in files:
        file["_id"] = str(file["_id"])

    data = {
        "files": json.loads(json.dumps(files, default=str)),
        "total_pages": (total_files + page_size - 1) // page_size,
        "current_page": page,
        "total_files": total_files,
    }
    media_cache[cache_key] = data
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=300"})

@api.get("/api/file/{file_id}")
async def get_file_details(file_id: str):
    try:
        file = await files_col.find_one({"_id": ObjectId(file_id)})
        if not file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        file_id_str = str(file["_id"])
        file["_id"] = file_id_str
        return file
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file ID")



# api.mount("/", StaticFiles(directory="static_frontend", html=True), name="static")
