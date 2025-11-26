import asyncio
import logging
import aiohttp
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

# ==========================================
# ⚙️ الإعدادات
# ==========================================

# 1. توكن البوت
BOT_TOKEN = "8395701844:AAHaPmHA4cM1WGqz3IWqNpx0YwS5tauqyhE"

# 2. آيدي المطور
ADMIN_ID = 6595593335

# 3. توكن GeminiGen (الجديد من طلبك الأخير)
# هذا التوكن سيعمل الآن، ولتفعيله تلقائياً لاحقاً نحتاج لـ Login API
CURRENT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NjQyNDkzMjgsInN1YiI6IjY3MGJkNmNlLWM5NTktMTFmMC1iNjcwLTJlZjgyZDcwM2EwOSJ9.H4_yBgPCdFn8ZB5ie8bbGu3FdsGfFcsySPKTwhjX9ac"

API_BASE = "https://api.geminigen.ai"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_pending = {}
album_buffer = {}

# ==========================================
# 🧠 كلاس التعامل مع Gemini API
# ==========================================
class GeminiClient:
    def __init__(self):
        self.token = CURRENT_TOKEN
        self.update_headers()

    def update_headers(self):
        """تحديث الهيدرز بناءً على التوكن الحالي"""
        # تم نسخ الهيدرز بدقة من طلب cURL الأخير
        self.headers = {
            "authority": "api.geminigen.ai",
            "accept": "application/json, text/plain, */*",
            "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": f"Bearer {self.token}", # رجعنا لاستخدام Bearer حسب طلبك الأخير
            "origin": "https://geminigen.ai",
            "referer": "https://geminigen.ai/",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; M2006C3LC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
        }

    async def report_error(self, type_err, msg):
        try:
            await bot.send_message(ADMIN_ID, f"🚨 **System Error**\nType: {type_err}\nDetails: `{str(msg)[:3000]}`")
        except: pass

    # 🔄 دالة التجديد التلقائي (مكان السحر المستقبلي)
    async def auto_refresh_token(self):
        # ملاحظة: لكي تعمل هذه الدالة، نحتاج لطلب Login cURL
        # حالياً سنقوم فقط بإبلاغك
        await self.report_error("Token Expired", "حاول البوت التجديد لكن لا يوجد رابط Login.")
        return False

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
                        # اسم الحقل: files (كما في الـ curl)
                        data.add_field('files', img_bytes, filename=f"image_{i}.jpg", content_type='image/jpeg')
                else:
                    print("🚀 Generate Request...")

                # 1. إرسال الطلب
                async with session.post(f"{API_BASE}/api/generate_image", data=data) as resp:
                    resp_text = await resp.text()
                    
                    # إذا انتهى التوكن (401)، نحاول التجديد (مستقبلاً)
                    if resp.status == 401:
                        await self.report_error("Token Expired (401)", "التوكن انتهى ويحتاج تجديد.")
                        return None, "انتهت صلاحية الجلسة."

                    if resp.status != 200:
                        await self.report_error(f"API Error {resp.status}", resp_text)
                        return None, f"خطأ من المصدر: {resp.status}"
                    
                    result = json.loads(resp_text)

                uuid = result.get('uuid')
                if not uuid: return None, "لم يتم استلام UUID"

                # 2. انتظار النتيجة
                print(f"⏳ UUID: {uuid}")
                image_url = None
                
                for _ in range(100):
                    async with session.get(f"{API_BASE}/api/history/{uuid}") as hist_resp:
                        if hist_resp.status == 200:
                            status_data = await hist_resp.json()
                            status = status_data.get('status')
                            
                            if status == 2:
                                image_url = status_data['generated_image'][0]['image_url']
                                break
                            elif status == 3:
                                err_msg = status_data.get('error_message') or "Unknown"
                                if "high traffic" in str(err_msg).lower():
                                    return None, "⚠️ السيرفر مشغول جداً، حاول لاحقاً."
                                return None, f"رفض السيرفر: {err_msg}"
                        
                    await asyncio.sleep(3)
                
                if not image_url: return None, "انتهى الوقت."

                # 3. تحميل الصورة (جلسة نظيفة)
                async with aiohttp.ClientSession() as dl_session:
                    async with dl_session.get(image_url) as img_resp:
                        if img_resp.status == 200:
                            return await img_resp.read(), None
                        else:
                            return None, "فشل تحميل الصورة النهائية"

            except Exception as e:
                return None, str(e)

gemini = GeminiClient()

# ==========================================
# 🔐 الصلاحيات والكيبورد
# ==========================================
def is_admin(uid): return uid == ADMIN_ID

def get_size_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="مربع (1:1) 🟦", callback_data="size:1:1")],
        [InlineKeyboardButton(text="عريض (16:9) 💻", callback_data="size:16:9"),
         InlineKeyboardButton(text="طولي (9:16) 📱", callback_data="size:9:16")],
        [InlineKeyboardButton(text="إلغاء ❌", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==========================================
# 📩 الهاندلرز
# ==========================================
@dp.message(CommandStart())
async def start(msg: types.Message):
    if is_admin(msg.from_user.id): await msg.answer("🤖 البوت جاهز ويعمل بالنظام الجديد.")

@dp.message(F.text)
async def handle_text(msg: types.Message):
    if not is_admin(msg.from_user.id): return
    user_pending[msg.from_user.id] = {'prompt': msg.text, 'images': None, 'msg_id': msg.message_id}
    await msg.reply("📏 اختر المقاس:", reply_markup=get_size_keyboard())

@dp.message(F.photo)
async def handle_photos(msg: types.Message):
    if not is_admin(msg.from_user.id): return
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
        await bot.send_message(ADMIN_ID, f"Error: {e}")

@dp.callback_query(F.data.startswith("size:"))
async def on_size(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
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
        await call.message.edit_text(f"❌ {err}")

@dp.callback_query(F.data == "cancel")
async def on_cancel(call: CallbackQuery):
    if call.from_user.id in user_pending: del user_pending[call.from_user.id]
    await call.message.delete()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
