import os
import logging
import asyncio
import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import uvicorn
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
# -------------------------------
# 1. Configuration & Setup
# -------------------------------
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "8499709723:AAG8jupyeAZxldYiyEXRJKCA13RMnpe7Y-0")

DB_HOST = os.getenv("SUPABASE_DB_HOST")
DB_PORT = os.getenv("SUPABASE_DB_PORT")
DB_NAME = os.getenv("SUPABASE_DB_NAME")
DB_USER = os.getenv("SUPABASE_DB_USER")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
db_pool: asyncpg.pool.Pool | None = None

DB_CONFIG = {
    "host": DB_HOST,
    "port": int(DB_PORT) if DB_PORT else 5432,
    "database": DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "statement_cache_size": 0
}

# -------------------------------
# Bot startup & Database Auto-Setup
# -------------------------------
async def init_db_tables():
    """Ensure new tables for Ad Packages exist without manual SQL execution."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_packages (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ad_requests (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    package_id INT,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        logging.info("✅ Auto-DB initialization for new tables completed.")
    except Exception as e:
        logging.error(f"Error creating tables: {e}")

async def on_startup():
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    logging.info("✅ Database pool initialized")
    
    await init_db_tables()

    # حذف أي ويب هوك قديم يسبب تعارض Conflict Error
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🧹 Cleared old webhook successfully.")

    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        # ربط الويب هوك بالمسار الصحيح لـ FastAPI
        clean_url = WEBHOOK_URL.rstrip('/')
        full_webhook_url = f"{clean_url}/webhook/{API_TOKEN}"
        
        await bot.set_webhook(full_webhook_url)
        logging.info(f"✅ Webhook set successfully to: {full_webhook_url}")
    else:
        logging.warning("⚠️ WEBHOOK_URL is missing in environment variables!")

# -------------------------------
# FastAPI app for webhook
# -------------------------------
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    logging.info("🚀 Starting bot and initializing DB...")
    await on_startup()

@app.post(f"/webhook/{API_TOKEN}")
async def telegram_webhook(request: Request):
    update = await request.json()
    telegram_update = types.Update(**update)
    await dp.feed_update(bot, update=telegram_update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "Bot server is running ✅"}

# -------------------------------
# FSM States
# -------------------------------
class SearchStudent(StatesGroup): waiting_for_search_term = State()
class SpecializationState(StatesGroup): waiting_for_name = State(); waiting_for_edit_name = State()
class SubjectState(StatesGroup): waiting_for_name = State(); waiting_for_spec = State(); waiting_for_edit_name = State()
class StudentRegistration(StatesGroup): waiting_for_contact = State(); waiting_for_fullname = State(); waiting_for_username = State(); waiting_for_specialization = State()
class JobRequestState(StatesGroup): choosing_subject = State(); waiting_for_class_number = State(); waiting_for_professor_name = State(); waiting_for_details = State()
class EditRequestState(StatesGroup): choosing_request = State(); choosing_field = State(); waiting_for_new_value = State()
class AdminBroadcast(StatesGroup): waiting_for_message = State()
class AdPackageState(StatesGroup): waiting_for_name = State(); waiting_for_details = State()

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📢 إرسال إعلان"), KeyboardButton(text="📦 إدارة باقات الإعلانات")],
        [KeyboardButton(text="📋 استعراض الطلبات"), KeyboardButton(text="❌ حذف الطلبات")],
        [KeyboardButton(text="👥 إدارة الطلاب"), KeyboardButton(text="🎓 إدارة التخصصات")],
        [KeyboardButton(text="📚 إدارة المواد"), KeyboardButton(text="📝 سجل العمليات")],
        [KeyboardButton(text="↩️ رجوع")]
    ], resize_keyboard=True
)

student_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ إضافة طلب وظيفة"), KeyboardButton(text="📢 طلب إعلان")],
        [KeyboardButton(text="✏️ تعديل طلب سابق"), KeyboardButton(text="🗑️ حذف طلب")],
        [KeyboardButton(text="👥 استعراض الشركاء المتاحين")]
    ], resize_keyboard=True
)

# -------------------------------
# Helper Functions
# -------------------------------
async def is_admin(user: types.User) -> bool:
    if user.username and user.username.lower() == "engghina": return True
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchval("SELECT EXISTS(SELECT 1 FROM admins WHERE user_id = $1::BIGINT)", user.id)
    except Exception: return False

async def is_student_registered(user_id: int) -> bool:
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchval("SELECT EXISTS(SELECT 1 FROM students WHERE user_id = $1::BIGINT AND is_registered = TRUE)", user_id)
    except Exception: return False

async def get_all_specializations():
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, name FROM specializations ORDER BY name")

async def get_spec_name_by_id(spec_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)

async def specialization_exists(name):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT id FROM specializations WHERE name = $1", name) is not None

async def subject_exists(subject_name: str, spec_id: int) -> bool:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT EXISTS(SELECT 1 FROM subjects WHERE name = $1 AND specialization_id = $2)", subject_name, spec_id)

async def log_operation(action, details):
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO audit_logs (action, details) VALUES ($1, $2)", action, details)
    except Exception as e: logging.error(f"Error logging operation: {e}")

async def save_student_contact(user_id: int, contact: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO students (user_id, contact) VALUES ($1::BIGINT, $2) ON CONFLICT (user_id) DO UPDATE SET contact = $2", user_id, contact)

async def save_student_info(user_id: int, fullname: str, username: str, specialization_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE students SET fullname = $1, username = $2, specialization_id = $3, is_registered = TRUE WHERE user_id = $4::BIGINT", fullname, username, specialization_id, user_id)

async def get_student_specialization(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT specialization_id FROM students WHERE user_id = $1 AND is_registered = TRUE", user_id)

async def get_subject_name_by_id(subject_id: int) -> str:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT name FROM subjects WHERE id = $1", subject_id) or "غير معروف"

# -------------------------------
# Core Handlers & Back Button
# -------------------------------
@dp.message(F.text == "↩️ رجوع")
async def back_button_handler(message: types.Message, state: FSMContext):
    await state.clear()
    if await is_admin(message.from_user):
        await message.answer("أهلاً بك في القائمة الرئيسية 🏠", reply_markup=admin_keyboard)
    elif await is_student_registered(message.from_user.id):
        await message.answer("القائمة الرئيسية 🏠", reply_markup=student_keyboard)
    else:
        await message.answer("الرجاء التسجيل أولاً عبر الأمر /start")

@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if await is_admin(user):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 الدخول كأدمن", callback_data="enter_admin"),
             InlineKeyboardButton(text="🎓 الدخول كطالب", callback_data="enter_student")]
        ])
        await message.answer(f"👋 أهلاً وسهلاً بك يا مهندسة غنى!\n🔑 تم التعرف عليك كأدمن في النظام.\n\nاختر وضع الدخول:", reply_markup=keyboard)
    else:
        if await is_student_registered(user.id):
            await show_student_dashboard(message)
        else:
            await start_student_registration(message, state)

@dp.callback_query(F.data == "enter_admin")
async def enter_admin(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("أهلاً بك في لوحة تحكم الأدمن 🤖\nاختر العملية:", reply_markup=admin_keyboard)
    await callback.answer()

@dp.callback_query(F.data == "enter_student")
async def enter_student(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    if await is_student_registered(callback.from_user.id):
        await show_student_dashboard(callback.message)
    else:
        await start_student_registration(callback.message, state)
    await callback.answer()

# -------------------------------
# Admin Feature: Broadcast (FIXED)
# -------------------------------
@dp.message(F.text == "📢 إرسال إعلان")
async def start_broadcast(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user): return
    await message.answer("📝 يرجى إرسال الإعلان الآن (نص، صورة مع كابشن، فيديو، أو ملف).\n\nللإلغاء أرسل: `إلغاء`", parse_mode="Markdown")
    await state.set_state(AdminBroadcast.waiting_for_message)

@dp.message(AdminBroadcast.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.text and message.text.strip() == "إلغاء":
        await state.clear()
        return await message.answer("تم إلغاء إرسال الإعلان 🚫", reply_markup=admin_keyboard)

    await message.answer("⏳ جاري إرسال الإعلان للطلاب في الخلفية... يمكنك الاستمرار في استخدام البوت ولن يتم تكرار الإعلان.")
    
    admin_chat_id = message.chat.id
    msg_id = message.message_id
    await state.clear()

    async def send_broadcast_task():
        try:
            async with db_pool.acquire() as conn:
                users = await conn.fetch("SELECT DISTINCT user_id FROM students WHERE is_registered = TRUE")
            success_count = 0
            for user in users:
                try:
                    await bot.copy_message(chat_id=user['user_id'], from_chat_id=admin_chat_id, message_id=msg_id)
                    success_count += 1
                    await asyncio.sleep(0.05) 
                except Exception: continue 
                    
            await bot.send_message(admin_chat_id, f"✅ انتهت عملية الإذاعة!\nتم إرسال الإعلان بنجاح إلى {success_count} طالب.", reply_markup=admin_keyboard)
            await log_operation("إرسال إعلان", f"تم إرسال إعلان لـ {success_count} طالب.")
        except Exception as e:
            logging.error(f"خطأ أثناء الإذاعة: {e}")

    asyncio.create_task(send_broadcast_task())

# -------------------------------
# Ad Packages Management (Admin & Student)
# -------------------------------
@dp.message(F.text == "📦 إدارة باقات الإعلانات")
async def manage_ad_packages(message: types.Message):
    if not await is_admin(message.from_user): return
    async with db_pool.acquire() as conn:
        packages = await conn.fetch("SELECT id, name FROM ad_packages")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for p in packages:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"🗑️ حذف {p['name']}", callback_data=f"del_adpack_{p['id']}")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="➕ إضافة باقة جديدة", callback_data="add_adpack")])
    await message.answer("📦 إدارة باقات الإعلانات:", reply_markup=keyboard)

@dp.callback_query(F.data == "add_adpack")
async def start_add_adpack(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 أرسل اسم أو عنوان الباقة الإعلانية (مثال: الباقة الذهبية):")
    await state.set_state(AdPackageState.waiting_for_name)
    await callback.answer()

@dp.message(AdPackageState.waiting_for_name)
async def process_adpack_name(message: types.Message, state: FSMContext):
    await state.update_data(pack_name=message.text.strip())
    await message.answer("تفاصيل الباقة:\nأرسل الآن السعر والميزات وتفاصيل الباقة:")
    await state.set_state(AdPackageState.waiting_for_details)

@dp.message(AdPackageState.waiting_for_details)
async def process_adpack_details(message: types.Message, state: FSMContext):
    details = message.text.strip()
    data = await state.get_data()
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO ad_packages (name, details) VALUES ($1, $2)", data['pack_name'], details)
    await message.answer(f"✅ تم إضافة الباقة '{data['pack_name']}' بنجاح!", reply_markup=admin_keyboard)
    await log_operation("إضافة باقة", f"تم إضافة باقة إعلانية جديدة: {data['pack_name']}")
    await state.clear()

@dp.callback_query(F.data.startswith("del_adpack_"))
async def delete_adpack(callback: types.CallbackQuery):
    pack_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        pack_name = await conn.fetchval("SELECT name FROM ad_packages WHERE id = $1", pack_id)
        await conn.execute("DELETE FROM ad_packages WHERE id = $1", pack_id)
    await callback.message.answer(f"✅ تم حذف باقة '{pack_name}' بنجاح!")
    await log_operation("حذف باقة", f"تم حذف الباقة الإعلانية: {pack_name}")
    await callback.answer()

@dp.message(F.text == "📢 طلب إعلان")
async def student_request_ad(message: types.Message):
    if not await is_student_registered(message.from_user.id): return
    async with db_pool.acquire() as conn:
        packages = await conn.fetch("SELECT id, name, details FROM ad_packages")
    if not packages:
        return await message.answer("❌ لا يوجد باقات إعلانية متوفرة حالياً. الرجاء المحاولة لاحقاً.")

    await message.answer("📦 *باقات الإعلانات المتوفرة:*\nتصفح الباقات أدناه واضغط على (طلب) تحت الباقة التي تناسبك:", parse_mode="Markdown")
    for p in packages:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📥 طلب هذه الباقة", callback_data=f"req_adpack_{p['id']}")
        ]])
        text = f"💎 *{p['name']}*\n\n{p['details']}"
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("req_adpack_"))
async def handle_ad_request_submission(callback: types.CallbackQuery):
    pack_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        req_id = await conn.fetchval("INSERT INTO ad_requests (user_id, package_id) VALUES ($1, $2) RETURNING id", user_id, pack_id)
        student = await conn.fetchrow("SELECT fullname, username, contact FROM students WHERE user_id = $1::BIGINT", user_id)
        pack_name = await conn.fetchval("SELECT name FROM ad_packages WHERE id = $1", pack_id)

    await callback.message.answer("✅ تم إرسال طلبك للإدارة بنجاح، سيتم مراجعته والتواصل معك قريباً.")
    await log_operation("طلب إعلان", f"الطالب {student['fullname']} طلب باقة: {pack_name}")

    # Notify Admins
    admin_msg = f"📢 *طلب إعلان جديد*\n\n👤 الطالب: {student['fullname']}\n📞 الرقم: {student['contact']}\n📧 اليوزر: @{student['username']}\n📦 الباقة: {pack_name}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ موافقة", callback_data=f"approve_ad_{req_id}_{user_id}"),
        InlineKeyboardButton(text="❌ رفض", callback_data=f"reject_ad_{req_id}_{user_id}")
    ]])
    
    async with db_pool.acquire() as conn:
        admins = await conn.fetch("SELECT user_id FROM admins")
    for admin in admins:
        try:
            await bot.send_message(admin['user_id'], admin_msg, parse_mode="Markdown", reply_markup=keyboard)
        except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("approve_ad_"))
async def approve_ad_request(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    req_id, student_id = int(parts[2]), int(parts[3])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE ad_requests SET status = 'approved' WHERE id = $1", req_id)
    await callback.message.edit_text(callback.message.text + "\n\n✅ *تمت الموافقة وتم إشعار الطالب*", parse_mode="Markdown")
    await bot.send_message(student_id, "🎉 *تمت الموافقة على طلب الإعلان!*\nسيتم التواصل معك من قبل الإدارة قريباً لإتمام التفاصيل.", parse_mode="Markdown")
    await log_operation("موافقة على إعلان", f"تم الموافقة على طلب إعلان للطالب {student_id}")
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_ad_"))
async def reject_ad_request(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    req_id, student_id = int(parts[2]), int(parts[3])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE ad_requests SET status = 'rejected' WHERE id = $1", req_id)
    await callback.message.edit_text(callback.message.text + "\n\n❌ *تم الرفض*", parse_mode="Markdown")
    await bot.send_message(student_id, "❌ نعتذر، تم رفض طلب الإعلان الخاص بك من قبل الإدارة.")
    await log_operation("رفض إعلان", f"تم رفض طلب إعلان للطالب {student_id}")
    await callback.answer()

# -------------------------------
# Request Management Handlers 
# -------------------------------
@dp.message(F.text == "📋 استعراض الطلبات")
async def select_specialization(message: types.Message):
    if not await is_admin(message.from_user): return
    specs = await get_all_specializations()
    if not specs: return await message.answer("لا يوجد أي تخصصات مسجّلة 😔")
    buttons = [[InlineKeyboardButton(text=s['name'], callback_data=f"view_spec_{s['id']}")] for s in specs]
    await message.answer("اختر التخصص لتستعرض الطلبات الخاصة فيه 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("view_spec_"))
async def select_subject(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name", spec_id)
    if not subjects:
        return await callback.message.answer(f"لا توجد مواد مسجلة في تخصص {spec_name} 😔")
    buttons = [[InlineKeyboardButton(text=s['name'], callback_data=f"view_subj_{spec_id}_{s['id']}_0")] for s in subjects]
    await callback.message.answer(f"اختر المادة في تخصص {spec_name} 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("view_subj_"))
async def view_requests_paginated(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    spec_id, subject_id, page = int(data_parts[2]), int(data_parts[3]), int(data_parts[4])
    limit = 5; offset = page * limit
    
    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, u.fullname as name, u.contact as phone, sb.name as subject_name, 
                   r.professor_name, r.class_number, r.details
            FROM requests r
            JOIN students u ON u.user_id = r.user_id
            LEFT JOIN subjects sb ON sb.id = r.subject_id
            WHERE r.is_active = TRUE AND r.specialization_id = $1 AND r.subject_id = $2
            ORDER BY r.created_at DESC LIMIT $3 OFFSET $4
        """, spec_id, subject_id, limit, offset)
        total_count = await conn.fetchval("SELECT COUNT(*) FROM requests WHERE is_active = TRUE AND specialization_id = $1 AND subject_id = $2", spec_id, subject_id)

    if not requests: return await callback.message.answer("لا يوجد طلبات نشطة لهذه المادة 😔")

    message_text = f"📋 الطلبات (الصفحة {page + 1}):\n\n"
    for req in requests:
        message_text += f"📝 طلب رقم: {req['id']}\n👤 الطالب: {req['name']}\n📞 الرقم: {req['phone']}\n📚 المادة: {req['subject_name']}\n👨‍🏫 الدكتور: {req['professor_name']}\n🏫 الصف: {req['class_number']}\n💡 تفاصيل: {req['details']}\n────────────────────\n"

    builder = InlineKeyboardBuilder()
    if page > 0: builder.add(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"view_subj_{spec_id}_{subject_id}_{page-1}"))
    if (page + 1) * limit < total_count: builder.add(InlineKeyboardButton(text="التالي ➡️", callback_data=f"view_subj_{spec_id}_{subject_id}_{page+1}"))
    builder.row(InlineKeyboardButton(text="🗑️ حذف كل طلبات هذه المادة", callback_data=f"del_all_subj_{spec_id}_{subject_id}"))
    builder.row(InlineKeyboardButton(text="🗑️ حذف كل طلبات هذا التخصص", callback_data=f"del_all_spec_{spec_id}"))

    await callback.message.answer(message_text, reply_markup=builder.as_markup())
    await callback.answer()

