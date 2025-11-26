# app.py
from flask import Flask, flash, render_template, request, redirect, url_for
import sqlite3
import os
from flask import Response
from datetime import datetime
import csv
import io
import json

from utils.stock_trends import forecast_profit_trend
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key_here_change_in_production')

DATABASE = 'database/stock.db'


def get_db_connection():
    # Ensure database directory exists
    os.makedirs(os.path.dirname(DATABASE) if os.path.dirname(DATABASE) else '.', exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn  



@app.route('/sell/<int:id>', methods=['GET', 'POST'])
def sell_item(id):
    conn = get_db_connection()
    item = conn.execute('SELECT * FROM stock WHERE id = ?', (id,)).fetchone()  # ✅ Fetch from stock

    if item is None:
        conn.close()
        flash("Item not found.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            quantity_sold = float(request.form['quantity_sold'])

            if quantity_sold <= 0:
                conn.close()
                flash("Quantity must be greater than zero.", "danger")
                return redirect(url_for('sell_item', id=id))

            if quantity_sold > item['quantity']:
                conn.close()
                flash("Not enough stock available.", "danger")
                return redirect(url_for('sell_item', id=id))

            # Record the sale
            conn.execute(
                'INSERT INTO sales (stock_id, quantity_sold) VALUES (?, ?)',
                (id, quantity_sold)
            )

            # Update stock quantity
            new_quantity = item['quantity'] - quantity_sold
            conn.execute(
                'UPDATE stock SET quantity = ? WHERE id = ?',
                (new_quantity, id)
            )

            conn.commit()
            conn.close()

            flash(f"Sold {quantity_sold} {item['unit']} of {item['name']}.", "success")
            return redirect(url_for('index'))

        except ValueError:
            conn.close()
            flash("Invalid quantity entered.", "danger")
            return redirect(url_for('sell_item', id=id))

    conn.close()
    return render_template('sell.html', item=item)



@app.route('/')
def index():
    name = request.args.get('name', '')
    unit = request.args.get('unit', '')
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')

    query = 'SELECT * FROM stock WHERE 1=1'
    params = []

    if name:
        query += ' AND name LIKE ?'
        params.append(f"%{name}%")
    if unit:
        query += ' AND unit = ?'
        params.append(unit)
    if min_price:
        query += ' AND selling_price >= ?'
        params.append(min_price)
    if max_price:
        query += ' AND selling_price <= ?'
        params.append(max_price)

    conn = get_db_connection()
    items = conn.execute(query, params).fetchall()
    conn.close()

    return render_template('index.html', items=items)


@app.route('/add', methods=('GET', 'POST'))
def add_item():
    if request.method == 'POST':
        name = request.form['name']
        quantity = int(request.form['quantity'])
        cost_price = float(request.form['cost_price'])
        selling_price = float(request.form['selling_price'])
        unit = request.form['unit']
        low_stock_threshold = int(request.form['low_stock_threshold'])

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO stock (name, quantity, cost_price, selling_price, unit, low_stock_threshold)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, quantity, cost_price, selling_price, unit, low_stock_threshold))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    return render_template('add.html')


@app.route('/edit/<int:id>', methods=('GET', 'POST'))
def edit_item(id):
    conn = get_db_connection()
    item = conn.execute('SELECT * FROM stock WHERE id = ?', (id,)).fetchone()

    if item is None:
        conn.close()
        return "Item not found", 404

    if request.method == 'POST':
        name = request.form['name']
        quantity = request.form['quantity']
        unit = request.form['unit']
        cost_price = request.form['cost_price']
        selling_price = request.form['selling_price']

        conn.execute('''
            UPDATE stock
            SET name = ?, quantity = ?, unit = ?, cost_price = ?, selling_price = ?
            WHERE id = ?
        ''', (name, quantity, unit, cost_price, selling_price, id))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    conn.close()
    return render_template('edit.html', item=item)


