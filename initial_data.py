import sqlite3
import json

def load_initial_data(db_file="shop.db"):
    """Загрузка начальных данных из JSON файлов"""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Данные категорий
    categories = [
        {"id": 1, "name": "Обувь", "parent_id": None},
        {"id": 2, "name": "Nike", "parent_id": 1},
        {"id": 3, "name": "Одежда", "parent_id": None},
        {"id": 4, "name": "Аксессуары", "parent_id": None}
    ]
    
    # Данные товаров
    products = [
        {"id": 1, "category_id": 2, "name": "Nike Skeleton Purple", "description": "Хорошая модная обувь", "price": 9999.0, "photo_id": None, "in_stock": 1},
        {"id": 2, "category_id": 2, "name": "Сперма единорога", "description": "Хорошая вкусная сперма", "price": 19999.0, "photo_id": None, "in_stock": 1},
        {"id": 3, "category_id": 2, "name": "Сучка", "description": "ебаная", "price": 2414.0, "photo_id": None, "in_stock": 1},
        {"id": 4, "category_id": 3, "name": "Футболка", "description": "Крутая футболка", "price": 1500.0, "photo_id": None, "in_stock": 1},
        {"id": 5, "category_id": 4, "name": "Рюкзак", "description": "Стильный рюкзак", "price": 3000.0, "photo_id": None, "in_stock": 1}
    ]
    
    # Очищаем таблицы
    cursor.execute("DELETE FROM products")
    cursor.execute("DELETE FROM categories")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'categories')")
    
    # Загружаем категории
    for cat in categories:
        cursor.execute("INSERT INTO categories (id, name, parent_id) VALUES (?, ?, ?)", 
                      (cat['id'], cat['name'], cat['parent_id']))
    
    # Загружаем товары
    for prod in products:
        cursor.execute("INSERT INTO products (id, category_id, name, description, price, photo_id, in_stock) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (prod['id'], prod['category_id'], prod['name'], prod['description'], prod['price'], prod['photo_id'], prod['in_stock']))
    
    conn.commit()
    conn.close()
    print("✅ Начальные данные загружены!")

if __name__ == "__main__":
    load_initial_data()