# -------------------------------
# Delete Requests Handlers
# -------------------------------
@dp.message(F.text == "❌ حذف الطلبات")
async def delete_requests_menu(message: types.Message):
    if not await is_admin(message.from_user): return
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🗑️ حذف طلب محدد"), KeyboardButton(text="🧹 حذف كل طلبات تخصص")],
        [KeyboardButton(text="📚 حذف كل طلبات مادة"), KeyboardButton(text="↩️ رجوع")]
    ], resize_keyboard=True)
    await message.answer("اختر نوع الحذف الذي تريد تنفيذه:", reply_markup=keyboard)

@dp.message(F.text == "🗑️ حذف طلب محدد")
async def delete_specific_request(message: types.Message):
    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, u.fullname as name, s.name as spec_name, r.professor_name
            FROM requests r JOIN students u ON r.user_id = u.user_id
            JOIN specializations s ON r.specialization_id = s.id
            WHERE r.is_active = TRUE ORDER BY r.created_at DESC LIMIT 10
        """)
    if not requests: return await message.answer("لا توجد طلبات نشطة لحذفها")
    buttons = [[InlineKeyboardButton(text=f"طلب #{r['id']} - {r['name']} - {r['spec_name']}", callback_data=f"delete_req_{r['id']}")] for r in requests]
    await message.answer("اختر الطلب الذي تريد حذفه:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("delete_req_"))
async def confirm_delete_request(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف", callback_data=f"confirm_del_req_{req_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer("⚠️ هل أنت متأكد من حذف هذا الطلب؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_del_req_"))
async def execute_delete_request(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE id = $1", req_id)
    await callback.message.answer(f"✅ تم حذف الطلب رقم {req_id} بنجاح")
    await log_operation("حذف طلب", f"قام الأدمن بحذف الطلب رقم {req_id}")
    await callback.answer()

@dp.message(F.text == "🧹 حذف كل طلبات تخصص")
async def delete_all_specialization_requests(message: types.Message):
    async with db_pool.acquire() as conn:
        specs = await conn.fetch("SELECT id, name FROM specializations ORDER BY name")
    if not specs: return await message.answer("لا يوجد تخصصات مسجلة")
    buttons = [[InlineKeyboardButton(text=s['name'], callback_data=f"del_all_spec_{s['id']}")] for s in specs]
    await message.answer("اختر التخصص لحذف جميع طلباته:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("del_all_spec_"))
async def confirm_delete_all_specialization(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف الكل", callback_data=f"confirm_del_spec_{spec_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer(f"⚠️ هل أنت متأكد من حذف جميع طلبات تخصص {spec_name}؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_del_spec_"))
async def execute_delete_all_specialization(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE specialization_id = $1", spec_id)
    await callback.message.answer(f"✅ تم حذف جميع طلبات تخصص {spec_name} بنجاح")
    await log_operation("تنظيف طلبات", f"حذف جميع طلبات تخصص: {spec_name}")
    await callback.answer()

@dp.message(F.text == "📚 حذف كل طلبات مادة")
async def delete_all_subject_requests(message: types.Message):
    async with db_pool.acquire() as conn:
        specs = await conn.fetch("SELECT id, name FROM specializations ORDER BY name")
    if not specs: return await message.answer("لا يوجد تخصصات مسجلة")
    buttons = [[InlineKeyboardButton(text=s['name'], callback_data=f"choose_subj_spec_{s['id']}")] for s in specs]
    await message.answer("اختر التخصص أولاً:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("choose_subj_spec_"))
async def choose_subject_for_deletion(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name", spec_id)
    if not subjects: return await callback.message.answer(f"لا توجد مواد في تخصص {spec_name}")
    buttons = [[InlineKeyboardButton(text=s['name'], callback_data=f"del_all_subj_{spec_id}_{s['id']}")] for s in subjects]
    await callback.message.answer(f"اختر المادة في تخصص {spec_name}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("del_all_subj_"))
async def confirm_delete_all_subject_requests(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    spec_id, subject_id = int(data_parts[3]), int(data_parts[4])
    async with db_pool.acquire() as conn:
        subject_name = await conn.fetchval("SELECT name FROM subjects WHERE id = $1", subject_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف الكل", callback_data=f"confirm_del_subj_{spec_id}_{subject_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer(f"⚠️ هل أنت متأكد من حذف جميع طلبات مادة {subject_name}؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_del_subj_"))
async def execute_delete_all_subject_requests(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    spec_id, subject_id = int(data_parts[3]), int(data_parts[4])
    async with db_pool.acquire() as conn:
        subject_name = await conn.fetchval("SELECT name FROM subjects WHERE id = $1", subject_id)
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE subject_id = $1", subject_id)
    await callback.message.answer(f"✅ تم حذف جميع طلبات مادة {subject_name} بنجاح")
    await log_operation("تنظيف طلبات", f"حذف جميع طلبات مادة: {subject_name}")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_del")
async def cancel_delete(callback: types.CallbackQuery):
    await callback.message.answer("❌ تم إلغاء العملية")
    await callback.answer()

# -------------------------------
# Student Management Handlers 
# -------------------------------
@dp.message(F.text == "👥 إدارة الطلاب")
async def manage_students_menu(message: types.Message):
    if not await is_admin(message.from_user): return
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👀 عرض جميع الطلاب"), KeyboardButton(text="🔍 بحث عن طالب")],
        [KeyboardButton(text="🚫 تعطيل حساب طالب"), KeyboardButton(text="✅ تفعيل حساب طالب")],
        [KeyboardButton(text="↩️ رجوع")]
    ], resize_keyboard=True)
    await message.answer("اختر عملية إدارة الطلاب:", reply_markup=keyboard)

@dp.message(F.text == "🔍 بحث عن طالب")
async def search_student_start(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user): return
    await message.answer("أرسل رقم هاتف الطالب أو اسمه للبحث:")
    await state.set_state(SearchStudent.waiting_for_search_term)

@dp.message(SearchStudent.waiting_for_search_term)
async def process_search_term(message: types.Message, state: FSMContext):
    search_term = message.text.strip()
    async with db_pool.acquire() as conn:
        students = await conn.fetch("""
            SELECT u.user_id as id, u.fullname as name, u.contact as phone, s.name as specialization_name, u.is_registered as is_active
            FROM students u LEFT JOIN specializations s ON u.specialization_id = s.id
            WHERE u.fullname ILIKE $1 OR u.contact ILIKE $2 ORDER BY u.fullname LIMIT 10
        """, f"%{search_term}%", f"%{search_term}%")

    if not students:
        await message.answer("❌ لم يتم العثور على أي طالب بهذا الاسم أو الرقم")
    else:
        response = "🔍 نتائج البحث:\n\n"
        for student in students:
            status = "✅ نشط" if student['is_active'] else "❌ معطل"
            spec_display = student['specialization_name'] or "غير محدد"
            response += f"#{student['id']} - {student['name']} - {student['phone']} - {spec_display} - {status}\n"
        await message.answer(response)
    await state.clear()

@dp.message(F.text == "🚫 تعطيل حساب طالب")
async def deactivate_student(message: types.Message):
    async with db_pool.acquire() as conn:
        students = await conn.fetch("SELECT user_id as id, fullname as name, contact as phone FROM students WHERE is_registered = TRUE ORDER BY fullname LIMIT 15")
    if not students: return await message.answer("لا يوجد طلاب نشطين")
    buttons = [[InlineKeyboardButton(text=f"{s['name']} - {s['phone']}", callback_data=f"deactivate_{s['id']}")] for s in students]
    await message.answer("اختر الطالب لتعطيل حسابه:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("deactivate_"))
async def confirm_deactivate_student(callback: types.CallbackQuery):
    student_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        student = await conn.fetchrow("SELECT fullname as name, contact as phone FROM students WHERE user_id = $1::BIGINT", student_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، عطل الحساب", callback_data=f"confirm_deact_{student_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer(f"⚠️ هل أنت متأكد من تعطيل حساب:\n{student['name']} - {student['phone']}؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_deact_"))
async def execute_deactivate_student(callback: types.CallbackQuery):
    student_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE students SET is_registered = FALSE WHERE user_id = $1::BIGINT", student_id)
    await callback.message.answer(f"✅ تم تعطيل حساب الطالب بنجاح")
    await log_operation("تعطيل حساب", f"تم تعطيل حساب الطالب برقم ID: {student_id}")
    await callback.answer()

@dp.message(F.text == "✅ تفعيل حساب طالب")
async def activate_student(message: types.Message):
    async with db_pool.acquire() as conn:
        students = await conn.fetch("SELECT user_id as id, fullname as name, contact as phone FROM students WHERE is_registered = FALSE ORDER BY fullname LIMIT 15")
    if not students: return await message.answer("لا يوجد طلاب معطلين")
    buttons = [[InlineKeyboardButton(text=f"{s['name']} - {s['phone']}", callback_data=f"activate_{s['id']}")] for s in students]
    await message.answer("اختر الطالب لتفعيل حسابه:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(lambda c: c.data.startswith("activate_"))
async def confirm_activate_student(callback: types.CallbackQuery):
    student_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        student = await conn.fetchrow("SELECT fullname as name, contact as phone FROM students WHERE user_id = $1::BIGINT", student_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، فعّل الحساب", callback_data=f"confirm_act_{student_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer(f"⚠️ هل أنت متأكد من تفعيل حساب:\n{student['name']} - {student['phone']}؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_act_"))
async def execute_activate_student(callback: types.CallbackQuery):
    student_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE students SET is_registered = TRUE WHERE user_id = $1::BIGINT", student_id)
    await callback.message.answer(f"✅ تم تفعيل حساب الطالب بنجاح")
    await log_operation("تفعيل حساب", f"تم تفعيل حساب الطالب برقم ID: {student_id}")
    await callback.answer()

@dp.message(F.text == "👀 عرض جميع الطلاب")
async def show_all_students_paginated(message: types.Message):
    await show_students_page(message, 0)

async def show_students_page(message: types.Message, page: int):
    limit = 10; offset = page * limit
    async with db_pool.acquire() as conn:
        students = await conn.fetch("""
            SELECT u.user_id as id, u.fullname as name, u.contact as phone, s.name as spec_name, u.is_registered as is_active
            FROM students u LEFT JOIN specializations s ON u.specialization_id = s.id
            ORDER BY u.created_at DESC LIMIT $1 OFFSET $2
        """, limit, offset)
        total_count = await conn.fetchval("SELECT COUNT(*) FROM students")

    if total_count == 0: return await message.answer("لا يوجد طلاب مسجلين")

    response = f"📋 قائمة الطلاب (الصفحة {page + 1}):\n\n"
    for st in students:
        status = "✅ نشط" if st['is_active'] else "❌ معطل"
        spec_name = st['spec_name'] or "غير محدد"
        response += f"#{st['id']} - {st['name']} - {st['phone']} - {spec_name} - {status}\n"

    builder = InlineKeyboardBuilder()
    if page > 0: builder.add(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"students_page_{page-1}"))
    if (page + 1) * limit < total_count: builder.add(InlineKeyboardButton(text="التالي ➡️", callback_data=f"students_page_{page+1}"))
    
    markup = builder.as_markup() if builder.as_markup().inline_keyboard else None
    await message.answer(response, reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith("students_page_"))
async def handle_students_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await callback.message.delete()
    await show_students_page(callback.message, page)

# -------------------------------
# Specialization & Subjects Management
# -------------------------------
@dp.message(F.text == "🎓 إدارة التخصصات")
async def manage_specializations(message: types.Message):
    if not await is_admin(message.from_user): return
    specializations = await get_all_specializations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    if specializations:
        for spec in specializations:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"✏️ {spec['name']}", callback_data=f"edit_spec_{spec['id']}"),
                InlineKeyboardButton(text=f"🗑️ حذف", callback_data=f"delete_spec_{spec['id']}")
            ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="➕ إضافة تخصص جديد", callback_data="add_spec")])
    await message.answer("🎓 إدارة التخصصات:", reply_markup=keyboard)

@dp.callback_query(F.data == "add_spec")
async def add_specialization(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 أرسل اسم التخصص الجديد:")
    await state.set_state(SpecializationState.waiting_for_name)
    await callback.answer()

@dp.message(SpecializationState.waiting_for_name)
async def process_spec_name(message: types.Message, state: FSMContext):
    spec_name = message.text.strip()
    if await specialization_exists(spec_name):
        await message.answer("❌ هذا التخصص موجود بالفعل!")
    else:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO specializations (name) VALUES ($1)", spec_name)
        await message.answer(f"✅ تم إضافة التخصص '{spec_name}' بنجاح!")
        await log_operation("إضافة تخصص", f"تم إضافة تخصص: {spec_name}")
    await state.clear()

@dp.callback_query(F.data.startswith("delete_spec_"))
async def delete_specialization(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        subjects_count = await conn.fetchval("SELECT COUNT(*) FROM subjects WHERE specialization_id = $1", spec_id)
    
    warning_text = f"⚠️ تحذير! التخصص '{spec_name}' يحتوي على {subjects_count} مادة. سيتم حذف جميع المواد المرتبطة به أيضاً!" if subjects_count > 0 else f"⚠️ هل أنت متأكد من حذف التخصص '{spec_name}'؟"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف مع المواد", callback_data=f"confirm_delete_spec_{spec_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer(warning_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_spec_"))
async def confirm_delete_spec(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[3])
    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        await conn.execute("DELETE FROM requests WHERE specialization_id = $1", spec_id)
        await conn.execute("DELETE FROM subjects WHERE specialization_id = $1", spec_id)
        await conn.execute("DELETE FROM students WHERE specialization_id = $1", spec_id)
        await conn.execute("DELETE FROM specializations WHERE id = $1", spec_id)
    await callback.message.answer(f"✅ تم حذف التخصص وجميع بياناته بنجاح!")
    await log_operation("حذف تخصص", f"حذف التخصص بالكامل: {spec_name}")
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_spec_"))
async def edit_specialization(callback: types.CallbackQuery, state: FSMContext):
    spec_id = int(callback.data.split("_")[2])
    spec_name = await get_spec_name_by_id(spec_id)
    await state.update_data(edit_spec_id=spec_id, edit_spec_name=spec_name)
    await callback.message.answer(f"📝 التخصص الحالي: {spec_name}\n\nأرسل الاسم الجديد للتخصص:")
    await state.set_state(SpecializationState.waiting_for_edit_name)
    await callback.answer()

@dp.message(SpecializationState.waiting_for_edit_name)
async def process_edit_spec_name(message: types.Message, state: FSMContext):
    new_name = message.text.strip()
    data = await state.get_data()
    spec_id = data['edit_spec_id']
    if await specialization_exists(new_name):
        await message.answer("❌ هذا الاسم مستخدم بالفعل لتخصص آخر!")
    else:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE specializations SET name = $1 WHERE id = $2", new_name, spec_id)
        await message.answer(f"✅ تم تعديل التخصص بنجاح!")
        await log_operation("تعديل تخصص", f"تعديل اسم التخصص إلى: {new_name}")
    await state.clear()

@dp.message(F.text == "📚 إدارة المواد")
async def manage_subjects(message: types.Message):
    if not await is_admin(message.from_user): return
    specializations = await get_all_specializations()
    if not specializations: return await message.answer("❌ لا توجد تخصصات. أضف تخصصاً أولاً!", reply_markup=admin_keyboard)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for spec in specializations:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=spec['name'], callback_data=f"manage_subjects_spec_{spec['id']}")])
    await message.answer("📝 اختر التخصص لإدارة مواده:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("manage_subjects_spec_"))
async def show_subjects_for_specialization(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[3])
    spec_name = await get_spec_name_by_id(spec_id)
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name", spec_id)
    
    text = f"📚 مواد تخصص '{spec_name}':\n\n"
    if not subjects: text = f"📭 لا توجد مواد في تخصص '{spec_name}'."
    else:
        for s in subjects: text += f"• {s['name']}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة مادة جديدة", callback_data=f"add_subject_to_{spec_id}")],
        [InlineKeyboardButton(text="✏️ تعديل مادة", callback_data=f"edit_subject_spec_{spec_id}")],
        [InlineKeyboardButton(text="🗑️ حذف مادة", callback_data=f"delete_subject_spec_{spec_id}")]
    ])
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("add_subject_to_"))
async def add_subject_to_specialization(callback: types.CallbackQuery, state: FSMContext):
    spec_id = int(callback.data.split("_")[3])
    spec_name = await get_spec_name_by_id(spec_id)
    await state.update_data(spec_id=spec_id)
    await callback.message.answer(f"📝 أرسل اسم المادة لتخصص {spec_name}:")
    await state.set_state(SubjectState.waiting_for_name)
    await callback.answer()

@dp.message(SubjectState.waiting_for_name)
async def process_subject_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    spec_id = data['spec_id']
    subject_name = message.text.strip()
    if await subject_exists(subject_name, spec_id):
        await message.answer("❌ هذه المادة موجودة بالفعل!")
    else:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO subjects (name, specialization_id) VALUES ($1, $2)", subject_name, spec_id)
        await message.answer(f"✅ تم إضافة المادة '{subject_name}' بنجاح!")
        await log_operation("إضافة مادة", f"تمت إضافة مادة: {subject_name}")
    await state.clear()

@dp.callback_query(F.data.startswith("edit_subject_spec_"))
async def edit_subject_for_specialization(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[3])
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name", spec_id)
    if not subjects: return await callback.message.answer(f"❌ لا توجد مواد للتعديل.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for s in subjects: keyboard.inline_keyboard.append([InlineKeyboardButton(text=s['name'], callback_data=f"edit_subject_{s['id']}")])
    await callback.message.answer(f"✏️ اختر المادة التي تريد تعديلها:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("edit_subject_"))
async def start_edit_subject(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        subject = await conn.fetchrow("SELECT id, name, specialization_id FROM subjects WHERE id = $1", subject_id)
    await state.update_data(subject_id=subject_id, current_name=subject['name'], spec_id=subject['specialization_id'])
    await callback.message.answer(f"✏️ المادة: {subject['name']}\nأرسل الاسم الجديد:")
    await state.set_state(SubjectState.waiting_for_edit_name)
    await callback.answer()

@dp.message(SubjectState.waiting_for_edit_name)
async def process_edit_subject_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    new_name = message.text.strip()
    if await subject_exists(new_name, data['spec_id']) and new_name != data['current_name']:
        await message.answer("❌ المادة موجودة بالفعل!")
    else:
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE subjects SET name = $1 WHERE id = $2", new_name, data['subject_id'])
        await message.answer(f"✅ تم تعديل المادة بنجاح!")
        await log_operation("تعديل مادة", f"تم تعديل المادة لاسم: {new_name}")
    await state.clear()

@dp.callback_query(F.data.startswith("delete_subject_spec_"))
async def delete_subject_for_specialization(callback: types.CallbackQuery):
    spec_id = int(callback.data.split("_")[3])
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name", spec_id)
    if not subjects: return await callback.message.answer("❌ لا توجد مواد للحذف.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for s in subjects: keyboard.inline_keyboard.append([InlineKeyboardButton(text=s['name'], callback_data=f"delete_subject_{s['id']}")])
    await callback.message.answer("🗑️ اختر المادة لحذفها:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_subject_"))
async def confirm_delete_subject(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[2])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف", callback_data=f"confirm_del_subject_{subject_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer("⚠️ هل أنت متأكد من حذف المادة؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_subject_"))
async def execute_delete_subject(callback: types.CallbackQuery):
    subject_id = int(callback.data.split("_")[3])
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM subjects WHERE id = $1", subject_id)
    await callback.message.answer("✅ تم حذف المادة بنجاح!")
    await log_operation("حذف مادة", f"حذف المادة رقم ID: {subject_id}")
    await callback.answer()

@dp.message(F.text == "📝 سجل العمليات")
async def show_operations_log(message: types.Message):
    if not await is_admin(message.from_user): return
    async with db_pool.acquire() as conn:
        operations = await conn.fetch("SELECT action, details, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 30")
    if not operations: return await message.answer("📭 لا توجد عمليات مسجلة بعد.")
    text = "📝 آخر 30 عملية:\n\n"
    for op in operations:
        date = op['created_at'].strftime("%Y-%m-%d %H:%M")
        text += f"⏰ {date}\n📋 {op['action']}\n💬 {op['details']}\n――――――――――\n"
    if len(text) > 4000:
        for part in [text[i:i+4000] for i in range(0, len(text), 4000)]: await message.answer(part)
    else: await message.answer(text)

# -------------------------------
# Student Section 
# -------------------------------
async def start_student_registration(message: types.Message, state: FSMContext):
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📞 مشاركة جهة الاتصال", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    welcome_text = "🎓 أهلاً بك في بوت شركاء الوظائف 👋\n\n1️⃣ شارك رقمك (الزر أدناه).\n2️⃣ أدخل اسمك.\n3️⃣ أدخل اسم المستخدم الجامعي."
    await message.answer(welcome_text, reply_markup=keyboard)
    await state.set_state(StudentRegistration.waiting_for_contact)

@dp.message(StudentRegistration.waiting_for_contact, F.contact)
async def process_contact(message: types.Message, state: FSMContext):
    await save_student_contact(message.from_user.id, message.contact.phone_number)
    await state.update_data(contact=message.contact.phone_number)
    await message.answer("شكراً! 📞\nالآن، أرسل اسمك الكامل:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(StudentRegistration.waiting_for_fullname)

@dp.message(StudentRegistration.waiting_for_fullname)
async def process_fullname(message: types.Message, state: FSMContext):
    await state.update_data(fullname=message.text.strip())
    await message.answer("جيد! الآن أرسل اسم المستخدم الجامعي (مثال: ahmed_202345):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(StudentRegistration.waiting_for_username)

@dp.message(StudentRegistration.waiting_for_username)
async def process_username(message: types.Message, state: FSMContext):
    import re
    username = message.text.strip()
    if not bool(re.match(r'^[a-zA-Z]+(?:_[a-zA-Z]+)*_[0-9]+$', username)):
        return await message.answer("❌ شكل خاطئ! (مثال صحيح: ali_202345)")
    async with db_pool.acquire() as conn:
        if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM students WHERE username = $1)", username):
            return await message.answer("❌ مسجل مسبقاً!")
    
    await state.update_data(username=username)
    specs = await get_all_specializations()
    if not specs:
        await state.clear()
        return await message.answer("❌ لا توجد تخصصات متاحة.")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for spec in specs: keyboard.inline_keyboard.append([InlineKeyboardButton(text=spec['name'], callback_data=f"stu_spec_{spec['id']}")])
    await message.answer("أخيراً، اختر تخصصك:", reply_markup=keyboard)
    await state.set_state(StudentRegistration.waiting_for_specialization)

@dp.callback_query(F.data.startswith("stu_spec_"))
async def process_specialization(callback: types.CallbackQuery, state: FSMContext):
    spec_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    await save_student_info(callback.from_user.id, data['fullname'], data['username'], spec_id)
    await log_operation("تسجيل طالب", f"تم تسجيل الطالب {data['fullname']} بنجاح")
    await callback.message.answer(f"تهانينا! ✅\nتم تسجيلك بنجاح.", reply_markup=student_keyboard)
    await state.clear()
    await callback.answer()

async def show_student_dashboard(message: types.Message):
    await message.answer("أهلاً بعودتك! 👋\nاختر ما تريد القيام به:", reply_markup=student_keyboard)

# -------------------------------
# Student Job Functions
# -------------------------------
@dp.message(F.text == "➕ إضافة طلب وظيفة")
async def add_job_request(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    spec_id = await get_student_specialization(user_id)
    if not spec_id: return await message.answer("❌ لم تكمل تسجيلك. أرسل /start")
    
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY id", spec_id)
    if not subjects: return await message.answer("❌ لا توجد مواد.")
    
    await state.update_data(subjects=subjects, page=0, specialization_id=spec_id)
    await show_subject_page(message, state, page=0)

async def show_subject_page(message, state, page: int):
    data = await state.get_data()
    subjects = data['subjects']
    PAGE_SIZE = 5
    start, end = page * PAGE_SIZE, (page * PAGE_SIZE) + PAGE_SIZE
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for s in subjects[start:end]: keyboard.inline_keyboard.append([InlineKeyboardButton(text=s['name'], callback_data=f"add_job_{s['id']}")])
    
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"job_subjects_page_{page-1}"))
    if end < len(subjects): nav_buttons.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"job_subjects_page_{page+1}"))
    if nav_buttons: keyboard.inline_keyboard.append(nav_buttons)
    
    await message.answer("📚 اختر المادة التي تريد إضافة طلب لها:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("job_subjects_page_"))
async def change_subject_page(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    await show_subject_page(callback.message, state, page)
    await callback.answer()

@dp.callback_query(F.data.startswith("add_job_"))
async def process_job_subject(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(subject_id=int(callback.data.split("_")[2]))
    await callback.message.answer("🏫 أرسل رقم الصف:")
    await state.set_state(JobRequestState.waiting_for_class_number)
    await callback.answer()

@dp.message(JobRequestState.waiting_for_class_number)
async def process_class_number(message: types.Message, state: FSMContext):
    await state.update_data(class_number=message.text.strip())
    await message.answer("👨‍🏫 أرسل اسم الدكتور:")
    await state.set_state(JobRequestState.waiting_for_professor_name)

@dp.message(JobRequestState.waiting_for_professor_name)
async def process_professor_name(message: types.Message, state: FSMContext):
    await state.update_data(professor_name=message.text.strip())
    await message.answer("📝 أرسل ملاحظات (أو أرسل 'لا يوجد'):")
    await state.set_state(JobRequestState.waiting_for_details)

@dp.message(JobRequestState.waiting_for_details)
async def process_job_details(message: types.Message, state: FSMContext):
    details = message.text.strip()
    if details == "لا يوجد": details = ""
    data = await state.get_data()
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO requests (user_id, specialization_id, subject_id, professor_name, class_number, details, is_active) 
            VALUES ($1, $2, $3, $4, $5, $6, TRUE)
        """, message.from_user.id, data['specialization_id'], data['subject_id'], data['professor_name'], data['class_number'], details)
    await message.answer("✅ تم إضافة طلبك بنجاح!", reply_markup=student_keyboard)
    await log_operation("إضافة طلب وظيفة", f"قام الطالب (ID: {message.from_user.id}) بإضافة طلب وظيفة جديد")
    await state.clear()

