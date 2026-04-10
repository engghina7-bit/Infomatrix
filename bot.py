Skip to content
engghina7-bit
Infomatrix
Repository navigation
Code
Issues
Pull requests
Actions
Projects
Wiki
Security and quality
Insights
Settings
Infomatrix
/bot.py/
Deleting Infomatrix/bot.py. Commit changes to save.
3448
bot.py
Original file line number	Diff line number	Diff line change
@@ -1,3448 +0,0 @@
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
import os
from dotenv import load_dotenv
# Telegram Bot Token (must be set in Koyeb environment variables)
API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
if not API_TOKEN:
    raise ValueError(
        "❌ TELEGRAM_API_TOKEN is not set in environment variables.")

# Database settings (Supabase - must be set in Koyeb environment variables)
DB_HOST = os.getenv("SUPABASE_DB_HOST")
DB_PORT = os.getenv("SUPABASE_DB_PORT")
DB_NAME = os.getenv("SUPABASE_DB_NAME")
DB_USER = os.getenv("SUPABASE_DB_USER")
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD")

# Check all DB vars exist
if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
    raise ValueError(
        "❌ One or more database environment variables are missing. Please check your Koyeb settings.")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Database connection configuration
DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "database": DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "statement_cache_size": 0
}

# Define FSM states


class SearchStudent(StatesGroup):
    waiting_for_search_term = State()


class SpecializationState(StatesGroup):
    waiting_for_name = State()
    waiting_for_edit_name = State()


class SubjectState(StatesGroup):
    waiting_for_name = State()
    waiting_for_spec = State()
    waiting_for_edit_name = State()  # لتعديل المواد

# Add to your states section


class StudentRegistration(StatesGroup):
    waiting_for_contact = State()
    waiting_for_fullname = State()
    waiting_for_username = State()
    waiting_for_specialization = State()


class JobRequestState(StatesGroup):
    choosing_subject = State()
    waiting_for_class_number = State()
    waiting_for_professor_name = State()
    waiting_for_details = State()


class EditRequestState(StatesGroup):
    choosing_request = State()
    choosing_field = State()
    waiting_for_new_value = State()


# Database connection pool
db_pool = None


# Admin keyboard layout
admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 استعراض الطلبات"),
         KeyboardButton(text="❌ حذف الطلبات")],
        [KeyboardButton(text="👥 إدارة الطلاب"),
         KeyboardButton(text="🎓 إدارة التخصصات")],
        [KeyboardButton(text="📚 إدارة المواد"),
         KeyboardButton(text="📝 سجل العمليات")],
        [KeyboardButton(text="↩️ رجوع")]
    ],
    resize_keyboard=True
)
# Add this to your keyboards section
student_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ إضافة طلب وظيفة")],
        [KeyboardButton(text="✏️ تعديل طلب سابق")],
        [KeyboardButton(text="🗑️ حذف طلب")],
        [KeyboardButton(text="👥 استعراض الشركاء المتاحين")]
    ],
    resize_keyboard=True
)
# ========== Helper Functions ==========


async def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    try:
        async with db_pool.acquire() as conn:
            # استخدام BIGINT للتأكد من دعم الأرقام الكبيرة
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM admins WHERE user_id = $1::BIGINT)",
                user_id
            )
            return exists
    except Exception as e:
        logging.error(f"Error checking admin permissions: {e}")
        return False


async def is_student_registered(user_id: int) -> bool:
    """Check if a user is registered as student"""
    try:
        async with db_pool.acquire() as conn:
            # استخدام BIGINT هنا أيضاً
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM students WHERE user_id = $1::BIGINT)",
                user_id
            )
            return exists
    except Exception as e:
        logging.error(f"Error checking student registration: {e}")
        return False


async def specialization_exists(name):
    """Check if specialization exists"""
    async with db_pool.acquire() as conn:
        existing_id = await conn.fetchval("SELECT id FROM specializations WHERE name = $1", name)
        return existing_id is not None


async def get_spec_name_by_id(spec_id):
    """Get specialization name by ID"""
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)


# async def subject_exists(name, spec_id):
#     """Check if subject exists in specialization"""
#     async with db_pool.acquire() as conn:
#         return await conn.fetchval(
#             "SELECT id FROM subjects WHERE name = $1 AND specialization_id = $2",
#             name, spec_id
#         )


async def get_all_specializations():
    """Get all specializations"""
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT id, name FROM specializations ORDER BY name")


async def get_all_subjects_with_spec():
    """Get all subjects with specialization names"""
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT s.id, s.name, sp.name as spec_name 
            FROM subjects s 
            JOIN specializations sp ON s.specialization_id = sp.id 
            ORDER BY sp.name, s.name
        """)


async def log_operation(action, details):
    """Log operation to audit logs"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO audit_logs (action, details) 
                VALUES ($1, $2)
            """, action, details)
    except Exception as e:
        logging.error(f"Error logging operation: {e}")


async def subject_exists(subject_name: str, spec_id: int) -> bool:
    """Check if a subject already exists in a specialization"""
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM subjects WHERE name = $1 AND specialization_id = $2)",
            subject_name, spec_id
        )
        return exists


async def save_student_contact(user_id: int, contact: str):
    """Save student contact information"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO students (user_id, contact) VALUES ($1::BIGINT, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET contact = $2",
            user_id, contact
        )


async def save_student_info(user_id: int, fullname: str, username: str, specialization_id: int):
    """Save student complete information"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE students SET fullname = $1, username = $2, specialization_id = $3, is_registered = TRUE "
            "WHERE user_id = $4::BIGINT",
            fullname, username, specialization_id, user_id
        )


async def get_student_specialization(user_id: int) -> int:
    """Get student's specialization ID"""
    async with db_pool.acquire() as conn:
        spec_id = await conn.fetchval(
            "SELECT specialization_id FROM students WHERE user_id = $1 AND is_registered = TRUE",
            user_id
        )
        return spec_id


async def get_subject_name_by_id(subject_id: int) -> str:
    """Get subject name by ID"""
    async with db_pool.acquire() as conn:
        subject_name = await conn.fetchval(
            "SELECT name FROM subjects WHERE id = $1",
            subject_id
        )
        return subject_name or "غير معروف"
# ========== Command Handlers ==========


@dp.message(Command(commands=["start"]))
async def start_handler(message: types.Message, state: FSMContext):
    """Handle the /start command and display the appropriate dashboard"""
    user_id = message.from_user.id

    # Check if user is admin
    if await is_admin(user_id):
        await message.answer(
            "أهلاً وسهلاً بك في لوحة تحكم الأدمن 🤖\n"
            "𝕀𝕟𝕗𝕠𝕄𝕒𝕥𝕣𝕚𝕩 𝕋𝕖𝕒𝕞\n\n"
            "اختر العملية التي تريد إجراؤها من الأزرار 👇",
            reply_markup=admin_keyboard
        )
    else:
        # Check if user is already registered as student
        if await is_student_registered(user_id):
            # Show student dashboard
            await show_student_dashboard(message)
        else:
            # Start registration process
            # الآن state معرفة
            await start_student_registration(message, state)


# ========== Request Management Handlers ==========


