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
async def create_db_pool():
    global db_pool
    try:
        print("🔄 جاري محاولة الاتصال بقاعدة البيانات...")
        print(f"📋 Host: {DB_CONFIG['host']}")
        print(f"📋 Port: {DB_CONFIG['port']}")
        print(f"📋 User: {DB_CONFIG['user']}")
        print(f"📋 Database: {DB_CONFIG['database']}")
        
        db_pool = await asyncpg.create_pool(**DB_CONFIG)
        print("✅ تم إنشاء connection pool لقاعدة البيانات بنجاح!")
        
    except Exception as e:
        print(f"❌ فشل في الاتصال بقاعدة البيانات: {e}")
        raise e

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
    # تحقق من أن db_pool متصل
    if db_pool is None:
        print("❌ Database not connected!")
        return
    
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
# ... (كل الكود السابق) ...

# ========== Bot Startup and Shutdown ==========
async def main():
    """Main function to start the bot"""
    try:
        # 1. إنشاء connection pool أولاً
        await create_db_pool()
        
        # 2. ثم بدء استقبال التحديثات
        print("🤖 بدء تشغيل البوت...")
        await dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown)
        
    except Exception as e:
        print(f"❌ فشل في تشغيل البوت: {e}")
    finally:
        await on_shutdown(dp)

# إضافة لربط port للتجنب خطأ Render
import socket
from contextlib import closing

def find_free_port():
    """Find a free port to bind to"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

# إربط على port عشوائي
port = find_free_port()
print(f"🔗 Bound to port: {port}")



if __name__ == "__main__":
    asyncio.run(main())


