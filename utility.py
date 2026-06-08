
import re
import asyncio
import random
import base64
import uuid
import logging
from bson.objectid import ObjectId
from datetime import datetime, timezone, timedelta
from pyrogram.errors import (FloodWait, UserIsBlocked,
                              InputUserDeactivated, PeerIdInvalid, UserIsBot)
from pyrogram import enums
from pyrogram.types import User
from db import (
    allowed_channels_col,
    users_col,
    files_col
)
from config import *
from cache import auth_cache, user_cache

# =========================
# Constants & Globals
# =========================

AUTO_DELETE_SECONDS = 2 * 60

logger = logging.getLogger(__name__)

def build_search_pipeline(query, search_field, match_query=None, skip=0, limit=12, sort_order=None):
    """
    Builds a flexible Atlas Search aggregation pipeline using compound search.

    Args:
        query (str): The search query string.
        search_field (str): The name of the field to search (e.g., 'title' or 'file_name').
        match_query (dict, optional): Additional filters for the $match stage. Defaults to None.
        skip (int, optional): The number of documents to skip for pagination. Defaults to 0.
        limit (int, optional): The number of documents to return. Defaults to 12.
        sort_order (list, optional): A list of (field, direction) tuples for sorting.

    Returns:
        list: The aggregation pipeline.
    """
    if not query:
        return []

    # Split query into words to implement 'AND' logic with fuzzy matching for each word
    words = query.strip().split()
    must_clauses = []
    for word in words:
        must_clauses.append({
            "text": {
                "query": word,
                "path": search_field,
                "fuzzy": {
                    "maxEdits": 2,
                    "prefixLength": 3
                }
            }
        })

    compound = {
        "must": must_clauses
    }

    # Atlas Search stage optimized for storage (using 'compound' operator)
    search_stage = {
        "$search": {
            "index": "default",
            "compound": compound
        }
    }
  
    # Match stage for additional filters (keeping it outside $search for robust compatibility with all operators)
    match_stage = {"$match": match_query} if match_query else None
  
    # Add search score to the results
    add_score_stage = {
        "$addFields": {
            "score": {"$meta": "searchScore"}
        }
    }

    # Sorting logic: if sort_order is provided, use it. Otherwise, default to relevance (score).
    if sort_order:
        sort_dict = {field: direction for field, direction in sort_order}
        sort_stage = {"$sort": sort_dict}
    else:
        sort_stage = {
            "$sort": {
                "score": -1
            }
        }

    pipeline = [search_stage]
    if match_stage:
        pipeline.append(match_stage)
    
    pipeline.append(add_score_stage)
    
    # Facet stage for pagination and total count
    facet_stage = {
        "$facet": {
            "results": [
                sort_stage,
                {"$skip": skip},
                {"$limit": limit}
            ],
            "totalCount": [
                {"$count": "total"}
            ]
        }
    }
    
    pipeline.append(facet_stage)

    return pipeline

# =========================
# Channel & User Utilities
# =========================

async def get_allowed_channels():
    return [
        doc["channel_id"]
        async for doc in allowed_channels_col.find({}, {"_id": 0, "channel_id": 1})
    ]

async def add_user(user_id):
    """
    Add a user to users_col only if not already present.
    Stores user_id, joined_date (UTC), and blocked status.
    Returns the user document with an extra key '_new' (True if newly added).
    """
    user_doc = await users_col.find_one({"user_id": user_id})
    
    if not user_doc:
        user_doc = {
            "user_id": user_id,
            "joined": datetime.now(timezone.utc),
            "blocked": False
        }

        await users_col.insert_one(user_doc)

        user_doc["_new"] = True
    else:
        user_doc["_new"] = False
    
    return user_doc


async def authorize_user(user_id):
    """Authorize a user and generate a new session token."""
    session_token = str(uuid.uuid4())
    
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"session_token": session_token},
            "$setOnInsert": {"file_count": 0, "joined": datetime.now(timezone.utc), "blocked": False}
        },
        upsert=True
    )
    return session_token

async def is_user_authorized(user_id, session_token):
    """
    Check if a user is authorized with a session token.
    Returns the user document if valid, else False.
    """
    cache_key = f"auth:{user_id}:{session_token}"
    if cache_key in auth_cache:
        return auth_cache[cache_key]

    query = {"user_id": user_id, "session_token": session_token}
  
    doc = await users_col.find_one(query)
    if not doc:
        auth_cache[cache_key] = False
        return False

    auth_cache[cache_key] = doc
    return doc

async def decode_file_link(file_link: str) -> tuple[str, int, str]:
    try:
        padding = '=' * (-len(file_link) % 4)
        decoded = base64.urlsafe_b64decode(file_link + padding).decode()
        parts = decoded.split("_")
        if len(parts) != 3:
            raise ValueError("Invalid format")
        _id, user_id, session_token = parts[0], int(parts[1]), parts[2]
        return _id, user_id, session_token
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid file link")

async def check_file_limit(user_id: int, user_data: dict = None, auth_user_doc: dict = None, raise_exception: bool = True):
    return True

