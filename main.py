import asyncio
import logging
import aiohttp
from typing import List, Dict, Union
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

# ---------------- إعدادات البوت ----------------
TOKEN = "8395701844:AAEAjFHFb75rbLpbPOShlwLgDnDhfc7F8Js"
PHP_API_URL = "https://salahahmedyn.free.nf/tts.php"

# هيدرز الموقع
PHP_HEADERS = {
    "Host": "salahahmedyn.free.nf",
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; M2006C3LC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://salahahmedyn.free.nf/tts.php",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://salahahmedyn.free.nf",
    "Connection": "keep-alive",
    "Cookie": "__test=99f73c6e763d01933042886484c97c56", 
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1"
}

DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_pending_requests = {}
album_cache: Dict[str, List[types.Message]] = {}

def get_aspect_ratio_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="مربع (1:1) 🟦", callback_data="size:1:1")],
        [
            InlineKeyboardButton(text="طولي (9:16) 📱", callback_data="size:9:16"),
            InlineKeyboardButton(text="عريض (16:9) 💻", callback_data="size:16:9"),
        ],
        [
            InlineKeyboardButton(text="أفقي (4:3) 📷", callback_data="size:4:3"),
            InlineKeyboardButton(text="سينمائي (21:9) 🎬", callback_data="size:21:9"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ✅ دالة جديدة: تحميل الصورة من تيليجرام ورفعها لـ tmpfiles (لتجاوز حظر الاستضافة)
async def rehost_image(file_id: str):
    try:
        # 1. الحصول على معلومات الملف من تيليجرام
        file_info = await bot.get_file(file_id)
        telegram_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        
        async with aiohttp.ClientSession() as session:
            # 2. تحميل الصورة (كبيانات)
            async with session.get(telegram_url) as resp:
                if resp.status != 200: return None
                img_bytes = await resp.read()
            
            # 3. رفع الصورة إلى tmpfiles.org
            data = aiohttp.FormData()
            data.add_field('file', img_bytes, filename='image.jpg', content_type='image/jpeg')
            
            async with session.post('https://tmpfiles.org/api/v1/upload', data=data) as upload_resp:
                if upload_resp.status != 200: return None
                json_res = await upload_resp.json()
                
                # 4. تحويل الرابط إلى رابط تحميل مباشر (dl)
                original_url = json_res['data']['url']
                direct_url = original_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                return direct_url
    except Exception as e:
        print(f"Rehost Error: {e}")
        return None

# --- دالة الاتصال بالـ API ---
async def generate_image_task(prompt: str, image_links: str = None, aspect_ratio: str = "1:1"):
    timeout = aiohttp.ClientTimeout(total=300)
    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            payload = {"prompt": prompt, "aspect_ratio": aspect_ratio}
            
            if image_links:
                payload["links"] = image_links
                print(f"🚀 Sending Edit Request ({aspect_ratio})...")
            else:
                print(f"🚀 Sending Gen Request ({aspect_ratio})...")

            async with session.post(PHP_API_URL, data=payload, headers=PHP_HEADERS) as response:
                text_response = await response.text()
                
                if "aes.js" in text_response:
                    return None, "⛔️ حماية AES: الكوكيز تحتاج تحديث."

                try:
                    import json
                    start = text_response.find('{')
                    end = text_response.rfind('}') + 1
                    if start != -1 and end != -1:
                        data = json.loads(text_response[start:end])
                    else:
                        data = await response.json()
                except:
                    return None, f"فشل قراءة الرد: {text_response[:100]}"

                image_url = data.get("url")
                if not image_url:
                    return None, f"خطأ API: {data.get('error', 'Unknown')}"

            print(f"📥 Downloading result: {image_url}")
            async with session.get(image_url, headers=DOWNLOAD_HEADERS) as img_response:
                if img_response.status == 200:
                    return await img_response.read(), None
                else:
                    return None, f"فشل تحميل الصورة النهائية."

        except asyncio.TimeoutError:
            return None, "⏰ انتهت مهلة الانتظار."
        except Exception as e:
            return None, f"خطأ غير متوقع: {e}"

# --- Callback ---
@dp.callback_query(F.data.startswith("size:"))
async def handle_size_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    selected_size = callback.data.replace("size:", "")

    if user_id not in user_pending_requests:
        await callback.message.edit_text("❌ انتهت الصلاحية.")
        return

    request_data = user_pending_requests.pop(user_id)
    prompt = request_data['prompt']
    links = request_data.get('links')

    await callback.message.edit_text(f"⏳ جاري العمل بمقاس **{selected_size}**...")
    await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_PHOTO)

    image_bytes, error = await generate_image_task(prompt, links, selected_size)

    if image_bytes:
        file = BufferedInputFile(image_bytes, filename=f"img_{selected_size}.png")
        await callback.message.delete()
        try:
            await callback.message.answer_photo(photo=file, caption=f"✅ تم!\n📝: {prompt[:40]}...", reply_to_message_id=request_data.get('msg_id'))
        except:
            await callback.message.answer_photo(photo=file, caption="✅ تم التوليد!")
    else:
        await callback.message.edit_text(f"❌ حدث خطأ:\n{error}")

# --- Handlers ---
@dp.message(F.text)
async def handle_text(message: types.Message):
    user_pending_requests[message.from_user.id] = {
        'prompt': message.text, 'links': None, 'msg_id': message.message_id
    }
    await message.reply("📏 اختر المقاس:", reply_markup=get_aspect_ratio_keyboard())

@dp.message(F.photo & ~F.media_group_id)
async def handle_single_photo(message: types.Message):
    if not message.caption:
        await message.reply("⚠️ اكتب وصفاً للتعديل.")
        return

    # ✅ استخدام دالة إعادة الرفع بدلاً من الرابط المباشر
    wait = await message.reply("🔄 جاري رفع الصورة للسيرفر الوسيط...")
    rehosted_url = await rehost_image(message.photo[-1].file_id)
    await wait.delete()
    
    if not rehosted_url:
        await message.reply("❌ فشل رفع الصورة الوسيطة.")
        return

    user_pending_requests[message.from_user.id] = {
        'prompt': message.caption, 'links': rehosted_url, 'msg_id': message.message_id
    }
    await message.reply("📏 اختر مقاس النتيجة:", reply_markup=get_aspect_ratio_keyboard())

@dp.message(F.media_group_id)
async def handle_albums(message: types.Message):
    group_id = message.media_group_id
    if group_id not in album_cache:
        album_cache[group_id] = []
        asyncio.create_task(process_album_later(group_id, message))
    album_cache[group_id].append(message)

async def process_album_later(group_id: str, message: types.Message):
    await asyncio.sleep(2)
    messages = album_cache.pop(group_id, [])
    if not messages: return
    messages.sort(key=lambda x: x.message_id)
    
    prompt = next((msg.caption for msg in messages if msg.caption), None)
    if not prompt:
        await message.reply("⚠️ مطلوب وصف.")
        return

    wait = await message.reply(f"🔄 جاري رفع {len(messages)} صور...")
    
    # ✅ إعادة رفع جميع الصور
    rehosted_urls = []
    for msg in messages[:10]:
        if msg.photo:
            url = await rehost_image(msg.photo[-1].file_id)
            if url: rehosted_urls.append(url)
    
    await wait.delete()
    
    if not rehosted_urls:
        await message.reply("❌ فشل معالجة الصور.")
        return

    links_string = ",".join(rehosted_urls)
    
    user_pending_requests[message.from_user.id] = {
        'prompt': prompt, 'links': links_string, 'msg_id': message.message_id
    }
    await message.reply(f"📥 تم استلام {len(rehosted_urls)} صورة.\n📏 اختر المقاس:", reply_markup=get_aspect_ratio_keyboard())

@dp.message(CommandStart())
async def start(msg: types.Message):
    await msg.answer("مرحباً! أرسل نصاً للتوليد، أو صورة مع وصف للتعديل. 🎨")

async def main():
    print("🤖 Bot Started with Re-hosting Bridge...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
