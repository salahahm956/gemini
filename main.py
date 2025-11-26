import asyncio
import logging
import aiohttp
import json
from io import BytesIO
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

# ==========================================
# ⚙️ الإعدادات (التوكنات الجديدة)
# ==========================================
# توكن بوت تيليجرام
BOT_TOKEN = "8395701844:AAHaPmHA4cM1WGqz3IWqNpx0YwS5tauqyhE"

# توكن GeminiGen (الجديد المستخرج من cURL)
GEMINI_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NjQxNzg0MTksInN1YiI6IjY3MGJkNmNlLWM5NTktMTFmMC1iNjcwLTJlZjgyZDcwM2EwOSJ9.PMeS1YB_Q_TrWKaQKhUe8jB4x7qZzwTnZHlAp--h-Xw"

# روابط API
API_BASE = "https://api.geminigen.ai"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ذاكرة مؤقتة
user_pending = {}

# ==========================================
# 🧠 كلاس التعامل مع Gemini API (محدث)
# ==========================================
class GeminiClient:
    def __init__(self):
        # تم تحديث الهيدرز بناءً على طلبك الأخير
        self.headers = {
            "authority": "api.geminigen.ai",
            "accept": "application/json, text/plain, */*",
            "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": f"Bearer {GEMINI_TOKEN}",
            "origin": "https://geminigen.ai",
            "referer": "https://geminigen.ai/",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; M2006C3LC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
            # ملاحظة: Content-Type يتم إضافته تلقائياً بواسطة aiohttp مع الـ boundary الصحيح
        }

    async def generate_image(self, prompt, aspect_ratio, images_data=None):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                # تجهيز البيانات كـ Multipart (كما في cURL)
                data = aiohttp.FormData()
                data.add_field('prompt', prompt)
                data.add_field('model', 'imagen-pro')
                data.add_field('aspect_ratio', aspect_ratio)
                data.add_field('style', 'None')

                # إذا كان تعديل صور
                if images_data:
                    print(f"🚀 Sending Edit Request ({len(images_data)} images)...")
                    for i, img_bytes in enumerate(images_data):
                        # إضافة الصور بنفس اسم الحقل 'files'
                        data.add_field('files', img_bytes, filename=f"image_{i}.jpg", content_type='image/jpeg')
                else:
                    print("🚀 Sending Generate Request...")

                # 1. إرسال طلب الإنشاء
                async with session.post(f"{API_BASE}/api/generate_image", data=data) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return None, f"خطأ في الطلب ({resp.status}): {text[:100]}"
                    result = await resp.json()

                uuid = result.get('uuid')
                if not uuid:
                    return None, f"فشل بدء المهمة: {result}"

                # 2. انتظار النتيجة (Polling)
                print(f"⏳ Waiting for UUID: {uuid}")
                for _ in range(60): # انتظار لمدة 3 دقائق
                    async with session.get(f"{API_BASE}/api/history/{uuid}") as hist_resp:
                        if hist_resp.status != 200:
                            await asyncio.sleep(3)
                            continue
                            
                        status_data = await hist_resp.json()
                        status = status_data.get('status')
                        
                        if status == 2: # نجاح
                            if not status_data.get('generated_image'):
                                return None, "تم الانتهاء ولكن لا يوجد رابط صورة!"
                                
                            image_url = status_data['generated_image'][0]['image_url']
                            
                            # 3. تحميل الصورة النهائية
                            async with session.get(image_url) as img_get:
                                if img_get.status == 200:
                                    return await img_get.read(), None
                                else:
                                    return None, "فشل تحميل الصورة النهائية"
                        
                        elif status == 3: # فشل من المصدر
                            return None, "فشلت عملية التوليد من المصدر (Status 3)"
                            
                    await asyncio.sleep(3)
                
                return None, "انتهت مهلة الانتظار (Timeout)"

            except Exception as e:
                return None, f"خطأ اتصال: {str(e)}"

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
        "👋 **أهلاً بك في بوت Gemini AI المحدث!**\n\n"
        "🎨 **للتوليد:** أرسل وصفاً نصياً.\n"
        "🖼️ **للتعديل:** أرسل صورة مع الوصف.\n"
    )

# استقبال النص
@dp.message(F.text)
async def handle_text(msg: types.Message):
    user_pending[msg.from_user.id] = {
        'prompt': msg.text,
        'images': None,
        'msg_id': msg.message_id
    }
    await msg.reply("📏 اختر مقاس الصورة:", reply_markup=get_size_keyboard())

# استقبال الصور
@dp.message(F.photo)
async def handle_photo(msg: types.Message):
    if not msg.caption:
        await msg.reply("⚠️ يرجى كتابة وصف للتعديل مع الصورة.")
        return

    wait = await msg.reply("📥 جاري تحميل الصورة...")
    try:
        file_id = msg.photo[-1].file_id
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        user_pending[msg.from_user.id] = {
            'prompt': msg.caption,
            'images': [file_bytes],
            'msg_id': msg.message_id
        }
        
        await wait.delete()
        await msg.reply("📏 اختر مقاس النتيجة:", reply_markup=get_size_keyboard())
        
    except Exception as e:
        await wait.edit_text(f"❌ خطأ: {e}")

# ==========================================
# 🖱️ معالجة الأزرار
# ==========================================

@dp.callback_query(F.data.startswith("size:"))
async def on_size_select(call: CallbackQuery):
    user_id = call.from_user.id
    size = call.data.replace("size:", "")
    
    if user_id not in user_pending:
        await call.message.edit_text("❌ انتهت الصلاحية.")
        return

    data = user_pending.pop(user_id)
    prompt = data['prompt']
    images = data['images']
    
    mode_text = "تعديل" if images else "توليد"
    await call.message.edit_text(f"⏳ جاري {mode_text} الصورة ({size})...\n📝: {prompt[:30]}...")
    await bot.send_chat_action(call.message.chat.id, ChatAction.UPLOAD_PHOTO)
    
    final_img_bytes, error = await gemini.generate_image(prompt, size, images)
    
    if final_img_bytes:
        file = BufferedInputFile(final_img_bytes, filename=f"gemini_{size}.png")
        await call.message.delete()
        try:
            await call.message.answer_photo(
                file, 
                caption=f"✅ **تم!**\n📝: {prompt}",
                reply_to_message_id=data['msg_id']
            )
        except:
             await call.message.answer_photo(file, caption=f"✅ {prompt}")
    else:
        await call.message.edit_text(f"❌ فشل: {error}")

@dp.callback_query(F.data == "cancel")
async def on_cancel(call: CallbackQuery):
    if call.from_user.id in user_pending:
        del user_pending[call.from_user.id]
    await call.message.delete()

# ==========================================
# 🚀 التشغيل
# ==========================================
async def main():
    print("🤖 Bot Started with New Token...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