@app.route('/delete/<int:id>', methods=('POST',))
def delete_item(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM stock WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/profit-report')
def profit_report():
    start = request.args.get('start')
    end = request.args.get('end')

    conn = get_db_connection()

    join_clauses = []
    where_clauses = []
    join_params = []
    where_params = []

    if start:
        join_clauses.append('date(sales.sale_date) >= date(?)')
        where_clauses.append('date(sales.sale_date) >= date(?)')
        join_params.append(start)
        where_params.append(start)
    if end:
        join_clauses.append('date(sales.sale_date) <= date(?)')
        where_clauses.append('date(sales.sale_date) <= date(?)')
        join_params.append(end)
        where_params.append(end)

    join_filter_sql = ''
    if join_clauses:
        join_filter_sql = ' AND ' + ' AND '.join(join_clauses)

    where_filter_sql = ''
    if where_clauses:
        where_filter_sql = 'WHERE ' + ' AND '.join(where_clauses)

    stock_rows = conn.execute(f'''
        SELECT 
            stock.id,
            stock.name,
            stock.unit,
            stock.quantity,
            stock.low_stock_threshold,
            stock.cost_price,
            stock.selling_price,
            IFNULL(SUM(sales.quantity_sold), 0) AS total_sold,
            IFNULL(SUM(sales.quantity_sold * (stock.selling_price - stock.cost_price)), 0) AS total_profit
        FROM stock
        LEFT JOIN sales ON stock.id = sales.stock_id {join_filter_sql}
        GROUP BY stock.id
        ORDER BY total_profit DESC
    ''', join_params).fetchall()

    profit_data = []
    low_stock_count = 0
    for row in stock_rows:
        cost_price = row['cost_price'] or 0
        selling_price = row['selling_price'] or 0
        profit_per_unit = selling_price - cost_price
        total_item_profit = row['total_profit'] or 0
        badges = []

        threshold = row['low_stock_threshold']
        current_quantity = row['quantity']
        if (
            threshold is not None
            and current_quantity is not None
            and current_quantity <= threshold
        ):
            badges.append('Low Stock')
            low_stock_count += 1

        profit_data.append({
            'name': row['name'],
            'quantity': row['total_sold'],
            'unit': row['unit'],
            'cost_price': round(cost_price, 2),
            'selling_price': round(selling_price, 2),
            'profit_per_unit': round(profit_per_unit, 2),
            'total_item_profit': round(total_item_profit, 2),
            'badges': badges,
        })

    total_profit = round(sum(item['total_item_profit'] for item in profit_data), 2)
    total_units_sold = round(sum(item['quantity'] for item in profit_data), 2)
    chart_labels = [item['name'] for item in profit_data]
    chart_data = [item['total_item_profit'] for item in profit_data]

    sales_rows = conn.execute(f'''
        SELECT 
            sales.sale_date,
            (stock.selling_price - stock.cost_price) * sales.quantity_sold AS profit
        FROM sales
        JOIN stock ON sales.stock_id = stock.id
        {where_filter_sql}
        ORDER BY sales.sale_date ASC
    ''', where_params).fetchall()

    forecast = forecast_profit_trend(sales_rows)

    if profit_data:
        top_earner = max(profit_data, key=lambda item: item['total_item_profit'])
        if top_earner['total_item_profit'] > 0:
            top_earner['badges'].append('Top Earner')

        biggest_loss = min(profit_data, key=lambda item: item['total_item_profit'])
        if biggest_loss['total_item_profit'] < 0:
            biggest_loss['badges'].append('Biggest Loss')

    summary = {
        'total_profit': total_profit,
        'total_units_sold': total_units_sold,
        'product_count': len(profit_data),
        'low_stock_count': low_stock_count,
        'ai_projection': forecast.get('projected_profit') if forecast.get('status') == 'ok' else None,
    }

    conn.close()

    return render_template(
        'profit.html',
        profit_data=profit_data,
        total_profit=total_profit,
        chart_labels=chart_labels or [],
        chart_data=chart_data or [],
        start=start or '',
        end=end or '',
        forecast=forecast,
        summary=summary,
    )

@app.route('/logout')
def logout():
    # Here you would typically handle user session termination
    return redirect(url_for('index')) 

@app.route('/sales')
def sales_history():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT sales.id,
               stock.name AS item_name,
               sales.quantity_sold,
               stock.selling_price,
               stock.cost_price,
               (sales.quantity_sold * stock.selling_price) AS revenue,
               (sales.quantity_sold * (stock.selling_price - stock.cost_price)) AS profit,
               sales.sale_date
        FROM sales
        JOIN stock ON sales.stock_id = stock.id
        ORDER BY sales.sale_date DESC
    ''').fetchall()
    conn.close()
    return render_template('sales_history.html', sales=rows)


# LOW STOCK PAGE
@app.route('/low-stock')
def low_stock():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT * FROM stock
        WHERE low_stock_threshold IS NOT NULL AND quantity <= low_stock_threshold
        ORDER BY quantity ASC
    ''').fetchall()
    conn.close()
    return render_template('low_stock.html', items=rows)

@app.route('/export/sales')
def export_csv():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT 
            sales.id,
            stock.name AS product_name,
            sales.quantity_sold,
            sales.sale_date,
            (stock.selling_price - stock.cost_price) * sales.quantity_sold AS profit
        FROM sales
        JOIN stock ON sales.stock_id = stock.id
    ''').fetchall()
    conn.close()

    # Convert to CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Sale ID', 'Product Name', 'Quantity Sold', 'Sale Date', 'Profit'])

    for row in rows:
        writer.writerow([
            row['id'],
            row['product_name'],
            row['quantity_sold'],
            row['sale_date'],
            row['profit']
        ])

    output.seek(0)

    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=sales_export.csv'}
    )


def init_database():
    """Initialize database tables if they don't exist"""
    conn = get_db_connection()
    
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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            quantity_sold REAL NOT NULL,
            sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stock(id)
        )
    ''')
    
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_database()
    app.run(debug=True)
else:
    # Initialize database when running with gunicorn
    init_database()