@dp.message(F.text == "📋 استعراض الطلبات")
async def select_specialization(message: types.Message):
    """Display all specializations for request browsing"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    async with db_pool.acquire() as conn:
        specs = await conn.fetch("SELECT id, name FROM specializations ORDER BY name")

    if not specs:
        await message.answer("لا يوجد أي تخصصات مسجّلة 😔")
        return

    buttons = []
    for spec in specs:
        buttons.append([InlineKeyboardButton(
            text=spec['name'],
            callback_data=f"view_spec_{spec['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("اختر التخصص لتستعرض الطلبات الخاصة فيه 👇", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("view_spec_"))
async def select_subject(callback: types.CallbackQuery):
    """Display subjects for a selected specialization"""
    spec_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        subjects = await conn.fetch(
            "SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name",
            spec_id
        )

    if not subjects:
        await callback.message.answer(f"لا توجد مواد مسجلة في تخصص {spec_name} 😔")
        return

    buttons = []
    for subject in subjects:
        buttons.append([InlineKeyboardButton(
            text=subject['name'],
            callback_data=f"view_subj_{spec_id}_{subject['id']}_0"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(f"اختر المادة في تخصص {spec_name} 👇", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("view_subj_"))
async def view_requests_paginated(callback: types.CallbackQuery):
    """Display paginated requests for a selected subject"""
    data_parts = callback.data.split("_")
    spec_id = int(data_parts[2])
    subject_id = int(data_parts[3])
    page = int(data_parts[4])

    limit = 5
    offset = page * limit

    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, u.name, u.phone, sb.name as subject_name, 
                   r.professor_name, r.class_number, r.details
            FROM requests r
            JOIN users u ON u.id = r.user_id
            LEFT JOIN subjects sb ON sb.id = r.subject_id
            WHERE r.is_active = TRUE AND r.specialization_id = $1 AND r.subject_id = $2
            ORDER BY r.created_at DESC
            LIMIT $3 OFFSET $4
        """, spec_id, subject_id, limit, offset)

        total_count = await conn.fetchval("""
            SELECT COUNT(*) FROM requests 
            WHERE is_active = TRUE AND specialization_id = $1 AND subject_id = $2
        """, spec_id, subject_id)

    if not requests:
        await callback.message.answer("لا يوجد طلبات نشطة لهذه المادة 😔")
        return

    message_text = f"📋 الطلبات (الصفحة {page + 1}):\n\n"
    for req in requests:
        message_text += (
            f"📝 طلب رقم: {req['id']}\n"
            f"👤 الطالب: {req['name']}\n"
            f"📞 الرقم: {req['phone']}\n"
            f"📚 المادة: {req['subject_name']}\n"
            f"👨‍🏫 الدكتور: {req['professor_name']}\n"
            f"🏫 الصف: {req['class_number']}\n"
            f"💡 تفاصيل: {req['details']}\n"
            f"────────────────────\n"
        )

    builder = InlineKeyboardBuilder()

    if page > 0:
        builder.add(InlineKeyboardButton(
            text="⬅️ السابق",
            callback_data=f"view_subj_{spec_id}_{subject_id}_{page-1}"
        ))

    if (page + 1) * limit < total_count:
        builder.add(InlineKeyboardButton(
            text="التالي ➡️",
            callback_data=f"view_subj_{spec_id}_{subject_id}_{page+1}"
        ))

    builder.row(InlineKeyboardButton(
        text="🗑️ حذف كل طلبات هذه المادة",
        callback_data=f"del_all_subj_{spec_id}_{subject_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🗑️ حذف كل طلبات هذا التخصص",
        callback_data=f"del_all_spec_{spec_id}"
    ))

    await callback.message.answer(message_text, reply_markup=builder.as_markup())
    await callback.answer()

# ========== Delete Requests Handlers ==========


@dp.message(F.text == "❌ حذف الطلبات")
async def delete_requests_menu(message: types.Message):
    """Display delete requests menu"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗑️ حذف طلب محدد"),
             KeyboardButton(text="🧹 حذف كل طلبات تخصص")],
            [KeyboardButton(text="📚 حذف كل طلبات مادة"),
             KeyboardButton(text="↩️ رجوع")]
        ],
        resize_keyboard=True
    )
    await message.answer("اختر نوع الحذف الذي تريد تنفيذه:", reply_markup=keyboard)


@dp.message(F.text == "🗑️ حذف طلب محدد")
async def delete_specific_request(message: types.Message):
    """Display recent requests for deletion"""
    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, u.name, s.name as spec_name, r.professor_name
            FROM requests r
            JOIN users u ON r.user_id = u.id
            JOIN specializations s ON r.specialization_id = s.id
            WHERE r.is_active = TRUE
            ORDER BY r.created_at DESC
            LIMIT 10
        """)

    if not requests:
        await message.answer("لا توجد طلبات نشطة لحذفها")
        return

    buttons = []
    for req in requests:
        text = f"طلب #{req['id']} - {req['name']} - {req['spec_name']} - {req['professor_name']}"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"delete_req_{req['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("اختر الطلب الذي تريد حذفه:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("delete_req_"))
