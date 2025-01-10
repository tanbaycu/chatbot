import asyncio
from concurrent.futures import ThreadPoolExecutor
from telebot.async_telebot import AsyncTeleBot
import aiohttp
from urllib.parse import urlparse, quote
import json
import logging
from collections import deque
import time
import re
import qrcode
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot and API configuration
BOT_TOKEN = "7431028632:AAEaOuGT17MZl2GBKGzfx3uwVOLxZQXu0G0"
GEMINI_API_KEY = "AIzaSyD8Zc-j7kc_FkSF_WXQdxQpc4bGBD5KElU"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"

bot = AsyncTeleBot(BOT_TOKEN)
executor = ThreadPoolExecutor(max_workers=50)

class MemoryHandler:
    def __init__(self, user_id):
        self.user_id = user_id
        self.file_path = f"memory_{user_id}.json"
        self.short_term_memory = deque(maxlen=5)
        self.long_term_memory = deque(maxlen=50)
        self.load_memory()

    def load_memory(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, 'r') as file:
                data = json.load(file)
                self.short_term_memory = deque(data.get('short_term', []), maxlen=5)
                self.long_term_memory = deque(data.get('long_term', []), maxlen=50)

    def save_memory(self):
        data = {
            'short_term': list(self.short_term_memory),
            'long_term': list(self.long_term_memory)
        }
        with open(self.file_path, 'w') as file:
            json.dump(data, file)

    def get_context(self):
        return list(self.short_term_memory) + list(self.long_term_memory)

    def update_memory(self, message, response):
        self.short_term_memory.append({"role": "user", "content": message})
        self.short_term_memory.append({"role": "assistant", "content": response})
        self.long_term_memory.append({"role": "user", "content": message})
        self.long_term_memory.append({"role": "assistant", "content": response})
        self.save_memory()

    def clear_memory(self):
        self.short_term_memory.clear()
        self.long_term_memory.clear()
        self.save_memory()

def get_memory_handler(user_id):
    return MemoryHandler(user_id)