@dp.message(F.text == "👥 استعراض الشركاء المتاحين")
async def show_available_partners(message: types.Message, state: FSMContext):
    spec_id = await get_student_specialization(message.from_user.id)
    if not spec_id: return await message.answer("❌ لم يتم تحديد تخصصك بعد.")
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY id", spec_id)
    if not subjects: return await message.answer("❌ لا توجد مواد.")
    await state.update_data(subjects=subjects)
    await show_subjects_page(message, state, page=0)

async def show_subjects_page(message, state: FSMContext, page: int):
    data = await state.get_data()
    subjects = data['subjects']
    start, end = page * 6, (page * 6) + 6
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for s in subjects[start:end]: keyboard.inline_keyboard.append([InlineKeyboardButton(text=s['name'], callback_data=f"view_partners_{s['id']}")])
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"partner_subjects_page_{page-1}"))
    if end < len(subjects): nav_buttons.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"partner_subjects_page_{page+1}"))
    if nav_buttons: keyboard.inline_keyboard.append(nav_buttons)
    await message.answer("📚 اختر المادة لرؤية الشركاء:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("partner_subjects_page_"))
async def paginate_partner_subjects(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    await show_subjects_page(callback.message, state, page)
    await callback.answer()

@dp.callback_query(F.data.startswith("view_partners_"))
async def show_partners_for_subject(callback: types.CallbackQuery, state: FSMContext):
    subject_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        partners = await conn.fetch("""
            SELECT s.fullname, s.username, s.contact, r.professor_name, r.class_number, r.details, r.id as request_id
            FROM requests r JOIN students s ON r.user_id = s.user_id WHERE r.subject_id = $1 AND r.is_active = TRUE ORDER BY r.created_at DESC
        """, subject_id)
    if not partners: return await callback.message.answer("❌ لا توجد طلبات.")
    await state.update_data(partners=partners, subject_id=subject_id)
    await show_partners_page(callback.message, state, page=0)
    await callback.answer()

async def show_partners_page(message, state: FSMContext, page: int):
    data = await state.get_data()
    partners = data['partners']
    subject_name = await get_subject_name_by_id(data['subject_id'])
    start, end = page * 5, (page * 5) + 5
    res = f"👥 الشركاء لمادة {subject_name} (صفحة {page+1}):\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for i, p in enumerate(partners[start:end], start + 1):
        res += f"{i}. {p['fullname']}\n📧 {p['username']}@svuonline.org\n📞 {p['contact']}\n🏫 {p['class_number']} - 👨‍🏫 {p['professor_name']}\n💡 {p['details']}\n\n"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"📞 تواصل مع {p['fullname']}", callback_data=f"contact_{p['request_id']}")])

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️ السابق", callback_data=f"partners_page_{page-1}"))
    if end < len(partners): nav_buttons.append(InlineKeyboardButton(text="التالي ➡️", callback_data=f"partners_page_{page+1}"))
    if nav_buttons: keyboard.inline_keyboard.append(nav_buttons)
    
    try: await message.edit_text(res, reply_markup=keyboard)
    except: await message.answer(res, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("partners_page_"))