async def confirm_delete_request(callback: types.CallbackQuery):
    """Confirm request deletion"""
    req_id = int(callback.data.split("_")[-1])

    buttons = [
        [InlineKeyboardButton(text="✅ نعم، احذف",
                              callback_data=f"confirm_del_req_{req_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del_req")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer("⚠️ هل أنت متأكد من حذف هذا الطلب؟", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_del_req_"))
async def execute_delete_request(callback: types.CallbackQuery):
    """Execute request deletion"""
    req_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE id = $1", req_id)

    await callback.message.answer(f"✅ تم حذف الطلب رقم {req_id} بنجاح")
    await callback.answer()


@dp.message(F.text == "🧹 حذف كل طلبات تخصص")
async def delete_all_specialization_requests(message: types.Message):
    """Display specializations for bulk deletion"""
    async with db_pool.acquire() as conn:
        specs = await conn.fetch("SELECT id, name FROM specializations ORDER BY name")

    if not specs:
        await message.answer("لا يوجد تخصصات مسجلة")
        return

    buttons = []
    for spec in specs:
        buttons.append([InlineKeyboardButton(
            text=spec['name'],
            callback_data=f"del_all_spec_{spec['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("اختر التخصص لحذف جميع طلباته:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("del_all_spec_"))
async def confirm_delete_all_specialization(callback: types.CallbackQuery):
    """Confirm bulk deletion of all requests in a specialization"""
    spec_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)

    buttons = [
        [InlineKeyboardButton(text="✅ نعم، احذف الكل",
                              callback_data=f"confirm_del_spec_{spec_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del_spec")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(f"⚠️ هل أنت متأكد من حذف جميع طلبات تخصص {spec_name}؟", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_del_spec_"))
async def execute_delete_all_specialization(callback: types.CallbackQuery):
    """Execute bulk deletion of all requests in a specialization"""
    spec_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE specialization_id = $1", spec_id)

    await callback.message.answer(f"✅ تم حذف جميع طلبات تخصص {spec_name} بنجاح")
    await callback.answer()


@dp.message(F.text == "📚 حذف كل طلبات مادة")
async def delete_all_subject_requests(message: types.Message):
    """Display specializations for subject-based deletion"""
    async with db_pool.acquire() as conn:
        specs = await conn.fetch("SELECT id, name FROM specializations ORDER BY name")

    if not specs:
        await message.answer("لا يوجد تخصصات مسجلة")
        return

    buttons = []
    for spec in specs:
        buttons.append([InlineKeyboardButton(
            text=spec['name'],
            callback_data=f"choose_subj_spec_{spec['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("اختر التخصص أولاً:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("choose_subj_spec_"))
async def choose_subject_for_deletion(callback: types.CallbackQuery):
    """Display subjects for a selected specialization"""
    spec_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        subjects = await conn.fetch(
            "SELECT id, name FROM subjects WHERE specialization_id = $1 ORDER BY name",
            spec_id
        )

    if not subjects:
        await callback.message.answer(f"لا توجد مواد في تخصص {spec_name}")
        return

    buttons = []
    for subject in subjects:
        buttons.append([InlineKeyboardButton(
            text=subject['name'],
            callback_data=f"del_all_subj_{spec_id}_{subject['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(f"اختر المادة في تخصص {spec_name}:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("del_all_subj_"))
async def confirm_delete_all_subject_requests(callback: types.CallbackQuery):
    """Confirm bulk deletion of all requests for a subject"""
    data_parts = callback.data.split("_")
    spec_id = int(data_parts[3])
    subject_id = int(data_parts[4])

    async with db_pool.acquire() as conn:
        subject_name = await conn.fetchval("SELECT name FROM subjects WHERE id = $1", subject_id)

    buttons = [
        [InlineKeyboardButton(
            text="✅ نعم، احذف الكل", callback_data=f"confirm_del_subj_{spec_id}_{subject_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del_subj")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(f"⚠️ هل أنت متأكد من حذف جميع طلبات مادة {subject_name}؟", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_del_subj_"))
async def execute_delete_all_subject_requests(callback: types.CallbackQuery):
    """Execute bulk deletion of all requests for a subject"""
    data_parts = callback.data.split("_")
    spec_id = int(data_parts[3])
    subject_id = int(data_parts[4])

    async with db_pool.acquire() as conn:
        subject_name = await conn.fetchval("SELECT name FROM subjects WHERE id = $1", subject_id)
        await conn.execute("UPDATE requests SET is_active = FALSE WHERE subject_id = $1", subject_id)

    await callback.message.answer(f"✅ تم حذف جميع طلبات مادة {subject_name} بنجاح")
    await callback.answer()

# ========== Cancel Handlers ==========


@dp.callback_query(lambda c: c.data == "cancel_del_req")
async def cancel_delete_req(callback: types.CallbackQuery):
    """Cancel request deletion"""
    await callback.message.answer("❌ تم إلغاء عملية حذف الطلب")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "cancel_del_spec")
async def cancel_delete_spec(callback: types.CallbackQuery):
    """Cancel specialization deletion"""
    await callback.message.answer("❌ تم إلغاء عملية حذف التخصص")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "cancel_del_subj")
async def cancel_delete_subj(callback: types.CallbackQuery):
    """Cancel subject deletion"""
    await callback.message.answer("❌ تم إلغاء عملية حذف المادة")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "cancel_del")
async def cancel_delete(callback: types.CallbackQuery):
    """Generic cancel deletion handler"""
    await callback.message.answer("❌ تم إلغاء عملية الحذف")
    await callback.answer()

# ========== Student Management Handlers ==========


@dp.message(F.text == "👥 إدارة الطلاب")
async def manage_students_menu(message: types.Message):
    """Display student management menu"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👀 عرض جميع الطلاب"),
             KeyboardButton(text="🔍 بحث عن طالب")],
            [KeyboardButton(text="🚫 تعطيل حساب طالب"),
             KeyboardButton(text="✅ تفعيل حساب طالب")],
            [KeyboardButton(text="↩️ رجوع")]
        ],
        resize_keyboard=True
    )
    await message.answer("اختر عملية إدارة الطلاب:", reply_markup=keyboard)


@dp.message(F.text == "🔍 بحث عن طالب")
async def search_student_start(message: types.Message, state: FSMContext):
    """Initiate student search process"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    await message.answer("أرسل رقم هاتف الطالب أو اسمه للبحث:")
    await state.set_state(SearchStudent.waiting_for_search_term)


@dp.message(SearchStudent.waiting_for_search_term)
async def process_search_term(message: types.Message, state: FSMContext):
    """Process student search term and display results"""
    search_term = message.text.strip()

    async with db_pool.acquire() as conn:
        students = await conn.fetch("""
            SELECT u.id, u.name, u.phone, s.name as specialization_name, u.is_active
            FROM users u
            LEFT JOIN specializations s ON u.specialization_id = s.id
            WHERE u.name ILIKE $1 OR u.phone ILIKE $2
            ORDER BY u.name
            LIMIT 10
        """, f"%{search_term}%", f"%{search_term}%")

    if not students:
        await message.answer("❌ لم يتم العثور على أي طالب بهذا الاسم أو الرقم")
        await state.clear()
        return

    response = "🔍 نتائج البحث:\n\n"
    for student in students:
        status = "✅ نشط" if student['is_active'] else "❌ معطل"
        spec_display = student['specialization_name'] if student['specialization_name'] else "غير محدد"
        response += f"#{student['id']} - {student['name']} - {student['phone']} - {spec_display} - {status}\n"

    await message.answer(response)
    await state.clear()


@dp.message(F.text == "🚫 تعطيل حساب طالب")
async def deactivate_student(message: types.Message):
    """Display active students for deactivation"""
    async with db_pool.acquire() as conn:
        students = await conn.fetch("""
            SELECT id, name, phone FROM users WHERE is_active = TRUE ORDER BY name LIMIT 15
        """)

    if not students:
        await message.answer("لا يوجد طلاب نشطين")
        return

    buttons = []
    for student in students:
        text = f"{student['name']} - {student['phone']}"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"deactivate_{student['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("اختر الطالب لتعطيل حسابه:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("deactivate_"))
async def confirm_deactivate_student(callback: types.CallbackQuery):
    """Confirm student deactivation"""
    student_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        student = await conn.fetchrow("SELECT name, phone FROM users WHERE id = $1", student_id)

    buttons = [
        [InlineKeyboardButton(text="✅ نعم، عطل الحساب",
                              callback_data=f"confirm_deact_{student_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_action")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(f"⚠️ هل أنت متأكد من تعطيل حساب الطالب:\n{student['name']} - {student['phone']}؟", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_deact_"))
async def execute_deactivate_student(callback: types.CallbackQuery):
    """Execute student deactivation"""
    student_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        student_name = await conn.fetchval("SELECT name FROM users WHERE id = $1", student_id)
        await conn.execute("UPDATE users SET is_active = FALSE WHERE id = $1", student_id)

    await callback.message.answer(f"✅ تم تعطيل حساب الطالب {student_name} بنجاح")
    await callback.answer()


@dp.message(F.text == "✅ تفعيل حساب طالب")
async def activate_student(message: types.Message):
    """Display inactive students for activation"""
    async with db_pool.acquire() as conn:
        students = await conn.fetch("""
            SELECT id, name, phone FROM users WHERE is_active = FALSE ORDER BY name LIMIT 15
        """)

    if not students:
        await message.answer("لا يوجد طلاب معطلين")
        return

    buttons = []
    for student in students:
        text = f"{student['name']} - {student['phone']}"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"activate_{student['id']}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("اختر الطالب لتفعيل حسابه:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("activate_"))
async def confirm_activate_student(callback: types.CallbackQuery):
    """Confirm student activation"""
    student_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        student = await conn.fetchrow("SELECT name, phone FROM users WHERE id = $1", student_id)

    buttons = [
        [InlineKeyboardButton(text="✅ نعم، فعّل الحساب",
                              callback_data=f"confirm_act_{student_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_action")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(f"⚠️ هل أنت متأكد من تفعيل حساب الطالب:\n{student['name']} - {student['phone']}؟", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_act_"))
async def execute_activate_student(callback: types.CallbackQuery):
    """Execute student activation"""
    student_id = int(callback.data.split("_")[-1])

    async with db_pool.acquire() as conn:
        student_name = await conn.fetchval("SELECT name FROM users WHERE id = $1", student_id)
        await conn.execute("UPDATE users SET is_active = TRUE WHERE id = $1", student_id)

    await callback.message.answer(f"✅ تم تفعيل حساب الطالب {student_name} بنجاح")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "cancel_action")
async def cancel_action(callback: types.CallbackQuery):
    """Cancel student management action"""
    await callback.message.answer("❌ تم إلغاء العملية")
    await callback.answer()


@dp.message(F.text == "👀 عرض جميع الطلاب")
async def show_all_students_paginated(message: types.Message):
    """Display paginated list of all students"""
    async with db_pool.acquire() as conn:
        total_count = await conn.fetchval("SELECT COUNT(*) FROM users")

    if total_count == 0:
        await message.answer("لا يوجد طلاب مسجلين")
        return

    await show_students_page(message, 0)


async def show_students_page(message: types.Message, page: int):
    """Display a page of students"""
    limit = 10
    offset = page * limit

    async with db_pool.acquire() as conn:
        students = await conn.fetch("""
            SELECT u.id, u.name, u.phone, s.name as spec_name, u.is_active
            FROM users u
            LEFT JOIN specializations s ON u.specialization_id = s.id
            ORDER BY u.created_at DESC
            LIMIT $1 OFFSET $2
        """, limit, offset)

        total_count = await conn.fetchval("SELECT COUNT(*) FROM users")

    response = f"📋 قائمة الطلاب (الصفحة {page + 1}):\n\n"
    for student in students:
        status = "✅ نشط" if student['is_active'] else "❌ معطل"
        spec_name = student['spec_name'] if student['spec_name'] else "غير محدد"
        response += f"#{student['id']} - {student['name']} - {student['phone']} - {spec_name} - {status}\n"

    builder = InlineKeyboardBuilder()

    if page > 0:
        builder.add(InlineKeyboardButton(
            text="⬅️ السابق",
            callback_data=f"students_page_{page-1}"
        ))

    if (page + 1) * limit < total_count:
        builder.add(InlineKeyboardButton(
            text="التالي ➡️",
            callback_data=f"students_page_{page+1}"
        ))

    await message.answer(response, reply_markup=builder.as_markup())


@dp.callback_query(lambda c: c.data.startswith("students_page_"))
async def handle_students_page(callback: types.CallbackQuery):
    """Handle pagination for student list"""
    page = int(callback.data.split("_")[-1])
    await callback.message.delete()
    await show_students_page(callback.message, page)

# ========== Specialization Management Handlers ==========


@dp.message(F.text == "🎓 إدارة التخصصات")
async def manage_specializations(message: types.Message):
    """Manage specializations"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    async with db_pool.acquire() as conn:
        specializations = await conn.fetch("SELECT id, name FROM specializations ORDER BY name")

    if not specializations:
        await message.answer("📭 لا توجد تخصصات حالياً.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    for spec in specializations:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"✏️ {spec['name']}", callback_data=f"edit_spec_{spec['id']}"),
            InlineKeyboardButton(
                text=f"🗑️ حذف", callback_data=f"delete_spec_{spec['id']}")
        ])

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="➕ إضافة تخصص جديد",
                             callback_data="add_spec")
    ])

    await message.answer("🎓 إدارة التخصصات:", reply_markup=keyboard)


@dp.callback_query(F.data == "add_spec")
async def add_specialization(callback: types.CallbackQuery, state: FSMContext):
    """Add new specialization"""
    await callback.message.answer("📝 أرسل اسم التخصص الجديد:")
    await state.set_state(SpecializationState.waiting_for_name)
    await callback.answer()


@dp.message(SpecializationState.waiting_for_name)
async def process_spec_name(message: types.Message, state: FSMContext):
    """Process specialization name"""
    spec_name = message.text.strip()

    if await specialization_exists(spec_name):
        await message.answer("❌ هذا التخصص موجود بالفعل!")
        await state.clear()
        return

    try:
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO specializations (name) VALUES ($1)", spec_name)

        await message.answer(f"✅ تم إضافة التخصص '{spec_name}' بنجاح!")
        await log_operation("إضافة تخصص", f"تم إضافة تخصص: {spec_name}")

    except Exception as e:
        await message.answer("❌ حدث خطأ أثناء إضافة التخصص!")
        logging.error(f"Error adding specialization: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("delete_spec_"))
async def delete_specialization(callback: types.CallbackQuery):
    """Delete specialization with confirmation"""
    spec_id = int(callback.data.split("_")[2])

    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)
        subjects_count = await conn.fetchval("SELECT COUNT(*) FROM subjects WHERE specialization_id = $1", spec_id)

    if subjects_count > 0:
        warning_text = f"⚠️ تحذير! التخصص '{spec_name}' يحتوي على {subjects_count} مادة.\n\n"
        warning_text += "إذا قمت بحذف التخصص، سيتم حذف جميع المواد المرتبطة به أيضاً!\n\n"
        warning_text += "هل أنت متأكد من أنك تريد المتابعة؟"
    else:
        warning_text = f"⚠️ هل أنت متأكد من حذف التخصص '{spec_name}'؟"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف مع المواد", callback_data=f"confirm_delete_spec_{spec_id}"),
         InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_delete_spec")]
    ])

    await callback.message.answer(warning_text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete_spec_"))
async def confirm_delete_spec(callback: types.CallbackQuery):
    """Confirm and execute specialization deletion with all related data"""
    spec_id = int(callback.data.split("_")[3])

    try:
        async with db_pool.acquire() as conn:
            # Get specialization name first
            spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)

            # Count related data for reporting
            users_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE specialization_id = $1", spec_id)
            subjects_count = await conn.fetchval("SELECT COUNT(*) FROM subjects WHERE specialization_id = $1", spec_id)
            requests_count = await conn.fetchval("SELECT COUNT(*) FROM requests WHERE specialization_id = $1", spec_id)

            # Delete all related data in correct order (to maintain referential integrity)
            # 1. Delete related requests first
            await conn.execute("DELETE FROM requests WHERE specialization_id = $1", spec_id)

            # 2. Delete related subjects
            await conn.execute("DELETE FROM subjects WHERE specialization_id = $1", spec_id)

            # 3. Delete related users
            await conn.execute("DELETE FROM users WHERE specialization_id = $1", spec_id)

            # 4. Finally delete the specialization itself
            await conn.execute("DELETE FROM specializations WHERE id = $1", spec_id)

        await callback.message.answer(
            f"✅ تم حذف التخصص '{spec_name}' وجميع بياناته بنجاح!\n\n"
            f"• الطلاب المحذوفين: {users_count}\n"
            f"• المواد المحذوفة: {subjects_count}\n"
            f"• الطلبات المحذوفة: {requests_count}"
        )

        await log_operation(
            "حذف تخصص كامل",
            f"تم حذف تخصص: {spec_name} مع {users_count} طالب, {subjects_count} مادة, {requests_count} طلب"
        )

    except Exception as e:
        await callback.message.answer("❌ حدث خطأ أثناء حذف التخصص والبيانات المرتبطة!")
        logging.error(f"Error deleting specialization and related data: {e}")

    await callback.answer()


@dp.callback_query(F.data == "cancel_delete_spec")
async def cancel_delete_spec(callback: types.CallbackQuery):
    """Cancel specialization deletion"""
    await callback.message.answer("❌ تم إلغاء عملية الحذف")
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_spec_"))
async def edit_specialization(callback: types.CallbackQuery, state: FSMContext):
    """Edit specialization name"""
    spec_id = int(callback.data.split("_")[2])

    async with db_pool.acquire() as conn:
        spec_name = await conn.fetchval("SELECT name FROM specializations WHERE id = $1", spec_id)

    await state.update_data(edit_spec_id=spec_id, edit_spec_name=spec_name)
    await callback.message.answer(f"📝 التخصص الحالي: {spec_name}\n\nأرسل الاسم الجديد للتخصص:")
    await state.set_state(SpecializationState.waiting_for_edit_name)
    await callback.answer()


@dp.message(SpecializationState.waiting_for_edit_name)
async def process_edit_spec_name(message: types.Message, state: FSMContext):
    """Process edited specialization name"""
    try:
        new_name = message.text.strip()
        data = await state.get_data()
        spec_id = data['edit_spec_id']
        old_name = data['edit_spec_name']

        if new_name == old_name:
            await message.answer("❌ الاسم الجديد مطابق للاسم الحالي! لم يتم التعديل.")
            await state.clear()
            return

        if await specialization_exists(new_name):
            await message.answer("❌ هذا الاسم مستخدم بالفعل لتخصص آخر!")
            await state.clear()
            return

        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE specializations SET name = $1 WHERE id = $2", new_name, spec_id)

        await message.answer(f"✅ تم تعديل التخصص من '{old_name}' إلى '{new_name}' بنجاح!")
        await log_operation("تعديل تخصص", f"تم تعديل تخصص: {old_name} → {new_name}")

    except Exception as e:
        await message.answer("❌ حدث خطأ أثناء تعديل التخصص!")
        logging.error(f"Error editing specialization: {e}")

    finally:
        await state.clear()

# ========== Subject Management Handlers ==========


@dp.message(F.text == "📚 إدارة المواد")
async def manage_subjects(message: types.Message):
    """Display specializations to choose from for subject management"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    try:
        # Get all specializations to choose from
        specializations = await get_all_specializations()

        if not specializations:
            await message.answer("❌ لا توجد تخصصات. أضف تخصصاً أولاً!", reply_markup=admin_keyboard)
            return

        # Create keyboard with specializations
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for spec in specializations:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=spec['name'],
                    callback_data=f"manage_subjects_spec_{spec['id']}"
                )
            ])

        await message.answer("📝 اختر التخصص لإدارة مواده:", reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Error in manage_subjects: {e}")
        await message.answer("❌ حدث خطأ في عرض التخصصات. يرجى المحاولة لاحقاً.")


@dp.callback_query(F.data.startswith("manage_subjects_spec_"))
async def show_subjects_for_specialization(callback: types.CallbackQuery):
    """Display subjects for selected specialization and management options"""
    spec_id = int(callback.data.split("_")[3])

    try:
        # Get specialization name
        spec_name = await get_spec_name_by_id(spec_id)

        # Get all subjects for this specialization
        async with db_pool.acquire() as conn:
            subjects = await conn.fetch("""
                SELECT s.id, s.name 
                FROM subjects s 
                WHERE s.specialization_id = $1 
                ORDER BY s.name
            """, spec_id)

        if not subjects:
            # No subjects found, show message with option to add
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="➕ إضافة مادة جديدة", callback_data=f"add_subject_to_{spec_id}")],
                [InlineKeyboardButton(
                    text="↩️ رجوع إلى التخصصات", callback_data="back_to_specs")]
            ])
            await callback.message.answer(
                f"📭 لا توجد مواد في تخصص '{spec_name}'.\n\n"
                f"يمكنك إضافة مواد جديدة لهذا التخصص.",
                reply_markup=keyboard
            )
        else:
            # Display existing subjects with management options
            text = f"📚 مواد تخصص '{spec_name}':\n\n"
            for subject in subjects:
                text += f"• {subject['name']}\n"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="➕ إضافة مادة جديدة", callback_data=f"add_subject_to_{spec_id}")],
                [InlineKeyboardButton(
                    text="✏️ تعديل مادة", callback_data=f"edit_subject_spec_{spec_id}")],
                [InlineKeyboardButton(
                    text="🗑️ حذف مادة", callback_data=f"delete_subject_spec_{spec_id}")],
                [InlineKeyboardButton(
                    text="↩️ رجوع إلى التخصصات", callback_data="back_to_specs")]
            ])

            await callback.message.answer(text, reply_markup=keyboard)

        await callback.answer()

    except Exception as e:
        logging.error(f"Error in show_subjects_for_specialization: {e}")
        await callback.message.answer("❌ حدث خطأ في عرض المواد. يرجى المحاولة لاحقاً.")


@dp.callback_query(F.data.startswith("add_subject_to_"))
async def add_subject_to_specialization(callback: types.CallbackQuery, state: FSMContext):
    """Start adding subject to specific specialization"""
    spec_id = int(callback.data.split("_")[3])

    try:
        spec_name = await get_spec_name_by_id(spec_id)
        await state.update_data(spec_id=spec_id)

        await callback.message.answer(f"📝 أنت تضيف مادة لتخصص: {spec_name}\n\nأرسل اسم المادة الجديدة:")
        await state.set_state(SubjectState.waiting_for_name)
        await callback.answer()

    except Exception as e:
        logging.error(f"Error in add_subject_to_specialization: {e}")
        await callback.message.answer("❌ حدث خطأ. يرجى المحاولة لاحقاً.")


@dp.message(SubjectState.waiting_for_name)
async def process_subject_name(message: types.Message, state: FSMContext):
    """Process new subject name and add to database"""
    try:
        data = await state.get_data()
        spec_id = data['spec_id']
        subject_name = message.text.strip()

        # Check if subject already exists in this specialization
        if await subject_exists(subject_name, spec_id):
            await message.answer("❌ هذه المادة موجودة بالفعل في هذا التخصص!")
            await state.clear()
            return

        # Add subject to database
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO subjects (name, specialization_id) VALUES ($1, $2)",
                               subject_name, spec_id)

        spec_name = await get_spec_name_by_id(spec_id)
        await message.answer(
            f"✅ تم إضافة المادة '{subject_name}' للتخصص '{spec_name}' بنجاح!",
            reply_markup=admin_keyboard
        )
        await log_operation("إضافة مادة", f"إضافة مادة: {subject_name} للتخصص: {spec_name}")

    except Exception as e:
        logging.error(f"Error in process_subject_name: {e}")
        await message.answer("❌ حدث خطأ أثناء إضافة المادة!")

    finally:
        await state.clear()


@dp.callback_query(F.data.startswith("edit_subject_spec_"))
async def edit_subject_for_specialization(callback: types.CallbackQuery):
    """Display subjects for editing in selected specialization"""
    spec_id = int(callback.data.split("_")[3])

    try:
        spec_name = await get_spec_name_by_id(spec_id)

        async with db_pool.acquire() as conn:
            subjects = await conn.fetch("""
                SELECT id, name FROM subjects 
                WHERE specialization_id = $1 
                ORDER BY name
            """, spec_id)

        if not subjects:
            await callback.message.answer(f"❌ لا توجد مواد في تخصص '{spec_name}' للتعديل.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for subject in subjects:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=subject['name'],
                    callback_data=f"edit_subject_{subject['id']}"
                )
            ])

        await callback.message.answer(f"✏️ اختر المادة التي تريد تعديلها في تخصص '{spec_name}':", reply_markup=keyboard)
        await callback.answer()

    except Exception as e:
        logging.error(f"Error in edit_subject_for_specialization: {e}")
        await callback.message.answer("❌ حدث خطأ. يرجى المحاولة لاحقاً.")


@dp.callback_query(F.data.startswith("delete_subject_spec_"))
async def delete_subject_for_specialization(callback: types.CallbackQuery):
    """Display subjects for deletion in selected specialization"""
    spec_id = int(callback.data.split("_")[3])

    try:
        spec_name = await get_spec_name_by_id(spec_id)

        async with db_pool.acquire() as conn:
            subjects = await conn.fetch("""
                SELECT id, name FROM subjects 
                WHERE specialization_id = $1 
                ORDER BY name
            """, spec_id)

        if not subjects:
            await callback.message.answer(f"❌ لا توجد مواد في تخصص '{spec_name}' للحذف.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for subject in subjects:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=subject['name'],
                    callback_data=f"delete_subject_{subject['id']}"
                )
            ])

        await callback.message.answer(f"🗑️ اختر المادة التي تريد حذفها من تخصص '{spec_name}':", reply_markup=keyboard)
        await callback.answer()

    except Exception as e:
        logging.error(f"Error in delete_subject_for_specialization: {e}")
        await callback.message.answer("❌ حدث خطأ. يرجى المحاولة لاحقاً.")


