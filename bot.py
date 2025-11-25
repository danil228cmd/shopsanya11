import asyncio
import logging
import os
import subprocess
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import sqlite3
from typing import List, Optional, Tuple
import json
from datetime import datetime
from aiogram.exceptions import TelegramBadRequest

# Загрузка переменных окружения
def load_env():
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env()

# Настройки
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.com")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

def push_to_github():
    """Автоматически пушит изменения на GitHub"""
    try:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        
        subprocess.run(['git', 'add', 'api/'], check=True)
        subprocess.run(['git', 'commit', '-m', 'Auto-update: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')], check=True)
        subprocess.run(['git', 'push', 'origin', 'master'], check=True)
        
        logger.info("✅ Изменения запушены на GitHub")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка пуша на GitHub: {e}")
        return False

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_file: str = "shop.db"):
        self.db_file = db_file
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES categories (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                photo_id TEXT,
                in_stock BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                items TEXT NOT NULL,
                total_price REAL NOT NULL,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    
    def clear_all_data(self):
        """Очистка всех данных (категории и товары)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products")
        cursor.execute("DELETE FROM categories")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'categories')")
        conn.commit()
        conn.close()
        logger.info("🗑️ Все данные очищены")
    
    async def export_to_json(self):
        """Экспорт товаров и категорий в JSON файлы для GitHub Pages"""
        try:
            products = self.get_all_products()
            categories = self.get_all_categories()
            
            # Конвертируем photo_id в URL для товаров
            for product in products:
                if product['photo_id']:
                    try:
                        file = await bot.get_file(product['photo_id'])
                        product['photo_url'] = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
                    except Exception as e:
                        logger.error(f"❌ Ошибка получения фото: {e}")
                        product['photo_url'] = None
                else:
                    product['photo_url'] = None
                
                if 'category_name' in product:
                    del product['category_name']
                if 'photo_id' in product:
                    del product['photo_id']
            
            os.makedirs('api', exist_ok=True)
            
            with open('api/products.json', 'w', encoding='utf-8') as f:
                json.dump(products, f, ensure_ascii=False, indent=2)
            
            with open('api/categories.json', 'w', encoding='utf-8') as f:
                json.dump(categories, f, ensure_ascii=False, indent=2)
            
            logger.info("✅ Данные экспортированы в JSON")
            push_to_github()
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка экспорта в JSON: {e}")
            return False
    
    # ===== КАТЕГОРИИ =====
    
    async def add_category(self, name: str, parent_id: Optional[int] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO categories (name, parent_id) VALUES (?, ?)", 
            (name, parent_id)
        )
        cat_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        await self.export_to_json()
        return cat_id
    
    def get_root_categories(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name FROM categories 
            WHERE parent_id IS NULL 
            ORDER BY name
        """)
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    def get_subcategories(self, parent_id: int) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name FROM categories 
            WHERE parent_id = ? 
            ORDER BY name
        """, (parent_id,))
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    def get_all_categories(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, parent_id FROM categories 
            ORDER BY parent_id, name
        """)
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    def get_category_name(self, category_id: int) -> Optional[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    async def delete_category(self, category_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        conn.close()
        
        await self.export_to_json()
        return True
    
    def get_leaf_categories(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.id, c.name, c.parent_id 
            FROM categories c
            WHERE NOT EXISTS (
                SELECT 1 FROM categories WHERE parent_id = c.id
            )
            ORDER BY c.name
        """)
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    # ===== ТОВАРЫ =====
    
    async def add_product(self, category_id: int, name: str, description: str, 
                    price: float, photo_id: Optional[str] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO products (category_id, name, description, price, photo_id, in_stock)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (category_id, name, description, price, photo_id))
        prod_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        await self.export_to_json()
        return prod_id
    
    def get_all_products(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.name, p.description, p.price, p.photo_id, 
                   p.category_id, p.in_stock, c.name as category_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            ORDER BY p.created_at DESC
        """)
        products = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return products
    
    def get_product(self, product_id: int) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, description, price, photo_id, category_id, in_stock
            FROM products WHERE id = ?
        """, (product_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    async def delete_product(self, product_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        conn.close()
        
        await self.export_to_json()
        return True
    
    async def toggle_product_stock(self, product_id: int) -> bool:
        """Переключить наличие товара"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Получаем текущий статус
        cursor.execute("SELECT in_stock FROM products WHERE id = ?", (product_id,))
        result = cursor.fetchone()
        
        if result is None:
            conn.close()
            return False
        
        current_stock = result[0]
        new_stock = 0 if current_stock else 1
        
        # Обновляем статус
        cursor.execute("UPDATE products SET in_stock = ? WHERE id = ?", (new_stock, product_id))
        conn.commit()
        conn.close()
        
        await self.export_to_json()
        logger.info(f"✅ Товар {product_id}: наличие изменено с {current_stock} на {new_stock}")
        return True
    
    # ===== ЗАКАЗЫ =====
    
    def create_order(self, user_id: int, username: str, items: str, total_price: float) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (user_id, username, items, total_price)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, items, total_price))
        order_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return order_id

