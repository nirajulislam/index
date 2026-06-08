
import logging
import asyncio
from pyrogram import filters, enums
from utility import (
    safe_api_call,
    auto_delete_message,
    queue_file_for_processing,
    AUTO_DELETE_SECONDS,
    add_user
)
from app import bot
from db import allowed_channels_col

logger = logging.getLogger(__name__)

@bot.on_chat_member_updated()
async def on_chat_member_updated_handler(client, chat_member_updated):
    try:
        # Get bot's own ID
        me = client.me or await client.get_me()
        
        if not (chat_member_updated.new_chat_member and chat_member_updated.new_chat_member.user.id == me.id):
            return

        was_not_member = not chat_member_updated.old_chat_member or chat_member_updated.old_chat_member.status in [
            enums.ChatMemberStatus.LEFT,
            enums.ChatMemberStatus.BANNED,
        ]
        
        if chat_member_updated.new_chat_member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.MEMBER]:
            if was_not_member:
                user_id = chat_member_updated.from_user.id if chat_member_updated.from_user else None
                if not user_id:
                    return
                
                if chat_member_updated.from_user.is_bot:
                    return

                chat_id = chat_member_updated.chat.id
                
                if chat_member_updated.chat.type in [enums.ChatType.CHANNEL, enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:                    
                    try:
                        await client.send_message(
                            user_id,
                            f"ℹ️️ Channel Details:\n🏷️ Title: <b>{chat_member_updated.chat.title}</b>\n🆔: <code>{chat_id}</code>"
                        )
                    except Exception as e:
                        logger.warning(f"Could not send confirmation message to user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in on_chat_member_updated_handler: {e}")

async def process_start_logic(client, user, message=None, query=None):
    try:
        user_id = user.id
        first_name = user.first_name or "there"
        user_doc = await add_user(user_id)

        welcome_text = (
            f"Hi <b>{first_name}</b> 🆔 <code>{user_id}</code> !👋\n\n"
            "Thanks for hopping in! 😄\n"
            "We will reach out to you soon.\n"
            "Sit tight — we’ll be in touch before you know it! 🚀"
        )

        if query:
            await query.answer("Thank you for joining! 😊")
            await safe_api_call(lambda: query.message.edit_text(welcome_text))
            
            user_msg = query.message.reply_to_message
            if user_msg:
                bot.loop.create_task(auto_delete_message(user_msg, query.message))
            else:
                # Fallback: only auto-delete the bot message
                async def delete_bot_msg_only(msg):
                    await asyncio.sleep(AUTO_DELETE_SECONDS)
                    await safe_api_call(lambda: msg.delete())
                bot.loop.create_task(delete_bot_msg_only(query.message))
        elif message:
            reply_msg = await safe_api_call(lambda: message.reply_text(
                welcome_text,
                quote=True,
            ))
            if reply_msg:
                bot.loop.create_task(auto_delete_message(message, reply_msg))

    except Exception as e:
        logger.error(f"⚠️ Error in process_start_logic: {e}")

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    await process_start_logic(client, message.from_user, message=message)

@bot.on_message(filters.channel & (filters.document | filters.video | filters.audio | filters.photo))
async def channel_file_handler(client, message):
    try:
        channel_id = message.chat.id
        channel_doc = await allowed_channels_col.find_one({"channel_id": channel_id})
        if not channel_doc:
            return

        asyncio.create_task(queue_file_for_processing(message))
        
    except Exception as e:
        logger.error(f"Error in channel_file_handler: {e}")
                