@dp.callback_query(F.data.startswith("delete_subject_"))
async def confirm_delete_subject(callback: types.CallbackQuery):
    """Confirm subject deletion with details"""
    try:
        subject_id = int(callback.data.split("_")[2])

        async with db_pool.acquire() as conn:
            subject = await conn.fetchrow("""
                SELECT s.name, sp.name as spec_name 
                FROM subjects s 
                JOIN specializations sp ON s.specialization_id = sp.id 
                WHERE s.id = $1
            """, subject_id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ نعم، احذف", callback_data=f"confirm_del_subject_{subject_id}")],
            [InlineKeyboardButton(
                text="❌ إلغاء", callback_data="cancel_delete_subject")]
        ])

        await callback.message.answer(
            f"⚠️ هل أنت متأكد من حذف المادة '{subject['name']}' من تخصص '{subject['spec_name']}'؟",
            reply_markup=keyboard
        )
        await callback.answer()

    except Exception as e:
        logging.error(f"Error in confirm_delete_subject: {e}")
        await callback.message.answer("❌ حدث خطأ. يرجى المحاولة لاحقاً.")


@dp.callback_query(F.data.startswith("confirm_del_subject_"))
async def execute_delete_subject(callback: types.CallbackQuery):
    """Execute subject deletion from database"""
    try:
        subject_id = int(callback.data.split("_")[3])

        async with db_pool.acquire() as conn:
            subject = await conn.fetchrow("""
                SELECT s.name, sp.name as spec_name 
                FROM subjects s 
                JOIN specializations sp ON s.specialization_id = sp.id 
                WHERE s.id = $1
            """, subject_id)

            await conn.execute("DELETE FROM subjects WHERE id = $1", subject_id)

        await callback.message.answer(
            f"✅ تم حذف المادة '{subject['name']}' من تخصص '{subject['spec_name']}' بنجاح!"
        )
        await log_operation(
            "حذف مادة",
            f"حذف مادة: {subject['name']} من تخصص: {subject['spec_name']}"
        )
        await callback.answer()

    except Exception as e:
        logging.error(f"Error in execute_delete_subject: {e}")
        await callback.message.answer("❌ حدث خطأ أثناء حذف المادة!")


