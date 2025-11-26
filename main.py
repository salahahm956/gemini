import asyncio
import logging
import aiohttp
import json
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

# ==========================================
# ⚙️ الإعدادات
# ==========================================

BOT_TOKEN = "8395701844:AAHaPmHA4cM1WGqz3IWqNpx0YwS5tauqyhE"
ADMIN_ID = 6595593335 # هذا هو "السوبر أدمن" الذي لا يمكن حذفه

# التوكن الحالي (من طلبك الأخير)
CURRENT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NjQyNTE0OTcsInN1YiI6IjA2ZmJhNjcwLWNhY2YtMTFmMC1iMDNiLTUyZTQxZGI1MzgyZCJ9.fEA2-5na2Jpu-eJhrDvfAb7uAl4m_lSpVo2n0VbE-dk"

API_BASE = "https://api.geminigen.ai/api"
USERS_FILE = "users.json" # ملف لحفظ المستخدمين

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_pending = {}
album_buffer = {}

# ==========================================
# 📂 نظام إدارة المستخدمين (JSON)
# ==========================================
def load_users():
    if not os.path.exists(USERS_FILE):
        return [ADMIN_ID] # الافتراضي: الأدمن فقط
    try:
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
            if ADMIN_ID not in users: users.append(ADMIN_ID)
            return users
    except:
        return [ADMIN_ID]

def save_users(users_list):
    with open(USERS_FILE, 'w') as f:
        json.dump(users_list, f)

# تحميل القائمة عند البدء
ALLOWED_USERS = set(load_users())

def is_authorized(user_id):
    return user_id in ALLOWED_USERS

# ==========================================
# 🧠 كلاس التعامل مع Gemini API
# ==========================================
class GeminiClient:
    def __init__(self):
        self.token = CURRENT_TOKEN
        self.update_headers()

    def update_headers(self):
        self.headers = {
            "authority": "api.geminigen.ai",
            "accept": "application/json, text/plain, */*",
            "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": f"Bearer {self.token}",
            "origin": "https://geminigen.ai",
            "referer": "https://geminigen.ai/",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; M2006C3LC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
        }

    def set_new_token(self, new_token):
        self.token = new_token.replace("Bearer ", "").strip()
        self.update_headers()

    async def generate_image(self, prompt, aspect_ratio, images_data=None):
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            try:
                data = aiohttp.FormData()
                data.add_field('prompt', prompt)
                data.add_field('model', 'imagen-pro')
                data.add_field('aspect_ratio', aspect_ratio)
                data.add_field('style', 'None')

                if images_data:
                    print(f"🚀 Edit Request ({len(images_data)} images)...")
                    for i, img_bytes in enumerate(images_data):
                        data.add_field('files', img_bytes, filename=f"image_{i}.jpg", content_type='image/jpeg')
                else:
                    print("🚀 Generate Request...")

                async with session.post(f"{API_BASE}/generate_image", data=data) as resp:
                    if resp.status != 200:
                        return None, f"خطأ {resp.status}"
                    result = await resp.json()

                uuid = result.get('uuid')
                if not uuid: return None, "No UUID"

                print(f"⏳ UUID: {uuid}")
                image_url = None
                for _ in range(60):
                    async with session.get(f"{API_BASE}/history/{uuid}") as hist_resp:
                        if hist_resp.status == 200:
                            status_data = await hist_resp.json()
                            if status_data.get('status') == 2:
                                image_url = status_data['generated_image'][0]['image_url']
                                break
                            elif status_data.get('status') == 3:
                                return None, "فشل التوليد"
                    await asyncio.sleep(5)
                
                if not image_url: return None, "Timeout"

                async with aiohttp.ClientSession() as dl_session:
                    async with dl_session.get(image_url) as img_resp:
                        if img_resp.status == 200:
                            return await img_resp.read(), None
                        return None, "Download Error"
            except Exception as e:
                return None, str(e)

gemini = GeminiClient()