async def increment_file_count(user_id: int, user_data: dict = None, auth_user_doc: dict = None):
    pass

async def get_user_link(user: User) -> str:
    try:
        user_id = user.id if hasattr(user, 'id') else None
        first_name = user.first_name if hasattr(user, 'first_name') else "Unknown"
    except Exception as e:
        logger.info(f"{e}")
        user_id = None
        first_name = "Unknown"
    
    if user_id:
        return f'<a href=tg://user?id={user_id}>{first_name}</a>'
    else:
        return first_name

async def get_user_data(user_id: int) -> dict:
    """
    Gets user data (first_name, premium status) from cache or DB.
    """
    if user_id in user_cache:
        return user_cache[user_id]

    # Initialize default data
    user_data = {
        "first_name": "Anonymous",
        "premium": False
    }

    if user_id == OWNER_ID:
        user_data["first_name"] = "ADMIN"
        user_data["premium"] = True
    else:
        # Fetch from DB
        db_user = await users_col.find_one({"user_id": user_id})
        if db_user:
            user_data["premium"] = db_user.get("premium", False)

        # Try to get first name from Bot if not in DB or to keep it fresh
        from app import bot
        try:
            user = await bot.get_users(user_id)
            user_data["first_name"] = user.first_name
        except Exception as e:
            logger.error(f"Error getting user's first name from bot for {user_id}: {e}")

    user_cache[user_id] = user_data
    return user_data

async def get_user_firstname(user_id: int) -> str:
    """Gets a user's first name."""
    data = await get_user_data(user_id)
    return data["first_name"]
    
# =========================
# Link & URL Utilities
# =========================

def generate_telegram_link(bot_username, channel_id, message_id):
    """Generate a base64-encoded Telegram deep link for a file."""
    raw = f"{channel_id}_{message_id}".encode()
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"https://telegram.dog/{bot_username}?start=file_{b64}" 

def generate_c_link(channel_id, message_id):
    # channel_id must be like -1001234567890
    return f"https://t.me/c/{str(channel_id)[4:]}/{message_id}"

def extract_channel_and_msg_id(link):
    # Only support t.me/c/(-?\d+)/(\d+)
    match = re.search(r"t\.me/c/(-?\d+)/(\d+)", link)
    if match:
        channel_id = int("-100" + match.group(1)) if not match.group(1).startswith("-100") else int(match.group(1))
        msg_id = int(match.group(2))
        return channel_id, msg_id
    raise ValueError("Invalid Telegram message link format. Only /c/ links are supported.")

    
# =========================
# File Utilities
# =========================
async def upsert_file_info(file_info):
    """Insert or update file info, avoiding duplicates."""
    await files_col.update_one(
        {"channel_id": file_info["channel_id"], "message_id": file_info["message_id"]},
        {"$set": file_info},
        upsert=True
    )

def extract_file_info(message, channel_id=None):
    """Extract file info from a Pyrogram message."""
    caption_name = message.caption.strip() if message.caption else None
    file_info = {
        "channel_id": channel_id if channel_id is not None else message.chat.id,
        "message_id": message.id,
        "file_name": None,
        "file_size": None,
        "file_format": None,
    }
    if message.document:
        file_info["file_name"] = caption_name or message.document.file_name
        file_info["file_size"] = message.document.file_size
        file_info["file_format"] = message.document.mime_type
    elif message.video:
        file_info["file_name"] = caption_name or (message.video.file_name or "video.mp4")
        file_info["file_size"] = message.video.file_size
        file_info["file_format"] = message.video.mime_type
    elif message.audio:
        file_info["file_name"] = caption_name or (message.audio.file_name or "audio.mp3")
        file_info["file_size"] = message.audio.file_size
        file_info["file_format"] = message.audio.mime_type
        file_info["file_title"] = message.audio.title
        file_info["file_artist"] = message.audio.performer
    elif message.photo:
        file_info["file_name"] = caption_name or "photo.jpg"
        file_info["file_size"] = getattr(message.photo, "file_size", None)
        file_info["file_format"] = "image/jpeg"
    if file_info["file_name"]:
        file_info["file_name"] = remove_extension(
            re.sub(r"[',]", "", file_info["file_name"].replace("&", "and")).split("\n")[0]
        )
    return file_info

