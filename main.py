import asyncio
import logging
import aiohttp
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

# ==========================================
# ⚙️ الإعدادات (التوكنات والآيدي)
# ==========================================

# 1. توكن البوت الجديد
BOT_TOKEN = "8395701844:AAHaPmHA4cM1WGqz3IWqNpx0YwS5tauqyhE"

# 2. آيدي الأدمن (ضع الآيدي الخاص بك هنا لاستقبال الأخطاء)
ADMIN_ID = 6595593335  # 👈 استبدل هذا الرقم بآيدي حسابك في تيليجرام

# 3. توكن GeminiGen (تأكد أنه صالح)
GEMINI_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NjQxNzg0MTksInN1YiI6IjY3MGJkNmNlLWM5NTktMTFmMC1iNjcwLTJlZjgyZDcwM2EwOSJ9.PMeS1YB_Q_TrWKaQKhUe8jB4x7qZzwTnZHlAp--h-Xw"

API_BASE = "https://api.geminigen.ai"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ذاكرة مؤقتة
user_pending = {} 
album_buffer = {} # لتخزين الصور القادمة كألبوم

# ==========================================
# 🧠 كلاس التعامل مع Gemini API
# ==========================================
class GeminiClient:
    def __init__(self):
        # تحديث الهيدرز بناءً على طلبك الأخير
        self.headers = {
            "authority": "api.geminigen.ai",
            "accept": "application/json, text/plain, */*",
            "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": f"Bearer {GEMINI_TOKEN}",
            "origin": "https://geminigen.ai",
            "referer": "https://geminigen.ai/",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; M2006C3LC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
        }

    async def generate_image(self, prompt, aspect_ratio, images_data=None):
        # زيادة وقت الانتظار إلى 5 دقائق (300 ثانية)
        timeout = aiohttp.ClientTimeout(total=300)
        
        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            try:
                data = aiohttp.FormData()
                data.add_field('prompt', prompt)
                data.add_field('model', 'imagen-pro')
                data.add_field('aspect_ratio', aspect_ratio)
                data.add_field('style', 'None')

                if images_data:
                    print(f"🚀 Sending Edit Request ({len(images_data)} images)...")
                    for i, img_bytes in enumerate(images_data):
                        # إرسال جميع الصور باسم 'files'
                        data.add_field('files', img_bytes, filename=f"image_{i}.jpg", content_type='image/jpeg')
                else:
                    print("🚀 Sending Generate Request...")

                # 1. طلب الإنشاء
                async with session.post(f"{API_BASE}/api/generate_image", data=data) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise Exception(f"API Error {resp.status}: {text[:200]}")
                    result = await resp.json()

                uuid = result.get('uuid')
                if not uuid:
                    raise Exception(f"No UUID returned: {result}")

                # 2. انتظار النتيجة (Polling)
                print(f"⏳ Waiting for UUID: {uuid}")
                for _ in range(100): # محاولة لمدة 5 دقائق (100 * 3 ثواني)
                    async with session.get(f"{API_BASE}/api/history/{uuid}") as hist_resp:
                        if hist_resp.status == 200:
                            status_data = await hist_resp.json()
                            status = status_data.get('status')
                            
                            if status == 2: # نجاح
                                image_url = status_data['generated_image'][0]['image_url']
                                async with session.get(image_url) as img_get:
                                    if img_get.status == 200:
                                        return await img_get.read(), None
                                    else:
                                        raise Exception("فشل تحميل الصورة النهائية")
                            
                            elif status == 3: # فشل
                                error_msg = status_data.get('error', 'Unknown Error')
                                raise Exception(f"فشل التوليد من المصدر (Status 3): {error_msg}")
                        
                    await asyncio.sleep(3)
                
                raise Exception("انتهت مهلة الانتظار (Timeout)")

            except Exception as e:
                return None, str(e)

gemini = GeminiClient()