db = Database()

# ==================== СОСТОЯНИЯ FSM ====================
class AddCategory(StatesGroup):
    selecting_parent = State()
    waiting_for_name = State()

class AddProduct(StatesGroup):
    selecting_category = State()
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_photo = State()

# ==================== КЛАВИАТУРЫ ====================

def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text="🛒 Открыть магазин", 
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ]
    
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="📋 Управление категориями", callback_data="manage_categories")],
        [InlineKeyboardButton(text="📦 Управление товарами", callback_data="manage_products")],
        [InlineKeyboardButton(text="🗑️ ОЧИСТИТЬ ВСЁ", callback_data="clear_all_data")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_category_type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📁 Основная категория", callback_data="addcat_root")],
        [InlineKeyboardButton(text="📂 Подкатегория", callback_data="addcat_sub")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_categories_keyboard(parent_id: Optional[int] = None, action: str = "select") -> InlineKeyboardMarkup:
    if parent_id is None:
        categories = db.get_root_categories()
    else:
        categories = db.get_subcategories(parent_id)
    
    buttons = []
    for cat in categories:
        buttons.append([InlineKeyboardButton(
            text=cat['name'],
            callback_data=f"{action}_cat_{cat['id']}"
        )])
    
    back_action = "admin_panel" if action == "select" else "admin_panel"
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_action)])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard(callback: str = "admin_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=callback)]
    ])

# ==================== ХЕНДЛЕРЫ ====================

