import asyncio
import logging
import aiohttp
import json
import base64
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

# ==========================================
# ⚙️ الإعدادات
# ==========================================

# 1. توكن بوت تيليجرام الخاص بك
BOT_TOKEN = "8395701844:AAHaPmHA4cM1WGqz3IWqNpx0YwS5tauqyhE"

# 2. الآيدي الخاص بك (للأمان)
ADMIN_ID = 6595593335

# 3. مفتاح API الرسمي الذي قدمته
GEMINI_API_KEY = "tts-4edd95699941eccb1816bd819c07fbe3"
API_URL = "https://api.geminigen.ai/uapi/v1/generate"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_pending = {}
album_buffer = {}

# ==========================================
# 🧠 كلاس التعامل مع API الرسمي الجديد
# ==========================================
class OfficialGeminiClient:
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
             "accept": "application/json" # توقع استجابة JSON
        }

    async def generate_image(self, prompt, aspect_ratio="1:1", source_image_bytes=None):
        """
        دالة الت generating الرسمية.
        تقوم بإرسال البرومبت، المقاس، والصورة (إن وجدت) كـ JSON.
        """
        timeout = aiohttp.ClientTimeout(total=120) # وقت انتظار أقصى دقيقتين

        # إعداد البيانات الأساسية (حسب طلب Curl الذي أرسلته)
        payload = {
            "type": "image", # قد يتغير هذا إذا كان تعديل، لكن سنبدأ هكذا
            "prompt": prompt
        }

        # إضافة المقاس (فرضية قياسية)
        # ملاحظة: قد يحتاج هذا التعديل إذا كان الـ API يتوقع صيغة مختلفة
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio

        # إضافة الصورة للتعديل (إذا وجدت)
        # يتم تحويل الصورة إلى Base64 لإرسالها داخل JSON
        if source_image_bytes:
            print("🔄 جاري تشفير الصورة إلى Base64...")
            base64_image = base64.b64encode(source_image_bytes).decode('utf-8')
            # فرضية: الـ API يتوقع الصورة في حقل اسمه init_image أو image_base64
            # سنستخدم init_image كمعيار شائع. إذا فشل، سنحتاج لمعرفة الاسم الصحيح.
            payload["init_image"] = base64_image
            # payload["type"] = "image_edit" # ربما نحتاج تغيير النوع هنا

        print(f"🚀 Sending Official API Request to {API_URL}...")
        # print(f"Payload (truncated): {str(payload)[:200]}...") # لطباعة جزء من البيانات للتجربة

        async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
            try:
                async with session.post(API_URL, json=payload) as resp:
                    resp_text = await resp.text()
                    
                    print(f"📡 API Response Status: {resp.status}")
                    # print(f"📡 API Response Body: {resp_text[:500]}") # طباعة أول 500 حرف من الرد

                    if resp.status != 200:
                        return None, f"خطأ من السيرفر: {resp.status} - {resp_text[:100]}"
                    
                    try:
                        result = json.loads(resp_text)
                        # فرضية هامة: نفترض أن الرد يحتوي على رابط الصورة في حقل اسمه url أو output
                        # بناءً على خبرتي في هذه الـ APIs، الرد لا يكون الصورة مباشرة بل رابط لها
                        
                        image_url = None
                        # محاولة العثور على الرابط في أماكن شائعة في الرد
                        if isinstance(result, dict):
                             image_url = result.get("url") or result.get("output", {}).get("url") or result.get("image_url")
                        
                        if not image_url and isinstance(result, list) and len(result) > 0:
                             # أحياناً يكون الرد قائمة من النتائج
                             image_url = result[0].get("url")

                        if not image_url:
                             # إذا لم نجد رابطاً، ربما الرد هو الصورة مباشرة؟ (نادر في JSON)
                             # أو ربما هيكل الرد مختلف عما توقعنا.
                             print(f"⚠️ Could not find image URL in standard fields. Response: {resp_text}")
                             return None, "تم إنشاء الصورة لكن لم أستطع العثور على الرابط في الرد. راجع السجلات."

                        # تحميل الصورة النهائية من الرابط المستلم
                        print(f"⬇️ Downloading finished image from: {image_url}")
                        async with aiohttp.ClientSession() as dl_session:
                            async with dl_session.get(image_url) as img_resp:
                                if img_resp.status == 200:
                                    return await img_resp.read(), None
                                else:
                                    return None, "فشل تحميل الصورة النهائية من الرابط."

                    except json.JSONDecodeError:
                        print(f"❌ Response is not JSON: {resp_text}")
                        return None, "الرد من السيرفر ليس بصيغة JSON المتوقعة."


            except Exception as e:
                print(f"❌ Connection Error: {e}")
                return None, str(e)

gemini = OfficialGeminiClient()

# ==========================================
# 🔐 الصلاحيات ولوحة التحكم
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
# 📩 الهاندلرز (نفس منطق البوت السابق)
# ==========================================
@dp.message(CommandStart())
async def start(msg: types.Message):
    if is_admin(msg.from_user.id): await msg.answer("👋 **البوت جاهز (Official API Mode)**\nأرسل نصاً للتوليد، أو صوراً للتعديل.")

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
        await ctx.reply("⚠️ اكتب وصفاً للتعديل.")
        return
    
    wait = await ctx.reply(f"📥 استلام الصور...")
    try:
        # في التعديل الرسمي، غالباً ما يتم دعم صورة واحدة فقط كمرجع (init_image)
        # سنأخذ أول صورة فقط.
        m = msgs[0]
        f = await bot.get_file(m.photo[-1].file_id)
        image_bytes = await bot.download_file(f.file_path)
        
        user_pending[ctx.from_user.id] = {'prompt': prompt, 'images': [image_bytes], 'msg_id': ctx.message_id}
        await wait.delete()
        await ctx.reply("📏 اختر المقاس (للتعديل):", reply_markup=get_size_keyboard())
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
    source_img = data['images'][0] if data['images'] else None
    
    await call.message.edit_text(f"⏳ جاري العمل ({size}) عبر الـ API الرسمي...")
    await bot.send_chat_action(call.message.chat.id, ChatAction.UPLOAD_PHOTO)
    
    # استدعاء الدالة الجديدة
    img_bytes, err = await gemini.generate_image(data['prompt'], size, source_img)
    
    if img_bytes:
        file = BufferedInputFile(img_bytes, filename="image.png")
        await call.message.delete()
        try:
            await call.message.answer_photo(file, caption=f"✅ {data['prompt']}", reply_to_message_id=data['msg_id'])
        except:
             await call.message.answer_photo(file, caption=f"✅ {data['prompt']}")
    else:
        await call.message.edit_text(f"❌ حدث خطأ:\n{err}")

@dp.callback_query(F.data == "cancel")
async def on_cancel(call: CallbackQuery):
    if call.from_user.id in user_pending: del user_pending[call.from_user.id]
    await call.message.delete()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
