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
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
WEBAPP_URL = os.getenv("WEBAPP_URL", "shopsanya11-production.up.railway.app")
ORDER_CHANNEL_ID = os.getenv("ORDER_CHANNEL_ID")

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация бота
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
        try:
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
                first_name TEXT,
                items TEXT NOT NULL,
                total_price REAL NOT NULL,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            conn.commit()
            logger.info("✅ База данных инициализирована")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
        finally:
            conn.close()
    
    def clear_all_data(self):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products")
            cursor.execute("DELETE FROM categories")
            cursor.execute("DELETE FROM orders")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'categories', 'orders')")
            conn.commit()
            logger.info("🗑️ Все данные очищены")
        except Exception as e:
            logger.error(f"❌ Ошибка очистки данных: {e}")
        finally:
            conn.close()
    
    async def export_to_json(self):
        try:
            products = self.get_all_products()
            categories = self.get_all_categories()
            
            for product in products:
                if product['photo_id']:
                    try:
                        file = await bot.get_file(product['photo_id'])
                        product['photo_url'] = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось получить фото для товара {product['id']}: {e}")
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
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id))
            cat_id = cursor.lastrowid
            conn.commit()
            await self.export_to_json()
            return cat_id
        except Exception as e:
            logger.error(f"❌ Ошибка добавления категории: {e}")
            raise
        finally:
            conn.close()
    
    def get_root_categories(self) -> List[dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY name")
            categories = [dict(row) for row in cursor.fetchall()]
            return categories
        except Exception as e:
            logger.error(f"❌ Ошибка получения корневых категорий: {e}")
            return []
        finally:
            conn.close()
    
    def get_subcategories(self, parent_id: int) -> List[dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM categories WHERE parent_id = ? ORDER BY name", (parent_id,))
            categories = [dict(row) for row in cursor.fetchall()]
            return categories
        except Exception as e:
            logger.error(f"❌ Ошибка получения подкатегорий: {e}")
            return []
        finally:
            conn.close()
    
    def get_all_categories(self) -> List[dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, parent_id FROM categories ORDER BY parent_id, name")
            categories = [dict(row) for row in cursor.fetchall()]
            return categories
        except Exception as e:
            logger.error(f"❌ Ошибка получения всех категорий: {e}")
            return []
        finally:
            conn.close()
    
    def get_category_name(self, category_id: int) -> Optional[str]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения названия категории: {e}")
            return None
        finally:
            conn.close()
    
    async def delete_category(self, category_id: int) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            conn.commit()
            await self.export_to_json()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления категории: {e}")
            return False
        finally:
            conn.close()
    
    def get_leaf_categories(self) -> List[dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""SELECT c.id, c.name, c.parent_id FROM categories c
                WHERE NOT EXISTS (SELECT 1 FROM categories WHERE parent_id = c.id)
                ORDER BY c.name""")
            categories = [dict(row) for row in cursor.fetchall()]
            return categories
        except Exception as e:
            logger.error(f"❌ Ошибка получения конечных категорий: {e}")
            return []
        finally:
            conn.close()
    
    # Товары
    async def add_product(self, category_id: int, name: str, description: str, 
                    price: float, photo_id: Optional[str] = None) -> int:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO products (category_id, name, description, price, photo_id, in_stock)
                VALUES (?, ?, ?, ?, ?, 1)""", (category_id, name, description, price, photo_id))
            prod_id = cursor.lastrowid
            conn.commit()
            await self.export_to_json()
            return prod_id
        except Exception as e:
            logger.error(f"❌ Ошибка добавления товара: {e}")
            raise
        finally:
            conn.close()
    
    def get_all_products(self) -> List[dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""SELECT p.id, p.name, p.description, p.price, p.photo_id, 
                p.category_id, p.in_stock, c.name as category_name
                FROM products p LEFT JOIN categories c ON p.category_id = c.id
                ORDER BY p.created_at DESC""")
            products = [dict(row) for row in cursor.fetchall()]
            return products
        except Exception as e:
            logger.error(f"❌ Ошибка получения товаров: {e}")
            return []
        finally:
            conn.close()
    
    def get_product(self, product_id: int) -> Optional[dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения товара: {e}")
            return None
        finally:
            conn.close()
    
    async def delete_product(self, product_id: int) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
            await self.export_to_json()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления товара: {e}")
            return False
        finally:
            conn.close()
    
    async def toggle_product_stock(self, product_id: int) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT in_stock FROM products WHERE id = ?", (product_id,))
            result = cursor.fetchone()
            if not result:
                return False
            new_stock = 0 if result[0] else 1
            cursor.execute("UPDATE products SET in_stock = ? WHERE id = ?", (new_stock, product_id))
            conn.commit()
            await self.export_to_json()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка изменения статуса товара: {e}")
            return False
        finally:
            conn.close()
    
    # Заказы - НОВЫЕ МЕТОДЫ
    def create_order_with_user(self, user_id: int, username: str, first_name: str, items: List[dict], total_price: float) -> int:
        """Создание заказа с полной информацией о пользователе"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Преобразуем items в JSON строку
            items_json = json.dumps(items, ensure_ascii=False)
            
            cursor.execute(
                """INSERT INTO orders (user_id, username, first_name, items, total_price, status) 
                VALUES (?, ?, ?, ?, ?, 'new')""",
                (user_id, username, first_name, items_json, total_price)
            )
            order_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"📦 Заказ #{order_id} создан для пользователя {user_id}")
            return order_id
        except Exception as e:
            logger.error(f"❌ Ошибка создания заказа: {e}")
            raise
        finally:
            conn.close()
    
    def get_new_orders(self) -> List[dict]:
        """Получение новых заказов"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, username, first_name, items, total_price, created_at 
                FROM orders 
                WHERE status = 'new' 
                ORDER BY created_at DESC
            """)
            orders = [dict(row) for row in cursor.fetchall()]
            return orders
        except Exception as e:
            logger.error(f"❌ Ошибка получения заказов: {e}")
            return []
        finally:
            conn.close()
    
    def get_all_orders(self) -> List[dict]:
        """Получение всех заказов"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, username, first_name, items, total_price, status, created_at 
                FROM orders 
                ORDER BY created_at DESC
            """)
            orders = [dict(row) for row in cursor.fetchall()]
            return orders
        except Exception as e:
            logger.error(f"❌ Ошибка получения всех заказов: {e}")
            return []
        finally:
            conn.close()
    
    def update_order_status(self, order_id: int, status: str) -> bool:
        """Обновление статуса заказа"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE orders SET status = ? WHERE id = ?",
                (status, order_id)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления заказа: {e}")
            return False
        finally:
            conn.close()
    
    def get_user_orders(self, user_id: int) -> List[dict]:
        """Получение заказов пользователя"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, items, total_price, status, created_at 
                FROM orders 
                WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            orders = [dict(row) for row in cursor.fetchall()]
            return orders
        except Exception as e:
            logger.error(f"❌ Ошибка получения заказов пользователя: {e}")
            return []
        finally:
            conn.close()

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
        [InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")]
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
        [InlineKeyboardButton(text="🛒 Управление заказами", callback_data="manage_orders")],
        [InlineKeyboardButton(text="🗑️ ОЧИСТИТЬ ВСЕ", callback_data="clear_all_data")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_orders")],
        [InlineKeyboardButton(text="✅ Обработать все", callback_data="process_all_orders")],
        [InlineKeyboardButton(text="📋 Все заказы", callback_data="all_orders")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

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

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]])

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
    new_orders_count = len(db.get_new_orders())
    
    try:
        await callback.message.edit_text(
            f"""⚙️ <b>Админ-панель</b>

📊 <b>Статистика:</b>
📦 Категорий: {categories_count}
🛒 Товаров: {products_count}
🆕 Новых заказов: {new_orders_count}

Выберите действие:""",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

# ==================== УПРАВЛЕНИЕ ЗАКАЗАМИ ====================
@router.callback_query(F.data == "manage_orders")
async def manage_orders(callback: CallbackQuery):
    """Показать новые заказы"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    orders = db.get_new_orders()
    
    if not orders:
        await callback.message.edit_text(
            "📦 <b>Новых заказов нет</b>",
            reply_markup=get_orders_keyboard(),
            parse_mode="HTML"
        )
        return
    
    text = "🛒 <b>НОВЫЕ ЗАКАЗЫ:</b>\n\n"
    
    for order in orders:
        try:
            items = json.loads(order['items'])
            items_text = '\n'.join([
                f"   ├ {item['name']} - {item['quantity']}шт. × {item['price']}₽"
                for item in items
            ])
            
            text += f"""📦 <b>Заказ #{order['id']}</b>
👤 <b>Клиент:</b> {order['first_name']} (@{order['username']})
🆔 <b>ID:</b> {order['user_id']}
📅 <b>Время:</b> {order['created_at']}
{items_text}
💰 <b>ИТОГО: {order['total_price']}₽</b>

"""
        except Exception as e:
            logger.error(f"❌ Ошибка обработки заказа #{order['id']}: {e}")
            continue
    
    await callback.message.edit_text(text, reply_markup=get_orders_keyboard(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "refresh_orders")
async def refresh_orders(callback: CallbackQuery):
    """Обновить список заказов"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    orders = db.get_new_orders()
    
    if not orders:
        await callback.message.edit_text(
            "📦 <b>Новых заказов нет</b>",
            reply_markup=get_orders_keyboard(),
            parse_mode="HTML"
        )
    else:
        text = "🛒 <b>НОВЫЕ ЗАКАЗЫ:</b>\n\n"
        
        for order in orders:
            try:
                items = json.loads(order['items'])
                items_text = '\n'.join([
                    f"   ├ {item['name']} - {item['quantity']}шт. × {item['price']}₽"
                    for item in items
                ])
                
                text += f"""📦 <b>Заказ #{order['id']}</b>
👤 <b>Клиент:</b> {order['first_name']} (@{order['username']})
🆔 <b>ID:</b> {order['user_id']}
📅 <b>Время:</b> {order['created_at']}
{items_text}
💰 <b>ИТОГО: {order['total_price']}₽</b>

"""
            except Exception as e:
                logger.error(f"❌ Ошибка обработки заказа #{order['id']}: {e}")
                continue
        
        await callback.message.edit_text(text, reply_markup=get_orders_keyboard(), parse_mode="HTML")
    
    await callback.answer()

@router.callback_query(F.data == "process_all_orders")
async def process_all_orders(callback: CallbackQuery):
    """Пометить все заказы как обработанные"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    orders = db.get_new_orders()
    processed_count = 0
    
    for order in orders:
        if db.update_order_status(order['id'], 'processed'):
            processed_count += 1
    
    await callback.message.edit_text(
        f"✅ <b>Обработано заказов: {processed_count}</b>",
        reply_markup=get_orders_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "all_orders")
async def show_all_orders(callback: CallbackQuery):
    """Показать все заказы"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    orders = db.get_all_orders()
    
    if not orders:
        await callback.message.edit_text(
            "📦 <b>Заказов нет</b>",
            reply_markup=get_orders_keyboard(),
            parse_mode="HTML"
        )
        return
    
    text = "🛒 <b>ВСЕ ЗАКАЗЫ:</b>\n\n"
    
    for order in orders[:10]:  # Показываем первые 10 заказов
        try:
            items = json.loads(order['items'])
            status_icon = "🆕" if order['status'] == 'new' else "✅"
            
            text += f"""{status_icon} <b>Заказ #{order['id']}</b>
👤 {order['first_name']} | 💰 {order['total_price']}₽ | 📅 {order['created_at']}
Статус: {order['status']}

"""
        except Exception as e:
            logger.error(f"❌ Ошибка обработки заказа #{order['id']}: {e}")
            continue
    
    if len(orders) > 10:
        text += f"\n... и еще {len(orders) - 10} заказов"
    
    await callback.message.edit_text(text, reply_markup=get_orders_keyboard(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "my_orders")
async def show_my_orders(callback: CallbackQuery):
    """Показать заказы пользователя"""
    user_id = callback.from_user.id
    orders = db.get_user_orders(user_id)
    
    if not orders:
        await callback.message.edit_text(
            "📦 <b>У вас пока нет заказов</b>\n\nПерейдите в магазин чтобы сделать первый заказ!",
            reply_markup=get_back_keyboard("main_menu"),
            parse_mode="HTML"
        )
        return
    
    text = "🛒 <b>ВАШИ ЗАКАЗЫ:</b>\n\n"
    
    for order in orders:
        try:
            items = json.loads(order['items'])
            items_text = '\n'.join([
                f"   ├ {item['name']} - {item['quantity']}шт."
                for item in items[:3]  # Показываем первые 3 товара
            ])
            
            if len(items) > 3:
                items_text += f"\n   └ ... и еще {len(items) - 3} товаров"
            
            status_icon = "🆕" if order['status'] == 'new' else "✅"
            status_text = "новый" if order['status'] == 'new' else "обработан"
            
            text += f"""{status_icon} <b>Заказ #{order['id']}</b>
{items_text}
💰 <b>Сумма: {order['total_price']}₽</b>
📅 <b>Дата:</b> {order['created_at']}
📊 <b>Статус:</b> {status_text}

"""
        except Exception as e:
            logger.error(f"❌ Ошибка обработки заказа #{order['id']}: {e}")
            continue
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard("main_menu"), parse_mode="HTML")
    await callback.answer()

# ==================== FSM ХЕНДЛЕРЫ ДЛЯ АДМИНКИ ====================
@router.callback_query(F.data == "add_category")
async def add_category_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📁 <b>Добавление категории</b>\n\nВыберите тип категории:",
        reply_markup=get_category_type_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("addcat_"))
async def add_category_type(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    cat_type = callback.data.replace("addcat_", "")
    
    if cat_type == "root":
        await state.set_state(AddCategory.waiting_for_name)
        await callback.message.edit_text(
            "📝 <b>Введите название основной категории:</b>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
    elif cat_type == "sub":
        await state.set_state(AddCategory.selecting_parent)
        await callback.message.edit_text(
            "📁 <b>Выберите родительскую категорию:</b>",
            reply_markup=get_categories_keyboard(action="selectparent"),
            parse_mode="HTML"
        )
    
    await callback.answer()

@router.callback_query(F.data.startswith("selectparent_cat_"))
async def select_parent_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    parent_id = int(callback.data.replace("selectparent_cat_", ""))
    await state.update_data(parent_id=parent_id)
    await state.set_state(AddCategory.waiting_for_name)
    
    parent_name = db.get_category_name(parent_id)
    await callback.message.edit_text(
        f"📝 <b>Введите название подкатегории для '{parent_name}':</b>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AddCategory.waiting_for_name)
async def process_category_name(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа!")
        return
    
    category_name = message.text.strip()
    if len(category_name) < 2:
        await message.answer("❌ Название категории должно быть не менее 2 символов!")
        return
    
    data = await state.get_data()
    parent_id = data.get('parent_id')
    
    try:
        category_id = await db.add_category(category_name, parent_id)
        await message.answer(
            f"✅ <b>Категория '{category_name}' успешно добавлена!</b>",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
    except Exception as e:
        await message.answer(
            f"❌ <b>Ошибка добавления категории:</b>\n{str(e)}",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )

# Добавление товара
@router.callback_query(F.data == "add_product")
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await state.set_state(AddProduct.selecting_category)
    await callback.message.edit_text(
        "📁 <b>Выберите категорию для товара:</b>",
        reply_markup=get_categories_keyboard(action="selectprodcat"),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("selectprodcat_cat_"))
async def select_product_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    category_id = int(callback.data.replace("selectprodcat_cat_", ""))
    await state.update_data(category_id=category_id)
    await state.set_state(AddProduct.waiting_for_name)
    
    category_name = db.get_category_name(category_id)
    await callback.message.edit_text(
        f"📝 <b>Введите название товара для категории '{category_name}':</b>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AddProduct.waiting_for_name)
async def process_product_name(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа!")
        return
    
    product_name = message.text.strip()
    if len(product_name) < 2:
        await message.answer("❌ Название товара должно быть не менее 2 символов!")
        return
    
    await state.update_data(name=product_name)
    await state.set_state(AddProduct.waiting_for_description)
    
    await message.answer(
        "📝 <b>Введите описание товара:</b>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AddProduct.waiting_for_description)
async def process_product_description(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа!")
        return
    
    description = message.text.strip()
    if len(description) < 5:
        await message.answer("❌ Описание должно быть не менее 5 символов!")
        return
    
    await state.update_data(description=description)
    await state.set_state(AddProduct.waiting_for_price)
    
    await message.answer(
        "💰 <b>Введите цену товара (только число):</b>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AddProduct.waiting_for_price)
async def process_product_price(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа!")
        return
    
    try:
        price = float(message.text.strip().replace(',', '.'))
        if price <= 0:
            raise ValueError("Цена должна быть больше 0")
    except (ValueError, TypeError):
        await message.answer("❌ Неверный формат цены! Введите число (например: 1500 или 99.99)")
        return
    
    await state.update_data(price=price)
    await state.set_state(AddProduct.waiting_for_photo)
    
    await message.answer(
        "📸 <b>Отправьте фото товара (или любой текст чтобы пропустить):</b>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )

@router.message(AddProduct.waiting_for_photo)
async def process_product_photo(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа!")
        return
    
    data = await state.get_data()
    photo_id = None
    
    if message.photo:
        photo_id = message.photo[-1].file_id
    
    try:
        product_id = await db.add_product(
            category_id=data['category_id'],
            name=data['name'],
            description=data['description'],
            price=data['price'],
            photo_id=photo_id
        )
        
        category_name = db.get_category_name(data['category_id'])
        response_text = f"""✅ <b>Товар успешно добавлен!</b>

📦 <b>Название:</b> {data['name']}
📝 <b>Описание:</b> {data['description']}
💰 <b>Цена:</b> {data['price']}₽
📁 <b>Категория:</b> {category_name}
🖼️ <b>Фото:</b> {'✅' if photo_id else '❌'}

ID товара: <code>{product_id}</code>"""
        
        await message.answer(
            response_text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(
            f"❌ <b>Ошибка добавления товара:</b>\n{str(e)}",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )

# Управление категориями и товарами
@router.callback_query(F.data == "manage_categories")
async def manage_categories(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    categories = db.get_all_categories()
    if not categories:
        await callback.message.edit_text(
            "📁 <b>Категории отсутствуют</b>",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        return
    
    text = "📁 <b>Управление категориями</b>\n\n"
    for cat in categories:
        parent_info = f" → {db.get_category_name(cat['parent_id'])}" if cat['parent_id'] else ""
        text += f"• {cat['name']}{parent_info}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "manage_products")
async def manage_products(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    products = db.get_all_products()
    if not products:
        await callback.message.edit_text(
            "📦 <b>Товары отсутствуют</b>",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        return
    
    text = "📦 <b>Управление товарами</b>\n\n"
    for prod in products[:10]:  # Показываем первые 10 товаров
        stock = "✅ В наличии" if prod['in_stock'] else "❌ Нет в наличии"
        text += f"• {prod['name']} - {prod['price']}₽ ({stock})\n"
    
    if len(products) > 10:
        text += f"\n... и еще {len(products) - 10} товаров"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "clear_all_data")
async def clear_all_data(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ ДА, ОЧИСТИТЬ ВСЁ", callback_data="confirm_clear")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\nВы уверены что хотите удалить ВСЕ данные (категории, товары и заказы)?\n\nЭто действие нельзя отменить!",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_clear")
async def confirm_clear(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    db.clear_all_data()
    await callback.message.edit_text(
        "✅ <b>Все данные очищены!</b>",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

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

@router.message(Command("orders"))
async def cmd_orders(message: Message):
    """Команда для просмотра заказов"""
    if message.from_user.id == ADMIN_ID:
        # Админ видит все заказы
        orders = db.get_new_orders()
        if not orders:
            await message.answer("📦 <b>Новых заказов нет</b>", parse_mode="HTML")
        else:
            text = "🛒 <b>НОВЫЕ ЗАКАЗЫ:</b>\n\n"
            for order in orders:
                items = json.loads(order['items'])
                items_text = '\n'.join([f"• {item['name']} - {item['quantity']}шт." for item in items[:3]])
                text += f"📦 <b>Заказ #{order['id']}</b>\n👤 {order['first_name']}\n{items_text}\n💰 {order['total_price']}₽\n\n"
            await message.answer(text, parse_mode="HTML")
    else:
        # Пользователь видит свои заказы
        orders = db.get_user_orders(message.from_user.id)
        if not orders:
            await message.answer("📦 <b>У вас пока нет заказов</b>", parse_mode="HTML")
        else:
            text = "🛒 <b>ВАШИ ЗАКАЗЫ:</b>\n\n"
            for order in orders:
                status_icon = "🆕" if order['status'] == 'new' else "✅"
                text += f"{status_icon} <b>Заказ #{order['id']}</b> - {order['total_price']}₽ ({order['status']})\n"
            await message.answer(text, parse_mode="HTML")

@router.message(Command("testchannel"))
async def test_channel_command(message: Message):
    """Тест отправки в канал"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа!")
        return
        
    try:
        logger.info(f"🔍 Тестирую канал: {ORDER_CHANNEL_ID}")
        
        # Проверяем доступ к каналу
        chat = await bot.get_chat(ORDER_CHANNEL_ID)
        logger.info(f"✅ Канал доступен: {chat.title}")
        
        # Отправляем тестовое сообщение
        await bot.send_message(
            chat_id=ORDER_CHANNEL_ID,
            text="🛒 <b>ТЕСТОВОЕ СООБЩЕНИЕ ОТ БОТА</b>\n\nЕсли вы видите это сообщение, значит бот может отправлять заказы в эту группу!",
            parse_mode="HTML"
        )
        
        await message.answer("✅ Тестовое сообщение отправлено в канал!")
        logger.info("✅ Тестовое сообщение отправлено в канал")
        
    except Exception as e:
        error_msg = f"❌ Ошибка отправки в канал: {e}"
        await message.answer(error_msg)
        logger.error(error_msg)

# ==================== API СЕРВЕР ====================
async def get_products_api(request):
    try:
        products = db.get_all_products()
        for product in products:
            if product['photo_id']:
                try:
                    file = await bot.get_file(product['photo_id'])
                    product['photo_url'] = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось получить фото URL: {e}")
                    product['photo_url'] = None
            else:
                product['photo_url'] = None
        
        response = web.json_response(products)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS, POST'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка API products: {e}")
        response = web.json_response({"error": "Internal server error"}, status=500)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

async def get_categories_api(request):
    try:
        categories = db.get_all_categories()
        response = web.json_response(categories)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS, POST'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    except Exception as e:
        logger.error(f"❌ Ошибка API categories: {e}")
        response = web.json_response({"error": "Internal server error"}, status=500)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

async def create_order_api(request):
    """API для создания заказа из WebApp"""
    try:
        data = await request.json()
        logger.info(f"📦 API Order received from user {data.get('user_id')}")
        
        # Создаем заказ в БД
        order_id = db.create_order_with_user(
            user_id=data.get('user_id'),
            username=data.get('username', 'не указан'),
            first_name=data.get('first_name', 'Пользователь'),
            items=data.get('items', []),
            total_price=data.get('total_price', 0)
        )
        
        # Уведомляем администратора
        if ADMIN_ID:
            items_text = '\n'.join([
                f"• {item['name']} - {item['quantity']}шт. × {item['price']}₽ = {item['price'] * item['quantity']}₽"
                for item in data.get('items', [])
            ])
            
            order_text = f"""🛒 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>

👤 <b>Клиент:</b>
├ Имя: {data.get('first_name', 'Пользователь')}
├ ID: {data.get('user_id', 'не указан')}
└ @{data.get('username', 'не указан')}

📦 <b>Заказ:</b>
{items_text}

💰 <b>ИТОГО: {data.get('total_price', 0)}₽</b>

⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"""
            
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=order_text,
                parse_mode="HTML"
            )
            
            # Также отправляем в группу, если указана
            if ORDER_CHANNEL_ID:
                await bot.send_message(
                    chat_id=ORDER_CHANNEL_ID,
                    text=order_text,
                    parse_mode="HTML"
                )
        
        logger.info(f"✅ Заказ #{order_id} создан и уведомления отправлены")
        
        return web.json_response({
            "status": "success", 
            "order_id": order_id,
            "message": "Заказ успешно создан"
        })
        
    except Exception as e:
        logger.error(f"❌ API Order error: {e}")
        return web.json_response({
            "status": "error",
            "message": "Ошибка создания заказа"
        }, status=500)

async def options_handler(request):
    response = web.Response()
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS, POST'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

async def health_check(request):
    response = web.json_response({"status": "ok", "message": "Bot is running"})
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def start_api_server():
    app = web.Application()
    
    # Добавляем маршруты
    app.router.add_get('/api/products', get_products_api)
    app.router.add_get('/api/categories', get_categories_api)
    app.router.add_post('/api/create_order', create_order_api)
    app.router.add_get('/health', health_check)
    
    # Добавляем OPTIONS handlers для CORS
    app.router.add_route('OPTIONS', '/api/products', options_handler)
    app.router.add_route('OPTIONS', '/api/categories', options_handler)
    app.router.add_route('OPTIONS', '/api/create_order', options_handler)
    app.router.add_route('OPTIONS', '/health', options_handler)
    
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