async def paginate_partners(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    await show_partners_page(callback.message, state, page)
    await callback.answer()

@dp.callback_query(F.data.startswith("contact_"))
async def contact_partner(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        p = await conn.fetchrow("""
            SELECT s.fullname, s.username, s.contact, r.professor_name, r.class_number
            FROM requests r JOIN students s ON r.user_id = s.user_id WHERE r.id = $1
        """, req_id)
    if p:
        await callback.message.answer(f"📞 التواصل مع {p['fullname']}:\n📧 {p['username']}@svuonline.org\n📞 {p['contact']}")
    await callback.answer()

@dp.message(F.text == "✏️ تعديل طلب سابق")
async def edit_job_request(message: types.Message, state: FSMContext):
    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, s.name as subject_name, r.class_number, r.professor_name
            FROM requests r JOIN subjects s ON r.subject_id = s.id WHERE r.user_id = $1 AND r.is_active = TRUE ORDER BY r.created_at DESC
        """, message.from_user.id)
    if not requests: return await message.answer("❌ ليس لديك أي طلبات لتعديلها.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for req in requests:
        txt = f"{req['subject_name']} - {req['class_number']} - {req['professor_name']}"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=txt[:40], callback_data=f"edit_job_{req['id']}")])
    await message.answer("اختر الطلب الذي تريد تعديله:", reply_markup=keyboard)
    await state.set_state(EditRequestState.choosing_request)

@dp.callback_query(F.data.startswith("edit_job_"))
async def choose_field_to_edit(callback: types.CallbackQuery, state: FSMContext):
    req_id = int(callback.data.split("_")[2])
    await state.update_data(request_id=req_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏫 رقم الصف", callback_data="edit_field_class")],
        [InlineKeyboardButton(text="👨‍🏫 اسم الدكتور", callback_data="edit_field_professor")],
        [InlineKeyboardButton(text="📝 الملاحظات", callback_data="edit_field_details")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_edit")]
    ])
    await callback.message.answer("اختر الحقل لتعديله:", reply_markup=keyboard)
    await state.set_state(EditRequestState.choosing_field)
    await callback.answer()

@dp.callback_query(EditRequestState.choosing_field, F.data.startswith("edit_field_"))
async def process_field_selection(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[2]
    prompts = {"class": "أرسل رقم الصف الجديد:", "professor": "أرسل اسم الدكتور الجديد:", "details": "أرسل الملاحظات الجديدة:"}
    if field not in prompts: return
    await state.update_data(field_to_edit=field)
    await callback.message.answer(prompts[field])
    await state.set_state(EditRequestState.waiting_for_new_value)
    await callback.answer()

@dp.message(EditRequestState.waiting_for_new_value)
async def process_new_value(message: types.Message, state: FSMContext):
    new_value = message.text.strip()
    data = await state.get_data()
    db_columns = {"class": "class_number", "professor": "professor_name", "details": "details"}
    async with db_pool.acquire() as conn:
        await conn.execute(f"UPDATE requests SET {db_columns[data['field_to_edit']]} = $1, updated_at = NOW() WHERE id = $2", new_value, data['request_id'])
    await message.answer(f"✅ تم التحديث بنجاح!", reply_markup=student_keyboard)
    await log_operation("تعديل طلب", f"قام الطالب بتعديل الحقل {data['field_to_edit']} للطلب رقم {data['request_id']}")
    await state.clear()

@dp.message(F.text == "🗑️ حذف طلب")
async def delete_job_request(message: types.Message):
    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, s.name as subject_name FROM requests r JOIN subjects s ON r.subject_id = s.id 
            WHERE r.user_id = $1 AND r.is_active = TRUE ORDER BY r.created_at DESC
        """, message.from_user.id)
    if not requests: return await message.answer("❌ ليس لديك طلبات نشطة.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for req in requests: keyboard.inline_keyboard.append([InlineKeyboardButton(text=req['subject_name'], callback_data=f"delete_job_{req['id']}")])
    await message.answer("اختر الطلب الذي تريد حذفه:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("delete_job_"))
async def confirm_delete_job_request(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[2])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف", callback_data=f"confirm_del_job_{req_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]
    ])
    await callback.message.answer("⚠️ هل أنت متأكد من حذف الطلب؟", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_del_job_"))
async def execute_delete_job_request(callback: types.CallbackQuery):
    req_id = int(callback.data.split("_")[3])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE id = $1", req_id)
    await callback.message.answer("✅ تم حذف الطلب بنجاح", reply_markup=student_keyboard)
    await log_operation("حذف طلب", f"قام الطالب بحذف طلبه الخاص برقم {req_id}")
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["cancel_edit", "cancel_del"])
async def cancel_actions(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ تم الإلغاء")
    await callback.answer()

# -------------------------------
# Run Uvicorn
# -------------------------------
if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info", lifespan="on")
