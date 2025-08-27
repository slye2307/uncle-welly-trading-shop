import sqlite3
import os

DB_PATH = 'database/stock.db'
os.makedirs('database', exist_ok=True)

conn = sqlite3.connect(DB_PATH)

# Create stock table
conn.execute('''
CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    cost_price REAL NOT NULL,
    selling_price REAL NOT NULL,
    low_stock_threshold REAL
)
''')

# Create sales table
conn.execute('DROP TABLE IF EXISTS sales')
conn.execute('''
CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id INTEGER NOT NULL,
    quantity_sold REAL NOT NULL,
    sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (stock_id) REFERENCES stock(id)
)
''')

conn.commit()
conn.close()

print(" stock.db initialized with stock and sales tables.")