@dp.callback_query(F.data == "cancel_delete_subject")
async def cancel_delete_subject(callback: types.CallbackQuery):
    """Cancel subject deletion process"""
    await callback.message.answer("❌ تم إلغاء عملية الحذف")
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_subject_"))
async def start_edit_subject(callback: types.CallbackQuery, state: FSMContext):
    """Start editing a subject - ask for new name"""
    try:
        subject_id = int(callback.data.split("_")[2])

        # Get current subject details
        async with db_pool.acquire() as conn:
            subject = await conn.fetchrow("""
                SELECT s.id, s.name, s.specialization_id, sp.name as spec_name 
                FROM subjects s 
                JOIN specializations sp ON s.specialization_id = sp.id 
                WHERE s.id = $1
            """, subject_id)

        # Store subject info in state
        await state.update_data(
            subject_id=subject_id,
            current_name=subject['name'],
            spec_id=subject['specialization_id']
        )

        await callback.message.answer(
            f"✏️ تعديل المادة: {subject['name']}\n\n"
            f"أرسل الاسم الجديد للمادة:"
        )
        await state.set_state(SubjectState.waiting_for_edit_name)
        await callback.answer()

    except Exception as e:
        logging.error(f"Error in start_edit_subject: {e}")
        await callback.message.answer("❌ حدث خطأ. يرجى المحاولة لاحقاً.")


@dp.message(SubjectState.waiting_for_edit_name)
async def process_edit_subject_name(message: types.Message, state: FSMContext):
    """Process the new subject name and update in database"""
    try:
        data = await state.get_data()
        subject_id = data['subject_id']
        current_name = data['current_name']
        spec_id = data['spec_id']
        new_name = message.text.strip()

        # Check if new name already exists in the same specialization
        if await subject_exists(new_name, spec_id) and new_name != current_name:
            await message.answer("❌ هذه المادة موجودة بالفعل في هذا التخصص!")
            await state.clear()
            return

        # Update subject in database
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE subjects SET name = $1 WHERE id = $2",
                new_name, subject_id
            )

            # Get specialization name for logging
            spec_name = await conn.fetchval(
                "SELECT name FROM specializations WHERE id = $1",
                spec_id
            )

        await message.answer(
            f"✅ تم تعديل المادة من '{current_name}' إلى '{new_name}' بنجاح!",
            reply_markup=admin_keyboard
        )
        await log_operation(
            "تعديل مادة",
            f"تعديل مادة: {current_name} إلى {new_name} في تخصص: {spec_name}"
        )

    except Exception as e:
        logging.error(f"Error in process_edit_subject_name: {e}")
        await message.answer("❌ حدث خطأ أثناء تعديل المادة!")

    finally:
        await state.clear()


