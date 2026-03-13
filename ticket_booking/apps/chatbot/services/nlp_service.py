import os
from django.conf import settings
from openai import OpenAI
from apps.chatbot.models import ChatHistory
from ticket_booking.settings import FRONTEND_URL
from django.utils import timezone
# Cấu hình OpenAI/Groq client từ Django settings (lazy init)
import threading

_client = None
_client_lock = threading.Lock()

def get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                api_key = getattr(settings, 'GROQ_API_KEY', '')
                if api_key:
                    try:
                        _client = OpenAI(
                            base_url="https://api.groq.com/openai/v1",
                            api_key=api_key
                        )
                        print("✅ GROQ/OpenAI client initialized.")
                    except Exception as e:
                        print(f"⚠️ Lỗi khi init client: {e}")
                        _client = None
                else:
                    _client = None
    return _client


def generate_ai_response(user_message: str, customer=None, session_id=None, context=None, top_match_id=None) -> str:
    """
    Chatbot sinh phản hồi dựa trên dữ liệu từ DB + ngữ cảnh Chroma, 
    có nhớ lịch sử hội thoại theo session_id.
    """
    client = get_client()
    if not client:
        return "Lỗi: GROQ_API_KEY chưa được cấu hình."
    
    try:
        # 🧠 Lấy lịch sử hội thoại trước đó của cùng session
        history = []
        if session_id:
            past_chats = ChatHistory.objects.filter(session_id=session_id).order_by("created_at")[:10]
            for chat in past_chats:
                history.append({"role": "user", "content": chat.user_message})
                history.append({"role": "assistant", "content": chat.bot_response})

        # 🎯 Hướng dẫn hệ thống
        system_prompt = (
            "Bạn là chatbot hỗ trợ khách hàng đặt vé thể thao. "
            "Trả lời thân thiện, dễ hiểu và chỉ dựa trên dữ liệu thật bên dưới. "
            "trả lời ngắn gọn không dài dòng. "
            "Nếu cùng một match_id thì không lặp lại nhắc đến match_name mà nói cái khác biệt."
        )
        
        if top_match_id:
            system_prompt += f"Nếu có thể, hãy chèn đường dẫn đến trang đặt vé dạng {FRONTEND_URL}/match/match_id khi người dùng có ý định đặt, mua, hoặc xem chi tiết vé. Nếu người dùng muốn đặt mua thì chèn đường dẫn vô, không nên có 2 link giống nhau nhé,nếu giống thì lấy 1 thôi"
        
        system_prompt += "Không bịa ra thông tin ngoài dữ liệu thật.\n\n"

        # 🗨️ Ghép tất cả message
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)  # thêm lịch sử hội thoại
        
        if context:
            messages.append({
                "role": "system",
                "content": f"Dữ liệu liên quan:\n{context}"
            })
        else:
            messages.append({
                "role": "system",
                "content": "Không có dữ liệu phù hợp."
            })
        
        messages.append({"role": "user", "content": user_message})

        # 🤖 Gọi model LLaMA (Groq)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=250,
        )

        answer = response.choices[0].message.content.strip()

        # 💾 Lưu hội thoại mới vào DB
        if customer:
            ChatHistory.objects.create(
                customer=customer,
                user_message=user_message,
                bot_response=answer,
                session_id=session_id,
            )

        return answer

    except Exception as e:
        return f"Lỗi khi gọi AI: {str(e)}"


def rewrite_query_with_context(user_message: str, session_id: str = None) -> str:
    """
    Dùng AI để diễn giải lại câu hỏi sao cho có đầy đủ ngữ cảnh từ hội thoại cũ.
    """
    client = get_client()
    if not client:
        return user_message
    
    try:
        now = timezone.now()
        current_date_info = now.strftime("%A, ngày %d/%m/%Y") # Ví dụ: Wednesday, ngày 24/12/2025
        # Lấy lịch sử hội thoại gần nhất (3 lượt gần đây)
        history_text = ""
        if session_id:
            last_chats = ChatHistory.objects.filter(session_id=session_id).order_by("-created_at")[:3]
            for chat in reversed(last_chats):
                history_text += f"Người dùng: {chat.user_message}\nBot: {chat.bot_response}\n"

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Bạn là trợ lý giúp diễn giải câu hỏi người dùng sao cho có đầy đủ ngữ cảnh. "
                        f"Hôm nay là {current_date_info}. "
                        "Nếu người dùng hỏi về 'hôm nay', 'mai', 'thứ mấy', hãy chuyển chúng thành ngày cụ thể (dd/mm/yyyy). "
                        "Chỉ viết lại câu hỏi hoàn chỉnh, không trả lời câu hỏi."
                    )
                },
                {
                    "role": "user",
                    "content": f"Lịch sử hội thoại:\n{history_text}\n\nNgười dùng vừa hỏi: {user_message}"
                }
            ],
            max_tokens=100,
        )
        
        new_query = response.choices[0].message.content.strip()
        return new_query or user_message
    except Exception as e:
        print("⚠️ Lỗi rewrite query:", str(e))
        return user_message