def human_readable_size(size):
    for unit in ['B','KB','MB','GB','TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def remove_extension(caption):
    try:
        # Remove the extension and everything after it
        cleaned_caption = re.sub(r'\.(mkv|mp4|webm).*$', '', caption, flags=re.IGNORECASE)
        return cleaned_caption
    except Exception as e:
        logger.error(e)
        return None
    
def remove_unwanted(caption):
    try:
        # Match and keep everything up to and including the extension
        match = re.match(r'^(.*?\.(mkv|mp4|webm))', caption, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return caption  # Return original if no match
    except Exception as e:
        logger.error(e)
        return None

# =========================
# Async/Bot Utilities
# =========================
async def safe_api_call(coro_factory, max_retries=3):
    """Utility wrapper to add delay and retry for flood waits."""
    retries = 0
    while retries < max_retries:
        try:
            return await coro_factory()
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid, UserIsBot) as e:
            raise e
        except FloodWait as e:
            retries += 1
            if retries < max_retries:
                sleep_duration = e.value * 1.2
                logger.warning(f"FloodWait: Sleeping for {sleep_duration:.2f} seconds before retrying. Attempt {retries}/{max_retries}")
                await asyncio.sleep(sleep_duration)
            else:
                logger.error(f"FloodWait limit reached after {max_retries} attempts. Giving up. {e}")
                return None
        except Exception as e:
            logger.error(f"An error occurred during an API call: {e}")
            return None
    return None

async def delete_after_delay(client, channel_id, message_id, delay=AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try:
        await safe_api_call(lambda: client.delete_messages(channel_id, message_id))
    except Exception as e:
        logger.error(f"Failed to auto delete message: {e}")

async def auto_delete_message(user_message, bot_message):
    try:        
        await asyncio.sleep(AUTO_DELETE_SECONDS)
        await safe_api_call(lambda: user_message.delete())
        await safe_api_call(lambda: bot_message.delete())
    except Exception as e:
        pass


# =========================
# Queue System for File Processing
# =========================

file_queue = asyncio.PriorityQueue()

def get_queue_size():
    """Returns the current size of the file processing queue."""
    return file_queue.qsize()

async def handle_duplicate_file(bot, file_info, log_duplicate: bool):
    """Checks for duplicate files and logs if requested."""
    existing = await files_col.find_one({"file_name": file_info["file_name"]})

    if existing:
        if log_duplicate:
            telegram_link = generate_c_link(
                file_info["channel_id"], file_info["message_id"]
            )
            await asyncio.sleep(3)
            await safe_api_call(
                lambda: bot.send_message(
                    LOG_CHANNEL_ID,
                    f"⚠️ Duplicate File.\nLink: {telegram_link}",
                    parse_mode=enums.ParseMode.HTML,
                )
            )
        return True
    return False

async def file_queue_worker(bot):
    while True:
        _priority, item = await file_queue.get()
        file_info, _, message, log_duplicate = item
        try:
            if await handle_duplicate_file(bot, file_info, log_duplicate):
                continue

            # Upsert file_info directly
            await upsert_file_info(file_info)

        except Exception as e:
            logger.error(f"❌ Error saving file: {e}")
        finally:
            file_queue.task_done()

# =========================
# Unified File Queueing
# =========================

async def queue_file_for_processing(
    message, channel_id=None, reply_func=None, log_duplicates=True
):
    try:
        file_info = extract_file_info(message, channel_id=channel_id)
        if file_info["file_name"]:
            item = (file_info, reply_func, message, log_duplicates)
            await file_queue.put((message.id, item))
    except Exception as e:
        if reply_func:
            await safe_api_call(lambda: reply_func(f"❌ Error queuing file: {e}"))

async def generate_otp(user_id):
    """
    Generate a 6-digit OTP and store it in users_col.
    Always generates a fresh OTP.
    """
    otp = str(random.randint(100000, 999999))
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10) # OTP valid for 10 mins

    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "otp": otp,
                "otp_expiry": expiry
            }
        },
        upsert=True
    )
    return otp

async def verify_otp(user_id, otp):
    """
    Verify the OTP for a given user_id.
    If valid, authorize the user and clear the OTP.
    Returns the session token if successful, else None.
    """
    doc = await users_col.find_one({"user_id": user_id, "otp": otp})
    if not doc:
        return None

    expiry = doc.get("otp_expiry")
    if isinstance(expiry, datetime) and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if not expiry or expiry < datetime.now(timezone.utc):
        await users_col.update_one({"user_id": user_id}, {"$unset": {"otp": "", "otp_expiry": ""}})
        return None

    session_token = await authorize_user(user_id)
    await users_col.update_one({"user_id": user_id}, {"$unset": {"otp": "", "otp_expiry": ""}})
    return session_token

def remove_redandent(filename):
    """
    Remove common username patterns from a filename while preserving the content title.

    Args:
        filename (str): The input filename

    Returns:
        str: Filename with usernames removed
    """
    filename = filename.replace("\n", "\\n")

    patterns = [
        r"^@[\w\.-]+?(?=_)",
        r"_@[A-Za-z]+_|@[A-Za-z]+_|[\[\]\s@]*@[^.\s\[\]]+[\]\[\s@]*",  
        r"^[\w\.-]+?(?=_Uploads_)",  
        r"^(?:by|from)[\s_-]+[\w\.-]+?(?=_)",  
        r"^\[[\w\.-]+?\][\s_-]*",  
        r"^\([\w\.-]+?\)[\s_-]*",  
    ]

    result = filename
    for pattern in patterns:
        match = re.search(pattern, result)
        if match:
            result = re.sub(pattern, " ", result)
            break  

    
    result = re.sub(r"^[_\s-]+|[_\s-]+$", " ", result)

    return result