@dp.callback_query(F.data == "back_to_specs")
async def back_to_specializations(callback: types.CallbackQuery):
    """Return to specialization selection"""
    await callback.message.answer("↩️ العودة إلى إدارة التخصصات")
    # You can call manage_subjects function here or use appropriate navigation

# ========== Audit Log Handlers ==========


@dp.message(F.text == "📝 سجل العمليات")
async def show_operations_log(message: types.Message):
    """Show operations log"""
    if not await is_admin(message.from_user.id):
        await message.answer("❌ ليس لديك صلاحية للوصول إلى هذه الوظيفة")
        return

    try:
        async with db_pool.acquire() as conn:
            operations = await conn.fetch("""
                SELECT action, details, created_at 
                FROM audit_logs 
                ORDER BY created_at DESC 
                LIMIT 20
            """)

        if not operations:
            await message.answer("📭 لا توجد عمليات مسجلة بعد.", reply_markup=admin_keyboard)
            return

        text = "📝 آخر 20 عملية:\n\n"
        for op in operations:
            date = op['created_at'].strftime("%Y-%m-%d %H:%M")
            text += f"⏰ {date}\n📋 {op['action']}\n💬 {op['details']}\n――――――――――\n"

        if len(text) > 4000:
            parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for part in parts:
                await message.answer(part)
        else:
            await message.answer(text)

        await message.answer("🔄 يمكنك تحديث السجل بإعادة الضغط على '📝 سجل العمليات'", reply_markup=admin_keyboard)

    except Exception as e:
        logging.error(f"Error showing operations log: {e}")
        await message.answer("❌ حدث خطأ في عرض سجل العمليات")


# ========== Student Section ==========


async def start_student_registration(message: types.Message, state: FSMContext):
    """Start student registration process"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="مشاركة جهة الاتصال 📞", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(
        "أهلاً بك في بوت شركاء الوظائف 👋\n"
        "𝕀𝕟𝕗𝕠𝕄𝕒𝕥𝕣𝕚𝕩 𝕋𝕖𝕒𝕞\n\n"
        "يبدو أنك جديد هنا! يرجى مشاركة جهة اتصالك للمتابعة",
        reply_markup=keyboard
    )
    await state.set_state(StudentRegistration.waiting_for_contact)


@dp.message(StudentRegistration.waiting_for_contact, F.contact)
async def process_contact(message: types.Message, state: FSMContext):
    """Process student contact sharing"""
    contact = message.contact.phone_number
    user_id = message.from_user.id

    await save_student_contact(user_id, contact)
    await state.update_data(contact=contact)

    await message.answer(
        "شكراً لمشاركة جهة الاتصال! 📞\n\n"
        "الآن، يرجى إرسال اسمك الكامل:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(StudentRegistration.waiting_for_fullname)


@dp.message(StudentRegistration.waiting_for_fullname)
async def process_fullname(message: types.Message, state: FSMContext):
    """Process student fullname"""
    fullname = message.text.strip()
    await state.update_data(fullname=fullname)

    await message.answer(
        "جيد! الآن يرجى إرسال اسم المستخدم الجامعي الخاص بك:\n\n"
        "📝 يجب أن يكون بالشكل: username_123456\n"
        "مثال: ahmed_202345 أو student_123789",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(StudentRegistration.waiting_for_username)


@dp.message(StudentRegistration.waiting_for_username)
async def process_username(message: types.Message, state: FSMContext):
    """Process student username with university format validation"""
    username = message.text.strip()

    # التحقق من صحة شكل اسم المستخدم الجامعي
    if not await validate_university_username(username):
        await message.answer(
            "❌ شكل اسم المستخدم غير صحيح!\n\n"
            "📋 يرجى إدخال اسم المستخدم بالشكل الصحيح:\n"
            "• يجب أن يحتوي على حروف وأرقام فقط\n"
            "• يجب أن يحتوي على شرطة سفلية (_)\n"
            "• مثال صحيح: ali_202345 أو mohammad_123456\n\n"
            "أعد إرسال اسم المستخدم الجامعي:"
        )
        return

    # التحقق إذا كان اسم المستخدم مستخدماً مسبقاً
    if await is_username_taken(username):
        await message.answer(
            "❌ اسم المستخدم هذا مسجل مسبقاً!\n\n"
            "يرجى استخدام اسم مستخدم مختلف أو التواصل مع الإدارة إذا كنت تعتقد أن هذا خطأ."
        )
        return

    await state.update_data(username=username)

    # Get all specializations for user to choose
    specializations = await get_all_specializations()

    if not specializations:
        await message.answer("❌ لا توجد تخصصات متاحة حالياً. يرجى المحاولة لاحقاً.")
        await state.clear()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for spec in specializations:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=spec['name'],
                callback_data=f"stu_spec_{spec['id']}"
            )
        ])

    await message.answer(
        "أخيراً، اختر تخصصك من القائمة:",
        reply_markup=keyboard
    )
    await state.set_state(StudentRegistration.waiting_for_specialization)


async def validate_university_username(username: str) -> bool:
    """Validate university username format: text_text_numbers"""
    import re
    # النمط: أحرف (قد تحتوي على شرطات سفلية) + شرطة سفلية + أرقام فقط
    # الأمثلة المقبولة: adel_123456, moohamed_adel_sari_121312, mohamed_adel_123456
    pattern = r'^[a-zA-Z]+(?:_[a-zA-Z]+)*_[0-9]+$'
    return bool(re.match(pattern, username))


async def is_username_taken(username: str) -> bool:
    """Check if username is already taken in the system"""
    try:
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM students WHERE username = $1)",
                username
            )
            return exists
    except Exception as e:
        logging.error(f"Error checking username availability: {e}")
        return False


@dp.callback_query(F.data.startswith("stu_spec_"))
async def process_specialization(callback: types.CallbackQuery, state: FSMContext):
    """Process student specialization selection"""
    spec_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    # Get data from state
    data = await state.get_data()
    contact = data.get('contact', '')
    fullname = data.get('fullname', '')
    username = data.get('username', '')

    # Save complete student info
    await save_student_info(user_id, fullname, username, spec_id)

    # Get specialization name
    spec_name = await get_spec_name_by_id(spec_id)

    await callback.message.answer(
        f"تهانينا! ✅\n\n"
        f"تم تسجيلك بنجاح في نظام شركاء الوظائف\n"
        f"𝕀𝕟𝕗𝕠𝕄𝕒𝕥𝕣𝕚𝕩 𝕋𝕖𝕒𝕞\n\n"
        f"الاسم: {fullname}\n"
        f"اسم المستخدم: @{username}\n"
        f"التخصص: {spec_name}\n\n"
        f"يمكنك الآن استخدام الخدمات المتاحة",
        reply_markup=student_keyboard
    )

    # التصحيح هنا - استخدام clear() بدلاً من finish()
    await state.clear()
    await callback.answer()


async def show_student_dashboard(message: types.Message):
    """Show student dashboard with available options"""
    await message.answer(
        "أهلاً بعودتك! 👋\n"
        "𝕀𝕟𝕗𝕠𝕄𝕒𝕥𝕣𝕚𝕩 𝕋𝕖𝕒𝕞\n\n"
        "اختر ما تريد القيام به من الخيارات التالية:",
        reply_markup=student_keyboard
    )


@dp.message(F.text == "👥 استعراض الشركاء المتاحين")
async def show_available_partners(message: types.Message):
    """Show available partners for student's specialization"""
    user_id = message.from_user.id

    # Get student's specialization
    spec_id = await get_student_specialization(user_id)
    if not spec_id:
        await message.answer("❌ لم يتم تحديد تخصصك بعد. يرجى التسجيل أولاً.")
        return

    # Get all subjects in student's specialization
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("""
            SELECT id, name FROM subjects 
            WHERE specialization_id = $1 
            ORDER BY name
        """, spec_id)

    if not subjects:
        await message.answer("❌ لا توجد مواد متاحة في تخصصك حالياً.")
        return

    # Create keyboard with subjects
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for subject in subjects:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=subject['name'],
                callback_data=f"view_partners_{subject['id']}"
            )
        ])

    await message.answer(
        "اختر المادة لرؤية الشركاء المتاحين:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("view_partners_"))
async def show_partners_for_subject(callback: types.CallbackQuery):
    """Show partners for selected subject"""
    subject_id = int(callback.data.split("_")[2])

    # Get available partners for this subject
    async with db_pool.acquire() as conn:
        partners = await conn.fetch("""
            SELECT s.fullname, s.username, s.contact, r.professor_name, r.class_number, r.details, r.id as request_id
            FROM requests r
            JOIN students s ON r.user_id = s.user_id
            WHERE r.subject_id = $1 AND r.is_active = TRUE
            ORDER BY r.created_at DESC
        """, subject_id)

    if not partners:
        await callback.message.answer("❌ لا توجد طلبات متاحة لهذه المادة حالياً.")
        await callback.answer()
        return

    # Get subject name
    subject_name = await get_subject_name_by_id(subject_id)

    response = f"👥 الشركاء المتاحين لمادة {subject_name}:\n\n"

    for i, partner in enumerate(partners, 1):
        university_email = f"{partner['username']}@svuonline.org"
        # التحقق من رقم الهاتف وإضافة + إذا لزم الأمر
        contact_number = partner['contact']
        if contact_number:
            if not contact_number.startswith('+'):
                contact_number = '+' + contact_number
        else:
            contact_number = "غير متوفر"
        response += f"{i}. {partner['fullname']}\n"
        response += f"   📧 البريد: {university_email}\n"
        response += f"   📞 الهاتف: {contact_number}\n"
        response += f"   👨‍🏫 الدكتور: {partner['professor_name']}\n"
        response += f"   🏫 الصف: {partner['class_number']}\n"
        if partner['details']:
            response += f"   📝 التفاصيل: {partner['details']}\n"
        response += "\n"

    # إضافة أزرار للتواصل مع الشركاء
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for partner in partners:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"📞 تواصل مع {partner['fullname']}",
                callback_data=f"contact_{partner['request_id']}"
            )
        ])

    await callback.message.answer(response, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("contact_"))