async def generate_response(prompt, user_id, session):
    max_retries = 3
    retry_delay = 5
    memory_handler = get_memory_handler(user_id)
    context = memory_handler.get_context()

    # Prompt engineering
    system_prompt = "Bạn là trợ lý AI thông minh trên Telegram được tanbaycu lập trình và điều hành. Sử dụng Markdown và thêm emoji phù hợp và đa dạng. Trả lời ngắn gọn, tránh trả lời giống nhau cần tạo ra sự đa dạng trong phản hồi thông minh, hãy làm cho cuộc trò chuyện trở nên sinh động hấp dẫn, chính xác. Nêu ý chính bằng cách làm nổi bật nó, giải thích ngắn gọn nếu cần. Thân thiện, chuyên nghiệp. Tránh ký tự đặc biệt. Luôn tạo câu trả lời độc đáo cho mỗi câu hỏi, kể cả khi câu hỏi tương tự. Thay đổi cách diễn đạt, cấu trúc câu và từ ngữ trong mỗi lần trả lời. Cung cấp thông tin mới hoặc góc nhìn khác nếu câu hỏi tương tự. Sử dụng ví dụ, so sánh hoặc câu chuyện ngắn để minh họa ý tưởng khác biệt. Thay đổi giọng điệu và phong cách viết để tạo sự đa dạng. Đặt câu hỏi phản xạ khi thích hợp để khuyến khích suy nghĩ sâu hơn."
    enhanced_prompt = f"{system_prompt}\n\nUser: {prompt}\n\nAssistant:"

    for attempt in range(max_retries):
        try:
            url = f"{API_URL}?key={GEMINI_API_KEY}"
            headers = {"Content-Type": "application/json"}

            data = {
                "contents": [
                    {
                        "parts": [{"text": msg["content"]} for msg in context] + [{"text": enhanced_prompt}]
                    }
                ],
                "generationConfig": {
                    "temperature": 1,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 4096,
                }
            }

            async with session.post(url, headers=headers, json=data, timeout=30) as response:
                response.raise_for_status()
                result = await response.json()

            if 'candidates' in result and result['candidates']:
                text_response = result['candidates'][0]['content']['parts'][0]['text']
            else:
                raise ValueError("No valid response from Gemini API")

            memory_handler.update_memory(prompt, text_response)
            return text_response

        except asyncio.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            return "Yêu cầu đã hết thời gian chờ. Vui lòng thử lại sau."

        except aiohttp.ClientError as e:
            logger.error(f"Request error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            return f"Lỗi kết nối: {str(e)}"

        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
            return f"Xin lỗi, đã xảy ra lỗi không mong đợi: {str(e)}"

    return "Không thể tạo câu trả lời sau nhiều lần thử. Vui lòng thử lại sau."

def create_qr_code(data):
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img_path = "qrcode.png"
        img.save(img_path)

        return img_path
    except Exception as e:
        logger.error(f"Lỗi khi tạo QR code: {str(e)}")
        return None

async def shorten_url(long_url, session):
    try:
        api_url = f"http://tinyurl.com/api-create.php?url={long_url}"
        async with session.get(api_url) as response:
            response.raise_for_status()
            return await response.text()
    except Exception as e:
        logger.error(f"Lỗi khi rút gọn URL: {str(e)}")
        return None

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    user_first_name = message.from_user.first_name
    current_hour = time.localtime().tm_hour

    if 5 <= current_hour < 12:
        greeting = f"🌅 *Chào buổi sáng, {user_first_name}!*"
    elif 12 <= current_hour < 18:
        greeting = f"☀️ *Chào buổi chiều, {user_first_name}!*"
    else:
        greeting = f"🌙 *Chào buổi tối, {user_first_name}!*"

    welcome_message = f"{greeting}\n\n"
    welcome_message += "Tôi là trợ lý AI thông minh, sử dụng mô hình Gemini 2.0 với khả năng ghi nhớ ngắn hạn và dài hạn. "
    welcome_message += "Hãy đặt câu hỏi hoặc chia sẻ chủ đề bạn muốn thảo luận nhé!\n\n"
    welcome_message += "🔍 *Một số tính năng của tôi:*\n"
    welcome_message += "• Trả lời câu hỏi và cung cấp thông tin\n"
    welcome_message += "• Tạo mã QR (`/qrcode`)\n"
    welcome_message += "• Rút gọn URL (`/short`)\n"
    welcome_message += "• Và nhiều tính năng thú vị khác!\n\n"
    welcome_message += "Gõ `/info` để biết thêm chi tiết về tôi nhé!"

    await bot.reply_to(message, welcome_message, parse_mode='Markdown')

@bot.message_handler(commands=['qrcode'])
async def handle_qrcode(message):
    try:
        data = message.text[len('/qrcode '):]
        if not data:
            await bot.reply_to(message, "Vui lòng cung cấp dữ liệu để tạo QR code.")
            return

        img_path = create_qr_code(data)
        if img_path:
            with open(img_path, 'rb') as img_file:
                await bot.send_photo(message.chat.id, img_file)
        else:
            await bot.reply_to(message, "Đã xảy ra lỗi khi tạo QR code.")
    except Exception as e:
        logger.error(f"Lỗi khi xử lý lệnh qrcode: {str(e)}")
        await bot.reply_to(message, "Đã xảy ra lỗi khi xử lý lệnh qrcode.")

@bot.message_handler(commands=['short'])
async def handle_short(message):
    try:
        long_url = message.text[len('/short '):]
        if not long_url:
            await bot.reply_to(message, "Vui lòng cung cấp URL để rút gọn.")
            return

        async with aiohttp.ClientSession() as session:
            short_url = await shorten_url(long_url, session)
        if short_url:
            await bot.reply_to(message, f"URL rút gọn: {short_url}")
        else:
            await bot.reply_to(message, "Đã xảy ra lỗi khi rút gọn URL.")
    except Exception as e:
        logger.error(f"Lỗi khi xử lý lệnh short: {str(e)}")
        await bot.reply_to(message, "Đã xảy ra lỗi khi xử lý lệnh short.")

@bot.message_handler(func=lambda message: not message.text.startswith('/'))
async def handle_message(message):
    async def process_and_send_response():
        try:
            thinking_message = await bot.reply_to(message, "🤔 Bot đang suy nghĩ...")

            start_time = time.time()
            async with aiohttp.ClientSession() as session:
                response = await generate_response(message.text, message.from_user.id, session)
            end_time = time.time()
            processing_time = end_time - start_time

            full_response = f"({processing_time:.2f}s) - {response}"

            max_length = 4096
            if len(full_response) > max_length:
                chunks = [full_response[i:i+max_length] for i in range(0, len(full_response), max_length)]
                for i, chunk in enumerate(chunks):
                    try:
                        if i == 0:
                            await bot.edit_message_text(
                                chat_id=thinking_message.chat.id,
                                message_id=thinking_message.message_id,
                                text=chunk,
                                parse_mode='Markdown'
                            )
                        else:
                            await bot.send_message(
                                chat_id=thinking_message.chat.id,
                                text=chunk,
                                parse_mode='Markdown'
                            )
                    except Exception as e:
                        logger.error(f"Telegram API error when sending chunk {i+1}: {str(e)}")
                        if "can't parse entities" in str(e):
                            if i == 0:
                                await bot.edit_message_text(
                                    chat_id=thinking_message.chat.id,
                                    message_id=thinking_message.message_id,
                                    text=chunk
                                )
                            else:
                                await bot.send_message(
                                    chat_id=thinking_message.chat.id,
                                    text=chunk
                                )
            else:
                try:
                    await bot.edit_message_text(
                        chat_id=thinking_message.chat.id,
                        message_id=thinking_message.message_id,
                        text=full_response,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Telegram API error when sending full response: {str(e)}")
                    if "can't parse entities" in str(e):
                        await bot.edit_message_text(
                            chat_id=thinking_message.chat.id,
                            message_id=thinking_message.message_id,
                            text=full_response
                        )

            logger.info(f"Đã trả lời tin nhắn cho user {message.from_user.id}")
        except Exception as e:
            logger.error(f"Lỗi khi xử lý tin nhắn: {str(e)}")
            error_message = "Xin lỗi, đã xảy ra lỗi khi xử lý tin nhắn của bạn. Vui lòng thử lại sau."
            try:
                await bot.edit_message_text(
                    chat_id=thinking_message.chat.id,
                    message_id=thinking_message.message_id,
                    text=error_message
                )
            except:
                await bot.send_message(
                    chat_id=thinking_message.chat.id,
                    text=error_message
                )

    asyncio.create_task(process_and_send_response())

def is_valid_url(url):
    if url.startswith('mailto:'):
        # Simple check for email format
        email = url[7:]  # Remove 'mailto:' prefix
        return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def create_button(text, url):
    if not is_valid_url(url):
        logger.warning(f"Invalid URL for button {text}: {url}")
        return None
    if url.startswith('mailto:'):
        # Don't encode mailto URLs
        return InlineKeyboardButton(text, url=url)
    encoded_url = quote(url, safe=':/?#@!$&()*+,;=')
    return InlineKeyboardButton(text, url=encoded_url)

@bot.message_handler(commands=['info'])
async def send_info(message):
    info_text = (
        "🤖 *Xin chào! Tôi là AI Assistant của bạn* 🤖\n\n"
        "Tôi được phát triển dựa trên mô hình Gemini Pro, với khả năng tạo ra các câu trả lời thông minh và linh hoạt. "
        "Hãy để tôi hỗ trợ bạn trong nhiều lĩnh vực khác nhau!\n\n"
        "🌟 *Các tính năng nổi bật:*\n"
        "• 💬 Trò chuyện và trả lời câu hỏi\n"
        "• 📚 Cung cấp thông tin đa dạng\n"
        "• 🔍 Hỗ trợ nghiên cứu và học tập\n"
        "• 🎨 Gợi ý ý tưởng sáng tạo\n"
        "• 📊 Phân tích dữ liệu đơn giản\n\n"
        "🛠 *Công cụ hữu ích:*\n"
        "• `/qrcode <nội dung>`: Tạo mã QR\n"
        "• `/short <URL>`: Rút gọn đường link\n"
        "• `/clear`: Xóa bộ nhớ cuộc trò chuyện\n\n"
        "💡 *Mẹo sử dụng:*\n"
        "1. Đặt câu hỏi rõ ràng và cụ thể\n"
        "2. Cung cấp ngữ cảnh nếu cần thiết\n"
        "3. Sử dụng các lệnh để truy cập tính năng đặc biệt\n\n"
        "🔒 *Bảo mật:*\n"
        "Tôi tôn trọng quyền riêng tư của bạn. Thông tin cá nhân sẽ không được lưu trữ sau khi kết thúc cuộc trò chuyện.\n\n"
        "Hãy khám phá thêm về tôi qua các liên kết dưới đây:"
    )

    markup = InlineKeyboardMarkup()

    buttons = [
        ("🌐 Github", "https://github.com/tanbaycu"),
        ("📘 Facebook", "https://facebook.com/tanbaycu.kaiser"),
        ("📞 Liên hệ hỗ trợ", "https://t.me/tanbaycu")
    ]

    for text, url in buttons:
        button = create_button(text, url)
        if button:
            markup.add(button)

    if not markup.keyboard:
        await bot.reply_to(message, "Xin lỗi, hiện tại không có thông tin liên hệ nào khả dụng.")
        return

    try:
        await bot.send_message(
            message.chat.id,
            info_text,
            reply_markup=markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error sending info message: {str(e)}")
        await bot.reply_to(message, "Xin lỗi, đã xảy ra lỗi khi gửi thông tin. Vui lòng thử lại sau.")

@bot.message_handler(commands=['clear'])
async def clear_memory(message):
    user_id = message.from_user.id
    memory_handler = get_memory_handler(user_id)
    memory_handler.clear_memory()
    await bot.reply_to(message, "Đã xóa bộ nhớ của bạn.")

async def main():
    logger.info("Bot đang chạy với mô hình Gemini 2.0 và bộ nhớ tạm thời...")
    while True:
        try:
            await bot.polling(non_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Lỗi polling: {str(e)}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())

# For running in Google Colab, you might need to add these lines:
# from google.colab import output
# output.clear()
# !pip install pyTelegramBotAPI nest_asyncio
# !python telegram_bot.py