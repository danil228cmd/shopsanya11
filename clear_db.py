import sqlite3
import os

def clear_database():
    """Полная очистка базы данных"""
    db_file = "shop.db"
    
    if not os.path.exists(db_file):
        print("❌ Файл базы данных не найден!")
        return
    
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Удаляем все товары
        cursor.execute("DELETE FROM products")
        print("✅ Все товары удалены")
        
        # Удаляем все категории
        cursor.execute("DELETE FROM categories")
        print("✅ Все категории удалены")
        
        # Удаляем все заказы (опционально)
        cursor.execute("DELETE FROM orders")
        print("✅ Все заказы удалены")
        
        # Сбрасываем автоинкремент
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'categories', 'orders')")
        print("✅ Счетчики ID сброшены")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 База данных полностью очищена!")
        print("📝 Теперь вы можете добавлять категории и товары заново.")
        
    except Exception as e:
        print(f"❌ Ошибка при очистке: {e}")

if __name__ == "__main__":
    print("⚠️  ВНИМАНИЕ: Это удалит ВСЕ данные из базы!")
    confirm = input("Вы уверены? (yes/no): ")
    
    if confirm.lower() == 'yes':
        clear_database()
    else:
        print("❌ Отменено")