async def contact_partner(callback: types.CallbackQuery):
    """Handle contact request with partner"""
    request_id = int(callback.data.split("_")[1])

    async with db_pool.acquire() as conn:
        partner_info = await conn.fetchrow("""
            SELECT s.fullname, s.username, s.contact, r.professor_name, r.class_number
            FROM requests r
            JOIN students s ON r.user_id = s.user_id
            WHERE r.id = $1
        """, request_id)

    if partner_info:
        university_email = f"{partner_info['username']}@svuonline.org"

        # التحقق من رقم الهاتف وإضافة + إذا لزم الأمر
        contact_number = partner_info['contact']
        if contact_number:
            if not contact_number.startswith('+'):
                contact_number = '+' + contact_number
        else:
            contact_number = "غير متوفر"
        contact_info = (
            f"📞 معلومات التواصل:\n\n"
            f"👤 الاسم: {partner_info['fullname']}\n"
            f"📧 البريد الجامعي: {university_email}\n"
            f"📞 رقم الهاتف: {contact_number}\n"
            f"👨‍🏫 الدكتور: {partner_info['professor_name']}\n"
            f"🏫 الصف: {partner_info['class_number']}\n\n"
            f"يمكنك التواصل مباشرة عبر الرقم أو البريد الإلكتروني"
        )

        await callback.message.answer(contact_info)
    else:
        await callback.message.answer("❌ لم يتم العثور على معلومات الشريك")

    await callback.answer()
# ========== Back Button Handler ==========


@dp.message(F.text == "↩️ رجوع")
async def back_to_main_menu(message: types.Message):
    """Handle back button to return to main menu"""
    await message.answer("العودة إلى القائمة الرئيسية", reply_markup=admin_keyboard)


@dp.message(F.text == "➕ إضافة طلب وظيفة")
async def add_job_request(message: types.Message, state: FSMContext):
    """Start adding a new job request"""
    user_id = message.from_user.id
    spec_id = await get_student_specialization(user_id)

    if not spec_id:
        await message.answer("❌ لم يتم تحديد تخصصك بعد. يرجى التسجيل أولاً.")
        return

    # عرض المواد المتاحة في تخصص الطالب
    async with db_pool.acquire() as conn:
        subjects = await conn.fetch("""
            SELECT id, name FROM subjects 
            WHERE specialization_id = $1 
            ORDER BY name
        """, spec_id)

    if not subjects:
        await message.answer("❌ لا توجد مواد متاحة في تخصصك حالياً.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for subject in subjects:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=subject['name'],
                callback_data=f"add_job_{subject['id']}"
            )
        ])

    await message.answer("📚 اختر المادة التي تريد إضافة طلب لها:", reply_markup=keyboard)
    await state.set_state(JobRequestState.choosing_subject)
    await state.update_data(specialization_id=spec_id)


@dp.callback_query(F.data.startswith("add_job_"))
async def process_job_subject(callback: types.CallbackQuery, state: FSMContext):
    """Process subject selection for job request"""
    subject_id = int(callback.data.split("_")[2])
    await state.update_data(subject_id=subject_id)

    await callback.message.answer(
        "🏫 الرجاء إرسال رقم الصف (الكـلاس):\n\n"
        "مثال: 101 أو A2 أو LAB3"
    )
    await state.set_state(JobRequestState.waiting_for_class_number)
    await callback.answer()


@dp.message(JobRequestState.waiting_for_class_number)
async def process_class_number(message: types.Message, state: FSMContext):
    """Process class number input"""
    class_number = message.text.strip()
    await state.update_data(class_number=class_number)

    await message.answer(
        "👨‍🏫 الرجاء إرسال اسم الدكتور:\n\n"
        "مثال: د. أحمد محمد أو أ. علي حسن"
    )
    await state.set_state(JobRequestState.waiting_for_professor_name)


@dp.message(JobRequestState.waiting_for_professor_name)
async def process_professor_name(message: types.Message, state: FSMContext):
    """Process professor name input"""
    professor_name = message.text.strip()
    await state.update_data(professor_name=professor_name)

    await message.answer(
        "📝 الرجاء إرسال أي ملاحظات إضافية:\n\n"
        "• موعد المحاضرة\n"
        "• المتطلبات\n"
        "• أي معلومات أخرى تريد إضافتها\n\n"
        "إذا لا توجد ملاحظات، أرسل \"لا يوجد\""
    )
    await state.set_state(JobRequestState.waiting_for_details)


@dp.message(JobRequestState.waiting_for_details)
async def process_job_details(message: types.Message, state: FSMContext):
    """Process job request details and save to database"""
    details = message.text.strip()
    if details.lower() == "لا يوجد":
        details = ""

    user_id = message.from_user.id
    data = await state.get_data()

    subject_id = data.get('subject_id')
    specialization_id = data.get('specialization_id')
    class_number = data.get('class_number')
    professor_name = data.get('professor_name')

    # حفظ الطلب في جدول requests
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO requests (
                user_id, specialization_id, subject_id, 
                professor_name, class_number, details, is_active
            ) VALUES ($1, $2, $3, $4, $5, $6, TRUE)
        """, user_id, specialization_id, subject_id, professor_name, class_number, details)

    # الحصول على اسم المادة للتأكيد
    subject_name = await get_subject_name_by_id(subject_id)

    response = (
        f"✅ تم إضافة طلبك بنجاح!\n\n"
        f"📚 المادة: {subject_name}\n"
        f"🏫 رقم الصف: {class_number}\n"
        f"👨‍🏫 الدكتور: {professor_name}\n"
    )

    if details:
        response += f"📝 الملاحظات: {details}\n"

    await message.answer(response, reply_markup=student_keyboard)
    await state.clear()
# إضافة حالة للطلبات


@dp.message(F.text == "✏️ تعديل طلب سابق")
async def edit_job_request(message: types.Message, state: FSMContext):
    """Edit existing job request"""
    user_id = message.from_user.id

    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, s.name as subject_name, r.class_number, r.professor_name
            FROM requests r
            JOIN subjects s ON r.subject_id = s.id
            WHERE r.user_id = $1 AND r.is_active = TRUE
            ORDER BY r.created_at DESC
        """, user_id)

    if not requests:
        await message.answer("❌ ليس لديك أي طلبات نشطة لتعديلها.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for req in requests:
        display_text = f"{req['subject_name']}"
        if req['class_number']:
            display_text += f" - {req['class_number']}"
        if req['professor_name']:
            display_text += f" - {req['professor_name']}"

        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=display_text[:40] +
                "..." if len(display_text) > 40 else display_text,
                callback_data=f"edit_job_{req['id']}"
            )
        ])

    await message.answer("اختر الطلب الذي تريد تعديله:", reply_markup=keyboard)
    await state.set_state(EditRequestState.choosing_request)


