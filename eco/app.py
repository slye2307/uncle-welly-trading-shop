# app.py
from flask import Flask, flash, render_template, request, redirect, url_for
import sqlite3
import os
from flask import Response
from datetime import datetime
import csv
import io
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

DATABASE = 'database/stock.db'


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn
DATABASE = 'database/stock.db'  # ✅ Use the same DB as init_db.py



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
    conn = sqlite3.connect('database/stock.db')
    conn.row_factory = sqlite3.Row  # ✅ Makes rows act like dictionaries
    cursor = conn.cursor()

    cursor.execute("""
        SELECT stock.id, stock.name, stock.cost_price, stock.selling_price, 
               SUM(sales.quantity_sold) as total_sold
        FROM stock
        LEFT JOIN sales ON stock.id = sales.stock_id
        GROUP BY stock.id
    """)
    rows = cursor.fetchall()

    profit_data = []
    total_profit = 0
    for stock in rows:
        if stock['cost_price'] is not None and stock['selling_price'] is not None:
            profit = (stock['selling_price'] - stock['cost_price']) * (stock['total_sold'] or 0)
            total_profit += profit
            profit_data.append({
                'name': stock['name'],
                'profit': profit
            })

    # Filter out items with no profit
    profit_data = [row for row in profit_data if row['profit'] > 0]
    total_profit = sum(row['profit'] for row in profit_data)
    chart_labels = [row['name'] for row in profit_data]
    chart_data = [row['profit'] for row in profit_data]

    return render_template('profit.html', profit_data=profit_data, total_profit=total_profit,
        chart_labels=chart_labels or [],
        chart_data=chart_data or [])

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


if __name__ == '__main__':
    if not os.path.exists('database'):
        os.makedirs('database')
    app.run(debug=True)

