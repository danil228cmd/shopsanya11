import asyncio
import logging
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
import sqlite3
from typing import List, Optional
from aiohttp import web
import aiohttp_cors

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
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBAPP_URL = os.getenv("WEBAPP_URL")
ORDER_CHANNEL_ID = os.getenv("ORDER_CHANNEL_ID")

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

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
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES categories (id) ON DELETE CASCADE
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            photo_id TEXT,
            in_stock BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            items TEXT NOT NULL,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    
    def clear_all_data(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products")
        cursor.execute("DELETE FROM categories")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'categories')")
        conn.commit()
        conn.close()
        logger.info("🗑️ Все данные очищены")
    
    async def export_to_json(self):
        try:
            products = self.get_all_products()
            categories = self.get_all_categories()
            
            for product in products:
                if product['photo_id']:
                    try:
                        file = await bot.get_file(product['photo_id'])
                        product['photo_url'] = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
                    except:
                        product['photo_url'] = None
                else:
                    product['photo_url'] = None
                
                product.pop('category_name', None)
                product.pop('photo_id', None)
            
            os.makedirs('api', exist_ok=True)
            
            with open('api/products.json', 'w', encoding='utf-8') as f:
                json.dump(products, f, ensure_ascii=False, indent=2)
            
            with open('api/categories.json', 'w', encoding='utf-8') as f:
                json.dump(categories, f, ensure_ascii=False, indent=2)
            
            logger.info("✅ Данные экспортированы в JSON")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка экспорта: {e}")
            return False
    
    # Категории
    async def add_category(self, name: str, parent_id: Optional[int] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id))
        cat_id = cursor.lastrowid
        conn.commit()
        conn.close()
        await self.export_to_json()
        return cat_id
    
    def get_root_categories(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY name")
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    def get_subcategories(self, parent_id: int) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM categories WHERE parent_id = ? ORDER BY name", (parent_id,))
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    def get_all_categories(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, parent_id FROM categories ORDER BY parent_id, name")
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
        cursor.execute("""SELECT c.id, c.name, c.parent_id FROM categories c
            WHERE NOT EXISTS (SELECT 1 FROM categories WHERE parent_id = c.id)
            ORDER BY c.name""")
        categories = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return categories
    
    # Товары
    async def add_product(self, category_id: int, name: str, description: str, 
                    price: float, photo_id: Optional[str] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO products (category_id, name, description, price, photo_id, in_stock)
            VALUES (?, ?, ?, ?, ?, 1)""", (category_id, name, description, price, photo_id))
        prod_id = cursor.lastrowid
        conn.commit()
        conn.close()
        await self.export_to_json()
        return prod_id
    
    def get_all_products(self) -> List[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""SELECT p.id, p.name, p.description, p.price, p.photo_id, 
            p.category_id, p.in_stock, c.name as category_name
            FROM products p LEFT JOIN categories c ON p.category_id = c.id
            ORDER BY p.created_at DESC""")
        products = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return products
    
    def get_product(self, product_id: int) -> Optional[dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
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
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT in_stock FROM products WHERE id = ?", (product_id,))
        result = cursor.fetchone()
        if not result:
            conn.close()
            return False
        new_stock = 0 if result[0] else 1
        cursor.execute("UPDATE products SET in_stock = ? WHERE id = ?", (new_stock, product_id))
        conn.commit()
        conn.close()
        await self.export_to_json()
        return True
    
    # Заказы
    def create_order(self, user_id: int, username: str, items: str, total_price: float) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO orders (user_id, username, items, total_price) VALUES (?, ?, ?, ?)",
            (user_id, username, items, total_price))
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
    buttons = [[InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="add_category")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="📋 Управление категориями", callback_data="manage_categories")],
        [InlineKeyboardButton(text="📦 Управление товарами", callback_data="manage_products")],
        [InlineKeyboardButton(text="🗑️ ОЧИСТИТЬ ВСЕ", callback_data="clear_all_data")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_category_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Основная категория", callback_data="addcat_root")],
        [InlineKeyboardButton(text="📂 Подкатегория", callback_data="addcat_sub")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

def get_categories_keyboard(parent_id: Optional[int] = None, action: str = "select") -> InlineKeyboardMarkup:
    categories = db.get_root_categories() if parent_id is None else db.get_subcategories(parent_id)
    buttons = [[InlineKeyboardButton(text=cat['name'], callback_data=f"{action}_cat_{cat['id']}")] for cat in categories]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard(callback: str = "admin_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=callback)]])

# ==================== ХЕНДЛЕРЫ ====================
@router.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        f"""🎉 <b>Добро пожаловать в магазин!</b>

Привет, {message.from_user.first_name}! 👋

🛒 <b>У нас есть:</b>
• Огромный выбор товаров
• Удобный каталог с поиском
• Быстрое оформление заказа

Нажми кнопку ниже, чтобы открыть магазин! 👇""",
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

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    categories_count = len(db.get_all_categories())
    products_count = len(db.get_all_products())
    
    try:
        await callback.message.edit_text(
            f"""⚙️ <b>Админ-панель</b>

📊 <b>Статистика:</b>
📦 Категорий: {categories_count}
🛒 Товаров: {products_count}

Выберите действие:""",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

# ==================== ОДИН ПРАВИЛЬНЫЙ ОБРАБОТЧИК WEBAPP ====================
@router.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    """ЕДИНСТВЕННЫЙ обработчик данных из WebApp"""
    logger.info(f"🟢 WebApp данные получены от {message.from_user.id}")
    
    try:
        data = json.loads(message.web_app_data.data)
        logger.info(f"📦 Данные: {data}")
        
        if data.get('type') != 'order':
            await message.answer("❌ Неизвестный тип данных")
            return
        
        items = data.get('items', [])
        total_price = data.get('total_price', 0)
        
        if not items:
            await message.answer("❌ Пустой заказ")
            return
        
        # Создаем заказ в БД
        order_id = db.create_order(
            user_id=message.from_user.id,
            username=message.from_user.username or '',
            items=json.dumps(items, ensure_ascii=False),
            total_price=total_price
        )
        
        # Формируем сообщение
        order_details = '\n'.join([
            f"• {item['name']} - {item['quantity']}шт. × {item['price']}₽ = {item['price'] * item['quantity']}₽"
            for item in items
        ])
        
        order_text = f"""🛒 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>

👤 <b>Клиент:</b>
├ Имя: {message.from_user.first_name}
├ ID: {message.from_user.id}
└ @{message.from_user.username or 'нет username'}

📦 <b>Заказ:</b>
{order_details}

💰 <b>ИТОГО: {total_price}₽</b>

⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"""
        
        # Отправляем в канал/группу
        try:
            await bot.send_message(chat_id=ORDER_CHANNEL_ID, text=order_text, parse_mode="HTML")
            logger.info(f"✅ Заказ #{order_id} отправлен в {ORDER_CHANNEL_ID}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в канал: {e}")
            await bot.send_message(chat_id=ADMIN_ID, text=f"❌ Ошибка отправки заказа:\n{e}")
        
        # Уведомляем пользователя
        await message.answer(
            f"""✅ <b>Заказ #{order_id} успешно оформлен!</b>

💰 Сумма: <b>{total_price}₽</b>
📦 Товаров: <b>{len(items)}</b>

📞 С вами свяжутся в течение 5-15 минут!""",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки: {e}")
        await message.answer("❌ Ошибка обработки заказа")

# ==================== КОМАНДЫ ====================
@router.message(Command("getid"))
async def cmd_get_id(message: Message):
    await message.answer(
        f"""📊 <b>Информация о чате:</b>
🆔 <b>ID:</b> <code>{message.chat.id}</code>
📝 <b>Тип:</b> {message.chat.type}
🏷️ <b>Название:</b> {getattr(message.chat, 'title', 'ЛС')}

<b>Используйте этот ID в .env файле!</b>""",
        parse_mode="HTML"
    )

# ==================== API СЕРВЕР ====================
async def get_products_api(request):
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
    return web.json_response(db.get_all_categories())

async def start_api_server():
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*")
    })
    cors.add(app.router.add_get('/api/products', get_products_api))
    cors.add(app.router.add_get('/api/categories', get_categories_api))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("🌐 API сервер запущен на http://0.0.0.0:8080")

# ==================== ЗАПУСК ====================
async def main():
    dp.include_router(router)
    logger.info("=" * 50)
    logger.info("🤖 Telegram Mini App Shop Bot")
    logger.info("=" * 50)
    logger.info(f"✅ Бот запущен!")
    logger.info(f"👤 Admin ID: {ADMIN_ID}")
    logger.info(f"🌐 WebApp URL: {WEBAPP_URL}")
    logger.info(f"📦 Order Channel: {ORDER_CHANNEL_ID}")
    logger.info("=" * 50)
    
    await start_api_server()
    
    try:
        await dp.start_polling(bot, skip_updates=True)
    except KeyboardInterrupt:
        logger.info("⚠️ Бот остановлен (Ctrl+C)")

if __name__ == "__main__":
    asyncio.run(main())