# ==========================================
# ⌨️ لوحة الأزرار
# ==========================================
def get_size_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="مربع (1:1) 🟦", callback_data="size:1:1")],
        [
            InlineKeyboardButton(text="طولي (9:16) 📱", callback_data="size:9:16"),
            InlineKeyboardButton(text="عريض (16:9) 💻", callback_data="size:16:9"),
        ],
        [
            InlineKeyboardButton(text="أفقي (4:3) 📷", callback_data="size:4:3"),
            InlineKeyboardButton(text="سينمائي (21:9) 🎬", callback_data="size:21:9"),
        ],
        [InlineKeyboardButton(text="إلغاء ❌", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==========================================
# 📩 معالجة الرسائل
# ==========================================

@dp.message(CommandStart())
async def start(msg: types.Message):
    await msg.answer(
        "👋 **مرحباً!**\n\n"
        "أرسل نصاً للتوليد، أو صورة (أو مجموعة صور) مع وصف للتعديل."
    )

# 1. استقبال النص
@dp.message(F.text)
async def handle_text(msg: types.Message):
    user_pending[msg.from_user.id] = {
        'prompt': msg.text,
        'images': None,
        'msg_id': msg.message_id
    }
    await msg.reply("📏 اختر مقاس الصورة:", reply_markup=get_size_keyboard())

# 2. استقبال الصور (نظام تجميع الألبومات)
@dp.message(F.photo)
async def handle_photos(msg: types.Message):
    user_id = msg.from_user.id
    group_id = msg.media_group_id

    # إذا لم يكن ألبوم (صورة واحدة)
    if not group_id:
        await process_images(msg, [msg])
        return

    # إذا كان ألبوم، ننتظر تجميع الباقي
    if group_id not in album_buffer:
        album_buffer[group_id] = []
        asyncio.create_task(wait_for_album(group_id, msg))
    
    album_buffer[group_id].append(msg)

async def wait_for_album(group_id, first_msg):
    await asyncio.sleep(2) # انتظار ثانيتين لوصول باقي الصور
    
    if group_id in album_buffer:
        messages = album_buffer.pop(group_id)
        # ترتيب الرسائل للتأكد
        messages.sort(key=lambda x: x.message_id)
        await process_images(first_msg, messages)

async def process_images(msg_context, messages_list):
    # البحث عن الوصف في أي من الصور
    prompt = next((m.caption for m in messages_list if m.caption), None)
    
    if not prompt:
        await msg_context.reply("⚠️ يرجى كتابة وصف للتعديل مع الصور.")
        return

    wait_msg = await msg_context.reply(f"📥 جاري تحميل {len(messages_list)} صور...")
    
    try:
        images_data = []
        for m in messages_list:
            # تحميل أعلى دقة
            file_id = m.photo[-1].file_id
            file = await bot.get_file(file_id)
            file_bytes = await bot.download_file(file.file_path)
            images_data.append(file_bytes)

        # حفظ البيانات في الذاكرة
        user_pending[msg_context.from_user.id] = {
            'prompt': prompt,
            'images': images_data,
            'msg_id': msg_context.message_id
        }
        
        await wait_msg.delete()
        await msg_context.reply(f"📸 تم استلام {len(images_data)} صور.\n📏 اختر مقاس النتيجة:", reply_markup=get_size_keyboard())

    except Exception as e:
        await wait_msg.delete()
        await msg_context.reply("❌ حدث خطأ أثناء معالجة الصور.")
        # إرسال الخطأ للأدمن
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, f"⚠️ Error processing images:\nUser: {msg_context.from_user.id}\nError: {str(e)}")

# ==========================================
# 🖱️ معالجة الأزرار
# ==========================================

@dp.callback_query(F.data.startswith("size:"))
async def on_size_select(call: CallbackQuery):
    user_id = call.from_user.id
    size = call.data.replace("size:", "")
    
    if user_id not in user_pending:
        await call.message.edit_text("❌ انتهت الصلاحية. أعد الإرسال.")
        return

    data = user_pending.pop(user_id)
    prompt = data['prompt']
    images = data['images']
    
    action_text = "تعديل" if images else "توليد"
    await call.message.edit_text(f"⏳ جاري {action_text} الصورة...\nهذا قد يستغرق دقيقتين.")
    await bot.send_chat_action(call.message.chat.id, ChatAction.UPLOAD_PHOTO)
    
    # الاتصال بالذكاء الاصطناعي
    final_img_bytes, error = await gemini.generate_image(prompt, size, images)
    
    if final_img_bytes:
        file = BufferedInputFile(final_img_bytes, filename=f"gemini_{size}.png")
        await call.message.delete()
        try:
            await call.message.answer_photo(
                file, 
                caption=f"✨ **تم {action_text} بنجاح!**\n📝: {prompt}",
                reply_to_message_id=data['msg_id']
            )
        except:
             await call.message.answer_photo(file, caption=f"✅ {prompt}")
    else:
        # 🛑 حالة الخطأ (للمستخدم والأدمن)
        
        # 1. للمستخدم (رسالة عامة)
        await call.message.edit_text("❌ عذراً، حدث خطأ أثناء المعالجة.\nيرجى المحاولة لاحقاً.")
        
        # 2. للأدمن (التفاصيل الكاملة)
        if ADMIN_ID:
            error_report = (
                f"🚨 **Technical Error Report**\n"
                f"User ID: `{user_id}`\n"
                f"Action: {action_text}\n"
                f"Prompt: {prompt}\n"
                f"Error Details: `{error}`"
            )
            try:
                await bot.send_message(ADMIN_ID, error_report)
            except:
                print("Failed to send error to admin")

@dp.callback_query(F.data == "cancel")
async def on_cancel(call: CallbackQuery):
    if call.from_user.id in user_pending:
        del user_pending[call.from_user.id]
    await call.message.delete()

# ==========================================
# 🚀 التشغيل
# ==========================================
async def main():
    print("🤖 Bot Started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