@dp.callback_query(F.data.startswith("edit_job_"))
async def choose_field_to_edit(callback: types.CallbackQuery, state: FSMContext):
    """Let user choose which field to edit"""
    request_id = int(callback.data.split("_")[2])

    # الحصول على معلومات الطلب
    async with db_pool.acquire() as conn:
        request_info = await conn.fetchrow("""
            SELECT r.*, s.name as subject_name 
            FROM requests r 
            JOIN subjects s ON r.subject_id = s.id 
            WHERE r.id = $1
        """, request_id)

    if not request_info:
        await callback.message.answer("❌ لم يتم العثور على الطلب")
        await callback.answer()
        return

    await state.update_data(request_id=request_id)

    # عرض خيارات التعديل
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🏫 رقم الصف", callback_data="edit_field_class_number")],
        [InlineKeyboardButton(text="👨‍🏫 اسم الدكتور",
                              callback_data="edit_field_professor_name")],
        [InlineKeyboardButton(text="📝 الملاحظات",
                              callback_data="edit_field_details")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_edit")]
    ])

    response = (
        f"📋 الطلب المحدد: {request_info['subject_name']}\n\n"
        f"🏫 رقم الصف الحالي: {request_info['class_number'] or 'غير محدد'}\n"
        f"👨‍🏫 الدكتور الحالي: {request_info['professor_name'] or 'غير محدد'}\n"
        f"📝 الملاحظات الحالية: {request_info['details'] or 'لا توجد'}\n\n"
        f"اختر الحقل الذي تريد تعديله:"
    )

    await callback.message.answer(response, reply_markup=keyboard)
    await state.set_state(EditRequestState.choosing_field)
    await callback.answer()


@dp.callback_query(EditRequestState.choosing_field, F.data.startswith("edit_field_"))
async def process_field_selection(callback: types.CallbackQuery, state: FSMContext):
    """Process which field user wants to edit"""
    field_name = callback.data.split("_")[2]

    field_display = {
        "class": "🏫 رقم الصف",
        "professor": "👨‍🏫 اسم الدكتور",
        "details": "📝 الملاحظات"
    }

    field_prompts = {
        "class": "أرسل رقم الصف الجديد:",
        "professor": "أرسل اسم الدكتور الجديد:",
        "details": "أرسل الملاحظات الجديدة:"
    }

    if field_name not in field_prompts:
        await callback.message.answer("❌ حقل غير صحيح")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(field_to_edit=field_name)
    await callback.message.answer(field_prompts[field_name])
    await state.set_state(EditRequestState.waiting_for_new_value)
    await callback.answer()


@dp.message(EditRequestState.waiting_for_new_value)
async def process_new_value(message: types.Message, state: FSMContext):
    """Process the new value for the field"""
    new_value = message.text.strip()
    data = await state.get_data()
    request_id = data['request_id']
    field_name = data['field_to_edit']

    field_db_columns = {
        "class": "class_number",
        "professor": "professor_name",
        "details": "details"
    }

    if field_name not in field_db_columns:
        await message.answer("❌ خطأ في النظام")
        await state.clear()
        return

    # تحديث الحقل في قاعدة البيانات
    async with db_pool.acquire() as conn:
        await conn.execute(
            f"UPDATE requests SET {field_db_columns[field_name]} = $1, updated_at = NOW() WHERE id = $2",
            new_value, request_id
        )

    field_display = {
        "class": "رقم الصف",
        "professor": "اسم الدكتور",
        "details": "الملاحظات"
    }

    await message.answer(
        f"✅ تم تحديث {field_display[field_name]} بنجاح!\n\n"
        f"القيمة الجديدة: {new_value}",
        reply_markup=student_keyboard
    )
    await state.clear()


@dp.callback_query(F.data == "cancel_edit")
async def cancel_edit(callback: types.CallbackQuery, state: FSMContext):
    """Cancel the edit process"""
    await callback.message.answer("❌ تم إلغاء عملية التعديل", reply_markup=student_keyboard)
    await state.clear()
    await callback.answer()


@dp.message(F.text == "🗑️ حذف طلب")
async def delete_job_request(message: types.Message):
    """Delete job request"""
    user_id = message.from_user.id

    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT r.id, s.name as subject_name, r.class_number, r.professor_name, r.details
            FROM requests r
            JOIN subjects s ON r.subject_id = s.id
            WHERE r.user_id = $1 AND r.is_active = TRUE
            ORDER BY r.created_at DESC
        """, user_id)

    if not requests:
        await message.answer("❌ ليس لديك أي طلبات نشطة لحذفها.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for req in requests:
        # إنشاء نص واضح للطلب
        display_text = f"{req['subject_name']}"
        if req['class_number']:
            display_text += f" - {req['class_number']}"
        if req['professor_name']:
            display_text += f" - {req['professor_name']}"
        if req['details']:
            # إضافة جزء من التفاصيل إذا كانت طويلة
            display_text += f" - {req['details'][:15]}..."

        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=display_text[:40] +
                "..." if len(display_text) > 40 else display_text,
                callback_data=f"delete_job_{req['id']}"
            )
        ])

    await message.answer("اختر الطلب الذي تريد حذفه:", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("delete_job_"))
async def confirm_delete_request(callback: types.CallbackQuery):
    """Confirm deletion of job request"""
    request_id = int(callback.data.split("_")[2])

    # الحصول على معلومات الطلب
    async with db_pool.acquire() as conn:
        request_info = await conn.fetchrow("""
            SELECT r.*, s.name as subject_name 
            FROM requests r 
            JOIN subjects s ON r.subject_id = s.id 
            WHERE r.id = $1
        """, request_id)

    if not request_info:
        await callback.message.answer("❌ لم يتم العثور على الطلب")
        await callback.answer()
        return

    # عرض تأكيد الحذف
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ نعم، احذف",
                              callback_data=f"confirm_delete_{request_id}")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_delete")]
    ])

    response = (
        f"⚠️ هل أنت متأكد من حذف هذا الطلب؟\n\n"
        f"📚 المادة: {request_info['subject_name']}\n"
        f"🏫 الصف: {request_info['class_number'] or 'غير محدد'}\n"
        f"👨‍🏫 الدكتور: {request_info['professor_name'] or 'غير محدد'}\n"
        f"📝 الملاحظات: {request_info['details'] or 'لا توجد'}\n\n"
        f"هذا الإجراء لا يمكن التراجع عنه!"
    )

    await callback.message.answer(response, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete_"))
async def execute_delete_request(callback: types.CallbackQuery):
    """Execute the deletion of job request"""
    request_id = int(callback.data.split("_")[2])

    # الحصول على معلومات الطلب قبل الحذف (للعرض)
    async with db_pool.acquire() as conn:
        request_info = await conn.fetchrow("""
            SELECT r.*, s.name as subject_name 
            FROM requests r 
            JOIN subjects s ON r.subject_id = s.id 
            WHERE r.id = $1
        """, request_id)

        # حذف الطلب (أو تعطيله)
        await conn.execute("""
            UPDATE requests SET is_active = FALSE, updated_at = NOW() 
            WHERE id = $1
        """, request_id)
        # أو إذا كنت تريد حذف نهائي:
        # await conn.execute("DELETE FROM requests WHERE id = $1", request_id)

    if request_info:
        response = (
            f"✅ تم حذف الطلب بنجاح!\n\n"
            f"📚 المادة: {request_info['subject_name']}\n"
            f"🏫 الصف: {request_info['class_number'] or 'غير محدد'}\n"
            f"👨‍🏫 الدكتور: {request_info['professor_name'] or 'غير محدد'}\n"
        )
    else:
        response = "✅ تم حذف الطلب بنجاح!"

    await callback.message.answer(response, reply_markup=student_keyboard)
    await callback.answer()


@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: types.CallbackQuery):
    """Cancel the deletion process"""
    await callback.message.answer("❌ تم إلغاء عملية الحذف", reply_markup=student_keyboard)
    await callback.answer()
# ========== Bot Startup and Shutdown ==========


async def main():
    """Main function to start the bot"""
    try:
        # تشغيل البوت وربط on_shutdown لإغلاق قاعدة البيانات بشكل صحيح
        await dp.start_polling(bot, on_shutdown=on_shutdown)
    finally:
        print("👋 تم إنهاء البوت")


async def on_shutdown(dispatcher: Dispatcher):
    """Cleanup on bot shutdown"""
    if db_pool:
        await db_pool.close()
        print("🔌 تم إغلاق الاتصال بقاعدة البيانات")


if __name__ == "__main__":
    asyncio.run(mainimport os
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
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_del")]])
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