@router.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    
    welcome_text = f"""
🎉 <b>Добро пожаловать в магазин!</b>

Привет, {message.from_user.first_name}! 👋

🛒 <b>У нас есть:</b>
• Огромный выбор товаров
• Удобный каталог с поиском
• Быстрое оформление заказа

Нажми кнопку ниже, чтобы открыть магазин! 👇
"""
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == ADMIN_ID
    
    try:
        await callback.message.edit_text(
            "🏠 <b>Главное меню</b>\n\nВыберите действие:",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    
    await callback.answer()

# ==================== АДМИН ПАНЕЛЬ ====================

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    categories_count = len(db.get_all_categories())
    products = db.get_all_products()
    products_count = len(products)
    
    admin_text = f"""
⚙️ <b>Админ-панель</b>

📊 <b>Статистика:</b>
📦 Категорий: {categories_count}
🛒 Товаров: {products_count}

Выберите действие:
"""
    
    try:
        await callback.message.edit_text(
            admin_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    
    await callback.answer()

@router.callback_query(F.data == "clear_all_data")
async def clear_all_data(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    db.clear_all_data()
    await db.export_to_json()
    
    await callback.answer("✅ Все данные очищены!", show_alert=True)
    await show_admin_panel(callback, FSMContext(storage=storage, key=None))

# ===== ДОБАВЛЕНИЕ КАТЕГОРИИ =====

@router.callback_query(F.data == "add_category")
async def start_add_category(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    try:
        await callback.message.edit_text(
            "➕ <b>Добавление категории</b>\n\n"
            "Выберите тип:\n\n"
            "📁 <b>Основная</b> - корневая категория (Обувь, Одежда)\n"
            "📂 <b>Подкатегория</b> - вложенная (Nike внутри Обуви)",
            reply_markup=get_category_type_keyboard(),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    
    await callback.answer()

@router.callback_query(F.data == "addcat_root")
async def add_root_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(parent_id=None)
    await callback.message.edit_text(
        "➕ <b>Добавление основной категории</b>\n\n"
        "Напишите название категории:\n"
        "<i>Например: Обувь, Одежда, Аксессуары</i>",
        parse_mode="HTML"
    )
    await state.set_state(AddCategory.waiting_for_name)
    await callback.answer()

@router.callback_query(F.data == "addcat_sub")
async def select_parent_category(callback: CallbackQuery, state: FSMContext):
    categories = db.get_root_categories()
    
    if not categories:
        await callback.message.edit_text(
            "❌ Сначала создайте основную категорию!",
            reply_markup=get_back_keyboard("admin_panel"),
            parse_mode="HTML"
        )
        return
    
    await callback.message.edit_text(
        "➕ <b>Добавление подкатегории</b>\n\nВыберите родительскую категорию:",
        reply_markup=get_categories_keyboard(parent_id=None, action="addsubcat"),
        parse_mode="HTML"
    )
    await state.set_state(AddCategory.selecting_parent)
    await callback.answer()

@router.callback_query(AddCategory.selecting_parent, F.data.startswith("addsubcat_cat_"))
async def parent_category_selected(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[-1])
    category_name = db.get_category_name(category_id)
    
    await state.update_data(parent_id=category_id, parent_name=category_name)
    
    await callback.message.edit_text(
        f"✅ Родитель: <b>{category_name}</b>\n\n"
        "Напишите название подкатегории:\n"
        "<i>Например: Nike, Adidas, Supreme</i>",
        parse_mode="HTML"
    )
    await state.set_state(AddCategory.waiting_for_name)
    await callback.answer()

@router.message(AddCategory.waiting_for_name)
async def process_category_name(message: Message, state: FSMContext):
    category_name = message.text.strip()
    
    if len(category_name) < 2:
        await message.answer("❌ Название слишком короткое! Минимум 2 символа.")
        return
    
    data = await state.get_data()
    parent_id = data.get('parent_id')
    
    cat_id = await db.add_category(category_name, parent_id)
    
    if parent_id:
        parent_name = data.get('parent_name')
        success_text = f"✅ Подкатегория <b>'{category_name}'</b> добавлена!\n📂 Путь: {parent_name} → {category_name}"
    else:
        success_text = f"✅ Категория <b>'{category_name}'</b> добавлена!"
    
    await message.answer(
        success_text,
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()

# ===== ДОБАВЛЕНИЕ ТОВАРА =====

@router.callback_query(F.data == "add_product")
async def start_add_product(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    leaf_categories = db.get_leaf_categories()
    
    if not leaf_categories:
        await callback.message.edit_text(
            "❌ Сначала создайте категории!",
            reply_markup=get_back_keyboard("admin_panel"),
            parse_mode="HTML"
        )
        return
    
    buttons = []
    for cat in leaf_categories:
        buttons.append([InlineKeyboardButton(
            text=cat['name'],
            callback_data=f"select_cat_{cat['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    
    await callback.message.edit_text(
        "➕ <b>Добавление товара</b>\n\nШаг 1/4: Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await state.set_state(AddProduct.selecting_category)
    await callback.answer()

@router.callback_query(AddProduct.selecting_category, F.data.startswith("select_cat_"))
async def select_product_category(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[-1])
    category_name = db.get_category_name(category_id)
    
    await state.update_data(category_id=category_id, category_name=category_name)
    
    await callback.message.edit_text(
        f"✅ Категория: <b>{category_name}</b>\n\n"
        "Шаг 2/4: Напишите <b>название товара</b>\n"
        "<i>Например: Nike Skeleton Purple</i>",
        parse_mode="HTML"
    )
    await state.set_state(AddProduct.waiting_for_name)
    await callback.answer()

@router.message(AddProduct.waiting_for_name)
async def process_product_name(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Название слишком короткое! Минимум 3 символа.")
        return
    
    await state.update_data(name=name)
    
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "Шаг 3/4: Напишите <b>описание</b>\n"
        "<i>Укажите размеры, характеристики и т.д.</i>",
        parse_mode="HTML"
    )
    await state.set_state(AddProduct.waiting_for_description)

@router.message(AddProduct.waiting_for_description)
async def process_product_description(message: Message, state: FSMContext):
    description = message.text.strip()
    
    await state.update_data(description=description)
    
    await message.answer(
        "Шаг 4/4: Укажите <b>цену</b> (только число)\n"
        "<i>Например: 26990</i>",
        parse_mode="HTML"
    )
    await state.set_state(AddProduct.waiting_for_price)

@router.message(AddProduct.waiting_for_price)
async def process_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректную цену (только число)!")
        return
    
    await state.update_data(price=price)
    
    await message.answer(
        "📸 Отправьте <b>фото товара</b> или напишите /skip чтобы пропустить",
        parse_mode="HTML"
    )
    await state.set_state(AddProduct.waiting_for_photo)

@router.message(AddProduct.waiting_for_photo, F.photo)
async def process_product_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await save_product(message, state, photo_id)

@router.message(AddProduct.waiting_for_photo, F.text == "/skip")
async def skip_product_photo(message: Message, state: FSMContext):
    await save_product(message, state, None)

async def save_product(message: Message, state: FSMContext, photo_id: Optional[str]):
    data = await state.get_data()
    
    prod_id = await db.add_product(
        category_id=data['category_id'],
        name=data['name'],
        description=data['description'],
        price=data['price'],
        photo_id=photo_id
    )
    
    media_status = "📸 С фото" if photo_id else "📝 Без фото"
    
    await message.answer(
        f"✅ <b>Товар добавлен!</b>\n\n"
        f"🆔 ID: {prod_id}\n"
        f"📂 Категория: {data['category_name']}\n"
        f"🛒 Название: {data['name']}\n"
        f"💰 Цена: {data['price']}₽\n"
        f"{media_status}",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    await state.clear()

# ===== УПРАВЛЕНИЕ =====

@router.callback_query(F.data == "manage_categories")
async def manage_categories(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    categories = db.get_all_categories()
    
    if not categories:
        try:
            await callback.message.edit_text(
                "📋 Категории отсутствуют",
                reply_markup=get_back_keyboard("admin_panel"),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    else:
        try:
            await callback.message.edit_text(
                "📋 <b>Управление категориями</b>\n\nВыберите для удаления:",
                reply_markup=get_categories_keyboard(parent_id=None, action="delete"),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    await callback.answer()

@router.callback_query(F.data.startswith("delete_cat_"))
async def delete_category(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    category_id = int(callback.data.split("_")[-1])
    category_name = db.get_category_name(category_id)
    
    await db.delete_category(category_id)
    
    await callback.answer(f"✅ Категория '{category_name}' удалена!", show_alert=True)
    await manage_categories(callback)

@router.callback_query(F.data == "manage_products")
async def manage_products(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    products = db.get_all_products()
    
    if not products:
        try:
            await callback.message.edit_text(
                "📦 Товары отсутствуют",
                reply_markup=get_back_keyboard("admin_panel"),
                parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
        return
    
    buttons = []
    for prod in products[:20]:
        stock_emoji = "✅" if prod['in_stock'] else "❌"
        buttons.append([InlineKeyboardButton(
            text=f"{stock_emoji} {prod['name']} - {prod['price']}₽",
            callback_data=f"manageprod_{prod['id']}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    
    try:
        await callback.message.edit_text(
            f"📦 <b>Управление товарами</b>\n\nВсего товаров: {len(products)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("manageprod_"))
async def manage_product_detail(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[-1])
    product = db.get_product(product_id)
    
    if not product:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return
    
    stock_text = "🟢 В наличии" if product['in_stock'] else "🔴 Нет в наличии"
    
    buttons = [
        [InlineKeyboardButton(
            text="🔄 Переключить наличие",
            callback_data=f"toggle_stock_{product_id}"
        )],
        [InlineKeyboardButton(
            text="🗑 Удалить товар",
            callback_data=f"delete_product_{product_id}"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="manage_products")]
    ]
    
    try:
        await callback.message.edit_text(
            f"📦 <b>{product['name']}</b>\n\n"
            f"💰 Цена: {product['price']}₽\n"
            f"📝 Описание: {product['description']}\n"
            f"📊 Статус: {stock_text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_stock_"))
async def toggle_stock(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[-1])
    success = await db.toggle_product_stock(product_id)
    
    if success:
        await callback.answer("✅ Статус изменен!", show_alert=False)
        # Обновляем информацию о товаре
        await manage_product_detail(callback)
    else:
        await callback.answer("❌ Ошибка изменения статуса", show_alert=True)

@router.callback_query(F.data.startswith("delete_product_"))
async def delete_product(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    product_id = int(callback.data.split("_")[-1])
    product = db.get_product(product_id)
    
    if product:
        await db.delete_product(product_id)
        await callback.answer(f"✅ Товар '{product['name']}' удален!", show_alert=True)
        await manage_products(callback)
    else:
        await callback.answer("❌ Товар не найден!", show_alert=True)

# ==================== НАСТРОЙКИ КАНАЛА ====================
ORDER_CHANNEL_ID = os.getenv("ORDER_CHANNEL_ID", "-1003478155443")  # Замените на ID вашего канала

# ==================== ОБРАБОТКА ЗАКАЗОВ ====================

@router.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    """Обработка данных из Mini App"""
    try:
        data = json.loads(message.web_app_data.data)
        
        if data.get('type') == 'order':
            items = data.get('items', [])
            total_price = data.get('total_price', 0)
            
            # Формируем детали заказа
            order_details = []
            for item in items:
                item_total = item['price'] * item['quantity']
                order_details.append(
                    f"• {item['name']}\n"
                    f"  💰 Цена: {item['price']}₽\n"
                    f"  📦 Количество: {item['quantity']} шт.\n"
                    f"  🧮 Сумма: {item_total}₽"
                )
            
            order_text = f"""
🛒 <b>НОВЫЙ ЗАКАЗ!</b>

👤 <b>Информация о клиенте:</b>
├ Имя: {message.from_user.first_name}
├ ID: {message.from_user.id}
└ Username: @{message.from_user.username or 'не указан'}

📦 <b>Состав заказа:</b>
{chr(10).join(order_details)}

💰 <b>ИТОГО: {total_price}₽</b>

⏰ <b>Время заказа:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
            
            # Создаем заказ в БД
            order_id = db.create_order(
                user_id=message.from_user.id,
                username=message.from_user.username or '',
                items=json.dumps(items, ensure_ascii=False),
                total_price=total_price
            )
            
            # Отправляем в канал
            try:
                await bot.send_message(
                    chat_id=ORDER_CHANNEL_ID,
                    text=order_text + f"\n\n🆔 <b>Заказ #{order_id}</b>",
                    parse_mode="HTML"
                )
                logger.info(f"✅ Заказ #{order_id} отправлен в канал")
            except Exception as channel_error:
                logger.error(f"❌ Ошибка отправки в канал: {channel_error}")
                # Если не удалось отправить в канал, отправляем администратору
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"❌ Ошибка отправки заказа в канал:\n{channel_error}\n\n{order_text}",
                    parse_mode="HTML"
                )
            
            # Уведомляем пользователя
            await message.answer(
                "✅ <b>Заказ успешно оформлен!</b>\n\n"
                f"🆔 Номер заказа: <b>#{order_id}</b>\n"
                f"💰 Сумма: <b>{total_price}₽</b>\n\n"
                "📞 С вами свяжется наш менеджер в ближайшее время для уточнения деталей!\n\n"
                "⏳ Обычно это занимает 5-15 минут.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки заказа: {e}")
        await message.answer(
            "❌ <b>Произошла ошибка при оформлении заказа</b>\n\n"
            "Пожалуйста, попробуйте еще раз или свяжитесь с поддержкой.",
            parse_mode="HTML"
        )
# ==================== API ДЛЯ MINI APP ====================

from aiohttp import web
import aiohttp_cors

async def get_products_api(request):
    """API для получения товаров"""
    products = db.get_all_products()
    
    for product in products:
        if product['photo_id']:
            try:
                file = await bot.get_file(product['photo_id'])
                product['photo_url'] = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
            except:
                product['photo_url'] = None
        else:
            product['photo_url'] = None
    
    return web.json_response(products)

async def get_categories_api(request):
    """API для получения категорий"""
    categories = db.get_all_categories()
    return web.json_response(categories)

async def start_api_server():
    """Запуск API сервера для Mini App"""
    app = web.Application()
    
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    
    cors.add(app.router.add_get('/api/products', get_products_api))
    cors.add(app.router.add_get('/api/categories', get_categories_api))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("🌐 API сервер запущен на http://0.0.0.0:8080")

# ==================== ЗАПУСК ====================

async def on_startup():
    logger.info("=" * 50)
    logger.info("🤖 Telegram Mini App Shop Bot")
    logger.info("=" * 50)
    logger.info(f"✅ Бот запущен!")
    logger.info(f"👤 Admin ID: {ADMIN_ID}")
    logger.info(f"🌐 WebApp URL: {WEBAPP_URL}")
    logger.info("=" * 50)

async def on_shutdown():
    logger.info("🛑 Бот остановлен")

async def main():
    dp.include_router(router)
    
    await on_startup()
    
    await start_api_server()
    
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await on_shutdown()

# ==================== ОБРАБОТКА ОШИБОК ====================

@router.errors()
async def errors_handler(event, exception):
    """ИСПРАВЛЕННЫЙ: Отлов всех ошибок, включая 'message is not modified'"""
    if isinstance(exception, TelegramBadRequest):
        if "message is not modified" in str(exception):
            logger.debug("Игнорируем 'message is not modified' (пользователь дважды нажал кнопку)")
            return True
    
    logger.error(f"Необработанная ошибка: {exception}")
    return True

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Бот остановлен (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise