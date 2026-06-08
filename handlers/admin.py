import logging
from fastapi import APIRouter, Depends, HTTPException, Header, status
from db import files_col, allowed_channels_col, comments_col
from utility import is_user_authorized, build_search_pipeline
from config import OWNER_ID
from app import bot
from bson.objectid import ObjectId

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.strip():
        logger.warning("Authorization header missing or empty")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning(f"Invalid authorization scheme: {parts[0] if parts else 'None'}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization scheme")

    token = parts[1]

    try:
        if ":" not in token:
            logger.warning("Invalid token format: missing colon")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")
        
        user_id_str, session_token = token.split(":", 1)
        user_id = int(user_id_str)

        if not await is_user_authorized(user_id, session_token):
            logger.warning(f"User {user_id} not authorized")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization required")
        return {"user_id": user_id, "session_token": session_token}
    except (ValueError, TypeError) as e:
        logger.warning(f"Error parsing token: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

async def get_current_admin(user_data: dict = Depends(get_current_user)):
    user_id = user_data["user_id"]
    if user_id != OWNER_ID:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user_id

@router.get("/channels")
async def get_channels(admin_id: int = Depends(get_current_admin)):
    channels = []
    async for channel in allowed_channels_col.find({}, {"_id": 0, "channel_id": 1, "channel_name": 1}):
        channels.append(channel)
    return channels

@router.get("/files")
async def get_files(
    admin_id: int = Depends(get_current_admin),
    page: int = 1,
    search: str = None,
    channel_id: int = None
):
    page_size = 10
    skip = (page - 1) * page_size
    query = {}
    
    if channel_id:
        query["channel_id"] = channel_id

    sort_order = [("_id", -1)]

    if search:
        sanitized_search = bot.sanitize_query(search)
        pipeline = build_search_pipeline(sanitized_search, 'file_name', query, skip, page_size, sort_order=sort_order)
        result = await files_col.aggregate(pipeline).to_list(length=None)
        files_data = result[0]['results'] if result and 'results' in result[0] else []
        total_files = result[0]['totalCount'][0]['total'] if result and 'totalCount' in result[0] and result[0]['totalCount'] else 0
    else:
        files_cursor = files_col.find(query).sort(sort_order).skip(skip).limit(page_size)
        total_files = await files_col.count_documents(query)
        files_data = await files_cursor.to_list(length=page_size)

    files = []
    for file in files_data:
        files.append({
            "id": str(file.get("_id")),
            "file_name": file.get("file_name"),
            "poster_url": file.get("poster_url"),
        })
        
    total_pages = (total_files + page_size - 1) // page_size
    
    return {
        "files": files,
        "total_pages": total_pages,
        "current_page": page
    }

@router.put("/files/{file_id}")
async def update_file_poster(file_id: str, data: dict, admin_id: int = Depends(get_current_admin)):
    poster_url = data.get("poster_url")
    try:
        db_update = {"poster_url": poster_url}
        await files_col.update_one({"_id": ObjectId(file_id)}, {"$set": db_update})
        return {"status": "success", "poster_url": poster_url}
    except ValueError as e:
        logger.error(f"Failed to update poster for file")
        raise HTTPException(status_code=400, detail="Failed to update image. Please try again.")
    
@router.delete("/files/{file_id}")
async def delete_file(file_id: str, admin_id: int = Depends(get_current_admin)):
    await files_col.delete_one({"_id": ObjectId(file_id)})
    return {"status": "success"}