# ==========================================
# ⌨️ الكيبورد
# ==========================================
def get_size_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="مربع (1:1) 🟦", callback_data="size:1:1")],
        [InlineKeyboardButton(text="عريض (16:9) 💻", callback_data="size:16:9"),
         InlineKeyboardButton(text="طولي (9:16) 📱", callback_data="size:9:16")],
        [InlineKeyboardButton(text="إلغاء ❌", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==========================================
# 👮‍♂️ أوامر الإدارة (Add/Remove Users)
# ==========================================

# إضافة مستخدم: /id 12345
@dp.message(Command("id"))
async def add_user(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return # للأدمن فقط
    try:
        new_id = int(msg.text.split()[1])
        if new_id in ALLOWED_USERS:
            await msg.reply("⚠️ المستخدم موجود بالفعل.")
        else:
            ALLOWED_USERS.add(new_id)
            save_users(list(ALLOWED_USERS))
            await msg.reply(f"✅ تمت إضافة المستخدم: `{new_id}`", parse_mode="Markdown")
            # إشعار للمستخدم الجديد (اختياري)
            try: await bot.send_message(new_id, "🎉 تم تفعيل حسابك لاستخدام البوت!")
            except: pass
    except:
        await msg.reply("⚠️ خطأ. الصيغة:\n`/id الآيدي`", parse_mode="Markdown")

# حذف مستخدم: /ids 12345
@dp.message(Command("ids"))
async def remove_user(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return
    try:
        target_id = int(msg.text.split()[1])
        if target_id == ADMIN_ID:
            await msg.reply("🚫 لا يمكنك حذف الأدمن!")
            return
        
        if target_id in ALLOWED_USERS:
            ALLOWED_USERS.remove(target_id)
            save_users(list(ALLOWED_USERS))
            await msg.reply(f"🗑️ تم حذف المستخدم: `{target_id}`", parse_mode="Markdown")
        else:
            await msg.reply("⚠️ هذا المستخدم غير موجود.")
    except:
        await msg.reply("⚠️ خطأ. الصيغة:\n`/ids الآيدي`", parse_mode="Markdown")

# عرض القائمة: /users
@dp.message(Command("users"))
async def list_users(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return
    text = "👥 **قائمة المصرح لهم:**\n\n"
    for uid in ALLOWED_USERS:
        text += f"🆔 `{uid}`\n"
    await msg.reply(text, parse_mode="Markdown")

# تحديث التوكن: /token
@dp.message(Command("token"))
async def update_token(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return
    try:
        new_key = msg.text.split(maxsplit=1)[1]
        gemini.set_new_token(new_key)
        await msg.reply("✅ تم تحديث التوكن.")
    except:
        await msg.reply("⚠️ خطأ في التوكن.")

# ==========================================
# 📩 معالجة الرسائل (للمصرح لهم فقط)
# ==========================================

@dp.message(CommandStart())
async def start(msg: types.Message):
    if not is_authorized(msg.from_user.id):
        await msg.answer("⛔️ عذراً، هذا البوت خاص.")
        return
    await msg.answer("👋 **أهلاً بك!**\nأرسل نصاً للتوليد، أو صورة للتعديل.")

@dp.message(F.text)
async def handle_text(msg: types.Message):
    if not is_authorized(msg.from_user.id): return
    if msg.text.startswith("/"): return # تجاهل الأوامر
    
    user_pending[msg.from_user.id] = {'prompt': msg.text, 'images': None, 'msg_id': msg.message_id}
    await msg.reply("📏 اختر مقاس الصورة:", reply_markup=get_size_keyboard())

@dp.message(F.photo)
async def handle_photos(msg: types.Message):
    if not is_authorized(msg.from_user.id): return
    
    group_id = msg.media_group_id
    if not group_id:
        await process_images(msg, [msg])
        return
    if group_id not in album_buffer:
        album_buffer[group_id] = []
        asyncio.create_task(wait_for_album(group_id, msg))
    album_buffer[group_id].append(msg)

async def wait_for_album(group_id, first_msg):
    await asyncio.sleep(2)
    if group_id in album_buffer:
        msgs = album_buffer.pop(group_id)
        msgs.sort(key=lambda x: x.message_id)
        await process_images(first_msg, msgs)

async def process_images(ctx, msgs):
    prompt = next((m.caption for m in msgs if m.caption), None)
    if not prompt:
        await ctx.reply("⚠️ اكتب وصفاً.")
        return
    
    wait = await ctx.reply(f"📥 استلام {len(msgs)} صور...")
    try:
        images = []
        for m in msgs:
            f = await bot.get_file(m.photo[-1].file_id)
            images.append(await bot.download_file(f.file_path))
        
        user_pending[ctx.from_user.id] = {'prompt': prompt, 'images': images, 'msg_id': ctx.message_id}
        await wait.delete()
        await ctx.reply("📏 اختر المقاس:", reply_markup=get_size_keyboard())
    except Exception as e:
        await wait.delete()
        if ctx.from_user.id == ADMIN_ID:
            await ctx.reply(f"Error: {e}")

@dp.callback_query(F.data.startswith("size:"))
async def on_size(call: CallbackQuery):
    if not is_authorized(call.from_user.id): return
    uid = call.from_user.id
    if uid not in user_pending:
        await call.message.edit_text("❌ انتهت الجلسة.")
        return
    
    data = user_pending.pop(uid)
    size = call.data.replace("size:", "")
    
    await call.message.edit_text(f"⏳ جاري العمل ({size})...")
    await bot.send_chat_action(call.message.chat.id, ChatAction.UPLOAD_PHOTO)
    
    img_bytes, err = await gemini.generate_image(data['prompt'], size, data['images'])
    
    if img_bytes:
        file = BufferedInputFile(img_bytes, filename="image.png")
        await call.message.delete()
        try:
            await call.message.answer_photo(file, caption=f"✅ {data['prompt']}", reply_to_message_id=data['msg_id'])
        except:
             await call.message.answer_photo(file, caption=f"✅ {data['prompt']}")
    else:
        await call.message.edit_text(f"❌ حدث خطأ: {err}")

@dp.callback_query(F.data == "cancel")
async def on_cancel(call: CallbackQuery):
    if call.from_user.id in user_pending: del user_pending[call.from_user.id]
    await call.message.delete()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
